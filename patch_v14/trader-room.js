(function () {
  "use strict";
  const root = document.getElementById("trader-room-root");
  const meta = document.getElementById("tr-meta");
  if (!root || !meta) return;

  function esc(v) {
    return String(v === null || v === undefined ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
  function chip(kind, text) { return '<span class="tr-chip ' + kind + '">' + esc(text) + "</span>"; }

  function render(packet) {
    if (!packet.available) {
      meta.innerHTML = chip("warn", "No published run");
      root.innerHTML = '<div class="tr-panel tr-empty">' + esc(packet.message || "No Trader Room run is available yet.") + "</div>";
      return;
    }
    meta.innerHTML = [
      chip("ok", packet.status || "complete"),
      '<span class="tr-chip">' + esc(packet.run_id || "") + "</span>",
      '<span class="tr-chip">' + esc(packet.as_of || "") + "</span>"
    ].join("");

    const rows = packet.trades || [];
    const cards = rows.map(function (row) {
      const trade = row.trade;
      const tradeHtml = trade ? (
        '<div class="tr-trade"><div class="tr-instrument">' + esc(trade.instrument || "Unspecified") +
        ' · ' + esc(trade.direction || "") + '</div><div class="tr-expression">' +
        esc(trade.expression || trade.structure || "") +
        (trade.horizon ? " · " + esc(trade.horizon) : "") + "</div></div>"
      ) : '<div class="tr-trade tr-no-trade"><b>No-trade recommendation</b></div>';

      const mispricing = row.mispricing ? '<div class="tr-detail"><b>Mispricing:</b> ' + esc(row.mispricing) + "</div>" : "";
      const rebuttal = row.rebuttal ? '<div class="tr-rebuttal"><b>Rebuttal:</b> ' +
        esc(row.rebuttal.trade_change || "") +
        (row.rebuttal.strongest_opponent_point ? " · " + esc(row.rebuttal.strongest_opponent_point) : "") +
        "</div>" : "";
      return '<article class="tr-card"><div class="tr-card-top"><div class="tr-seat">' +
        esc(row.agent) + '</div><div class="tr-confidence">Confidence ' +
        esc(row.confidence === null || row.confidence === undefined ? "—" : row.confidence) +
        "</div></div>" + tradeHtml +
        '<div class="tr-why"><b>Why enter this trade</b><p>' + esc(row.entry_reason || "") +
        "</p></div>" + mispricing + rebuttal + "</article>";
    }).join("");

    root.innerHTML =
      '<section class="tr-panel"><div class="tr-summary">' +
      '<div class="tr-stat"><span>Seats</span><b>' + esc(packet.seat_count) + "</b></div>" +
      '<div class="tr-stat"><span>Trade pitches</span><b>' + esc(packet.trade_count) + "</b></div>" +
      '<div class="tr-stat"><span>Conflicts</span><b>' + esc(packet.conflict_count) + "</b></div>" +
      '<div class="tr-stat"><span>Evidence cutoff</span><b>' + esc(packet.as_of || "—") + "</b></div>" +
      '</div></section><section class="tr-panel"><div class="tr-grid">' + cards + "</div></section>";
  }

  fetch("trader-room.json", {cache:"no-store"})
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(render)
    .catch(function (e) {
      meta.innerHTML = chip("warn", "Trader Room unavailable");
      root.innerHTML = '<div class="tr-panel tr-empty">Trader Room did not load: ' + esc(e.message || "unknown error") + "</div>";
    });
})();
