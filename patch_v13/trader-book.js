(function () {
  "use strict";

  const root = document.getElementById("trader-book-root");
  const meta = document.getElementById("tb-meta");
  if (!root || !meta) return;

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

  function money(value) {
    if (!finite(value)) return "—";
    const abs = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (abs >= 1e6) return sign + "$" + (abs / 1e6).toFixed(2) + "m";
    if (abs >= 1e3) return sign + "$" + (abs / 1e3).toFixed(1) + "k";
    return sign + "$" + abs.toFixed(0);
  }

  function cls(value) {
    if (!finite(value) || value === 0) return "";
    return value > 0 ? "tb-pos" : "tb-neg";
  }

  function level(value) {
    if (!finite(value)) return "—";
    const abs = Math.abs(value);
    if (abs >= 100) return value.toFixed(2);
    if (abs >= 10) return value.toFixed(3);
    return value.toFixed(4);
  }

  function renderPosition(pos) {
    const markLine = (finite(pos.entry_price) || finite(pos.mark_price))
      ? '<div class="tb-position-marks"><span>Entry <b>' + level(pos.entry_price) +
        '</b></span><span>Mark <b>' + level(pos.mark_price) + '</b></span></div>'
      : "";
    const thesis = pos.thesis
      ? '<div class="tb-position-reason"><b>Why:</b> ' + esc(pos.thesis) + "</div>"
      : '<div class="tb-position-reason tb-muted"><b>Why:</b> No position-specific thesis recorded.</div>';
    const invalidation = pos.invalidation
      ? '<div class="tb-position-invalidation"><b>Invalidation:</b> ' + esc(pos.invalidation) + "</div>"
      : "";
    const hedge = pos.hedge_of
      ? '<div class="tb-position-link">Hedge of ' + esc(pos.hedge_of) + "</div>"
      : "";
    return '<div class="tb-position-card"><div class="tb-position-head"><div><b>' +
      esc(pos.instrument) + '</b><span>' + esc(pos.side) + " · " + esc(pos.asset_class) +
      '</span></div><div class="tb-position-risk"><b>' + money(pos.notional_usd) +
      '</b><span>Risk ' + money(pos.risk_capital_usd) + '</span><span class="' + cls(pos.unrealized_pnl_usd) + '">' +
      money(pos.unrealized_pnl_usd) + "</span></div></div>" +
      markLine + thesis + invalidation + hedge + "</div>";
  }

  function chip(status, label) {
    const kind = status === "fresh" || status === "ok" ? "ok" : status === "failed" || status === "bad" ? "bad" : "warn";
    return '<span class="tb-chip ' + kind + '">' + esc(label) + "</span>";
  }

  function render(packet) {
    const pub = packet.publication || {};
    const status = pub.trader_books_status || packet.review_status || "stale";
    meta.innerHTML = [
      chip(pub.core_status || "ok", "Core " + (pub.core_status || "ok")),
      chip(status, "Trader books " + status),
      '<span class="tb-chip">' + esc(packet.overnight_run_id || "no run") + "</span>"
    ].join("");

    const seats = packet.seats || [];
    const nav = seats.reduce(function (sum, seat) { return sum + (finite(seat.nav_usd) ? seat.nav_usd : 0); }, 0);
    const realized = seats.reduce(function (sum, seat) { return sum + (finite(seat.realized_pnl_usd) ? seat.realized_pnl_usd : 0); }, 0);
    const unrealized = seats.reduce(function (sum, seat) { return sum + (finite(seat.unrealized_pnl_usd) ? seat.unrealized_pnl_usd : 0); }, 0);
    const funding = seats.reduce(function (sum, seat) { return sum + (finite(seat.funding_cost_usd) ? seat.funding_cost_usd : 0); }, 0);
    const cashYield = seats.reduce(function (sum, seat) { return sum + (finite(seat.cash_yield_usd) ? seat.cash_yield_usd : 0); }, 0);
    const netPnl = seats.reduce(function (sum, seat) { return sum + (finite(seat.net_pnl_usd) ? seat.net_pnl_usd : 0); }, 0);
    const openCount = seats.reduce(function (sum, seat) { return sum + ((seat.positions || []).length); }, 0);
    const changes = packet.overnight_changes || [];
    const research = packet.overnight_research || null;

    let stale = "";
    if (status !== "fresh") {
      stale = '<div class="tb-stale"><b>Stale or failed trader review.</b> ' +
        esc(pub.reason || "Publishing last successful books rather than blocking the website.") +
        (pub.last_successful_review_run_id ? " Last successful review: " + esc(pub.last_successful_review_run_id) + "." : "") +
        "</div>";
    }

    const seatHtml = seats.map(function (seat) {
      const positions = seat.positions || [];
      const posHtml = positions.length ? positions.map(renderPosition).join("") : '<div class="tb-empty">No open risk</div>';
      const pitch = seat.required_pitch ? '<div class="tb-pitch"><b>Required pitch (not necessarily risked):</b> ' +
        esc(typeof seat.required_pitch === "string" ? seat.required_pitch : JSON.stringify(seat.required_pitch)) + "</div>" : "";
      return '<article class="tb-seat"><div class="tb-seat-top"><div class="tb-seat-name">' +
        (seat.competition_rank ? "#" + esc(seat.competition_rank) + " · " : "") + esc(seat.seat) +
        '</div><div class="tb-action">' + esc(seat.last_action || "HOLD") +
        (seat.risk_stopped ? (seat.risk_stop_pending ? " · STOP PENDING" : " · RISK STOPPED") : "") +
        "</div></div><p class=\"tb-remit\">" + esc(seat.remit || "") + "</p>" +
        '<div class="tb-metrics"><div><span>Risk limit</span><b>' + money(seat.risk_capital_limit_usd) +
        " / 1% move</b></div><div><span>Net P&amp;L</span><b class=\"" + cls(seat.net_pnl_usd) + "\">" +
        money(seat.net_pnl_usd) + "</b></div><div><span>Risk used</span><b>" +
        money(seat.risk_capital_usd) +
        "</b></div><div><span>Drawdown</span><b class=\"" + (seat.risk_stopped ? "tb-neg" : "") + "\">" +
        money(seat.drawdown_usd) + " / " + money(seat.max_drawdown_usd) +
        "</b></div><div><span>Risk funding</span><b class=\"tb-neg\">" +
        (finite(seat.funding_cost_usd) && seat.funding_cost_usd !== 0 ? "-" + money(seat.funding_cost_usd).replace("-", "") : money(seat.funding_cost_usd)) +
        "</b></div></div><div class=\"tb-positions\">" + posHtml + "</div>" +
        (seat.thesis ? '<p class="tb-thesis"><b>Current book view:</b> ' + esc(seat.thesis) + "</p>" : "") +
        (seat.invalidation ? '<p class="tb-thesis"><b>Book invalidation:</b> ' + esc(seat.invalidation) + "</p>" : "") +
        pitch + "</article>";
    }).join("");

    const changeHtml = changes.length ? changes.map(function (row) {
      return '<div class="tb-change"><b>' + esc(row.seat) + "</b><span>" + esc(row.action) +
        "</span><span>" + esc(row.instrument || "") + "</span><span>" + money(row.notional_usd) + "</span></div>";
    }).join("") : '<div class="tb-empty">No overnight position changes</div>';

    const leaderboard = packet.leaderboard || [];
    const leaderboardHtml = leaderboard.length ? leaderboard.map(function (row) {
      const rank = row.rank ? "#" + row.rank : "—";
      return '<div class="tb-change"><b>' + esc(rank + " " + row.seat) + '</b><span>Net ' +
        '<span class="' + cls(row.net_pnl_usd) + '">' + money(row.net_pnl_usd) + '</span></span><span>Funding ' +
        money(row.funding_cost_usd) + '</span></div>';
    }).join("") : '<div class="tb-empty">Leaderboard unavailable</div>';

    let researchHtml = "";
    if (research) {
      const items = []
        .concat(research.news || [])
        .concat(research.central_bank_research || [])
        .slice(0, 8);
      const rows = items.length ? items.map(function (item) {
        const title = item.headline || item.title || item.name || "Research item";
        const note = item.summary || item.market_read || item.note || "";
        return '<div class="tb-change"><b>' + esc(title) + '</b><span>' + esc(note) + '</span></div>';
      }).join("") : '<div class="tb-empty">No additional overnight research items</div>';
      researchHtml = '<section class="tb-panel"><div class="tb-panel-head"><h3>Overnight research</h3><p>' +
        esc(research.summary || "Research gathered before the trader packet was frozen.") +
        '</p></div><div class="tb-changes">' + rows + "</div></section>";
    }

    root.innerHTML = stale +
      researchHtml +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Book snapshot</h3><p>' +
      esc(packet.as_of || "") + " · evidence cutoff " + esc(packet.evidence_cutoff || "n/a") +
      '</p></div><div class="tb-kpis"><div class="tb-kpi"><span>Seats</span><b>' +
      esc(packet.seat_count || seats.length) + '</b></div><div class="tb-kpi"><span>Combined NAV</span><b>' +
      money(nav) + '</b></div><div class="tb-kpi"><span>Net P&amp;L</span><b class="' +
      cls(netPnl) + '">' + money(netPnl) + '</b></div><div class="tb-kpi"><span>Funding costs</span><b>-' +
      money(funding).replace("-", "") + '</b></div><div class="tb-kpi"><span>Cash yield</span><b class="tb-pos">' +
      money(cashYield) + '</b></div><div class="tb-kpi"><span>Open sleeves</span><b>' +
      openCount + "</b></div></div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Overnight position changes</h3><p>OPEN / ADD / REDUCE / HEDGE / CLOSE applied in the latest review</p></div><div class="tb-changes">' +
      changeHtml + "</div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>P&amp;L leaderboard</h3><p>All seats use the same financing rule: official SOFR on standard-shock risk capital. Notional is descriptive; the hard drawdown stop is separate.</p></div><div class="tb-changes">' +
      leaderboardHtml + "</div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Seat books</h3><p>Each trader has a $10m risk limit per 1% standard move and a $5m max drawdown. A breached book is forcibly flattened and marked RISK_STOPPED.</p></div><div class="tb-seat-grid">' +
      seatHtml + "</div></section>" +
      '<div id="tb-pm-root"></div>';
    loadPMs();
  }

  function statusLabel(status, review) {
    if (review === "stale") return "stale vs latest review packet";
    const map = {
      awaiting_chatgpt_decision: "awaiting ChatGPT decision",
      awaiting_automated_pm_review: "awaiting automated PM review",
      no_trade: "explicit NO TRADE",
      hold: "explicit HOLD",
      active: "active",
      risk_stopped: "RISK STOPPED"
    };
    return map[status] || status || "awaiting";
  }

  function statusClass(status, review) {
    if (review === "stale") return "stale";
    if (status === "active") return "active";
    if (status === "risk_stopped") return "stale";
    if (status === "no_trade" || status === "hold") return "";
    return "awaiting";
  }

  function renderPMs(packet) {
    const mount = document.getElementById("tb-pm-root");
    if (!mount) return;
    const pms = packet.pms || [];
    const cards = pms.map(function (pm) {
      const positions = pm.positions || [];
      const posHtml = positions.length ? positions.map(renderPosition).join("") : '<div class="tb-empty">No open risk</div>';
      return '<article class="tb-pm"><div class="tb-seat-top"><div class="tb-seat-name">' +
        esc(pm.label || pm.pm_id) + '</div><div class="tb-pm-status ' +
        statusClass(pm.decision_status, pm.review_status) + '">' +
        esc(statusLabel(pm.decision_status, pm.review_status)) +
        "</div></div><p class=\"tb-remit\">" + esc(pm.mandate || "") + "</p>" +
        '<div class="tb-metrics"><div><span>Risk limit</span><b>' + money(pm.risk_capital_limit_usd) +
        " / 1% move</b></div><div><span>Risk used</span><b>" + money(pm.risk_capital_usd) +
        "</b></div><div><span>Drawdown</span><b class=\"" +
        (pm.risk_stopped ? "tb-neg" : "") + "\">" + money(pm.drawdown_usd) + " / " + money(pm.max_drawdown_usd) +
        "</b></div><div><span>Paper P&amp;L</span><b class=\"" + cls(pm.total_pnl_usd) + "\">" +
        money(pm.total_pnl_usd) + "</b></div><div><span>Last action</span><b>" +
        esc(pm.last_action || "—") + "</b></div></div><div class=\"tb-positions\">" + posHtml + "</div>" +
        (pm.thesis ? '<p class="tb-thesis"><b>Current book view:</b> ' + esc(pm.thesis) + "</p>" : "") +
        (pm.invalidation ? '<p class="tb-thesis"><b>Book invalidation:</b> ' + esc(pm.invalidation) + "</p>" : "") +
        "</article>";
    }).join("");
    const comparison = (packet.comparison || []).map(function (row) {
      return '<div class="tb-change"><b>' + esc(row.label || row.pm_id) + '</b><span class="' +
        cls(row.total_pnl_usd) + '">' + money(row.total_pnl_usd) + "</span><span>" +
        esc(statusLabel(row.decision_status, row.review_status)) + "</span><span>" +
        "Risk " + money(row.risk_capital_usd) + " / " + money(row.risk_capital_limit_usd) + "</span></div>";
    }).join("") || '<div class="tb-empty">No PM comparison yet</div>';
    const requests = ((packet.data_requests || {}).requests) || [];
    const reqHtml = requests.length ? requests.map(function (row) {
      return '<div class="tb-req-row"><b>' + esc((row.originating_pms || []).join(", ")) +
        "</b><span>" + esc(row.request) + " — " + esc(row.reason) +
        "</span><span>" + esc(row.priority) + " · ×" + esc(row.repeat_count || 1) + "</span></div>";
    }).join("") : '<div class="tb-empty">No future data requests. Requests never break the current evidence freeze.</div>';

    mount.innerHTML =
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Portfolio Managers</h3><p>' +
      "ChatGPT, Swinger, Pragmatist and Grinder each have a $100m risk limit per 1% standard move and a $50m max drawdown. Gross notional is descriptive.</p></div>" +
      '<div class="tb-pm-grid">' + cards + "</div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Four-PM P&amp;L comparison</h3><p>Paper P&amp;L after deterministic packet marks. Comparison is allowed only after decisions are committed.</p></div><div class="tb-changes">' +
      comparison + "</div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>PM Data Requests</h3><p>' +
      esc((packet.data_requests || {}).note || "Future runs only; collectors are not launched.") +
      '</p></div><div class="tb-req">' + reqHtml + "</div></section>";
  }

  function loadPMs() {
    fetch("pm-books.json", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(renderPMs)
      .catch(function () {
        const mount = document.getElementById("tb-pm-root");
        if (!mount) return;
        mount.innerHTML = '<section class="tb-panel"><div class="tb-panel-head"><h3>Portfolio Managers</h3><p>PM public state is not on this build yet.</p></div></section>';
      });
  }

  function fail(message) {
    meta.innerHTML = chip("bad", "Trader books unavailable");
    root.innerHTML = '<div class="tb-stale"><b>Trader Book did not load.</b> ' + esc(message) +
      " The rest of the dashboard is unchanged.</div>";
  }

  fetch("trader-books.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(render)
    .catch(function (error) {
      fail(error.message || "trader-books.json missing");
    });
})();
