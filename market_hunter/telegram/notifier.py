import requests
import logging
from market_hunter.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4000


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------

def send_message(text: str) -> bool:
    """Send a single HTML message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(val, plus: bool = True) -> str:
    if val is None:
        return "N/A"
    sign = "+" if (plus and val >= 0) else ""
    return f"{sign}{val:.1f}%"


def _price(val) -> str:
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def _dollar_vol(val) -> str:
    """Format dollar volume as e.g. $8.2B / $450M."""
    if val is None:
        return "N/A"
    val = float(val)
    if val >= 1e9:
        return f"${val / 1e9:.1f}B"
    if val >= 1e6:
        return f"${val / 1e6:.0f}M"
    return f"${val:,.0f}"


def _ma_str(diag: dict) -> str:
    parts = []
    for key in ("ma20", "ma50", "ma60", "ma200"):
        v = diag.get(key)
        parts.append(f"{v:,.2f}" if v is not None else "N/A")
    return " / ".join(parts)


def _strategy_label(strategy_name: str) -> str:
    return {
        "ma60_reclaim": "📐 MA60 Reclaim Pullback",
        "strong_trend": "📈 Strong Trend Pullback",
        "new_high": "🚀 New High Breakout",
    }.get(strategy_name, strategy_name)


def _strategy_reason(strategy_name: str, details: dict, diag: dict) -> str:
    """Generate a short plain-text reason for a triggered strategy."""
    try:
        if strategy_name == "ma60_reclaim":
            days = details.get("cross_days_ago", "?")
            pct = details.get("pct_from_ma60")
            pct_str = f"{pct:+.1f}%" if pct is not None else "near"
            days_below = details.get("days_below_before_cross", "?")
            return (f"Crossed above MA60 after {days_below}d downtrend, "
                    f"{days}d ago; now {pct_str} from MA60.")

        if strategy_name == "strong_trend":
            near = "MA20" if details.get("near_ma20") else "MA50"
            dist = details.get("dist_52w_pct")
            dist_str = f"{dist:.1f}%" if dist is not None else "N/A"
            return (f"MA20>MA50>MA200 aligned; pulled back near {near}; "
                    f"{dist_str} from 52W high.")

        if strategy_name == "new_high":
            pct = details.get("pct_above_52w_high")
            vol_r = details.get("vol_ratio")
            pct_str = f"+{pct:.1f}%" if pct is not None else "N/A"
            vol_str = f"{vol_r:.1f}x" if vol_r is not None else "N/A"
            return (f"Broke 52W high by {pct_str} on {vol_str} avg volume.")
    except Exception:
        pass
    return ""


def _format_stock_card(sig: dict, strategy_name: str) -> str:
    """Format one stock into a rich multi-line Telegram card."""
    diag = sig.get("diagnostics") or {}
    details = sig.get("strategy_details") or {}

    reason = sig.get("reason") or _strategy_reason(strategy_name, details, diag)

    vol_ratio = diag.get("volume_ratio")
    vol_ratio_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "N/A"

    lines = [
        f"<b>{sig['symbol']}</b> | Score {sig['total_score']:.0f} | "
        f"{_strategy_label(strategy_name)}",
        f"<b>Sector:</b> {sig.get('sector') or 'N/A'}",
        f"<b>Price:</b> {_price(sig.get('close_price'))}",
        f"<b>MA20/50/60/200:</b> {_ma_str(diag)}",
        f"<b>52W High Dist:</b> {_pct(diag.get('distance_52w_high'))}",
        f"<b>Vol Ratio:</b> {vol_ratio_str} | "
        f"<b>DolVol:</b> {_dollar_vol(diag.get('dollar_volume'))}",
        f"<b>20D/60D Return:</b> {_pct(diag.get('return_20d'))} / "
        f"{_pct(diag.get('return_60d'))}",
        f"<b>RS vs SPY:</b> 20D {_pct(diag.get('rs_vs_spy_20d'))} | "
        f"60D {_pct(diag.get('rs_vs_spy_60d'))}",
    ]
    if reason:
        lines.append(f"<b>Reason:</b> {reason}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-message report
# ---------------------------------------------------------------------------

def _format_summary_message(scan_date: str, results: dict) -> str:
    """Header message: scan stats + compact Top 20 list."""
    summary = results.get("summary", {})
    scanned = summary.get("scanned_count", results.get("total_scanned", 0))
    valid = summary.get("valid_price_count", scanned)
    rejected = summary.get("rejected_bad_price_count", 0)
    signals = summary.get("signal_count", results.get("total_signals", 0))
    duration = results.get("duration_seconds", 0)

    lines = [
        "<b>📊 Market Hunter — US Daily Scan</b>",
        f"<b>Date:</b> {scan_date}",
        "",
        f"<b>Stats:</b> {scanned} scanned | {valid} valid | "
        f"{rejected} rejected | {signals} signals | {duration:.0f}s",
        "",
        "<b>🏆 Top 20 by Score</b>",
    ]

    for i, s in enumerate(results.get("top20", [])[:20], 1):
        strats = s.get("strategies") or []
        strat_tag = f" [{','.join(strats)}]" if strats else ""
        lines.append(
            f"{i:2}. <b>{s['symbol']:<5}</b> {s['total_score']:4.0f}  "
            f"{_price(s.get('close_price')):>10}  "
            f"{(s.get('sector') or '')[:22]}{strat_tag}"
        )

    return "\n".join(lines)


def _format_strategy_section(strategy_key: str, picks: list[dict]) -> str | None:
    """Format one strategy's picks into a single message."""
    label = _strategy_label(strategy_key)
    if not picks:
        return None

    parts = [f"<b>{label} — Top {len(picks)}</b>", ""]
    for sig in picks:
        parts.append(_format_stock_card(sig, strategy_key))
        parts.append("")  # blank separator

    return "\n".join(parts).rstrip()


def send_scan_report(scan_date: str, results: dict) -> bool:
    """
    Send the scan report as multiple Telegram messages:
      1. Summary + Top 20 list
      2. MA60 Reclaim Pullback details
      3. Strong Trend Pullback details
      4. New High Breakout details (omitted if empty)
    """
    ok = True

    # Message 1: summary
    summary_text = _format_summary_message(scan_date, results)
    if len(summary_text) > TELEGRAM_MAX_CHARS:
        summary_text = summary_text[:TELEGRAM_MAX_CHARS - 20] + "\n<i>...truncated</i>"
    ok &= send_message(summary_text)

    # Messages 2-4: one per strategy
    for strategy_key in ("ma60_reclaim", "strong_trend", "new_high"):
        picks = results.get(strategy_key, [])
        text = _format_strategy_section(strategy_key, picks)
        if not text:
            continue
        if len(text) > TELEGRAM_MAX_CHARS:
            text = text[:TELEGRAM_MAX_CHARS - 20] + "\n<i>...truncated</i>"
        ok &= send_message(text)

    if ok:
        logger.info("Telegram scan report sent (multiple messages)")
    return ok


def send_error(error_msg: str) -> bool:
    """Send an error notification to Telegram."""
    text = f"<b>❌ Market Hunter Error</b>\n\n<code>{error_msg}</code>"
    return send_message(text)
