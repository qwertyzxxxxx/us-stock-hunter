"""
Telegram notifier — Chinese output.
All user-facing text is in Simplified Chinese; stock symbols remain in English.
"""

import requests
import logging
from market_hunter.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from market_hunter.scoring.scorer import volume_rating, volume_label_pullback, volume_label_breakout

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4000

# ---------------------------------------------------------------------------
# Translation tables
# ---------------------------------------------------------------------------

SECTOR_ZH: dict[str, str] = {
    "Information Technology": "信息技术",
    "Technology": "信息技术",
    "Financials": "金融",
    "Finance": "金融",
    "Industrials": "工业",
    "Health Care": "医疗健康",
    "Healthcare": "医疗健康",
    "Consumer Discretionary": "可选消费",
    "Consumer Staples": "日常消费",
    "Real Estate": "房地产",
    "Communication Services": "通信服务",
    "Communications": "通信服务",
    "Energy": "能源",
    "Utilities": "公用事业",
    "Materials": "材料",
}

STRATEGY_ZH: dict[str, str] = {
    "ma60_reclaim": "MA60回踩反转",
    "strong_trend": "主升浪回踩",
    "new_high": "52周新高突破",
}

STRATEGY_EMOJI: dict[str, str] = {
    "ma60_reclaim": "📐",
    "strong_trend": "📈",
    "new_high": "🚀",
}

# action_status display config: (emoji, short label)
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "可关注买点":       ("✅", "可关注买点"),
    "观察":            ("⚠️", "观察，不可买入"),
    "风险过高，等待回踩": ("❗", "风险过高，等待更低回踩"),
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _zh_sector(sector: str) -> str:
    return SECTOR_ZH.get(sector, sector or "其他")


def _zh_strategy(key: str) -> str:
    return STRATEGY_ZH.get(key, key)


def _zh_strategy_with_emoji(key: str) -> str:
    emoji = STRATEGY_EMOJI.get(key, "")
    return f"{emoji} {STRATEGY_ZH.get(key, key)}"


def _price_str(val) -> str:
    if val is None:
        return "N/A"
    return f"{float(val):,.2f}美元"


def _ma_str(val) -> str:
    if val is None:
        return "N/A"
    return f"{float(val):,.2f}"


def _pct_str(val, plus: bool = True) -> str:
    if val is None:
        return "N/A"
    sign = "+" if (plus and float(val) >= 0) else ""
    return f"{sign}{float(val):.1f}%"


def _dollar_vol_zh(val) -> str:
    """Format dollar volume in Chinese units. 1亿 = 100M USD."""
    if val is None:
        return "N/A"
    v = float(val)
    yi = v / 1e8
    if yi >= 1:
        return f"{yi:.1f}亿美元"
    wan = v / 1e4
    if wan >= 1:
        return f"{wan:.0f}万美元"
    return f"{v:,.0f}美元"


def _entry_zone_str(ep: dict) -> str:
    lo = ep.get("entry_zone_low")
    hi = ep.get("entry_zone_high")
    if lo is None or hi is None:
        return "N/A"
    return f"{lo:,.2f} - {hi:,.2f}"


def _target2_str(ep: dict) -> str:
    t2 = ep.get("target2")
    note = ep.get("target2_note")
    if t2 is not None:
        s = f"{float(t2):,.2f}"
        if note:
            s += f"（{note}）"
        return s
    return note or "N/A"


def _rr_str(ep: dict) -> str:
    rr = ep.get("rr_ratio")
    if rr is None:
        return "N/A"
    return f"1:{float(rr):.1f}"


def _status_lines(ep: dict) -> list[str]:
    """
    Return the 状态 / 原因 block for a stock card.

    状态：✅ 可关注买点
    or
    状态：⚠️ 观察，不可买入
    原因：风险回报比不足（1:0.3）
    or
    状态：❗ 风险过高，等待更低回踩
    原因：当前风险 23.7%，超过 8% 上限
    """
    if not ep:
        return []

    status = ep.get("action_status", "观察")
    emoji, label = STATUS_DISPLAY.get(status, ("⚠️", status))
    rr = ep.get("rr_ratio")
    risk_pct = ep.get("risk_pct")

    lines = [f"状态：{emoji} {label}"]

    if status == "观察":
        rr_txt = _rr_str(ep)
        lines.append(f"原因：风险回报比不足（{rr_txt}）")
    elif status == "风险过高，等待回踩":
        risk_txt = f"{float(risk_pct):.1f}%" if risk_pct is not None else "N/A"
        lines.append(f"原因：当前风险 {risk_txt}，超过 8% 上限")

    return lines


# ---------------------------------------------------------------------------
# Reason lines
# ---------------------------------------------------------------------------

def _build_reason_text(strategy_name: str, details: dict, diag: dict) -> str:
    lines = _reason_lines(strategy_name, details, diag)
    return "\n".join(lines)


def _reason_lines(strategy_name: str, details: dict, diag: dict) -> list[str]:
    vol_ratio = diag.get("volume_ratio")
    rs_20d = diag.get("rs_vs_spy_20d")

    lines: list[str] = []

    if strategy_name == "ma60_reclaim":
        days_ago = details.get("cross_days_ago", "?")
        days_below = details.get("days_below_before_cross", "?")
        pct_ma60 = details.get("pct_from_ma60")
        pct_str = f"{pct_ma60:+.1f}%" if pct_ma60 is not None else ""
        lines.append(f"✓ {days_below}天下降趋势后，{days_ago}天前突破MA60")
        if pct_str:
            lines.append(f"✓ 回踩至MA60附近（{pct_str}）")
        vol_lbl = volume_label_pullback(vol_ratio)
        if vol_lbl:
            lines.append(f"✓ {vol_lbl}")
        if rs_20d is not None and rs_20d > 0:
            lines.append(f"✓ 20日相对SPY强势（{rs_20d:+.1f}%）")

    elif strategy_name == "strong_trend":
        near_ma20 = details.get("near_ma20", True)
        pct_ma20 = details.get("pct_from_ma20")
        pct_ma50 = details.get("pct_from_ma50")
        dist_52 = details.get("dist_52w_pct")
        lines.append("✓ MA20 > MA50 > MA200 趋势对齐")
        if near_ma20 and pct_ma20 is not None:
            lines.append(f"✓ 回踩至MA20附近（{pct_ma20:+.1f}%）")
        elif pct_ma50 is not None:
            lines.append(f"✓ 回踩至MA50附近（{pct_ma50:+.1f}%）")
        vol_lbl = volume_label_pullback(vol_ratio)
        if vol_lbl:
            lines.append(f"✓ {vol_lbl}")
        if dist_52 is not None:
            lines.append(f"✓ 距52周高点 {dist_52:.1f}%")
        if rs_20d is not None and rs_20d > 0:
            lines.append(f"✓ 强于SPY（20日：{rs_20d:+.1f}%）")

    elif strategy_name == "new_high":
        pct_above = details.get("pct_above_52w_high")
        vol_r = details.get("vol_ratio") or vol_ratio
        vol_lbl = volume_label_breakout(vol_r)
        if pct_above is not None:
            lines.append(f"✓ 突破52周高点 +{pct_above:.1f}%")
        if vol_lbl:
            lines.append(f"✓ {vol_lbl}（量比：{vol_r:.1f}倍）" if vol_r else f"✓ {vol_lbl}")
        lines.append("✓ MA20 和 MA50 趋势向上")
        if rs_20d is not None and rs_20d > 0:
            lines.append(f"✓ 强于SPY（20日：{rs_20d:+.1f}%）")

    return lines


# ---------------------------------------------------------------------------
# Stock card formatter
# ---------------------------------------------------------------------------

def _format_stock_card(sig: dict, strategy_name: str) -> str:
    """Format one stock into the full Chinese card."""
    diag = sig.get("diagnostics") or {}
    details = sig.get("strategy_details") or {}
    ep = sig.get("entry_plan") or {}

    vol_ratio = diag.get("volume_ratio")
    vol_label, _ = volume_rating(vol_ratio)

    symbol = sig["symbol"]
    sector = _zh_sector(sig.get("sector") or "")
    strategy_zh = _zh_strategy_with_emoji(strategy_name)
    score = sig.get("total_score", 0)

    t_score  = sig.get("trend_score", 0)
    rs_score = sig.get("relative_strength_score", 0)
    v_score  = sig.get("volume_score", 0)
    pb_score = sig.get("pullback_risk_score", 0)
    sec_score = sig.get("sector_score", 0)

    reason_lns = _reason_lines(strategy_name, details, diag)
    status_lns = _status_lines(ep)

    parts = [
        f"<b>{symbol}</b>",
        f"行业：{sector}",
        "",
        f"策略：",
        f"{strategy_zh}",
    ]

    # ── action status block ──────────────────────────────────────────────
    if status_lns:
        parts.append("")
        parts.extend(status_lns)

    # ── scoring ──────────────────────────────────────────────────────────
    parts += [
        "",
        f"评分：",
        f"<b>{score:.0f}分</b>",
        f"（趋势{t_score:.0f} 强弱{rs_score:.0f} 量能{v_score:.0f} 回踩{pb_score:.0f} 行业{sec_score:.0f}）",
        "",
        f"当前价格：",
        f"{_price_str(sig.get('close_price'))}",
        "",
        f"{vol_label}",
        f"量比：{f'{vol_ratio:.2f}倍' if vol_ratio is not None else 'N/A'}",
        "",
        f"成交额：",
        f"{_dollar_vol_zh(diag.get('dollar_volume'))}",
        "",
        f"趋势：",
        f"MA20：{_ma_str(diag.get('ma20'))}",
        f"MA50：{_ma_str(diag.get('ma50'))}",
        f"MA60：{_ma_str(diag.get('ma60'))}",
        f"MA200：{_ma_str(diag.get('ma200'))}",
        "",
        f"52周高点距离：",
        f"{_pct_str(diag.get('distance_52w_high'))}",
        "",
        f"20日/60日涨幅：",
        f"{_pct_str(diag.get('return_20d'))} / {_pct_str(diag.get('return_60d'))}",
        "",
        f"相对SPY强弱：",
        f"20日：{_pct_str(diag.get('rs_vs_spy_20d'))}  "
        f"60日：{_pct_str(diag.get('rs_vs_spy_60d'))}",
    ]

    # ── entry plan (always show, even for non-actionable) ────────────────
    if ep:
        rr = ep.get("rr_ratio")
        risk_pct = ep.get("risk_pct")
        risk_note = ""
        if risk_pct is not None and float(risk_pct) > 8.0:
            risk_note = f"  ❗超过8%上限"

        parts += [
            "",
            f"买入观察区：",
            f"{_entry_zone_str(ep)}",
            "",
            f"触发买点：",
            f"{_price_str(ep.get('trigger_price'))}",
            "",
            f"止损：",
            f"{_price_str(ep.get('stop_loss'))}",
            "",
            f"目标1：",
            f"{_price_str(ep.get('target1'))}",
            "",
            f"目标2：",
            f"{_target2_str(ep)}",
            "",
            f"风险：{f'{float(risk_pct):.1f}%' if risk_pct is not None else 'N/A'}{risk_note}",
            f"风险回报比：{_rr_str(ep)}",
        ]

    # ── reason ───────────────────────────────────────────────────────────
    if reason_lns:
        parts += ["", "原因：", ""] + reason_lns

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Summary message
# ---------------------------------------------------------------------------

def _format_summary(scan_date: str, results: dict) -> str:
    summary = results.get("summary", {})
    scanned = summary.get("scanned_count", results.get("total_scanned", 0))
    valid    = summary.get("valid_price_count", scanned)
    rejected = summary.get("rejected_bad_price_count", 0)
    duration = results.get("duration_seconds", 0)

    dr = results.get("diagnostics_report", {})
    ma60_cnt   = dr.get("ma60_count", 0)
    strong_cnt = dr.get("strong_trend_count", 0)
    nh_cnt     = dr.get("new_high_count", 0)
    total_sig  = ma60_cnt + strong_cnt + nh_cnt
    avg_score  = dr.get("avg_score", 0)
    top_sectors = dr.get("top_sectors", [])

    lines = [
        "📊 <b>美股扫描结果</b>",
        f"📅 {scan_date}",
        "",
        f"扫描股票：{scanned}只 | 信号：{total_sig}个",
        f"✅ 价格验证通过：{valid}只  ❌ 异常剔除：{rejected}只  ⏱ 耗时：{duration:.0f}秒",
        "",
        "策略分布：",
        f"• {STRATEGY_ZH['ma60_reclaim']}：{ma60_cnt}个",
        f"• {STRATEGY_ZH['strong_trend']}：{strong_cnt}个",
        f"• {STRATEGY_ZH['new_high']}：{nh_cnt}个",
        "",
        f"信号平均评分：{avg_score:.1f}分",
    ]

    if top_sectors:
        lines.append("")
        lines.append("热门行业 Top5：")
        medals = ["①", "②", "③", "④", "⑤"]
        for i, (sector, cnt) in enumerate(top_sectors):
            m = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"  {m} {_zh_sector(sector)} {cnt}只")

    top20 = results.get("top20", [])
    if top20:
        lines += ["", "🏆 <b>综合评分 Top10</b>"]
        for i, s in enumerate(top20[:10], 1):
            strats = s.get("strategies") or []
            strat_tags = "  ".join(_zh_strategy(st) for st in strats)
            lines.append(
                f"{i:2}. <b>{s['symbol']:<5}</b> "
                f"{s['total_score']:4.0f}分  "
                f"{_price_str(s.get('close_price')):>12}  "
                f"{_zh_sector(s.get('sector') or '')[:8]}"
            )
            if strat_tags:
                lines.append(f"     └ {strat_tags}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-message send
# ---------------------------------------------------------------------------

def _chunked_send(messages: list[str]) -> bool:
    ok = True
    for text in messages:
        if not text.strip():
            continue
        if len(text) > TELEGRAM_MAX_CHARS:
            text = text[:TELEGRAM_MAX_CHARS - 25] + "\n<i>...（内容过长已截断）</i>"
        ok &= send_message(text)
    return ok


def send_scan_report(scan_date: str, results: dict) -> bool:
    """
    Send full Chinese scan report as multiple Telegram messages:
      1. Summary (scan stats + diagnostics + Top 10)
      2–4. One message per strategy with detailed stock cards
           — actionable cards (✅) appear first within each section.
    """
    messages: list[str] = []
    messages.append(_format_summary(scan_date, results))

    strategy_map = [
        ("ma60_reclaim", STRATEGY_ZH["ma60_reclaim"]),
        ("strong_trend",  STRATEGY_ZH["strong_trend"]),
        ("new_high",      STRATEGY_ZH["new_high"]),
    ]

    for key, label_zh in strategy_map:
        picks = results.get(key, [])
        if not picks:
            continue

        # Count actionable for section header info
        actionable_n = sum(
            1 for s in picks
            if (s.get("entry_plan") or {}).get("action_status") == "可关注买点"
        )
        header = (
            f"{STRATEGY_EMOJI.get(key, '')} <b>{label_zh} — Top {len(picks)}</b>"
            f"（可买入 {actionable_n} 个）"
        )

        section_parts = [header, "━" * 20]
        for sig in picks:
            section_parts.append(_format_stock_card(sig, key))
            section_parts.append("━" * 20)

        section_text = "\n".join(section_parts)

        if len(section_text) > TELEGRAM_MAX_CHARS:
            messages.append(header)
            for sig in picks:
                messages.append(_format_stock_card(sig, key))
        else:
            messages.append(section_text)

    ok = _chunked_send(messages)
    if ok:
        logger.info(f"Telegram scan report sent ({len(messages)} messages)")
    return ok


# ---------------------------------------------------------------------------
# Low-level
# ---------------------------------------------------------------------------

def send_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping")
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


def send_error(error_msg: str) -> bool:
    text = f"<b>❌ Market Hunter 错误</b>\n\n<code>{error_msg}</code>"
    return send_message(text)
