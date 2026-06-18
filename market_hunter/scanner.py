import logging
import time
from datetime import date

from market_hunter.config import MIN_AVG_DOLLAR_VOLUME, MIN_MARKET_CAP
from market_hunter.data.fmp import get_us_stock_universe
from market_hunter.data.price import (
    get_ohlcv_and_market_cap, get_spy_ohlcv,
    compute_indicators, avg_dollar_volume, get_sector_industry,
)
from market_hunter.strategies.ma60_reclaim import check_ma60_reclaim_pullback
from market_hunter.strategies.strong_trend import check_strong_trend_pullback
from market_hunter.strategies.new_high import check_new_high_breakout
from market_hunter.scoring.scorer import compute_total_score
from market_hunter.database import db
from market_hunter.telegram import notifier

logger = logging.getLogger(__name__)


def _enrich_missing_sectors(signals: list[dict]) -> None:
    """
    Fill in sector/industry from yfinance for any signal still missing it.
    Called only on the small final set (≤ 20 stocks) so the heavier
    ticker.info calls don't affect the main scan loop.
    Mutates the dicts in-place.
    """
    cache: dict[str, dict] = {}
    for sig in signals:
        if sig.get("sector"):
            continue
        sym = sig["symbol"]
        if sym not in cache:
            cache[sym] = get_sector_industry(sym)
        sig["sector"] = cache[sym]["sector"]
        sig["industry"] = cache[sym]["industry"]


def run_us_scan(notify: bool = True) -> dict:
    """Run the full US stock daily scan."""
    start_time = time.time()
    scan_date = date.today().isoformat()
    logger.info(f"Starting US scan — {scan_date}")

    db.init_db()

    # Fetch universe (FMP constituents → public S&P 500 fallback)
    universe = get_us_stock_universe()
    if not universe:
        error = "Failed to fetch stock universe from all sources"
        logger.error(error)
        db.insert_scan_run(scan_date, 0, 0, 0, "failed", error)
        if notify:
            notifier.send_error(error)
        return {}

    logger.info(f"Universe: {len(universe)} stocks")

    # SPY for relative strength scoring
    spy_df = get_spy_ohlcv()
    spy_df = compute_indicators(spy_df) if not spy_df.empty else spy_df

    all_signals: list[dict] = []
    ma60_signals: list[dict] = []
    strong_trend_signals: list[dict] = []
    new_high_signals: list[dict] = []
    total_scanned = 0

    for stock in universe:
        symbol = stock.get("symbol", "")
        if not symbol:
            continue

        try:
            # Single Ticker object → OHLCV + market_cap (fast_info)
            df, market_cap = get_ohlcv_and_market_cap(symbol)
            if df.empty or len(df) < 60:
                continue

            df = compute_indicators(df)

            # Dollar volume filter
            adv = avg_dollar_volume(df)
            if adv < MIN_AVG_DOLLAR_VOLUME:
                continue

            # Market cap filter (yfinance fast_info)
            # S&P 500 stocks all qualify, but keep the check for correctness.
            if market_cap > 0 and market_cap < MIN_MARKET_CAP:
                continue

            total_scanned += 1

            # Sector from universe (populated by FMP constituents or S&P 500 CSV).
            # If still empty, _enrich_missing_sectors fills it in after the loop
            # for the small final set of results only.
            sector = stock.get("sector", "")
            scores = compute_total_score(df, spy_df, sector=sector)

            last = df.iloc[-1]
            signal_base: dict = {
                "symbol": symbol,
                "company_name": stock.get("companyName", ""),
                "sector": sector,
                "industry": stock.get("industry", ""),
                "market_cap": market_cap,
                "signal_date": scan_date,
                "close_price": round(float(last["Close"]), 2),
                "volume": int(last["Volume"]),
                "strategies": [],
                **scores,
            }

            # Strategy A — MA60 Reclaim Pullback
            ma60 = check_ma60_reclaim_pullback(df)
            if ma60["triggered"]:
                signal_base["strategies"].append("ma60_reclaim")
                ma60_signals.append({**signal_base, "strategy_details": ma60["details"]})

            # Strategy B — Strong Trend Pullback
            strong = check_strong_trend_pullback(df)
            if strong["triggered"]:
                signal_base["strategies"].append("strong_trend")
                strong_trend_signals.append({**signal_base, "strategy_details": strong["details"]})

            # Strategy C — New High Breakout
            new_high = check_new_high_breakout(df)
            if new_high["triggered"]:
                signal_base["strategies"].append("new_high")
                new_high_signals.append({**signal_base, "strategy_details": new_high["details"]})

            all_signals.append(signal_base)

        except Exception as e:
            logger.warning(f"Error processing {symbol}: {e}")
            continue

    # Sort by total_score descending
    all_signals.sort(key=lambda x: x["total_score"], reverse=True)
    ma60_signals.sort(key=lambda x: x["total_score"], reverse=True)
    strong_trend_signals.sort(key=lambda x: x["total_score"], reverse=True)
    new_high_signals.sort(key=lambda x: x["total_score"], reverse=True)

    top20 = all_signals[:20]
    top_ma60 = ma60_signals[:5]
    top_strong = strong_trend_signals[:5]
    top_new_high = new_high_signals[:5]

    # Enrich sector/industry only where still missing (small set)
    all_top = top20 + top_ma60 + top_strong + top_new_high
    _enrich_missing_sectors(all_top)

    duration = time.time() - start_time
    total_signals = len(ma60_signals) + len(strong_trend_signals) + len(new_high_signals)

    # Persist to DB
    run_id = db.insert_scan_run(scan_date, total_scanned, total_signals, duration)

    def _save_signals(signals: list[dict], strategy_name: str) -> None:
        for rank, sig in enumerate(signals, 1):
            sig_id = db.upsert_signal(run_id, sig)
            db.insert_strategy_result(
                sig_id, strategy_name, sig["symbol"], scan_date, rank,
                str(sig.get("strategy_details", {}))
            )

    _save_signals(top_ma60, "ma60_reclaim")
    _save_signals(top_strong, "strong_trend")
    _save_signals(top_new_high, "new_high")
    for rank, sig in enumerate(top20, 1):
        db.upsert_signal(run_id, sig)

    results = {
        "scan_date": scan_date,
        "total_scanned": total_scanned,
        "total_signals": total_signals,
        "top20": top20,
        "ma60_reclaim": top_ma60,
        "strong_trend": top_strong,
        "new_high": top_new_high,
        "duration_seconds": round(duration, 1),
    }

    logger.info(
        f"Scan complete in {duration:.1f}s — scanned {total_scanned}, "
        f"signals: MA60={len(ma60_signals)}, Strong={len(strong_trend_signals)}, "
        f"NewHigh={len(new_high_signals)}"
    )

    if notify:
        notifier.send_scan_report(scan_date, results)

    return results
