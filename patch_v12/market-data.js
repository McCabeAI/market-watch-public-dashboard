(function () {
  const root = document.getElementById("market-data-root");
  const meta = document.getElementById("md-meta");
  if (!root || !meta) return;

  function fmtNum(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return '<span class="na">—</span>';
    return Number(v).toFixed(digits);
  }

  function fmtBp(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return '<span class="na">—</span>';
    const sign = v > 0 ? "+" : "";
    return sign + Number(v).toFixed(1);
  }

  function fmtPct(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return '<span class="na">—</span>';
    const sign = v > 0 ? "+" : "";
    return sign + Number(v).toFixed(2) + "%";
  }

  function pill(text, kind) {
    const cls = kind ? " md-pill " + kind : " md-pill";
    return '<span class="' + cls.trim() + '">' + text + "</span>";
  }

  function renderMeta(packet) {
    const stale = (packet.stale_sources || []).join(", ") || "none";
    const unavail = (packet.unavailable_sources || []).join(", ") || "none";
    const status = packet.status || "unknown";
    const kind = status === "ok" ? "" : "warn";
    meta.innerHTML =
      pill("Packet " + status, kind) +
      pill("Generated " + (packet.generated_at || "—")) +
      pill("FX as-of " + (packet.fx && packet.fx.source_observation ? packet.fx.source_observation : "—")) +
      pill("Stale: " + stale, stale !== "none" ? "warn" : "") +
      (unavail !== "none" ? pill("Unavailable: " + unavail, "bad") : "");
  }

  function ratesTable(packet) {
    const order = ["US", "CA", "AU", "NZ"];
    const extra = { US: ["30Y"], CA: ["LONG"], AU: [], NZ: [] };
    let rows = "";
    for (const c of order) {
      const block = packet.rates[c];
      if (!block) continue;
      if (block.status === "unavailable") {
        rows +=
          "<tr><td><b>" +
          c +
          '</b> <span class="na">(official source blocked)</span></td><td colspan="8">' +
          (block.error || "unavailable") +
          "</td></tr>";
        continue;
      }
      const tenors = block.tenors || {};
      const tenorList = ["2Y", "5Y", "10Y"].concat(extra[c]);
      for (const t of tenorList) {
        const m = tenors[t];
        if (!m) continue;
        rows +=
          "<tr><td><b>" +
          c +
          "</b> " +
          t +
          "</td><td>" +
          fmtNum(m.value, 3) +
          "%</td><td>" +
          m.as_of +
          "</td><td>" +
          fmtBp(m.bp_1d) +
          "</td><td>" +
          fmtBp(m.bp_5d) +
          "</td><td>" +
          fmtBp(m.bp_1m) +
          "</td><td>" +
          fmtBp(m.bp_3m) +
          "</td><td>" +
          fmtNum(m.pctile_1y, 0) +
          "</td><td>" +
          (block.status === "stale" ? "stale" : "ok") +
          "</td></tr>";
      }
      const curves = block.curves || {};
      for (const key of ["2s10s", "5s10s"]) {
        const cv = curves[key];
        if (!cv) continue;
        rows +=
          "<tr><td><b>" +
          c +
          "</b> curve " +
          key +
          "</td><td>" +
          fmtBp(cv.bps) +
          " bps</td><td>" +
          (cv.as_of || "—") +
          "</td><td>" +
          fmtBp(cv.chg_1d_bps) +
          "</td><td>" +
          fmtBp(cv.chg_5d_bps) +
          "</td><td>" +
          fmtBp(cv.chg_1m_bps) +
          "</td><td>" +
          fmtBp(cv.chg_3m_bps) +
          "</td><td>" +
          fmtNum(cv.pctile_1y, 0) +
          "</td><td>" +
          block.status +
          "</td></tr>";
      }
    }
    return (
      '<div class="md-panel"><h4>Sovereign yields &amp; curve slopes</h4><div class="table-scroll"><table><thead><tr>' +
      "<th>Country / series</th><th>Level</th><th>As-of</th><th>1D bp</th><th>5D bp</th><th>1M bp</th><th>3M bp</th><th>1Y %ile</th><th>Status</th>" +
      "</tr></thead><tbody>" +
      rows +
      "</tbody></table></div></div>"
    );
  }

  function rvTable(packet) {
    const keys = Object.keys(packet.rate_rv || {}).sort();
    let rows = "";
    for (const k of keys) {
      const rv = packet.rate_rv[k];
      if (rv.status === "unavailable") {
        rows +=
          "<tr><td><b>" +
          k +
          '</b></td><td colspan="7" class="na">' +
          (rv.reason || "unavailable") +
          "</td></tr>";
        continue;
      }
      rows +=
        "<tr><td><b>" +
        k +
        "</b></td><td>" +
        fmtBp(rv.bps) +
        "</td><td>" +
        (rv.as_of || "—") +
        "</td><td>" +
        fmtBp(rv.chg_1d_bps) +
        "</td><td>" +
        fmtBp(rv.chg_5d_bps) +
        "</td><td>" +
        fmtBp(rv.chg_1m_bps) +
        "</td><td>" +
        fmtBp(rv.chg_3m_bps) +
        "</td><td>" +
        fmtNum(rv.pctile_1y, 0) +
        "</td></tr>";
    }
    return (
      '<div class="md-panel"><h4>Cross-market rate spreads (bps)</h4><div class="table-scroll"><table><thead><tr>' +
      "<th>Spread</th><th>Level</th><th>As-of</th><th>1D</th><th>5D</th><th>1M</th><th>3M</th><th>1Y %ile</th>" +
      "</tr></thead><tbody>" +
      rows +
      "</tbody></table></div></div>"
    );
  }

  function fxTable(packet) {
    const pairs = Object.keys((packet.fx && packet.fx.pairs) || {}).sort();
    let rows = "";
    for (const p of pairs) {
      const m = packet.fx.pairs[p];
      rows +=
        "<tr><td><b>" +
        p +
        "</b></td><td>" +
        fmtNum(m.spot, 4) +
        "</td><td>" +
        (m.as_of || "—") +
        "</td><td>" +
        fmtPct(m.ret_1d) +
        "</td><td>" +
        fmtPct(m.ret_5d) +
        "</td><td>" +
        fmtPct(m.ret_1m) +
        "</td><td>" +
        fmtPct(m.ret_3m) +
        "</td><td>" +
        fmtNum(m.rv_20d, 2) +
        "</td><td>" +
        fmtNum(m.rv_60d, 2) +
        "</td><td>" +
        fmtNum(m.pctile_1y, 0) +
        "</td></tr>";
    }
    const fxNote =
      packet.sources && packet.sources.FX
        ? packet.sources.FX.name + " · " + (packet.sources.FX.note || "")
        : "";
    return (
      '<div class="md-panel"><h4>G10 FX crosses (45)</h4><div class="fx-scroll"><table><thead><tr>' +
      "<th>Pair</th><th>Spot</th><th>As-of</th><th>1D</th><th>5D</th><th>1M</th><th>3M</th><th>RV 20D</th><th>RV 60D</th><th>1Y %ile</th>" +
      "</tr></thead><tbody>" +
      rows +
      '</tbody></table></div><p class="md-note">' +
      fxNote +
      "</p></div>"
    );
  }

  function sourcesBlock(packet) {
    const src = packet.sources || {};
    let rows = "";
    for (const key of Object.keys(src).sort()) {
      const s = src[key];
      rows +=
        "<tr><td><b>" +
        key +
        "</b></td><td>" +
        (s.status || "—") +
        "</td><td>" +
        (s.observation_date || '<span class="na">—</span>') +
        '</td><td><a href="' +
        (s.url || "#") +
        '" target="_blank" rel="noopener">official ↗</a></td><td>' +
        (s.error || "") +
        "</td></tr>";
    }
    return (
      '<div class="md-panel"><h4>Provenance</h4><div class="table-scroll"><table><thead><tr>' +
      "<th>Source</th><th>Status</th><th>Observation</th><th>Link</th><th>Error</th>" +
      "</tr></thead><tbody>" +
      rows +
      "</tbody></table></div></div>"
    );
  }

  function render(packet) {
    renderMeta(packet);
    root.className = "md-grid";
    root.innerHTML = ratesTable(packet) + rvTable(packet) + fxTable(packet) + sourcesBlock(packet);
  }

  fetch("market-state.json", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (err) {
      meta.innerHTML = pill("Failed to load market-state.json", "bad");
      root.innerHTML =
        '<div class="md-panel"><p class="md-note">Could not load the generated packet: ' +
        err.message +
        ". Deploy workflow must run scripts/market_state.py into <code>_site/market-state.json</code>.</p></div>";
    });
})();
