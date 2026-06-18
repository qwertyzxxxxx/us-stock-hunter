import requests
import logging
from market_hunter.config import FMP_API_KEY

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"


def get_us_stock_universe() -> list[dict]:
    """Fetch US common stocks with market cap >= 10B from FMP."""
    if not FMP_API_KEY:
        logger.error("FMP_API_KEY not set")
        return []

    url = f"{FMP_BASE}/stock-screener"
    params = {
        "apikey": FMP_API_KEY,
        "exchange": "NYSE,NASDAQ,AMEX",
        "marketCapMoreThan": 10_000_000_000,
        "isEtf": "false",
        "isActivelyTrading": "true",
        "country": "US",
        "limit": 2000,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            filtered = _filter_universe(data)
            logger.info(f"FMP universe: {len(data)} raw -> {len(filtered)} after filter")
            return filtered
        logger.error(f"Unexpected FMP response: {data}")
        return []
    except Exception as e:
        logger.error(f"FMP universe fetch error: {e}")
        return []


def _filter_universe(stocks: list[dict]) -> list[dict]:
    """Remove ETFs, warrants, units, preferred shares, ADRs."""
    excluded_keywords = ["warrant", "unit", "preferred", "adr", "depositary"]
    result = []
    for s in stocks:
        name = (s.get("companyName") or "").lower()
        symbol = (s.get("symbol") or "")
        # Skip if name contains exclusion keywords
        if any(kw in name for kw in excluded_keywords):
            continue
        # Skip symbols with more than one dot or slash (ADRs, units)
        if symbol.count(".") > 1 or "/" in symbol:
            continue
        # Skip preferred shares (symbol ending in p/P followed by letter)
        if len(symbol) > 4 and symbol[-1].isalpha() and symbol[-2].isalpha():
            continue
        result.append(s)
    return result


def get_stock_profile(symbol: str) -> dict:
    """Fetch company profile from FMP."""
    if not FMP_API_KEY:
        return {}
    url = f"{FMP_BASE}/profile/{symbol}"
    try:
        resp = requests.get(url, params={"apikey": FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
        return {}
    except Exception as e:
        logger.error(f"FMP profile error for {symbol}: {e}")
        return {}
