(function () {
  "use strict";

  const root = document.getElementById("market-data-root");
  const meta = document.getElementById("md-meta");
  if (!root || !meta) return;

  const CURRENCIES = ["USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "NOK", "SEK"];
  const FOCUS_PAIRS = ["USDCAD", "AUDUSD", "NZDUSD", "AUDNZD", "EURUSD", "USDJPY"];
  const RATE_COUNTRIES = ["US", "CA", "AU", "NZ"];
  const RV_GROUPS = ["CA-US", "AU-US", "CA-AU", "NZ-US", "AU-NZ"];
  const HORIZONS = {
    "1D": { fx: "ret_1d", rate: "bp_1d", curve: "chg_1d_bps", rv: "chg_1d_bps" },
    "5D": { fx: "ret_5d", rate: "bp_5d", curve: "chg_5d_bps", rv: "chg_5d_bps" },
    "1M": { fx: "ret_1m", rate: "bp_1m", curve: "chg_1m_bps", rv: "chg_1m_bps" },
    "3M": { fx: "ret_3m", rate: "bp_3m", curve: "chg_3m_bps", rv: "chg_3m_bps" }
  };

  let selectedHorizon = "1D";
  let currentPacket = null;

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function finite(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function fmtNum(value, digits) {
    return finite(value) ? Number(value).toFixed(digits) : "—";
  }

  function fmtSpot(pair, value) {
    if (!finite(value)) return "—";
    return Number(value).toFixed(pair.indexOf("JPY") >= 0 ? 3 : 4);
  }

  function fmtSigned(value, digits, suffix) {
    if (!finite(value)) return "—";
    const n = Number(value);
    return (n > 0 ? "+" : "") + n.toFixed(digits) + (suffix || "");
  }

  function fmtPct(value) {
    return fmtSigned(value, 2, "%");
  }

  function fmtBp(value) {
    return fmtSigned(value, 1, "bp");
  }

  function moveClass(value) {
    if (!finite(value) || Math.abs(value) < 0.00001) return "md-flat";
    return value > 0 ? "md-pos" : "md-neg";
  }

  function shortDate(value) {
    if (!value) return "—";
    const bits = String(value).split("-");
    return bits.length === 3 ? bits[1] + "/" + bits[2] : String(value);
  }

  function shortDateTime(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function percentile(value) {
    return finite(value) ? Math.max(0, Math.min(100, value)) : null;
  }

  function percentileLabel(value) {
    if (!finite(value)) return "—";
    return Math.round(value) + "%ile";
  }

  function chip(text, kind) {
    return '<span class="md-chip ' + esc(kind || "") + '">' + esc(text) + "</span>";
  }

  function pairData(packet, pair) {
    return packet.fx && packet.fx.pairs ? packet.fx.pairs[pair] : null;
  }

  function crossMetric(packet, base, quote, field) {
    if (base === quote) return 0;
    const direct = pairData(packet, base + quote);
    if (direct && finite(direct[field])) return direct[field];
    const inverse = pairData(packet, quote + base);
    if (!inverse || !finite(inverse[field])) return null;
    const r = inverse[field] / 100;
    if (r <= -1) return null;
    return (1 / (1 + r) - 1) * 100;
  }

  function currencyStrength(packet, field) {
    const sums = {};
    const counts = {};
    CURRENCIES.forEach(function (ccy) { sums[ccy] = 0; counts[ccy] = 0; });
    Object.keys((packet.fx && packet.fx.pairs) || {}).forEach(function (pair) {
      const m = packet.fx.pairs[pair];
      if (!m || !finite(m[field])) return;
      const base = pair.slice(0, 3);
      const quote = pair.slice(3, 6);
      const simple = m[field] / 100;
      if (simple <= -1) return;
      const logMove = Math.log1p(simple);
      sums[base] += logMove;
      counts[base] += 1;
      sums[quote] -= logMove;
      counts[quote] += 1;
    });
    return CURRENCIES.map(function (ccy) {
      const avg = counts[ccy] ? sums[ccy] / counts[ccy] : 0;
      return { ccy: ccy, value: (Math.exp(avg) - 1) * 100 };
    }).sort(function (a, b) { return b.value - a.value; });
  }

  function renderMeta(packet) {
    const unavailable = packet.unavailable_sources || [];
    const healthy = unavailable.length === 0 && packet.status === "ok";
    let html = chip(healthy ? "Official packet · fresh" : "Official packet · partial", healthy ? "ok" : "warn");
    html += chip("Generated " + shortDateTime(packet.generated_at), "");
    if (packet.fx && packet.fx.source_observation) html += chip("FX " + shortDate(packet.fx.source_observation), "");
    if (unavailable.length) html += chip("Unavailable: " + unavailable.join(", "), "bad");
    meta.innerHTML = html;
  }

  function horizonBar() {
    const buttons = Object.keys(HORIZONS).map(function (label) {
      return '<button class="md-horizon-btn' + (label === selectedHorizon ? " active" : "") + '" data-horizon="' + label + '" type="button">' + label + "</button>";
    }).join("");
    return '<div class="md-horizonbar"><div class="md-horizon-copy"><b>Move horizon</b> · controls the strength ranking, mover list, heatmap and rate-change columns.</div><div class="md-horizon-controls">' + buttons + "</div></div>";
  }

  function focusCards(packet) {
    const field = HORIZONS[selectedHorizon].fx;
    return '<div class="md-focus-grid">' + FOCUS_PAIRS.map(function (pair) {
      const m = pairData(packet, pair) || {};
      const move = m[field];
      return '<div class="md-focus-card">' +
        '<div class="md-focus-top"><span class="md-pair">' + pair + '</span><span class="md-asof">' + shortDate(m.as_of) + "</span></div>" +
        '<div class="md-spot">' + fmtSpot(pair, m.spot) + "</div>" +
        '<div class="md-focus-move"><span>' + selectedHorizon + ' move</span><b class="' + moveClass(move) + '">' + fmtPct(move) + "</b></div>" +
        '<div class="md-focus-foot"><span>1Y range <strong>' + percentileLabel(m.pctile_1y) + '</strong></span><span>RV20 <strong>' + fmtNum(m.rv_20d, 1) + "%</strong></span></div>" +
        "</div>";
    }).join("") + "</div>";
  }

  function strengthPanel(packet) {
    const field = HORIZONS[selectedHorizon].fx;
    const ranking = currencyStrength(packet, field);
    const maxAbs = Math.max.apply(null, ranking.map(function (x) { return Math.abs(x.value); }).concat([0.01]));
    const rows = ranking.map(function (x) {
      const width = Math.min(50, Math.abs(x.value) / maxAbs * 50);
      const barClass = x.value >= 0 ? "pos" : "neg";
      return '<div class="md-strength-row"><span class="md-strength-ccy">' + x.ccy + '</span><div class="md-strength-track"><span class="md-strength-mid"></span><span class="md-strength-bar ' + barClass + '" style="width:' + width.toFixed(1) + '%"></span></div><span class="md-strength-val ' + moveClass(x.value) + '">' + fmtPct(x.value) + "</span></div>";
    }).join("");
    return '<div class="md-panel"><div class="md-panel-head"><div><h3>G10 currency strength</h3><p>Mean log return versus the other nine G10 currencies; ranking aid, not a tradable index.</p></div><span class="md-chip">' + selectedHorizon + '</span></div><div class="md-strength-list">' + rows + '</div></div>';
  }

  function moversPanel(packet) {
    const field = HORIZONS[selectedHorizon].fx;
    const movers = Object.keys((packet.fx && packet.fx.pairs) || {}).map(function (pair) {
      return { pair: pair, value: packet.fx.pairs[pair][field], spot: packet.fx.pairs[pair].spot };
    }).filter(function (x) { return finite(x.value); }).sort(function (a, b) { return Math.abs(b.value) - Math.abs(a.value); }).slice(0, 8);
    const maxAbs = Math.max.apply(null, movers.map(function (x) { return Math.abs(x.value); }).concat([0.01]));
    const rows = movers.map(function (x) {
      const width = Math.max(5, Math.abs(x.value) / maxAbs * 100);
      return '<div class="md-mover"><span class="md-mover-pair">' + x.pair + '</span><div class="md-mover-bar"><div class="md-mover-fill" style="width:' + width.toFixed(1) + '%"></div></div><span class="md-mover-val ' + moveClass(x.value) + '">' + fmtPct(x.value) + "</span></div>";
    }).join("");
    return '<div class="md-panel"><div class="md-panel-head"><div><h3>Largest FX moves</h3><p>Absolute move across all 45 G10 crosses.</p></div><span class="md-chip">' + selectedHorizon + '</span></div><div class="md-movers">' + rows + '</div></div>';
  }

  function signalBoard(packet) {
    const h = HORIZONS[selectedHorizon];
    const strength = currencyStrength(packet, h.fx);
    const leader = strength[0];
    const laggard = strength[strength.length - 1];
    const pairs = Object.keys((packet.fx && packet.fx.pairs) || {});
    const topMover = pairs.map(function (pair) { return { pair: pair, value: packet.fx.pairs[pair][h.fx] }; }).filter(function (x) { return finite(x.value); }).sort(function (a, b) { return Math.abs(b.value) - Math.abs(a.value); })[0];
    const extremeFx = pairs.map(function (pair) { const m = packet.fx.pairs[pair]; return { pair: pair, pct: m.pctile_1y }; }).filter(function (x) { return finite(x.pct); }).sort(function (a, b) { return Math.abs(b.pct - 50) - Math.abs(a.pct - 50); })[0];
    const availableRv = Object.keys(packet.rate_rv || {}).map(function (key) { const m = packet.rate_rv[key]; return { key: key, z: m.z_1y, pct: m.pctile_1y, bps: m.bps }; }).filter(function (x) { return finite(x.z); }).sort(function (a, b) { return Math.abs(b.z) - Math.abs(a.z); });
    const extremeRv = availableRv[0];
    const frontEnd = RATE_COUNTRIES.map(function (country) {
      const m = packet.rates[country] && packet.rates[country].tenors && packet.rates[country].tenors["2Y"];
      return m && finite(m[h.rate]) ? { country: country, value: m[h.rate], level: m.value } : null;
    }).filter(Boolean).sort(function (a, b) { return Math.abs(b.value) - Math.abs(a.value); })[0];

    const signals = [
      { kicker: "G10 breadth", main: leader.ccy + " leads · " + laggard.ccy + " lags", sub: fmtPct(leader.value) + " vs " + fmtPct(laggard.value) + " average cross move over " + selectedHorizon + "." },
      { kicker: "Largest cross", main: topMover ? topMover.pair + " " + fmtPct(topMover.value) : "—", sub: "Largest absolute G10 FX move over " + selectedHorizon + "." },
      { kicker: "Range extreme", main: extremeFx ? extremeFx.pair + " · " + percentileLabel(extremeFx.pct) : "—", sub: "Most extreme spot location inside its trailing 1Y range." },
      { kicker: "Rates extreme", main: extremeRv ? extremeRv.key + " · " + fmtSigned(extremeRv.z, 2, "σ") : (frontEnd ? frontEnd.country + " 2Y " + fmtBp(frontEnd.value) : "—"), sub: extremeRv ? (fmtBp(extremeRv.bps) + " spread · " + percentileLabel(extremeRv.pct) + " of 1Y history.") : "Largest available front-end move over " + selectedHorizon + "." }
    ];

    return '<div class="md-signal-grid">' + signals.map(function (s) {
      return '<div class="md-signal"><div class="md-signal-kicker">' + esc(s.kicker) + '</div><div class="md-signal-main">' + esc(s.main) + '</div><div class="md-signal-sub">' + esc(s.sub) + "</div></div>";
    }).join("") + "</div>";
  }

  function heatmapPanel(packet) {
    const field = HORIZONS[selectedHorizon].fx;
    const all = [];
    CURRENCIES.forEach(function (base) {
      CURRENCIES.forEach(function (quote) {
        if (base !== quote) {
          const v = crossMetric(packet, base, quote, field);
          if (finite(v)) all.push(Math.abs(v));
        }
      });
    });
    const maxAbs = Math.max.apply(null, all.concat([0.01]));
    let html = '<table class="md-heatmap"><thead><tr><th>BASE ↓ / QUOTE →</th>' + CURRENCIES.map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead><tbody>";
    CURRENCIES.forEach(function (base) {
      html += '<tr><th class="md-rowhead">' + base + "</th>";
      CURRENCIES.forEach(function (quote) {
        if (base === quote) {
          html += '<td class="md-diag">—</td>';
          return;
        }
        const v = crossMetric(packet, base, quote, field);
        if (!finite(v)) {
          html += '<td class="md-na">—</td>';
          return;
        }
        const ratio = Math.min(1, Math.abs(v) / maxAbs);
        const alpha = 0.06 + ratio * 0.34;
        const bg = v >= 0 ? "rgba(19,114,74," + alpha.toFixed(3) + ")" : "rgba(180,64,52," + alpha.toFixed(3) + ")";
        html += '<td style="background:' + bg + '" title="' + base + "/" + quote + " " + selectedHorizon + " " + fmtPct(v) + '">' + fmtPct(v) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    return '<div class="md-panel"><div class="md-panel-head"><div><h3>G10 cross heatmap</h3><p>Row currency performance versus column currency. Green = row stronger; red = row weaker.</p></div><span class="md-chip">' + selectedHorizon + '</span></div><div class="md-heat-wrap">' + html + '</div><div class="md-heat-legend"><span class="md-heat-swatch neg"></span> row weaker <span class="md-heat-swatch pos"></span> row stronger · intensity scales to the largest move in the selected window</div></div>';
  }

  function ratesSection(packet) {
    const h = HORIZONS[selectedHorizon];
    const labels = { US: "United States", CA: "Canada", AU: "Australia", NZ: "New Zealand" };
    const cards = RATE_COUNTRIES.map(function (country) {
      const block = packet.rates[country];
      if (!block || block.status === "unavailable") {
        return '<div class="md-rate-card"><div class="md-rate-head"><span class="md-rate-country">' + labels[country] + '</span><span class="md-rate-date">unavailable</span></div><div class="md-rate-unavailable"><b>Official source unavailable</b>NZ-dependent values remain blank rather than using a substitute feed.</div></div>';
      }
      const rows = ["2Y", "5Y", "10Y"].map(function (tenor) {
        const m = block.tenors && block.tenors[tenor];
        if (!m) return "";
        const move = m[h.rate];
        return '<div class="md-rate-row"><span class="md-rate-tenor">' + tenor + '</span><span class="md-rate-level">' + fmtNum(m.value, 3) + '%</span><span class="md-rate-move ' + moveClass(move) + '">' + fmtBp(move) + '</span><span class="md-rate-pct">' + percentileLabel(m.pctile_1y) + "</span></div>";
      }).join("");
      const curves = block.curves || {};
      const curveHtml = ["2s10s", "5s10s"].map(function (key) {
        const m = curves[key];
        if (!m) return "";
        return '<div class="md-curve"><span>' + key + '</span><b>' + fmtBp(m.bps) + ' <small class="' + moveClass(m[h.curve]) + '">' + fmtBp(m[h.curve]) + "</small></b></div>";
      }).join("");
      return '<div class="md-rate-card"><div class="md-rate-head"><span class="md-rate-country">' + labels[country] + '</span><span class="md-rate-date">' + shortDate(block.latest_observation) + (finite(block.age_days) ? " · " + block.age_days + "d old" : "") + '</span></div><div class="md-rate-body">' + rows + '</div><div class="md-curve-strip">' + curveHtml + "</div></div>";
    }).join("");
    return '<div class="md-section-title"><div><h3>Sovereign curves</h3><p>Level · ' + selectedHorizon + ' change · trailing 1Y percentile.</p></div></div><div class="md-rates-grid">' + cards + "</div>";
  }

  function rvSection(packet) {
    const h = HORIZONS[selectedHorizon];
    const cards = RV_GROUPS.map(function (group) {
      const rows = ["2Y", "5Y", "10Y"].map(function (tenor) {
        const key = group + "_" + tenor;
        const m = packet.rate_rv && packet.rate_rv[key];
        if (!m || m.status === "unavailable" || !finite(m.bps)) {
          return '<div class="md-rv-row"><span class="md-rv-tenor">' + tenor + '</span><span class="md-rv-unavailable" style="grid-column:2 / 6">unavailable</span></div>';
        }
        const pct = percentile(m.pctile_1y);
        const move = m[h.rv];
        return '<div class="md-rv-row"><span class="md-rv-tenor">' + tenor + '</span><span class="md-rv-level">' + fmtBp(m.bps) + '</span><span class="md-rv-move ' + moveClass(move) + '">' + fmtBp(move) + '</span><div class="md-pct-track"><div class="md-pct-fill" style="width:' + (pct === null ? 0 : pct).toFixed(1) + '%"></div></div><span class="md-pct-label">' + (pct === null ? "—" : Math.round(pct)) + "</span></div>";
      }).join("");
      return '<div class="md-rv-card"><div class="md-rv-title"><b>' + group.replace("-", " − ") + '</b><span>spread bps · 1Y %ile</span></div>' + rows + "</div>";
    }).join("");
    return '<div class="md-section-title"><div><h3>Cross-market relative value</h3><p>First country minus second country. Change column follows the selected horizon.</p></div></div><div class="md-rv-grid">' + cards + "</div>";
  }

  function fullFxTable(packet) {
    const field = HORIZONS[selectedHorizon].fx;
    const pairs = Object.keys((packet.fx && packet.fx.pairs) || {}).map(function (pair) {
      return { pair: pair, m: packet.fx.pairs[pair] };
    }).sort(function (a, b) {
      const av = finite(a.m[field]) ? Math.abs(a.m[field]) : -1;
      const bv = finite(b.m[field]) ? Math.abs(b.m[field]) : -1;
      return bv - av;
    });
    const rows = pairs.map(function (x) {
      const m = x.m;
      return "<tr><td><b>" + x.pair + "</b></td><td>" + fmtSpot(x.pair, m.spot) + '</td><td class="' + moveClass(m[field]) + '">' + fmtPct(m[field]) + "</td><td>" + fmtPct(m.ret_1m) + "</td><td>" + fmtNum(m.rv_20d, 1) + "%</td><td>" + fmtNum(m.rv_60d, 1) + "%</td><td>" + percentileLabel(m.pctile_1y) + "</td><td>" + shortDate(m.as_of) + "</td></tr>";
    }).join("");
    return '<details class="md-detail"><summary>All 45 G10 crosses <span class="md-na">sorted by ' + selectedHorizon + ' move</span></summary><div class="md-detail-body"><div class="md-table-scroll"><table class="md-table"><thead><tr><th>Pair</th><th>Spot</th><th>' + selectedHorizon + '</th><th>1M</th><th>RV20</th><th>RV60</th><th>1Y range</th><th>As-of</th></tr></thead><tbody>' + rows + '</tbody></table></div></div></details>';
  }

  function provenance(packet) {
    const src = packet.sources || {};
    const rows = Object.keys(src).sort().map(function (key) {
      const s = src[key] || {};
      const statusClass = s.status === "unavailable" ? "md-neg" : "md-pos";
      return "<tr><td><b>" + esc(key) + '</b></td><td class="' + statusClass + '">' + esc(s.status || "—") + "</td><td>" + esc(shortDate(s.observation_date)) + '</td><td><a class="md-source-link" href="' + esc(s.url || "#") + '" target="_blank" rel="noopener">official ↗</a></td><td class="md-error">' + esc(s.error || "") + "</td></tr>";
    }).join("");
    return '<details class="md-detail"><summary>Data health &amp; provenance <span class="md-na">official-source diagnostics</span></summary><div class="md-detail-body"><div class="md-table-scroll"><table class="md-table"><thead><tr><th>Source</th><th>Status</th><th>Observation</th><th>Link</th><th>Error</th></tr></thead><tbody>' + rows + '</tbody></table></div><p class="md-footnote">Live authorities remain canonical. The snapshot is research context only; unavailable values remain blank rather than being backfilled from an unapproved vendor.</p></div></details>';
  }

  function bindHorizonButtons() {
    root.querySelectorAll("[data-horizon]").forEach(function (button) {
      button.addEventListener("click", function () {
        const next = button.getAttribute("data-horizon");
        if (!HORIZONS[next] || next === selectedHorizon) return;
        selectedHorizon = next;
        render(currentPacket);
      });
    });
  }

  function render(packet) {
    currentPacket = packet;
    renderMeta(packet);
    root.innerHTML =
      horizonBar() +
      focusCards(packet) +
      signalBoard(packet) +
      '<div class="md-overview-grid">' + strengthPanel(packet) + moversPanel(packet) + "</div>" +
      heatmapPanel(packet) +
      ratesSection(packet) +
      rvSection(packet) +
      '<div class="md-detail-grid">' + fullFxTable(packet) + provenance(packet) + "</div>";
    bindHorizonButtons();
  }

  fetch("market-state.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(render)
    .catch(function (err) {
      meta.innerHTML = chip("Market-state packet unavailable", "bad");
      root.innerHTML = '<div class="md-panel"><div class="md-signal-kicker">Data load failed</div><div class="md-signal-main">Could not load market-state.json</div><p class="md-subtitle">' + esc(err.message) + '. The dashboard remains available, but the Market Data view requires a successful market-state build.</p></div>';
    });
})();
