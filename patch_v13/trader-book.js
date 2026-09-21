(function () {
  "use strict";

  const root = document.getElementById("trader-book-root");
  const meta = document.getElementById("tb-meta");
  const traderTotalEl = document.getElementById("tb-trader-total");
  const pmTotalEl = document.getElementById("tb-pm-total");
  if (!root || !meta) return;

  let traderTotalPnl = null;
  let pmTotalPnl = null;

  function renderSystemSummary() {
    if (traderTotalEl) {
      traderTotalEl.textContent = money(traderTotalPnl);
      traderTotalEl.className = cls(traderTotalPnl);
    }
    if (pmTotalEl) {
      pmTotalEl.textContent = money(pmTotalPnl);
      pmTotalEl.className = cls(pmTotalPnl);
    }
  }

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

  function displayName(id) {
    return String(id || "")
      .split("-")
      .filter(Boolean)
      .map(function (part) {
        return part.charAt(0).toUpperCase() + part.slice(1);
      })
      .join(" ");
  }

  function directionClass(side) {
    const dir = String(side || "").toLowerCase();
    if (dir === "long") return "long";
    if (dir === "short") return "short";
    return "";
  }

  const MONTH_CODE = {
    "01": "F", "02": "G", "03": "H", "04": "J", "05": "K", "06": "M",
    "07": "N", "08": "Q", "09": "U", "10": "V", "11": "X", "12": "Z"
  };

  function futuresCode(year, month) {
    const code = MONTH_CODE[String(month || "").padStart(2, "0")];
    return code ? code + String(year || "").slice(-1) : "";
  }

  function humanInstrument(instrument, paperExpression) {
    const raw = String(instrument || "");
    if (paperExpression && paperExpression.type === "futures_strip_average" &&
        paperExpression.curve_id && Array.isArray(paperExpression.expiries)) {
      const legs = paperExpression.expiries.map(function (expiry) {
        const m = String(expiry).match(/^(\d{4})-(\d{2})$/);
        return m ? futuresCode(m[1], m[2]) : String(expiry);
      });
      if (legs.length) return legs.join("/") + " " + String(paperExpression.curve_id).toUpperCase();
    }
    let m = raw.match(/^(CORRA|SOFR|AONIA)_(\d{4})-(\d{2})$/i);
    if (m) return futuresCode(m[2], m[3]) + " " + m[1].toUpperCase();
    m = raw.match(/^(CORRA|SOFR|AONIA)_(\d{4})([FGHJKMNQUVXZ])-([FGHJKMNQUVXZ])$/i);
    if (m) return m[3].toUpperCase() + String(m[2]).slice(-1) + "–" + m[4].toUpperCase() +
      String(m[2]).slice(-1) + " " + m[1].toUpperCase() + " strip";
    return raw;
  }

  function actionWord(pos) {
    const asset = String((pos || {}).asset_class || "");
    const side = String((pos || {}).side || "").toLowerCase();
    if (asset === "rates" || asset === "curve" || asset === "rates_rv") {
      if (side === "long") return "Receive";
      if (side === "short") return "Pay";
    }
    if (side === "long") return "Long";
    if (side === "short") return "Short";
    return "";
  }

  function marketExpression(pos) {
    if (!pos) return "";
    const presentation = pos.presentation || {};
    if (presentation.market_expression) return String(presentation.market_expression);
    const verb = actionWord(pos);
    const instrument = humanInstrument(pos.instrument, pos.paper_expression);
    return (verb ? verb + " " : "") + instrument;
  }

  function stripDeskLabels(value) {
    return String(value || "")
      .replace(/^\s*(FACT|INFERENCE|UNKNOWN)\s*:\s*/gi, "")
      .replace(/([.!?]\s+)(FACT|INFERENCE|UNKNOWN)\s*:\s*/gi, "$1");
  }

  function humanizeText(value) {
    let text = stripDeskLabels(value);
    text = text.replace(/\s*\(paper alias [^)]+\)/gi, "");
    text = text.replace(/\b(CORRA|SOFR|AONIA)_(\d{4})-(\d{2})\b/gi, function (_m, curve, year, month) {
      return futuresCode(year, month) + " " + String(curve).toUpperCase();
    });
    text = text.replace(/\b(CORRA|SOFR|AONIA)_(\d{4})([FGHJKMNQUVXZ])-([FGHJKMNQUVXZ])\b/gi,
      function (_m, curve, year, start, end) {
        const y = String(year).slice(-1);
        return String(start).toUpperCase() + y + "–" + String(end).toUpperCase() + y + " " +
          String(curve).toUpperCase() + " strip";
      });
    text = text.replace(/\bCRA([FGHJKMNQUVXZ])(\d{2})\b/g, function (_m, month, year) {
      return String(month).toUpperCase() + String(year).slice(-1) + " CORRA";
    });
    text = text.replace(/\bSR3([FGHJKMNQUVXZ])(\d)\b/g, function (_m, month, year) {
      return String(month).toUpperCase() + String(year) + " SOFR";
    });
    text = text.replace(/\b(?:pos|pm)-[a-z0-9-]+\b/gi, "the position");
    text = text.replace(/\bposition_id\b/gi, "position");
    text = text.replace(/\bopened_run_id\b/gi, "opening run");
    text = text.replace(/\b(?:tr|overnight)-[a-z0-9-]+\b/gi, "prior run");
    text = text.replace(/\b[A-Fa-f0-9]{64}\b/g, "packet hash");
    text = text.replace(/\b(?:CRAH|CRAM|CRAU|CRAZ)([FGHJKMNQUVXZ])(\d{1,2})\b/g,
      function (_m, month, year) {
        const y = String(year).length === 1 ? year : String(year).slice(-1);
        return String(month).toUpperCase() + y + " CORRA";
      });
    text = text.replace(/\bpacket mid\b/gi, "current mark");
    text = text.replace(/\bcanonical mark\b/gi, "mark");
    text = text.replace(/\bimplied_rate\b/gi, "implied rate");
    text = text.replace(/\bMX\s+(?=[FGHJKMNQUVXZ]\d\s+CORRA\b)/g, "");
    return text.trim();
  }

  const MECHANICAL_SENTENCE = /opened_run_id|opening run|packet source|trader room status|awaiting_chatgpt|unarbitrated|risk[_ -]?capital|risk_stopped|unrealized|p&l inverted|side long|side short|do not migrate|family locked|canonical mark|current mark implied|entry_mark|notional_usd|shocked-risk|calibration closed|packet hash|on_demand|on-demand fallback|duration-long \/ receive|family locked to|position_id|opened_run|do not open|do not hedge|remaining \d/i;

  function thesisSentences(value) {
    const text = humanizeText(value);
    if (!text) return [];
    return text.split(/(?<=[.!?])\s+/).map(function (item) { return item.trim(); }).filter(Boolean);
  }

  function isUsefulSentence(item) {
    return item && !MECHANICAL_SENTENCE.test(item);
  }

  function capPunchline(text) {
    const trimmed = String(text || "").trim();
    if (trimmed.length <= 320) return trimmed;
    return trimmed.slice(0, 317).replace(/\s+\S*$/, "") + "…";
  }

  function legacyStoryFromThesis(pos, expression) {
    const sentences = thesisSentences(pos.thesis);
    const useful = sentences.filter(isUsefulSentence);
    const pool = useful.length ? useful : sentences.slice(0, 1);
    let why = pool[0] || "";
    const prefix = expression + " — ";
    const maxWhy = Math.max(40, 320 - prefix.length);
    if (why.length > maxWhy) {
      why = why.slice(0, maxWhy - 1).replace(/\s+\S*$/, "") + "…";
    }
    const punchline = capPunchline(pool.length ? prefix + why : expression + ".");
    const support = pool.slice(1, 5).filter(isUsefulSentence);
    return { punchline: punchline, support: support };
  }

  function hasRealTradeStory(presentation) {
    if (!presentation || typeof presentation !== "object") return false;
    const headline = String(
      presentation.market_expression || presentation.punchline || ""
    ).toLowerCase();
    if (/stay flat|no trade|no incremental|n\/a while flat/.test(headline)) return false;
    return Boolean(presentation.punchline || (presentation.support && presentation.support.length));
  }

  function pickPresentation(pos, owner) {
    const posP = pos.presentation || {};
    const ownerP = (owner || {}).presentation || {};
    if (hasRealTradeStory(posP)) return posP;
    if (hasRealTradeStory(ownerP)) return ownerP;
    if (posP.punchline || (posP.support && posP.support.length)) return posP;
    if (ownerP.punchline || (ownerP.support && ownerP.support.length)) return ownerP;
    return {};
  }

  function storyForPosition(pos, owner) {
    const presentation = pickPresentation(pos, owner);
    const expression = marketExpression(pos);
    let punchline = humanizeText(presentation.punchline || "");
    let support;
    if (!punchline) {
      const legacy = legacyStoryFromThesis(pos, expression);
      punchline = legacy.punchline;
      support = legacy.support;
    }
    if (!Array.isArray(support)) {
      if (Array.isArray(presentation.support) && presentation.support.length) {
        support = presentation.support.map(humanizeText).filter(Boolean);
      } else if (!support) {
        support = legacyStoryFromThesis(pos, expression).support;
      }
    }
    const tp = presentation.take_profit || {};
    const objective = humanizeText(tp.objective || "");
    const basis = humanizeText(tp.basis || "");
    const takeProfit = objective
      ? objective + (basis ? " — " + basis : "")
      : "Legacy position: no explicit take-profit was stored.";
    const invalidation = humanizeText(presentation.invalidation || pos.invalidation || "");
    return {
      punchline: capPunchline(punchline),
      support: support,
      takeProfit: takeProfit,
      invalidation: invalidation
    };
  }

  function renderStory(story) {
    const support = (story.support || []).length
      ? '<ul class="tb-story-support">' + story.support.map(function (item) {
          return "<li>" + esc(item) + "</li>";
        }).join("") + "</ul>"
      : '<span class="tb-story-muted">No support note recorded.</span>';
    return '<div class="tb-trade-story">' +
      '<div class="tb-story-row tb-story-punchline"><b>Punchline</b><div>' + esc(story.punchline || "—") + "</div></div>" +
      '<div class="tb-story-row"><b>Support</b><div>' + support + "</div></div>" +
      '<div class="tb-story-row"><b>Take profit</b><div>' + esc(story.takeProfit || "—") + "</div></div>" +
      '<div class="tb-story-row tb-story-invalidation"><b>Invalidation</b><div>' +
      esc(story.invalidation || "No explicit invalidation recorded.") + "</div></div></div>";
  }

  function legacySupport(value) {
    return legacyStoryFromThesis({ thesis: value }, "").support;
  }

  function renderFlatStory(owner, label) {
    const presentation = (owner || {}).presentation || {};
    const punchline = humanizeText(presentation.punchline || label || "Stay flat.");
    let support = presentation.support;
    if (!Array.isArray(support) || !support.length) support = owner && owner.thesis ? legacySupport(owner.thesis) : [];
    const tp = presentation.take_profit || {};
    const takeProfit = humanizeText(tp.objective || "N/A while flat") +
      (tp.basis ? " — " + humanizeText(tp.basis) : "");
    return renderStory({
      punchline: punchline,
      support: support,
      takeProfit: takeProfit,
      invalidation: humanizeText(presentation.invalidation || (owner || {}).invalidation || "")
    });
  }

  function sumKnownPnl(rows, pick) {
    let found = false;
    let total = 0;
    (rows || []).forEach(function (row) {
      const value = pick(row);
      if (finite(value)) {
        found = true;
        total += value;
      }
    });
    return found ? total : null;
  }

  function pmNetPnl(pm) {
    return finite(pm.net_after_funding_pnl_usd) ? pm.net_after_funding_pnl_usd : pm.total_pnl_usd;
  }

  function emptyTradeLabel(status) {
    const kind = String(status || "").toLowerCase();
    if (kind === "no_trade") return "NO TRADE";
    if (kind === "hold") return "FLAT";
    if (kind.indexOf("awaiting") === 0) return "NO OPEN RISK";
    return "FLAT";
  }

  function renderTradeScan(positions, emptyLabel) {
    if (!positions.length) {
      return '<div class="tb-trade-scan tb-trade-scan-empty"><span class="tb-flat-label">' +
        esc(emptyLabel) + "</span></div>";
    }
    return '<div class="tb-trade-scan">' + positions.map(function (pos) {
      const kind = directionClass(pos.side);
      return '<div class="tb-trade-line"><b class="tb-instrument ' + kind + '">' +
        esc(marketExpression(pos)) + "</b></div>";
    }).join("") + "</div>";
  }

  function renderPosition(pos, owner) {
    const markLine = (finite(pos.entry_price) || finite(pos.mark_price))
      ? '<div class="tb-position-marks"><span>Entry <b>' + level(pos.entry_price) +
        '</b></span><span>Mark <b>' + level(pos.mark_price) + '</b></span></div>'
      : "";
    const hedge = pos.hedge_of
      ? '<div class="tb-position-link">Hedge of ' + esc(pos.hedge_of) + "</div>"
      : "";
    const kind = directionClass(pos.side);
    const story = storyForPosition(pos, owner);
    return '<div class="tb-position-card' + (kind ? " tb-side-" + kind : "") +
      '"><div class="tb-position-head"><div class="tb-position-trade">' +
      '<b class="tb-instrument">' + esc(marketExpression(pos)) +
      '</b><span class="tb-asset">' + esc(pos.asset_class) + '</span></div><div class="tb-position-risk">' +
      '<b>' + money(pos.notional_usd) + '</b><span>Notional</span><span>Risk ' +
      money(pos.risk_capital_usd) + '</span><span class="' + cls(pos.unrealized_pnl_usd) + '">' +
      money(pos.unrealized_pnl_usd) + " P&amp;L</span></div></div>" +
      markLine + renderStory(story) + hedge + "</div>";
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
    const netFinancing = seats.reduce(function (sum, seat) {
      if (finite(seat.net_financing_pnl_usd)) return sum + seat.net_financing_pnl_usd;
      return sum - (finite(seat.funding_cost_usd) ? seat.funding_cost_usd : 0);
    }, 0);
    const netPnl = sumKnownPnl(seats, function (seat) { return seat.net_pnl_usd; });
    traderTotalPnl = netPnl;
    renderSystemSummary();
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
      const posHtml = positions.length ? positions.map(function (pos) { return renderPosition(pos, seat); }).join("") : '<div class="tb-empty">No open risk</div>';
      const pitch = seat.required_pitch ? '<div class="tb-pitch"><b>Required pitch (not necessarily risked):</b> ' +
        esc(typeof seat.required_pitch === "string" ? seat.required_pitch : JSON.stringify(seat.required_pitch)) + "</div>" : "";
      const seatLabel = displayName(seat.seat);
      const emptyLabel = seat.risk_stopped ? "FLAT" : emptyTradeLabel(seat.last_action);
      return '<article class="tb-seat"><div class="tb-seat-top"><div class="tb-seat-name">' +
        (seat.competition_rank ? "#" + esc(seat.competition_rank) + " · " : "") + esc(seatLabel) +
        '</div><div class="tb-action">' + esc(seat.last_action || "HOLD") +
        (seat.risk_stopped ? (seat.risk_stop_pending ? " · STOP PENDING" : " · RISK STOPPED") : "") +
        "</div></div>" + renderTradeScan(positions, emptyLabel) +
        "<p class=\"tb-remit\">" + esc(seat.remit || "") + "</p>" +
        '<div class="tb-positions">' + posHtml + "</div>" +
        '<div class="tb-metrics"><div><span>Risk limit</span><b>' + money(seat.risk_capital_limit_usd) +
        " / 1% move</b></div><div><span>Net P&amp;L</span><b class=\"" + cls(seat.net_pnl_usd) + "\">" +
        money(seat.net_pnl_usd) + "</b></div><div><span>Risk used</span><b>" +
        money(seat.risk_capital_usd) +
        "</b></div><div><span>Drawdown</span><b class=\"" + (seat.risk_stopped ? "tb-neg" : "") + "\">" +
        money(seat.drawdown_usd) + " / " + money(seat.max_drawdown_usd) +
        "</b></div><div><span>Risk funding</span><b class=\"tb-neg\">" +
        (finite(seat.funding_cost_usd) && seat.funding_cost_usd !== 0 ? "-" + money(seat.funding_cost_usd).replace("-", "") : money(seat.funding_cost_usd)) +
        "</b></div></div>" +
        (!positions.length ? renderFlatStory(seat, emptyLabel) : "") +
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
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Trader snapshot</h3><p>' +
      esc(packet.as_of || "") + " · evidence cutoff " + esc(packet.evidence_cutoff || "n/a") +
      '</p></div><div class="tb-kpis"><div class="tb-kpi"><span>Seats</span><b>' +
      esc(packet.seat_count || seats.length) + '</b></div><div class="tb-kpi"><span>Combined NAV</span><b>' +
      money(nav) + '</b></div><div class="tb-kpi"><span>Net P&amp;L</span><b class="' +
      cls(netPnl) + '">' + money(netPnl) + '</b></div><div class="tb-kpi"><span>Funding costs</span><b>-' +
      money(funding).replace("-", "") + '</b></div><div class="tb-kpi"><span>Net financing</span><b class="' +
      cls(netFinancing) + '">' + money(netFinancing) + '</b></div><div class="tb-kpi"><span>Open sleeves</span><b>' +
      openCount + "</b></div></div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>Overnight position changes</h3><p>OPEN / ADD / REDUCE / HEDGE / CLOSE applied in the latest review</p></div><div class="tb-changes">' +
      changeHtml + "</div></section>" +
      '<section class="tb-panel"><div class="tb-panel-head"><h3>P&amp;L leaderboard</h3><p>Official SOFR is the zero-return benchmark. Competition P&amp;L subtracts SOFR only on standard-shock risk capital; flat books earn zero financing P&amp;L. Notional is descriptive; the hard drawdown stop is separate.</p></div><div class="tb-changes">' +
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
    pmTotalPnl = sumKnownPnl(pms, pmNetPnl);
    renderSystemSummary();
    const cards = pms.map(function (pm) {
      const positions = pm.positions || [];
      const posHtml = positions.length ? positions.map(function (pos) { return renderPosition(pos, pm); }).join("") : '<div class="tb-empty">No open risk</div>';
      const emptyLabel = pm.risk_stopped ? "FLAT" : emptyTradeLabel(pm.decision_status || pm.last_action);
      return '<article class="tb-pm"><div class="tb-seat-top"><div class="tb-seat-name">' +
        esc(pm.label || displayName(pm.pm_id)) + '</div><div class="tb-pm-status ' +
        statusClass(pm.decision_status, pm.review_status) + '">' +
        esc(statusLabel(pm.decision_status, pm.review_status)) +
        "</div></div>" + renderTradeScan(positions, emptyLabel) +
        "<p class=\"tb-remit\">" + esc(pm.mandate || "") + "</p>" +
        '<div class="tb-positions">' + posHtml + "</div>" +
        '<div class="tb-metrics"><div><span>Risk limit</span><b>' + money(pm.risk_capital_limit_usd) +
        " / 1% move</b></div><div><span>Risk used</span><b>" + money(pm.risk_capital_usd) +
        "</b></div><div><span>Drawdown</span><b class=\"" +
        (pm.risk_stopped ? "tb-neg" : "") + "\">" + money(pm.drawdown_usd) + " / " + money(pm.max_drawdown_usd) +
        "</b></div><div><span>Paper P&amp;L</span><b class=\"" + cls(pm.total_pnl_usd) + "\">" +
        money(pm.total_pnl_usd) + "</b></div><div><span>Last action</span><b>" +
        esc(pm.last_action || "—") + "</b></div></div>" +
        (!positions.length ? renderFlatStory(pm, emptyLabel) : "") +
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
        pmTotalPnl = null;
        renderSystemSummary();
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
