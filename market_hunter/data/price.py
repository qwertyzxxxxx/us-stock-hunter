import logging
import yfinance as yf
import pandas as pd
from market_hunter.config import LOOKBACK_DAYS

logger = logging.getLogger(__name__)


def _yf_symbol(symbol: str) -> str:
    """
    Normalise a ticker for yfinance.
    S&P 500 CSV uses dots (BRK.B, BF.B); yfinance expects dashes (BRK-B, BF-B).
    """
    return symbol.replace(".", "-")


def get_ohlcv(symbol: str, period_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch daily OHLCV data from yfinance."""
    try:
        ticker = yf.Ticker(_yf_symbol(symbol))
        df = ticker.history(period=f"{period_days}d", auto_adjust=True)
        if df.empty:
            logger.warning(f"No data for {symbol}")
            return pd.DataFrame()
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logger.error(f"yfinance error for {symbol}: {e}")
        return pd.DataFrame()


def get_ohlcv_and_market_cap(symbol: str, period_days: int = LOOKBACK_DAYS) -> tuple[pd.DataFrame, float]:
    """
    Fetch OHLCV data and market cap using a single Ticker object.
    Avoids creating two separate yfinance sessions per stock.
    Returns (df, market_cap_usd). market_cap is 0.0 on failure.
    """
    try:
        ticker = yf.Ticker(_yf_symbol(symbol))

        df = ticker.history(period=f"{period_days}d", auto_adjust=True)
        if df.empty:
            logger.warning(f"No price data for {symbol}")
            return pd.DataFrame(), 0.0
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.dropna(inplace=True)

        market_cap = 0.0
        try:
            fi = ticker.fast_info
            market_cap = float(fi.market_cap or 0)
        except Exception:
            pass

        return df, market_cap

    except Exception as e:
        logger.error(f"yfinance error for {symbol}: {e}")
        return pd.DataFrame(), 0.0


def get_sector_industry(symbol: str) -> dict:
    """
    Fetch sector and industry from yfinance ticker.info.
    Only call this for a small set of triggered signals — it is slower
    than fast_info as it hits a heavier Yahoo Finance endpoint.
    Returns {"sector": str, "industry": str}.
    """
    try:
        info = yf.Ticker(symbol).info
        return {
            "sector": info.get("sector", ""),
            "industry": info.get("industryDisp") or info.get("industry", ""),
        }
    except Exception as e:
        logger.warning(f"Could not fetch sector/industry for {symbol}: {e}")
        return {"sector": "", "industry": ""}


def get_spy_ohlcv(period_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch SPY data for relative strength calculation."""
    return get_ohlcv("SPY", period_days)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA and volume indicators to OHLCV dataframe."""
    if df.empty or len(df) < 20:
        return df
    df = df.copy()
    for n in [20, 50, 60, 200]:
        if len(df) >= n:
            df[f"MA{n}"] = df["Close"].rolling(n).mean()
        else:
            df[f"MA{n}"] = None

    df["VolMA20"] = df["Volume"].rolling(20).mean()
    df["DollarVol"] = df["Close"] * df["Volume"]
    df["DollarVolMA20"] = df["DollarVol"].rolling(20).mean()

    high_52w = df["High"].rolling(min(252, len(df))).max()
    df["High52W"] = high_52w

    return df


def avg_dollar_volume(df: pd.DataFrame, days: int = 20) -> float:
    """Calculate average daily dollar volume over recent N days."""
    if df.empty or len(df) < days:
        return 0.0
    recent = df.tail(days)
    dollar_vol = (recent["Close"] * recent["Volume"]).mean()
    return float(dollar_vol)
