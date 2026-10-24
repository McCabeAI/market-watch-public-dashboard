"""Post-build dashboard repair. Runs after the legacy tab patches.

Legacy apply steps keep their string anchors. This pass replaces the tape,
score board, country jumps, redundant tabs, Releases, and Sources on the
finished HTML.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.dashboard_repair.brief import format_freeze_day, format_packet_time, render_brief
from scripts.dashboard_repair.calendar_view import build_release_model, render_releases
from scripts.dashboard_repair.htmlutil import balanced_element_end, esc, replace_element_containing
from scripts.dashboard_repair.scoreboard import render_scoreboard
from scripts.dashboard_repair.source_health import build_source_health_snapshot, load_latest_ingest
from scripts.dashboard_repair.sources_view import render_sources
from scripts.dashboard_repair.tape import render_tape, tape_cards
from scripts.macro_ingestion.contract import load_catalog

ROOT = Path(__file__).resolve().parents[2]

CSS = """
<style id="dashboard-repair-css">
.tape-banner{font-size:13px;line-height:1.45}
.tape-card .sub{font-size:12px;line-height:1.35}
.tape-card .val{font-size:20px}
.scoreboard{margin:0 0 18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#fff}
.scoreboard-head{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
.scoreboard-head b{font-size:18px}
.scoreboard-head span,.score-headline,.score-mean,.score-cov{font-size:14px;line-height:1.4}
.scoreboard-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.score-card{border:1px solid var(--line);border-radius:8px;padding:10px;background:#fbfcfd}
.score-card h3{margin:0 0 6px;font-size:16px}
.score-dim{display:grid;grid-template-columns:minmax(88px,1.1fr) auto auto;gap:6px 8px;align-items:center;margin-top:8px;font-size:14px}
.score-dim-name{font-weight:750}
.score-cov{grid-column:1 / -1;color:var(--muted);font-size:12px}
.score-bar{grid-column:1 / -1;display:block;height:8px;background:#e6eef2;border-radius:4px;overflow:hidden}
.score-bar i{display:block;height:100%}
.score-bar i.cold{background:var(--cold)}.score-bar i.cool{background:var(--cool)}.score-bar i.neutral{background:var(--neutral)}.score-bar i.warm{background:var(--warm)}.score-bar i.hot{background:var(--hot)}
button.jump{width:100%;font:inherit;color:inherit;min-height:44px;font-size:14px}
.jump:focus,.nav label:focus,.country-switch label:focus{outline:2px solid var(--navy);outline-offset:2px}
#country-detail{scroll-margin-top:64px}
.release-card,.source-summary{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;margin:0 0 8px}
.release-card header{font-size:15px}
.release-card p,.release-card li,.source-country li{font-size:14px;line-height:1.4}
.release-day h3{margin:12px 0 6px;font-size:14px}
.source-country{margin:0 0 8px}
#source-filter{min-height:44px;width:min(100%,420px);font-size:16px}
.research-debate{margin:0 0 12px}
.debate-card{border:1px solid var(--line);border-radius:8px;padding:10px;margin:8px 0;background:#fff}
.debate-card h3{margin:0 0 4px;font-size:15px}
.debate-grid{display:grid;gap:8px}
@media(min-width:800px){.debate-grid{grid-template-columns:1fr 1fr}}
@media(max-width:720px){
 .nav{height:48px;flex-wrap:nowrap;overflow-x:auto;align-items:center}
 .nav label{height:auto;padding:8px 0;font-size:14px}
 .score-dim{grid-template-columns:1fr}
}
.topbar .meta{display:block}
.topbar{align-items:flex-end;gap:12px}
.stamp{background:var(--mw-panel-2);color:var(--mw-ink-2);border-color:var(--mw-line)}
.desk-brief{margin:0 0 12px}
.desk-brief-head h2{margin:0 0 6px;font-size:var(--mw-fs-title,16px);font-weight:750}
.desk-brief-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.brief-block{background:var(--mw-panel);border:1px solid var(--mw-line);border-radius:var(--mw-r,8px);padding:8px 10px;min-width:0}
.brief-block h3{margin:0 0 4px;font-size:13px;font-weight:750;display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center}
.brief-caption,.brief-sub{margin:0 0 4px;font-size:12px;line-height:1.3;color:var(--mw-muted)}
.brief-sub{font-weight:700;color:var(--mw-ink-2)}
.brief-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}
.brief-list li{min-width:0;display:flex;flex-wrap:wrap;gap:2px 8px;align-items:baseline}
.brief-list .mw-asof{white-space:normal}
.desk-brief button.jump{width:auto;min-height:40px;display:flex;flex-wrap:wrap;gap:2px 8px;align-items:baseline;text-align:left;padding:4px 6px;background:transparent;border:0;border-radius:6px}
.desk-brief button.jump:hover{background:var(--mw-panel-3)}
.brief-k{font-weight:750}
.brief-name{min-width:0;overflow-wrap:anywhere}
.brief-impulse,.brief-level,.brief-value{font-variant-numeric:tabular-nums}
.brief-tab{display:inline-flex;align-items:center;min-height:40px;color:var(--mw-accent);font-weight:700;cursor:pointer}
.imp-warming{color:var(--mw-warming)} .imp-cooling{color:var(--mw-cooling)} .imp-static{color:var(--mw-static)}
.mw-tape{min-width:0}
.mw-tape .tape{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:8px;margin:8px 0 14px}
.tape-card{display:flex;flex-direction:column;gap:2px;min-width:0;padding:8px 10px;min-height:132px;background:var(--mw-panel);border:1px solid var(--mw-line);border-radius:8px}
.tape-card .lab{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--mw-muted)}
.tape-card .val{font-size:20px;font-weight:750;line-height:1.15}
.tape-change{font-size:13px;font-variant-numeric:tabular-nums}
.tape-change-missing{color:var(--mw-muted)}
.tape-more{background:transparent;border:0;padding:0;margin-top:4px}
.tape-more summary{font-size:12px;min-height:32px;color:var(--mw-accent)}
.tape-more p{font-size:12px;color:var(--mw-muted);overflow-wrap:anywhere}
.scoreboard{background:var(--mw-panel);border:1px solid var(--mw-line);color:var(--mw-ink)}
.score-scroll{overflow-x:auto;max-width:100%}
.score-matrix{width:100%;border-collapse:collapse}
.score-matrix tbody tr:nth-child(odd),.score-matrix tbody tr:nth-child(even),.score-matrix tbody tr:hover{background:transparent}
.score-matrix th,.score-matrix td{white-space:normal;text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--mw-line);background:transparent;font-size:13px;color:var(--mw-ink)}
.score-matrix thead th{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--mw-muted)}
.lvl-num{font-size:18px;font-weight:750;display:block}
.lvl-scale{font-size:11px;color:var(--mw-muted)}
.imp-line{display:flex;flex-wrap:wrap;gap:2px 6px;align-items:baseline;font-size:12px;margin-top:2px}
.score-matrix .mw-asof{white-space:normal}
.score-bar{display:block;height:3px;background:var(--mw-panel-3);border-radius:2px;overflow:hidden;margin:3px 0}
.score-bar i{display:block;height:100%}
.score-peak{display:block;margin-top:3px;font-size:11px;font-weight:750;letter-spacing:.03em;text-transform:uppercase;color:var(--mw-warn)}
.score-legend{margin:0 0 8px;font-size:12.5px;line-height:1.35;color:var(--mw-muted)}
.scoreboard button.jump{width:auto;min-height:40px;padding:6px 10px}
.mw-archived{margin:12px 0;padding:8px 12px;background:var(--mw-panel);border:1px solid var(--mw-warn);border-radius:8px;max-width:100%;overflow-x:auto}
.mw-archived > summary{color:var(--mw-warn);font-weight:750;min-height:40px;cursor:pointer}
.mw-archived .kpi,.mw-archived .ladvals span,.mw-archived .thermo,.mw-archived details{background:var(--mw-panel-2);color:var(--mw-ink)}
.app,.wrap,.page,.cdetail{min-width:0;max-width:100%}
.news-alert{grid-template-columns:auto minmax(0,1fr) auto;background:var(--mw-panel);color:var(--mw-ink);border:1px solid var(--mw-line);border-left:4px solid var(--mw-warn)}
.news-alert h3{color:var(--mw-ink)}
.news-alert p,.news-alert .alert-sub{color:var(--mw-muted)}
.news-alert .flag{color:var(--mw-warn)}
.news-alert label{background:var(--mw-panel-3);color:var(--mw-ink)}
.news-alert h3,.news-alert p{overflow-wrap:anywhere}
.country-switch label{background:var(--mw-panel-2);color:var(--mw-ink);border-color:var(--mw-line)}
.country-detail .cd-vintage{white-space:normal;overflow-wrap:anywhere}
button:focus-visible,.jump:focus-visible,summary:focus-visible,.brief-tab:focus-visible,label:focus-visible{outline:2px solid var(--mw-focus);outline-offset:2px}
@media(max-width:1200px){
 .desk-brief-grid{grid-template-columns:1fr 1fr}
}
@media(max-width:720px){
 .topbar{flex-direction:column;align-items:flex-start}
 .topbar .meta{text-align:left}
 .desk-brief-grid{grid-template-columns:1fr}
 .mw-tape .tape{display:flex;flex-wrap:nowrap;overflow-x:auto;max-width:100%}
 .mw-tape .tape-card{flex:0 0 160px}
 .score-matrix thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
 .score-matrix,.score-matrix tbody,.score-matrix tr,.score-matrix td,.score-matrix th{display:block;width:auto}
 .score-matrix tr{display:grid;grid-template-columns:1fr 1fr;gap:6px;border:1px solid var(--mw-line);border-radius:8px;margin:0 0 8px;padding:8px;background:var(--mw-panel-2)}
 .score-matrix tbody tr:nth-child(odd),.score-matrix tbody tr:nth-child(even),.score-matrix tbody tr:hover{background:var(--mw-panel-2)}
 .country-detail .score-compact{grid-template-columns:1fr 1fr}
 .score-matrix th[scope="row"],.score-matrix .score-mean-cell,.score-matrix .score-open{grid-column:1 / -1}
 .news-alert{grid-template-columns:1fr}
 .news-alert label{white-space:normal}
}
</style>
"""

SCRIPT = """
<script id="dashboard-repair-script">
(function () {
  "use strict";
  function go(code) {
    var page = document.getElementById("p-country");
    var country = document.getElementById("c-" + code);
    if (page) page.checked = true;
    if (country) country.checked = true;
    var section = document.getElementById("country-detail");
    if (section && section.scrollIntoView) section.scrollIntoView({block: "start"});
    var label = document.querySelector('label[for="c-' + code + '"]');
    if (label && label.focus) label.focus();
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".country-jump") : null;
    if (!btn) return;
    ev.preventDefault();
    go(btn.getAttribute("data-country"));
  });
  var filter = document.getElementById("source-filter");
  if (filter) {
    filter.addEventListener("input", function () {
      var query = filter.value.toLowerCase();
      document.querySelectorAll("[data-source-row]").forEach(function (row) {
        row.hidden = query && row.textContent.toLowerCase().indexOf(query) < 0;
      });
    });
  }
  function escText(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
  function debateCards(packet) {
    return (packet.trades || []).map(function (row) {
      var trade = row.trade || {};
      var rebuttal = row.rebuttal || {};
      var rebuttalText = [rebuttal.trade_change, rebuttal.strongest_opponent_point].filter(Boolean).join(" ");
      return '<article class="debate-card" data-debate-card="1"><h3>' + escText(row.agent) + '</h3>'
        + '<p><b>' + escText(trade.instrument || "No trade") + '</b> ' + escText(trade.direction || "")
        + (trade.expression ? ' · ' + escText(trade.expression) : '')
        + (trade.horizon ? ' · ' + escText(trade.horizon) : '') + '</p>'
        + '<p><b>Why</b> ' + escText(row.entry_reason || "") + '</p>'
        + (row.mispricing ? '<p><b>Mispricing</b> ' + escText(row.mispricing) + '</p>' : '')
        + (rebuttalText ? '<p><b>Rebuttal</b> ' + escText(rebuttalText) + '</p>' : '')
        + '<p>Confidence ' + escText(row.confidence === null || row.confidence === undefined ? "—" : row.confidence) + '</p></article>';
    }).join("");
  }
  var debate = document.getElementById("research-debate");
  if (!debate) return;
  fetch("trader-room.json", {cache: "no-store"}).then(function (response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function (packet) {
    var trades = packet && packet.trades;
    if (!packet || packet.available !== true || packet.seat_count !== 14 || !trades || trades.length !== 14) {
      if (!debate.querySelector("[data-debate-card]")) debate.remove();
      return;
    }
    debate.hidden = false;
    var body = document.getElementById("research-debate-body");
    if (!body) return;
    body.innerHTML = '<p class="note">Research archive ' + escText(packet.run_id || "")
      + ', evidence ' + escText(packet.as_of || "date not recorded")
      + '. Separate from accepted Trader Book decisions. Not a book instruction.</p><div class="debate-grid">'
      + debateCards(packet) + '</div>';
  }).catch(function () {
    if (!debate.querySelector("[data-debate-card]")) debate.remove();
  });
})();
</script>
"""


def _marker_outside_style(html: str, marker: str) -> int:
    """Find a markup anchor, skipping copies that live in style or script text."""
    cursor = 0
    while True:
        index = html.find(marker, cursor)
        if index < 0:
            return -1
        style = html.rfind("<style", 0, index)
        if style >= 0 and html.find("</style>", style) > index:
            cursor = html.find("</style>", style) + len("</style>")
            continue
        script = html.rfind("<script", 0, index)
        if script >= 0 and html.find("</script>", script) > index:
            cursor = html.find("</script>", script) + len("</script>")
            continue
        return index


def _replace_balanced_marker(html: str, marker: str, replacement: str) -> str:
    index = _marker_outside_style(html, marker)
    if index < 0:
        raise ValueError(f"missing {marker}")
    start = html.rfind("<", 0, index)
    end = balanced_element_end(html, start)
    return html[:start] + replacement + html[end:]


def _replace_tape(html: str, packet: dict[str, Any] | None) -> str:
    replacement = render_tape(packet)
    if 'data-global-tape="repair"' in html:
        return _replace_balanced_marker(html, 'data-global-tape="repair"', replacement)
    marker = "Global Tape"
    if marker not in html:
        raise ValueError("Global Tape anchor missing")
    start = html.rfind('<div class="stitle">', 0, html.find(marker))
    tape = html.find('<div class="tape">', start)
    if tape < 0:
        raise ValueError("tape grid missing")
    end = balanced_element_end(html, tape)
    return html[:start] + replacement + html[end:]


def _replace_scoreboard(html: str, state: dict[str, Any]) -> str:
    replacement = render_scoreboard(state)
    if 'data-score-overview="calibrated"' in html:
        return _replace_balanced_marker(html, 'data-score-overview="calibrated"', replacement)
    if 'data-score-overview="live"' in html:
        return _replace_balanced_marker(html, 'data-score-overview="live"', replacement)
    raise ValueError("score overview anchor missing")


def _country_jumps(html: str) -> str:
    pattern = re.compile(
        r'<label class="jump" for="(c-[a-z]{2})">([^<]*)</label>',
    )

    def swap(match: re.Match[str]) -> str:
        code = match.group(1).split("-", 1)[1]
        label = match.group(2)
        return (
            f'<button type="button" class="jump country-jump" data-country="{esc(code)}" '
            f'aria-controls="country-detail">{label}</button>'
        )

    return pattern.sub(swap, html)


def _section_bounds(html: str, class_name: str) -> tuple[int, int] | None:
    marker = f'<section class="page {class_name}'
    start = html.find(marker)
    if start < 0:
        return None
    end = balanced_element_end(html, start)
    return start, end


def _remove_section(html: str, class_name: str) -> str:
    bounds = _section_bounds(html, class_name)
    if bounds is None:
        return html
    return html[: bounds[0]] + html[bounds[1] :]


def _replace_section(html: str, class_name: str, replacement: str) -> str:
    bounds = _section_bounds(html, class_name)
    if bounds is None:
        raise ValueError(f"{class_name} section missing")
    return html[: bounds[0]] + replacement + html[bounds[1] :]


def _remove_nav(html: str) -> str:
    for radio_id in ("p-feed", "p-relative", "p-traderroom"):
        html = re.sub(
            rf'\s*<input\b[^>]*\bid="{radio_id}"[^>]*>',
            "",
            html,
            count=1,
        )
        html = re.sub(
            rf'<label\b[^>]*\bfor="{radio_id}"[^>]*>.*?</label>',
            "",
            html,
            count=1,
        )
    for class_name in ("feed", "relative", "traderroom"):
        html = _remove_section(html, class_name)
    return html


def _remove_momentum(html: str) -> str:
    """Drop the static Momentum Watch grid. There is no maintained replacement series."""
    note = (
        '<p class="note" data-momentum="removed">The static multi-horizon run-rate table was removed. '
        "It was a September base-page snapshot, not a score-ledger or market-state series. "
        "Current dimension levels are on the scoreboard. Dated releases are on the Releases tab.</p>"
    )
    for marker in ("Momentum Watch", "base-page snapshot"):
        index = html.find(marker)
        if index < 0:
            continue
        start = html.rfind('<div class="grid2">', 0, index)
        if start < 0:
            continue
        end = balanced_element_end(html, start)
        html = html[:start] + note + html[end:]
        break
    lone = '<div class="stitle">Momentum Watch</div>'
    if lone in html:
        html = html.replace(lone, note, 1)
    return html


def _annotate_static_front(html: str) -> str:
    html = _remove_momentum(html)
    catalysts = '<div class="stitle" style="margin-top:10px">Next Catalysts</div>'
    if catalysts in html:
        start = html.find(catalysts)
        grid = html.find('<div class="catalysts">', start)
        if grid > 0:
            end = balanced_element_end(html, grid)
            html = (
                html[:start]
                + '<div class="stitle" style="margin-top:10px">Next releases</div>'
                + '<p class="note">Dated official releases are on the Releases tab. The old September catalyst list is not kept here.</p>'
                + html[end:]
            )
    if 'id="country-detail"' not in html:
        html = html.replace('<section class="page country">', '<section class="page country" id="country-detail">', 1)
    return html


def _debate_text(value: object) -> str:
    return esc(value)


def render_debate_html(packet: dict[str, Any] | None) -> str:
    """Read-only 14-seat debate. Incomplete packets produce no control."""
    shell = (
        '<details id="research-debate" class="research-debate" hidden>'
        "<summary>View research debate</summary>"
        '<div id="research-debate-body"></div></details>'
    )
    if packet is None:
        return shell
    trades = packet.get("trades")
    if (
        packet.get("available") is not True
        or packet.get("seat_count") != 14
        or not isinstance(trades, list)
        or len(trades) != 14
    ):
        return ""
    cards = []
    for row in trades:
        if not isinstance(row, dict):
            continue
        trade = row.get("trade") if isinstance(row.get("trade"), dict) else {}
        rebuttal = row.get("rebuttal") if isinstance(row.get("rebuttal"), dict) else {}
        rebuttal_text = " ".join(
            part
            for part in (
                str(rebuttal.get("trade_change") or "").strip(),
                str(rebuttal.get("strongest_opponent_point") or "").strip(),
            )
            if part
        )
        instrument = trade.get("instrument") or "No trade"
        cards.append(
            '<article class="debate-card" data-debate-card="1">'
            f'<h3>{_debate_text(row.get("agent"))}</h3>'
            f'<p><b>{_debate_text(instrument)}</b> {_debate_text(trade.get("direction") or "")}'
            + (f' · {_debate_text(trade.get("expression"))}' if trade.get("expression") else "")
            + (f' · {_debate_text(trade.get("horizon"))}' if trade.get("horizon") else "")
            + "</p>"
            f'<p><b>Why</b> {_debate_text(row.get("entry_reason") or "")}</p>'
            + (f'<p><b>Mispricing</b> {_debate_text(row.get("mispricing"))}</p>' if row.get("mispricing") else "")
            + (f'<p><b>Rebuttal</b> {_debate_text(rebuttal_text)}</p>' if rebuttal_text else "")
            + f'<p>Confidence {_debate_text(row.get("confidence") if row.get("confidence") is not None else "—")}</p>'
            "</article>"
        )
    if len(cards) != 14:
        return ""
    return (
        '<details id="research-debate" class="research-debate">'
        "<summary>View research debate</summary>"
        f'<p class="note">Research archive {_debate_text(packet.get("run_id") or "")}, '
        f'evidence {_debate_text(packet.get("as_of") or "date not recorded")}. '
        "Separate from accepted Trader Book decisions. Not a book instruction.</p>"
        f'<div id="research-debate-body" class="debate-grid">{"".join(cards)}</div></details>'
    )


def _research_link(html: str, packet: dict[str, Any] | None) -> str:
    block = render_debate_html(packet)
    marker = '<div id="trader-book-root"'
    if 'id="research-debate"' in html:
        if not block:
            start = html.find('<details id="research-debate"')
            if start < 0:
                return html
            end = balanced_element_end(html, start)
            return html[:start] + html[end:]
        return replace_element_containing(html, 'id="research-debate"', block)
    if not block or marker not in html:
        return html
    return html.replace(marker, block + marker, 1)


THEME_PATH = Path(__file__).resolve().parent / "theme.css"


def theme_css() -> str:
    return '<style id="mw-theme-css">\n' + THEME_PATH.read_text(encoding="utf-8") + "\n</style>\n"


def _style_and_script(html: str) -> str:
    if 'id="dashboard-repair-css"' in html:
        html = replace_element_containing(html, 'id="dashboard-repair-css"', CSS)
    elif "</head>" in html:
        html = html.replace("</head>", CSS + "</head>", 1)
    if 'id="mw-theme-css"' in html:
        html = replace_element_containing(html, 'id="mw-theme-css"', theme_css())
    elif "</head>" in html:
        html = html.replace("</head>", theme_css() + "</head>", 1)
    if 'id="dashboard-repair-script"' in html:
        html = replace_element_containing(html, 'id="dashboard-repair-script"', SCRIPT)
    elif "</body>" in html:
        html = html.replace("</body>", SCRIPT + "</body>", 1)
    if 'data-dashboard-repair="applied"' not in html:
        html = html.replace("<body>", '<body data-dashboard-repair="applied">', 1)
    return html


def _inside_archived(html: str, index: int) -> bool:
    opener = html.rfind('<details class="mw-archived"', 0, index)
    if opener < 0:
        return False
    return "</details>" not in html[opener:index]


def _fence_macro_snapshot(html: str) -> str:
    """Collapse the undated September country cards. Jump buttons stay in the HTML."""
    marker = '<div class="stitle">Macro Snapshot</div>'
    start = html.find(marker)
    if start < 0 or _inside_archived(html, start):
        return html
    ends = []
    for token in ('<div class="grid2">', 'data-momentum="removed"', "</section>"):
        pos = html.find(token, start)
        if pos >= 0:
            ends.append(pos)
    if not ends:
        return html
    end = min(ends)
    summary = "September base-page country snapshot — not refreshed; figures may be superseded"
    wrapped = (
        '<details class="mw-archived"><summary>'
        + esc(summary)
        + "</summary>"
        + html[start:end]
        + "</details>"
    )
    return html[:start] + wrapped + html[end:]


def _replace_header(html: str, packet: dict[str, Any] | None, scores: dict[str, Any]) -> str:
    header = html.find('<header class="topbar">')
    if header >= 0:
        meta = html.find('<div class="meta">', header)
        header_end = html.find("</header>", header)
        if meta >= 0 and (header_end < 0 or meta < header_end):
            end = balanced_element_end(html, meta)
            when = format_packet_time(packet.get("generated_at")) if isinstance(packet, dict) else ""
            if not when:
                when = "Market packet time unavailable"
            freeze = format_freeze_day(scores.get("as_of"))
            freeze_line = f"Scores frozen {freeze}" if freeze else "Score freeze date unavailable"
            replacement = (
                '<div class="meta">'
                f'<b class="mw-asof">{esc(when)}</b><br/>'
                f'<span class="mw-asof">{esc(freeze_line)}</span><br/>'
                "Dated official data · not a quote feed"
                "</div>"
            )
            html = html[:meta] + replacement + html[end:]
    html = html.replace(
        '<span class="stamp">public snapshot</span>',
        '<span class="stamp">Daily research snapshot</span>',
        1,
    )
    html = html.replace(
        "Public-data prototype · CAD / AUD / NZD focus · US benchmark · level and direction separated",
        "Six economies · US, CA, AU, NZ, EA, JP",
        1,
    )
    return html


def _insert_brief(html: str, block: str) -> str:
    if _marker_outside_style(html, 'data-desk-brief="repair"') >= 0:
        return replace_element_containing(html, 'data-desk-brief="repair"', block)
    marker = '<section class="page front">'
    index = html.find(marker)
    if index < 0:
        return html
    insert_at = index + len(marker)
    return html[:insert_at] + block + html[insert_at:]


def apply_dashboard_repair(
    html: str,
    *,
    market_state: dict[str, Any] | None,
    scores: dict[str, Any],
    now: datetime,
    audit: dict[str, Any] | None = None,
    series: list[dict[str, Any]] | None = None,
    ingest: dict[str, Any] | None = None,
    trader_room: dict[str, Any] | None = None,
    schedule_fetch: dict[str, Any] | None = None,
    country_detail: dict[str, Any] | None = None,
) -> str:
    del audit
    html = _replace_tape(html, market_state)
    html = _replace_scoreboard(html, scores)
    html = _country_jumps(html)
    html = _annotate_static_front(html)
    html = _fence_macro_snapshot(html)
    html = _remove_nav(html)
    html = _research_link(html, trader_room)
    catalog_series = series if series is not None else load_catalog()["series"]
    model = build_release_model(
        now,
        series=catalog_series,
        score_as_of=str(scores.get("as_of") or "2026-09-21"),
        fetched_slots=(schedule_fetch or {}).get("slots"),
        schedule_fetch=schedule_fetch,
    )
    html = _replace_section(html, "releases", render_releases(model))
    if ingest is None and series is None:
        ingest = load_latest_ingest()
    snapshot = build_source_health_snapshot(catalog_series, ingest, model)
    names = {str(spec.get("id") or ""): str(spec.get("canonical_name") or "").strip() for spec in catalog_series}
    display_rows = [dict(row, canonical_name=names.get(str(row.get("series_id") or ""), "")) for row in snapshot.get("rows") or []]
    html = _replace_section(html, "sources", render_sources(market_state, snapshot, display_rows))
    html = _replace_header(html, market_state, scores)
    html = _insert_brief(
        html,
        render_brief(
            scores=scores,
            tape_cards=tape_cards(market_state),
            packet=market_state,
            calendar=model,
            country_detail=country_detail,
        ),
    )
    html = _style_and_script(html)
    html_result = html
    # Attach the read-models for the publication step without changing the HTML return.
    apply_dashboard_repair.last_snapshot = snapshot  # type: ignore[attr-defined]
    apply_dashboard_repair.last_calendar = model  # type: ignore[attr-defined]
    return html_result


def load_scores(path: Path | None = None) -> dict[str, Any]:
    score_path = path or (ROOT / "data" / "temperature_scores.json")
    payload = json.loads(score_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("temperature score state is not an object")
    return payload
