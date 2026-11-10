"""Truthful fallbacks for optional dashboard render steps.

A fallback receives the page as it was before the failed step and returns a
page that does not present stale base-page content as current: the affected
part becomes a quiet, local "unavailable" placeholder. Fallbacks never insert
values. When a fallback cannot locate what it must neutralize it raises
``FallbackUnavailable`` and the caller treats the step as hard.
"""

from __future__ import annotations

import re
from typing import Callable

from scripts.dashboard_repair.htmlutil import balanced_element_end

TOP_DRIVERS_ANCHOR = '<div class="stitle">Top Market Drivers</div>'
X_SIGNAL_ANCHOR = '<div class="x-signal">'
LAST24_START = '<div class="last24"'
NEWS_UNAVAILABLE = "News unavailable for this edition."
SCORE_UNAVAILABLE = "Score unavailable"
COUNTRY_KEYS = ("us", "ca", "au", "nz", "ea", "jp")

LAST_REFRESHED_RE = re.compile(r"Last refreshed\s+\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}[^<]*", re.I)
LAST_SCANNED_BLOCK_RE = re.compile(
    r'<div class="scanline"><b>Last scanned:</b>.*?</div>',
    re.S | re.I,
)
NEWS_WINDOW_SCAN_RE = re.compile(
    r'<div class="news-window"><b>Last scanned:</b>.*?</div>',
    re.S | re.I,
)
SOURCES_REUTERS_RE = re.compile(r"Sources include Reuters[^<]*", re.I)
LAST24_ITEM_RE = re.compile(r'<a class="last24-item"[^>]*>.*?</a>', re.S)
DRIVER_CARD_RE = re.compile(r'<a class="driver-card"[^>]*>.*?</a>', re.S)
STORY_RE = re.compile(r"<details class=\"story\".*?</details>", re.S)
FRONT_ALERT_RE = re.compile(
    r'<div class="news-alert market-alert"[^>]*>.*?'
    r'(<label for="p-news">Open News &amp; Research</label>\s*</div>|</div>\s*</div>)',
    re.S,
)
SCORE_NUM_RE = re.compile(r'(<span class="score-num">)([^<]*)(</span>)')
SCORE_OVERVIEW_MARKER = '<div class="stitle">Temperature Board</div>'
TEMP_BOARD_REGION_RE = re.compile(
    r'<div class="stitle">Temperature Board</div>.*?<div class="stitle">Momentum Watch</div>',
    re.S,
)


class FallbackUnavailable(RuntimeError):
    pass


def _idempotent(html: str, marker: str) -> bool:
    return f'data-component-state="unavailable"' in html and marker in html


def _last24_placeholder() -> str:
    return (
        '<div class="last24" data-component-state="unavailable">\n'
        '  <div class="last24-head">\n'
        "    <div>\n"
        '      <div class="stitle">Last 24 Hours · Desk Summary</div>\n'
        f"      <p>{NEWS_UNAVAILABLE}</p>\n"
        "    </div>\n"
        "  </div>\n"
        "</div>\n"
    )


def _rolling_news_placeholder() -> str:
    return (
        f"{TOP_DRIVERS_ANCHOR}\n"
        '<div class="news-rollup-unavailable" data-component-state="unavailable">\n'
        '  <div class="stitle">Accepted Overnight Research · Age Unverified</div>\n'
        f"  <p>{NEWS_UNAVAILABLE}</p>\n"
        "</div>\n"
    )


def _front_alert_placeholder() -> str:
    return (
        '<div class="news-alert market-alert" data-news-state="unavailable" '
        'data-component-state="unavailable">\n'
        "<div>\n"
        "<h3>Market news</h3>\n"
        f"<p>{NEWS_UNAVAILABLE}</p>\n"
        "</div>\n"
        '<label for="p-news">Open News &amp; Research</label>\n'
        "</div>"
    )


def _scrub_stale_news_labels(html: str) -> str:
    out = LAST_REFRESHED_RE.sub("", html)
    out = LAST_SCANNED_BLOCK_RE.sub("", out)
    out = NEWS_WINDOW_SCAN_RE.sub(
        '<div class="news-window"><b>News commentary:</b> unavailable for this edition.</div>',
        out,
    )
    out = SOURCES_REUTERS_RE.sub("", out)
    out = LAST24_ITEM_RE.sub("", out)
    return out


def _replace_last24_block(html: str) -> str:
    idx = html.find(LAST24_START)
    if idx < 0:
        return html
    end = balanced_element_end(html, idx)
    return html[:idx] + _last24_placeholder() + html[end:]


def _replace_rolling_region(html: str) -> str:
    if TOP_DRIVERS_ANCHOR not in html:
        return html
    start = html.find(TOP_DRIVERS_ANCHOR)
    end = html.find(X_SIGNAL_ANCHOR, start)
    if end < 0:
        raise FallbackUnavailable("rolling news region end anchor missing")
    return html[:start] + _rolling_news_placeholder() + html[end:]


def _replace_front_alert(html: str) -> str:
    match = FRONT_ALERT_RE.search(html)
    if match:
        return html[: match.start()] + _front_alert_placeholder() + html[match.end() :]
    anchor = '<div class="news-alert market-alert">'
    idx = html.find(anchor)
    if idx < 0:
        return html
    end = balanced_element_end(html, idx)
    return html[:idx] + _front_alert_placeholder() + html[end:]


def news_unavailable(html: str, *, reason: str = "") -> str:
    del reason
    if _idempotent(html, 'data-news-state="unavailable"') and "Accepted Overnight Research · Age Unverified" in html:
        return html
    if TOP_DRIVERS_ANCHOR not in html and LAST24_START not in html and "news-alert market-alert" not in html:
        raise FallbackUnavailable("no news regions to neutralize")
    out = _replace_last24_block(html)
    out = _replace_rolling_region(out)
    out = _replace_front_alert(out)
    out = DRIVER_CARD_RE.sub("", out)
    out = STORY_RE.sub("", out)
    out = _scrub_stale_news_labels(out)
    if LAST_REFRESHED_RE.search(out):
        raise FallbackUnavailable("Last refreshed label survived news_unavailable")
    if "Last refreshed 18 Sep 2026" in out:
        raise FallbackUnavailable("stale static news survived")
    return out


def _score_board_placeholder() -> str:
    return (
        '<div data-score-overview="calibrated" class="score-overview-unavailable" '
        'data-component-state="unavailable" style="margin:0 0 18px;padding:12px;'
        'border:1px solid currentColor;border-radius:10px;">'
        "<b>Live 1–100 Score Board</b>"
        f"<p>{SCORE_UNAVAILABLE}</p></div>"
        '<div class="stitle">Macro Snapshot</div>'
    )


def _neutralize_score_numbers(html: str) -> str:
    def sub_num(match: re.Match[str]) -> str:
        inner = match.group(2).strip()
        if inner in ("—", "n/a", SCORE_UNAVAILABLE):
            return match.group(0)
        return f"{match.group(1)}{SCORE_UNAVAILABLE}{match.group(3)}"

    html = SCORE_NUM_RE.sub(sub_num, html)
    html = re.sub(
        r'(<span class="evidence-value">)([^<]+)(</span>)',
        lambda m: m.group(0)
        if m.group(2).strip() in ("n/a", SCORE_UNAVAILABLE)
        else f"{m.group(1)}{SCORE_UNAVAILABLE}{m.group(3)}",
        html,
    )
    return html


def _replace_score_overview_div(html: str, marker: str) -> str:
    idx = html.find(marker)
    if idx < 0:
        return html
    start = html.rfind("<div", 0, idx)
    if start < 0:
        raise FallbackUnavailable("score overview container missing")
    end = balanced_element_end(html, start)
    block = _score_board_placeholder()
    return html[:start] + block + html[end:]


def scores_unavailable(html: str, *, reason: str = "") -> str:
    del reason
    if (
        'class="score-overview-unavailable"' in html
        and 'data-score-overview="calibrated"' in html
        and 'data-component-state="unavailable"' in html
        and SCORE_OVERVIEW_MARKER not in html
    ):
        return html
    if (
        SCORE_OVERVIEW_MARKER not in html
        and 'data-score-overview="calibrated"' not in html
        and 'data-score-overview="live"' not in html
    ):
        raise FallbackUnavailable("score board anchor missing")
    out = html
    if TEMP_BOARD_REGION_RE.search(out):
        out = TEMP_BOARD_REGION_RE.sub(
            _score_board_placeholder() + '<div class="stitle">Momentum Watch</div>',
            out,
            count=1,
        )
    elif SCORE_OVERVIEW_MARKER in out:
        out = out.replace(SCORE_OVERVIEW_MARKER, _score_board_placeholder(), 1)
    else:
        for marker in ('data-score-overview="live"', 'data-score-overview="calibrated"'):
            if marker in out:
                out = _replace_score_overview_div(out, marker)
                break
    out = _neutralize_score_numbers(out)
    if 'data-score-overview="calibrated"' not in out and 'data-score-overview="live"' not in out:
        raise FallbackUnavailable("score overview anchor missing after scores_unavailable")
    return out


def _country_placeholder(key: str) -> str:
    return (
        f'<div class="temp-inputs country-detail-unavailable" data-country-detail-state="unavailable" '
        f'data-component-state="unavailable" data-country-key="{key}">\n'
        f"<p>Country detail unavailable for this edition.</p>\n"
        "</div>"
    )


def _replace_temp_inputs(html: str, key: str) -> str:
    anchor = f'<div class="cdetail {key}">'
    start = html.find(anchor)
    if start < 0:
        return html
    temp = '<div class="temp-inputs"'
    rel = html.find(temp, start)
    if rel < 0:
        insert = start + len(anchor)
        return html[:insert] + "\n" + _country_placeholder(key) + html[insert:]
    end = balanced_element_end(html, rel)
    return html[:rel] + _country_placeholder(key) + html[end:]


def country_detail_unavailable(html: str, *, reason: str = "") -> str:
    del reason
    if not any(f'<div class="cdetail {key}">' in html for key in COUNTRY_KEYS):
        raise FallbackUnavailable("no country detail containers")
    present = [key for key in COUNTRY_KEYS if f'<div class="cdetail {key}">' in html]
    if present and all(
        f'data-country-detail-state="unavailable" data-component-state="unavailable" data-country-key="{key}"'
        in html
        for key in present
    ):
        return html
    out = html
    touched = False
    for key in COUNTRY_KEYS:
        if f'<div class="cdetail {key}">' not in out:
            continue
        out = _replace_temp_inputs(out, key)
        touched = True
    if not touched:
        raise FallbackUnavailable("country detail blocks missing")
    return out


def legacy_patch_skipped(html: str, *, reason: str = "") -> str:
    """Legacy static patch (v10/v11/Sep 18). Its absence leaves dated archive text only.

    Dated central-bank research cards and KPI rows remain labeled by ``data-date``;
    undated legacy scan lines are removed so nothing undated claims freshness.
    """
    del reason
    out = _scrub_stale_news_labels(html)
    out = LAST_SCANNED_BLOCK_RE.sub("", out)
    return out


FALLBACKS: dict[str, Callable[..., str]] = {
    "legacy_patch_skipped": legacy_patch_skipped,
    "news_unavailable": news_unavailable,
    "scores_unavailable": scores_unavailable,
    "country_detail_unavailable": country_detail_unavailable,
}


def apply_fallback(name: str, html: str, *, reason: str = "") -> str:
    try:
        fn = FALLBACKS[name]
    except KeyError as exc:
        raise FallbackUnavailable(f"unknown fallback {name!r}") from exc
    return fn(html, reason=reason)
