"""
Entry Engine — rule-based entry/exit level computation per strategy.

No AI, no prediction. All levels derived from OHLCV + indicators.
Called per (strategy, stock) pair inside the scan loop.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def _r2(v) -> float:
    return round(float(v), 2)


def _rr(reward: float, risk: float) -> float | None:
    if risk <= 0:
        return None
    return round(reward / risk, 1)


def compute_entry_plan(strategy_name: str, df: pd.DataFrame, details: dict) -> dict:
    """
    Compute entry zone, trigger, stop, targets, and R:R for one strategy signal.

    Returns a flat dict:
        entry_zone_low, entry_zone_high, trigger_price,
        stop_loss, risk_pct, target1, target2, target2_note, rr_ratio
    Returns {} on any error.
    """
    try:
        if df.empty or len(df) < 2:
            return {}
        last = df.iloc[-1]
        close = float(last["Close"])

        if strategy_name == "ma60_reclaim":
            return _plan_ma60(last, df, close, details)
        if strategy_name == "strong_trend":
            return _plan_strong_trend(last, df, close, details)
        if strategy_name == "new_high":
            return _plan_new_high(last, df, close, details)
        return {}
    except Exception as e:
        logger.debug(f"entry_engine error ({strategy_name}): {e}")
        return {}


# ---------------------------------------------------------------------------
# Strategy A — MA60 Reclaim Pullback
# ---------------------------------------------------------------------------

def _plan_ma60(last, df: pd.DataFrame, close: float, details: dict) -> dict:
    ma60 = float(last.get("MA60") or details.get("ma60") or close)
    high52 = float(last.get("High52W") or close * 1.25)

    entry_low = _r2(ma60 * 0.98)
    entry_high = _r2(ma60 * 1.02)
    trigger = _r2(ma60 * 1.005)   # close just above MA60
    stop = _r2(ma60 * 0.97)       # MA60 -3%

    # Target1: swing high after the MA60 cross (peak_after_cross from strategy)
    swing_high = float(details.get("peak_after_cross") or df["High"].tail(30).max())
    # If swing high is already lower than trigger, use a conservative +8%
    target1 = _r2(max(swing_high, trigger * 1.08))
    target2 = _r2(high52)

    risk = max(trigger - stop, 0.01)
    reward1 = max(target1 - trigger, 0)
    risk_pct = _r2((risk / trigger) * 100) if trigger > 0 else None
    rr = _rr(reward1, risk)

    return {
        "entry_zone_low": entry_low,
        "entry_zone_high": entry_high,
        "trigger_price": trigger,
        "stop_loss": stop,
        "risk_pct": risk_pct,
        "target1": target1,
        "target2": target2,
        "target2_note": None,
        "rr_ratio": rr,
    }


# ---------------------------------------------------------------------------
# Strategy B — Strong Trend Pullback
# ---------------------------------------------------------------------------

def _plan_strong_trend(last, df: pd.DataFrame, close: float, details: dict) -> dict:
    ma20 = float(last.get("MA20") or details.get("ma20") or close)
    ma50 = float(last.get("MA50") or details.get("ma50") or close)
    near_ma20 = details.get("near_ma20", True)

    anchor = ma20 if near_ma20 else ma50
    entry_low = _r2(anchor * 0.98)
    entry_high = _r2(anchor * 1.02)

    # Trigger: break above previous day's high
    trigger = _r2(float(df["High"].iloc[-2]))
    stop = _r2(ma50 * 0.99)        # just below MA50
    target1 = _r2(close * 1.10)    # +10%

    risk = max(trigger - stop, 0.01)
    reward1 = max(target1 - trigger, 0)
    risk_pct = _r2((risk / trigger) * 100) if trigger > 0 else None
    rr = _rr(reward1, risk)

    return {
        "entry_zone_low": entry_low,
        "entry_zone_high": entry_high,
        "trigger_price": trigger,
        "stop_loss": stop,
        "risk_pct": risk_pct,
        "target1": target1,
        "target2": None,
        "target2_note": "跟踪止盈（MA20）",
        "rr_ratio": rr,
    }


# ---------------------------------------------------------------------------
# Strategy C — 52-Week High Breakout
# ---------------------------------------------------------------------------

def _plan_new_high(last, df: pd.DataFrame, close: float, details: dict) -> dict:
    prev_high = float(details.get("prev_52w_high") or close * 0.98)

    entry_low = _r2(prev_high)
    entry_high = _r2(prev_high * 1.05)
    trigger = _r2(close)                    # already broken out
    stop = _r2(prev_high * 0.935)           # ~6.5% below breakout
    target1 = _r2(trigger * 1.15)           # +15%

    risk = max(trigger - stop, 0.01)
    reward1 = max(target1 - trigger, 0)
    risk_pct = _r2((risk / trigger) * 100) if trigger > 0 else None
    rr = _rr(reward1, risk)

    return {
        "entry_zone_low": entry_low,
        "entry_zone_high": entry_high,
        "trigger_price": trigger,
        "stop_loss": stop,
        "risk_pct": risk_pct,
        "target1": target1,
        "target2": None,
        "target2_note": "跟踪止盈",
        "rr_ratio": rr,
    }
