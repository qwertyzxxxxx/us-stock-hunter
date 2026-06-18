import requests
import logging
from market_hunter.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    """Send a message to the configured Telegram chat."""
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
        logger.info("Telegram notification sent")
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def format_scan_report(scan_date: str, results: dict) -> str:
    """Format the scan results into a Telegram-friendly HTML message."""
    lines = [
        f"<b>📊 Market Hunter — US Scan</b>",
        f"<b>Date:</b> {scan_date}",
        "",
    ]

    top20 = results.get("top20", [])
    lines.append(f"<b>🏆 Top 20 Strongest ({len(top20)} stocks)</b>")
    for i, s in enumerate(top20[:20], 1):
        lines.append(
            f"{i}. <b>{s['symbol']}</b> ({s.get('sector', 'N/A')}) "
            f"Score: {s['total_score']:.1f} | ${s['close_price']:.2f}"
        )
    lines.append("")

    for strategy_key, label, emoji in [
        ("ma60_reclaim", "MA60 Reclaim Pullback", "📐"),
        ("strong_trend", "Strong Trend Pullback", "📈"),
        ("new_high", "New High Breakout", "🚀"),
    ]:
        picks = results.get(strategy_key, [])
        lines.append(f"<b>{emoji} Top 5 {label}</b>")
        for i, s in enumerate(picks[:5], 1):
            lines.append(
                f"{i}. <b>{s['symbol']}</b> Score: {s['total_score']:.1f} | ${s['close_price']:.2f}"
            )
        lines.append("")

    total_scanned = results.get("total_scanned", 0)
    total_signals = results.get("total_signals", 0)
    lines.append(f"<i>Scanned {total_scanned} stocks | {total_signals} signals found</i>")

    return "\n".join(lines)


def send_scan_report(scan_date: str, results: dict) -> bool:
    """Send a formatted scan report to Telegram."""
    text = format_scan_report(scan_date, results)
    # Telegram max length is 4096 chars
    if len(text) > 4000:
        text = text[:3990] + "\n<i>...truncated</i>"
    return send_message(text)


def send_error(error_msg: str) -> bool:
    """Send an error notification to Telegram."""
    text = f"<b>❌ Market Hunter Error</b>\n\n<code>{error_msg}</code>"
    return send_message(text)
