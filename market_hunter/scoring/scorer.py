import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

SECTOR_SCORES = {
    "Technology": 10,
    "Health Care": 9,
    "Consumer Discretionary": 8,
    "Industrials": 7,
    "Financials": 7,
    "Communication Services": 6,
    "Energy": 6,
    "Materials": 5,
    "Consumer Staples": 5,
    "Real Estate": 4,
    "Utilities": 3,
}


def compute_trend_score(df: pd.DataFrame) -> float:
    """Score 0-30: measures trend alignment and strength."""
    if df.empty:
        return 0.0

    df = df.dropna(subset=["MA20", "MA50"], how="any")
    if df.empty:
        return 0.0

    last = df.iloc[-1]
    close = last["Close"]
    score = 0.0

    ma20 = last.get("MA20")
    ma50 = last.get("MA50")
    ma200 = last.get("MA200")

    if pd.notna(ma20) and close > ma20:
        score += 8
    if pd.notna(ma50) and close > ma50:
        score += 8
    if pd.notna(ma200) and close > ma200:
        score += 7

    if pd.notna(ma20) and pd.notna(ma50) and ma20 > ma50:
        score += 4
    if pd.notna(ma50) and pd.notna(ma200) and pd.notna(ma20) and ma20 > ma50 > ma200:
        score += 3

    return min(score, 30.0)


def compute_relative_strength_score(df: pd.DataFrame, spy_df: pd.DataFrame) -> float:
    """Score 0-25: relative strength vs SPY over 20 and 60 days."""
    if df.empty or spy_df.empty:
        return 0.0

    score = 0.0

    for days, weight in [(20, 12), (60, 13)]:
        if len(df) < days or len(spy_df) < days:
            continue
        stock_ret = df["Close"].iloc[-1] / df["Close"].iloc[-days] - 1
        spy_ret = spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-days] - 1
        rs = stock_ret - spy_ret

        if rs > 0.10:
            score += weight
        elif rs > 0.05:
            score += weight * 0.8
        elif rs > 0.02:
            score += weight * 0.6
        elif rs > 0:
            score += weight * 0.3
        else:
            score += 0

    return min(score, 25.0)


def compute_volume_score(df: pd.DataFrame) -> float:
    """Score 0-20: measures recent volume relative to average."""
    if df.empty or "VolMA20" not in df.columns:
        return 0.0

    df = df.dropna(subset=["VolMA20"])
    if df.empty:
        return 0.0

    last = df.iloc[-1]
    vol = last["Volume"]
    vol_ma20 = last["VolMA20"]

    if vol_ma20 == 0:
        return 0.0

    ratio = vol / vol_ma20
    if ratio >= 2.0:
        return 20.0
    elif ratio >= 1.5:
        return 15.0
    elif ratio >= 1.2:
        return 10.0
    elif ratio >= 1.0:
        return 7.0
    elif ratio >= 0.8:
        return 4.0
    return 2.0


def compute_pullback_risk_score(df: pd.DataFrame) -> float:
    """Score 0-15: lower drawdown from recent high = higher score."""
    if df.empty or "High52W" not in df.columns:
        return 0.0

    df = df.dropna(subset=["High52W"])
    if df.empty:
        return 0.0

    last = df.iloc[-1]
    close = last["Close"]
    high52 = last["High52W"]

    if high52 == 0:
        return 0.0

    dist = (high52 - close) / high52

    if dist <= 0.03:
        return 15.0
    elif dist <= 0.07:
        return 12.0
    elif dist <= 0.12:
        return 9.0
    elif dist <= 0.20:
        return 6.0
    elif dist <= 0.30:
        return 3.0
    return 1.0


def compute_sector_score(sector: str) -> float:
    """Score 0-10 based on sector momentum bias."""
    return float(SECTOR_SCORES.get(sector, 5))


def compute_total_score(df: pd.DataFrame, spy_df: pd.DataFrame, sector: str) -> dict:
    """Compute all sub-scores and total score for a stock."""
    trend = compute_trend_score(df)
    rs = compute_relative_strength_score(df, spy_df)
    vol = compute_volume_score(df)
    pullback = compute_pullback_risk_score(df)
    sect = compute_sector_score(sector)
    total = trend + rs + vol + pullback + sect

    return {
        "trend_score": round(trend, 2),
        "relative_strength_score": round(rs, 2),
        "volume_score": round(vol, 2),
        "pullback_risk_score": round(pullback, 2),
        "sector_score": round(sect, 2),
        "total_score": round(total, 2),
    }
