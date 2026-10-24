(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var CCY = { USD: 1, EUR: 1, GBP: 1, JPY: 1, AUD: 1, NZD: 1, CAD: 1, CHF: 1, NOK: 1, SEK: 1, DKK: 1 };

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
    var abs = Math.abs(value);
    var sign = value < 0 ? "-" : "";
    if (abs >= 1e6) return sign + "$" + (abs / 1e6).toFixed(2) + "m";
    if (abs >= 1e3) return sign + "$" + (abs / 1e3).toFixed(1) + "k";
    return sign + "$" + abs.toFixed(0);
  }

  function signedMoney(value) {
    if (!finite(value)) return "—";
    if (value > 0) return "+" + money(value);
    return money(value);
  }

  function costMoney(value) {
    if (!finite(value)) return "—";
    if (value === 0) return money(0);
    if (value > 0) return "-" + money(value);
    return money(value);
  }

  function cls(value) {
    if (!finite(value) || value === 0) return "";
    return value > 0 ? "tb-pos" : "tb-neg";
  }

  function toneClass(value) {
    if (!finite(value) || value === 0) return "mw-flat";
    return value > 0 ? "mw-up tb-pos" : "mw-down tb-neg";
  }

  function level(value) {
    if (!finite(value)) return "—";
    var abs = Math.abs(value);
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
    var dir = String(side || "").toLowerCase();
    if (dir === "long") return "long";
    if (dir === "short") return "short";
    return "";
  }

  function humaniseInstrument(id) {
    var raw = String(id || "");
    if (!raw) return "";
    var fx = raw.match(/^([A-Z]{3})([A-Z]{3})$/);
    if (fx && CCY[fx[1]] && CCY[fx[2]]) return fx[1] + "/" + fx[2];
    var spread = raw.match(/^([A-Z]+)-([A-Z]+)_(\d+Y)_(\d{4}H[12])$/);
    if (spread) return spread[1] + "\u2013" + spread[2] + " " + spread[3] + " " + spread[4];
    var month = raw.match(/^([A-Z]+)_(\d{4})-(\d{2})$/);
    if (month) {
      var mi = parseInt(month[3], 10);
      if (mi >= 1 && mi <= 12) return month[1] + " " + MONTHS[mi - 1] + " " + month[2];
    }
    var pack = raw.match(/^([A-Z]+)_(\d{4})([A-Z])-([A-Z])$/);
    if (pack) return pack[1] + " " + pack[2] + " " + pack[3] + "\u2013" + pack[4];
    var curve = raw.match(/^([A-Z]{2,3})-([A-Z]{2,3})_(\d+Y)$/);
    if (curve) return curve[1] + "\u2013" + curve[2] + " " + curve[3];
    var tenor = raw.match(/^([A-Z]{2,3})_(\d+Y)$/);
    if (tenor) return tenor[1] + " " + tenor[2];
    return raw.replace(/_/g, " ");
  }

  function humaniseAssetClass(value) {
    var key = String(value || "");
    if (key === "rates") return "Rates";
    if (key === "rates_rv") return "Rates RV";
    if (key === "spot_fx") return "Spot FX";
    if (!key) return "";
    return key.split("_").map(function (part) {
      return part ? part.charAt(0).toUpperCase() + part.slice(1) : "";
    }).join(" ");
  }

  function humaniseRule(value) {
    if (value === "rates_first") return "Rates first";
    if (value === "spot_only") return "Spot only";
    return humaniseAssetClass(value);
  }

  function humaniseBlockedSources(sources) {
    var groups = [];
    var index = {};
    (sources || []).forEach(function (raw) {
      var parts = String(raw || "").split(".");
      if (parts.length < 2) {
        groups.push({ label: String(raw || "").replace(/_/g, " ") });
        return;
      }
      var country = parts[0];
      var family = String(parts[1] || "").replace(/_/g, " ").toLowerCase();
      var leaf = parts.slice(2).join(" ").replace(/_/g, " ").toLowerCase();
      var key = country + "." + family;
      if (!index[key]) {
        index[key] = { country: country, family: family, leaves: [] };
        groups.push(index[key]);
      }
      if (leaf) index[key].leaves.push(leaf);
    });
    return groups.map(function (group) {
      if (!group.country) return group.label;
      if (!group.leaves.length) return group.country + " " + group.family;
      return group.country + " " + group.family + " (" + group.leaves.join(", ") + ")";
    }).join("; ");
  }

  function humaniseWatch(text) {
    var raw = String(text || "");
    if (/^[a-z0-9]+(?:-[a-z0-9]+)+$/.test(raw)) return raw.replace(/-/g, " ");
    return raw;
  }

  function humaniseSource(value) {
    var raw = String(value || "");
    if (raw === "NY_FED") return "NY Fed";
    return raw.replace(/_/g, " ");
  }

  function tzLabel(text) {
    var value = String(text || "");
    if (/Z$/i.test(value)) return " UTC";
    var off = value.match(/([+-])(\d{2}):(\d{2})$/);
    if (!off) return "";
    if (off[1] === "-" && (off[2] === "04" || off[2] === "05")) return " ET";
    if (off[1] === "+" && off[2] === "00") return " UTC";
    return " UTC" + off[1] + off[2] + ":" + off[3];
  }

  function formatStamp(iso, withTime) {
    var text = String(iso || "");
    var match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if (!match) return text;
    var month = MONTHS[parseInt(match[2], 10) - 1] || match[2];
    var out = String(parseInt(match[3], 10)) + " " + month + " " + match[1];
    if (withTime && match[4]) out += " " + match[4] + ":" + match[5] + tzLabel(text);
    return out;
  }

  function formatTime(iso) {
    var text = String(iso || "");
    var match = text.match(/T(\d{2}):(\d{2})/);
    if (!match) return "";
    return match[1] + ":" + match[2] + tzLabel(text);
  }

  var MACHINE_PROSE = [
    /\b(?:base_)?packet(?:_sha256)?\b/i,
    /\bsha256\b/i,
    /\breview-\d+\b/i,
    /\bmwl-\d{8}T\d{6}Z-[0-9a-f]+\b/i,
    /\bovernight-\d{8}\b/i,
    /\bfamilies\./i,
    /\bmacro_hard\b/i,
    /\bmarket_state\b/i,
    /\bsource_failed\b/i,
    /\bbudget_deferred\b/i,
    /\bPASS\/PARTIAL\b/i,
    /\bfail[- ]closed\b/i,
    /\bpmd-[0-9a-f]+\b/i,
    /\bMW_[A-Z0-9_]+\b/i,
    /\bVERIFIED:/i,
    /\bselected\s*=\s*none\b/i,
    /\bcandidate_assessments\b/i,
    /\bOPEN\/ADD\/HEDGE\b/i,
    /\brates_tenor_scan\b/i,
    /\brates_candidate\b/i,
    /\bHOLD\/REDUCE\/CLOSE\b/i
  ];

  var SCRUB_PROSE = [
    /\b(?:base_)?packet(?:_sha256)?\s*=\s*[0-9a-f]+\b/gi,
    /\bsha256\b/gi,
    /\breview-\d+\b/gi,
    /\bmwl-\d{8}T\d{6}Z-[0-9a-f]+\b/gi,
    /\bovernight-\d{8}\b/gi,
    /\bfamilies\.[A-Za-z0-9_.]+/gi,
    /\bmacro_hard\b(?:\s+is|\s+was|\s*=)?\s*(?:STALE|FRESH|MISSING|INVALID)?/gi,
    /\bmarket_state\b/gi,
    /\bsource_failed\b/gi,
    /\bbudget_deferred\b/gi,
    /\bPASS\/PARTIAL\b/gi,
    /\bfail[- ]closed\b/gi,
    /\bpmd-[0-9a-f]+\b/gi,
    /\bMW_[A-Z0-9_]+\b/g,
    /\bselected\s*=\s*none\b/gi,
    /\bcandidate_assessments\b/gi,
    /\bOPEN\/ADD\/HEDGE\b/gi,
    /\brates_tenor_scan\b:?/gi,
    /\brates_candidate\b/gi,
    /(?:\bso\s+)?(?:\band\s+)?\bonly\s+HOLD\/REDUCE\/CLOSE\s+are\s+live\b/gi,
    /\bHOLD\/REDUCE\/CLOSE\b/gi
  ];

  function hasMachineProse(value) {
    var text = String(value || "");
    return MACHINE_PROSE.some(function (pattern) { return pattern.test(text); });
  }

  function cleanBlurb(value, fallback, maxChars) {
    if (!value) return fallback || "";
    var chunks = String(value).match(/[^.!?]+[.!?]?/g) || [];
    var kept = chunks.map(function (chunk) {
      var text = chunk.replace(/\b(?:FACT|INFERENCE|UNKNOWN|VERIFIED):\s*/gi, "");
      SCRUB_PROSE.forEach(function (pattern) { text = text.replace(pattern, ""); });
      return text.replace(/\s{2,}/g, " ").replace(/\s+([,.;:])/g, "$1").replace(/;\s*\./g, ".").trim();
    }).filter(function (chunk) {
      return chunk && !hasMachineProse(chunk) && !(chunk.length > 420 && (chunk.match(/;/g) || []).length >= 3);
    });
    var out = kept.join(" ").trim();
    if (!out) return fallback || "";
    var limit = maxChars || 700;
    if (out.length > limit) out = out.slice(0, limit).replace(/\s+\S*$/, "").replace(/[ ,;:]+$/, "") + "…";
    return out;
  }

  function cleanResearchSummary(value) {
    var fallback = "Accepted overnight developments are listed below; no clean desk summary was published for this cycle.";
    if (!value || hasMachineProse(value) || String(value).length > 1400) return fallback;
    return cleanBlurb(value, fallback, 1400);
  }

  function sumKnownPnl(rows, pick) {
    var found = false;
    var total = 0;
    (rows || []).forEach(function (row) {
      var value = pick(row);
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
    var kind = String(status || "").toLowerCase();
    if (kind === "no_trade") return "NO TRADE";
    if (kind === "hold") return "FLAT";
    if (kind.indexOf("awaiting") === 0) return "NO OPEN RISK";
    return "FLAT";
  }

  function classifyAlert(text) {
    var raw = String(text || "");
    if (raw.indexOf("funding_accrual_failed_closed") === 0) {
      var colon = raw.indexOf(":");
      return { kind: "funding", reason: colon >= 0 ? raw.slice(colon + 1).trim() : "", text: raw };
    }
    var mark = raw.match(/^Paper mark unavailable for ([^:]+):\s*(.*)$/);
    if (mark) return { kind: "paper_mark", instrument: mark[1].trim(), reason: mark[2].trim(), text: raw };
    if (raw.indexOf("reduced without a price") !== -1) {
      var idMatch = raw.match(/^(\S+)\s+reduced without a price/);
      return { kind: "reduced_without_price", positionId: idMatch ? idMatch[1] : "", text: raw };
    }
    return { kind: "watch", text: raw };
  }

  function bookFlagCount(row) {
    var count = 0;
    var seen = {};
    var alerts = (row && row.alerts) || [];
    for (var i = 0; i < alerts.length; i++) {
      var item = classifyAlert(alerts[i]);
      if (item.kind !== "paper_mark" && item.kind !== "reduced_without_price") continue;
      var key = item.kind + "|" + (item.instrument || item.positionId || "") + "|" + (item.reason || "");
      if (seen[key]) continue;
      seen[key] = true;
      count += 1;
    }
    if (row && row.risk_stopped) count += 1;
    if (row && row.risk_stop_pending) count += 1;
    if (row && row.pnl_unavailable) count += 1;
    return count;
  }

  function isChanged(row) {
    var last = String((row && row.last_action) || "HOLD");
    if (last !== "HOLD") return true;
    if (!row) return false;
    var prior = row.prior_action;
    if (prior === undefined || prior === null || prior === "") return false;
    return String(prior) !== last;
  }

  function pushUnique(list, seen, key, row) {
    if (seen[key]) {
      seen[key].count += 1;
      return;
    }
    row.count = 1;
    seen[key] = row;
    list.push(row);
  }

  function fleetFlags(seats, pms, permissions) {
    var fundingSeats = {};
    var fundingPms = {};
    var fundingReason = "";
    var paper = [];
    var paperSeen = {};
    var reduced = [];
    var reducedSeen = {};
    var riskStopped = [];
    var riskStopPending = [];
    var pnlUnavailable = [];
    var staleReviews = [];

    function takeBook(book, kind) {
      var id = kind === "pm" ? book.pm_id : book.seat;
      var label = kind === "pm" ? (book.label || displayName(book.pm_id)) : displayName(book.seat);
      (book.alerts || []).forEach(function (alert) {
        var item = classifyAlert(alert);
        if (item.kind === "funding") {
          if (kind === "pm") fundingPms[id] = true;
          else fundingSeats[id] = true;
          if (!fundingReason && item.reason) fundingReason = item.reason;
        } else if (item.kind === "paper_mark") {
          pushUnique(paper, paperSeen, kind + "|" + id + "|" + item.instrument + "|" + item.reason, {
            book: kind,
            id: id,
            label: label,
            instrument: item.instrument,
            human: humaniseInstrument(item.instrument),
            reason: item.reason
          });
        } else if (item.kind === "reduced_without_price") {
          pushUnique(reduced, reducedSeen, kind + "|" + id + "|" + item.positionId, {
            book: kind,
            id: id,
            label: label,
            positionId: item.positionId,
            text: item.text
          });
        }
      });
      if (book.risk_stopped) riskStopped.push({ book: kind, id: id, label: label });
      if (book.risk_stop_pending) riskStopPending.push({ book: kind, id: id, label: label });
      if (book.pnl_unavailable) pnlUnavailable.push({ book: kind, id: id, label: label });
      if (kind === "pm" && book.review_status === "stale") staleReviews.push({ id: id, label: label });
    }

    (seats || []).forEach(function (seat) { takeBook(seat, "seat"); });
    (pms || []).forEach(function (pm) { takeBook(pm, "pm"); });

    var perms = permissions || {};
    var countries = perms.countries || {};
    var restricted = Object.keys(countries).filter(function (code) { return countries[code] && !countries[code].eligible; });
    var eligible = perms.trade_eligible_countries || [];
    var blocked = perms.blocked_sources || [];
    var quarantined = (perms.quarantined_positions || []).map(function (row) {
      return {
        seat: row.seat,
        label: displayName(row.seat),
        instrument: row.instrument,
        human: humaniseInstrument(row.instrument),
        reason: row.reason || ""
      };
    });

    return {
      funding: {
        seatCount: Object.keys(fundingSeats).length,
        seatTotal: (seats || []).length,
        pmCount: Object.keys(fundingPms).length,
        pmTotal: (pms || []).length,
        reason: fundingReason
      },
      paperMarks: paper,
      reducedWithoutPrice: reduced,
      riskStopped: riskStopped,
      riskStopPending: riskStopPending,
      pnlUnavailable: pnlUnavailable,
      staleReviews: staleReviews,
      restriction: {
        eligible: eligible,
        restricted: restricted,
        blockedSources: blocked,
        blockedLabel: humaniseBlockedSources(blocked),
        quarantined: quarantined,
        sentence: permissionSentence(perms)
      }
    };
  }

  function permissionSentence(permissions) {
    var perms = permissions || {};
    var allowed = perms.trade_eligible_countries || [];
    var countries = perms.countries || {};
    var restricted = Object.keys(countries).filter(function (code) {
      return countries[code] && !countries[code].eligible;
    });
    if (!allowed.length && !restricted.length) return "";
    return "New risk eligible: " + allowed.join(" / ") +
      (restricted.length ? " · Restricted: " + restricted.join(" / ") : "") +
      ". Existing positions may still be held, reduced or closed.";
  }

  function describeFunding(funding) {
    var parts = [];
    if (funding && funding.seatTotal) parts.push(funding.seatCount + " of " + funding.seatTotal + " seats");
    if (funding && funding.pmTotal) parts.push(funding.pmCount + " of " + funding.pmTotal + " portfolio managers");
    var who = parts.join(" and ");
    var reason = funding && funding.reason ? funding.reason : "";
    if (reason) reason = reason.charAt(0).toUpperCase() + reason.slice(1);
    if (!who) return reason;
    return reason ? who + ". " + reason : who;
  }

  function fleetSnapshot(seats) {
    var rows = seats || [];
    var net = sumKnownPnl(rows, function (seat) { return seat.net_pnl_usd; });
    var winners = 0;
    var losers = 0;
    var flatPnl = 0;
    var openRisk = 0;
    var flatSeats = 0;
    var riskUsed = 0;
    var riskLimit = 0;
    var best = null;
    var worst = null;
    var largestDd = null;
    rows.forEach(function (seat) {
      var pnl = seat.net_pnl_usd;
      if (finite(pnl)) {
        if (pnl > 0) winners += 1;
        else if (pnl < 0) losers += 1;
        else flatPnl += 1;
        if (!best || pnl > best.net_pnl_usd || (pnl === best.net_pnl_usd && String(seat.seat) < String(best.seat))) best = seat;
        if (!worst || pnl < worst.net_pnl_usd || (pnl === worst.net_pnl_usd && String(seat.seat) < String(worst.seat))) worst = seat;
      }
      if ((seat.positions || []).length) openRisk += 1;
      else flatSeats += 1;
      if (finite(seat.risk_capital_usd)) riskUsed += seat.risk_capital_usd;
      if (finite(seat.risk_capital_limit_usd)) riskLimit += seat.risk_capital_limit_usd;
      if (finite(seat.drawdown_usd)) {
        if (!largestDd || seat.drawdown_usd > largestDd.drawdown_usd ||
          (seat.drawdown_usd === largestDd.drawdown_usd && String(seat.seat) < String(largestDd.seat))) {
          largestDd = seat;
        }
      }
    });
    var nav = rows.reduce(function (sum, seat) { return sum + (finite(seat.nav_usd) ? seat.nav_usd : 0); }, 0);
    var funding = rows.reduce(function (sum, seat) { return sum + (finite(seat.funding_cost_usd) ? seat.funding_cost_usd : 0); }, 0);
    var netFinancing = rows.reduce(function (sum, seat) {
      if (finite(seat.net_financing_pnl_usd)) return sum + seat.net_financing_pnl_usd;
      return sum - (finite(seat.funding_cost_usd) ? seat.funding_cost_usd : 0);
    }, 0);
    var openSleeves = rows.reduce(function (sum, seat) { return sum + ((seat.positions || []).length); }, 0);
    return {
      netPnl: net,
      winners: winners,
      losers: losers,
      flatPnl: flatPnl,
      openRisk: openRisk,
      flatSeats: flatSeats,
      riskUsed: riskUsed,
      riskLimit: riskLimit,
      nav: nav,
      funding: funding,
      netFinancing: netFinancing,
      openSleeves: openSleeves,
      best: best,
      worst: worst,
      largestDrawdown: largestDd
    };
  }

  function ticketDate(row) {
    var day = String((row && row.at) || "").slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : "";
  }

  function latestTicketDate(changes) {
    var best = "";
    (changes || []).forEach(function (row) {
      var day = ticketDate(row);
      if (day && day > best) best = day;
    });
    return best;
  }

  function latestTickets(changes) {
    var day = latestTicketDate(changes);
    if (!day) return [];
    return (changes || []).filter(function (row) { return ticketDate(row) === day; });
  }

  function groupTickets(changes) {
    var groups = {};
    var order = [];
    (changes || []).forEach(function (row, index) {
      var day = ticketDate(row) || "undated";
      if (!groups[day]) {
        groups[day] = [];
        order.push(day);
      }
      groups[day].push({ row: row, index: index });
    });
    order.sort(function (a, b) {
      if (a === "undated") return 1;
      if (b === "undated") return -1;
      if (a < b) return 1;
      if (a > b) return -1;
      return 0;
    });
    return order.map(function (day) {
      var rows = groups[day].slice().sort(function (a, b) {
        var at = String(a.row.at || "");
        var bt = String(b.row.at || "");
        if (at < bt) return 1;
        if (at > bt) return -1;
        return a.index - b.index;
      });
      return { date: day, rows: rows.map(function (item) { return item.row; }) };
    });
  }

  function ratio(part, whole) {
    if (!finite(part)) return null;
    if (!finite(whole) || whole === 0) return part;
    return part / whole;
  }

  function sortValue(row, key, kind) {
    if (!row) return null;
    if (key === "rank") return finite(row.competition_rank) ? row.competition_rank : null;
    if (key === "name" || key === "seat") {
      var label = kind === "pm" ? (row.label || displayName(row.pm_id)) : displayName(row.seat);
      return String(label || "").toLowerCase();
    }
    if (key === "action") return String(row.last_action || "");
    if (key === "status") return String(statusLabel(row.decision_status, row.review_status) || "");
    if (key === "positions") return (row.positions || []).length;
    if (key === "net") {
      var net = kind === "pm" ? pmNetPnl(row) : row.net_pnl_usd;
      return finite(net) ? net : null;
    }
    if (key === "gross") return finite(row.gross_pnl_usd) ? row.gross_pnl_usd : null;
    if (key === "paper") return finite(row.total_pnl_usd) ? row.total_pnl_usd : null;
    if (key === "funding") return finite(row.funding_cost_usd) ? row.funding_cost_usd : null;
    if (key === "risk") return ratio(row.risk_capital_usd, row.risk_capital_limit_usd);
    if (key === "drawdown") return ratio(row.drawdown_usd, row.max_drawdown_usd);
    if (key === "conviction") return finite(row.conviction) ? row.conviction : null;
    if (key === "flags") return bookFlagCount(row);
    return null;
  }

  function tieBreak(a, b) {
    var left = String((a && (a.seat || a.pm_id || a.label)) || "");
    var right = String((b && (b.seat || b.pm_id || b.label)) || "");
    if (left < right) return -1;
    if (left > right) return 1;
    return 0;
  }

  function compareRows(a, b, key, direction, kind) {
    var left = sortValue(a, key, kind);
    var right = sortValue(b, key, kind);
    var leftMissing = left === null || left === undefined || left === "";
    var rightMissing = right === null || right === undefined || right === "";
    if (leftMissing || rightMissing) {
      if (leftMissing && rightMissing) return tieBreak(a, b);
      return leftMissing ? 1 : -1;
    }
    var cmp = 0;
    if (typeof left === "number" && typeof right === "number") cmp = left < right ? -1 : left > right ? 1 : 0;
    else {
      var ls = String(left);
      var rs = String(right);
      cmp = ls < rs ? -1 : ls > rs ? 1 : 0;
    }
    if (cmp === 0) return tieBreak(a, b);
    return cmp * (direction < 0 ? -1 : 1);
  }

  function matchesQuery(row, query) {
    if (!query) return true;
    var parts = [row.seat, row.pm_id, row.label, row.remit, row.mandate, row.last_action, displayName(row.seat || ""), displayName(row.pm_id || "")];
    var positions = row.positions || [];
    for (var i = 0; i < positions.length; i++) {
      parts.push(positions[i].instrument);
      parts.push(humaniseInstrument(positions[i].instrument));
      parts.push(positions[i].side);
    }
    return parts.filter(Boolean).join(" ").toLowerCase().indexOf(query) !== -1;
  }

  function passesFilter(row, filter, kind) {
    if (!filter || filter === "all") return true;
    var positions = row.positions || [];
    if (filter === "open") return positions.length > 0;
    if (filter === "flat") return positions.length === 0;
    if (filter === "changed") return isChanged(row);
    if (filter === "flagged") return bookFlagCount(row) > 0;
    var net = kind === "pm" ? pmNetPnl(row) : row.net_pnl_usd;
    if (filter === "winners") return finite(net) && net > 0;
    if (filter === "losers") return finite(net) && net < 0;
    return true;
  }

  function filteredSorted(rows, view, kind) {
    var query = String((view && view.query) || "").trim().toLowerCase();
    var filter = (view && view.filter) || "all";
    var list = (rows || []).filter(function (row) {
      return matchesQuery(row, query) && passesFilter(row, filter, kind);
    });
    var key = (view && view.sortKey) || "rank";
    var dir = view && view.sortDir < 0 ? -1 : 1;
    return list.slice().sort(function (a, b) { return compareRows(a, b, key, dir, kind); });
  }

  function countFilters(rows, query, kind) {
    var base = (rows || []).filter(function (row) {
      return matchesQuery(row, String(query || "").trim().toLowerCase());
    });
    function n(filter) {
      return base.filter(function (row) { return passesFilter(row, filter, kind); }).length;
    }
    return { all: base.length, open: n("open"), flat: n("flat"), changed: n("changed"), winners: n("winners"), losers: n("losers"), flagged: n("flagged") };
  }

  function renderTradeScan(positions, emptyLabel) {
    if (!positions || !positions.length) {
      return '<div class="tb-trade-scan tb-trade-scan-empty"><span class="tb-flat-label">' +
        esc(emptyLabel) + "</span></div>";
    }
    return '<div class="tb-trade-scan">' + positions.map(function (pos) {
      var direction = String(pos.side || "").toUpperCase();
      var kind = directionClass(pos.side);
      var dirHtml = direction
        ? '<span class="tb-direction ' + kind + '">' + esc(direction) + "</span>"
        : "";
      return '<div class="tb-trade-line">' + dirHtml +
        '<b class="tb-instrument" title="' + esc(pos.instrument) + '">' + esc(humaniseInstrument(pos.instrument)) + "</b></div>";
    }).join("") + "</div>";
  }

  function priceBit(label, price, asOf, source) {
    if (!finite(price) && !asOf && !source) return "";
    var shown = finite(price) ? level(price) : "—";
    var title = finite(price) ? ' title="' + esc(String(price)) + '"' : "";
    return "<span>" + esc(label) + ' <b class="mw-num"' + title + ">" + esc(shown) + "</b>" +
      (asOf ? ' <span class="mw-asof">' + esc(formatStamp(asOf, true)) + "</span>" : "") +
      (source ? ' <span class="mw-raw">' + esc(source) + "</span>" : "") + "</span>";
  }

  function renderPosition(pos) {
    var kind = directionClass(pos.side);
    var direction = String(pos.side || "").toUpperCase();
    var human = humaniseInstrument(pos.instrument);
    var dirHtml = direction ? '<span class="tb-direction ' + kind + '">' + esc(direction) + "</span>" : "";
    var marks = priceBit("Entry", pos.entry_price, pos.entry_price_as_of, pos.entry_price_source) +
      priceBit("Mark", pos.mark_price, pos.mark_price_as_of, pos.mark_price_source);
    var markLine = marks ? '<div class="tb-position-marks">' + marks + "</div>" : "";
    var publicThesis = cleanBlurb(pos.thesis, "", 500);
    var publicInvalidation = cleanBlurb(pos.invalidation, "", 400);
    var thesis = publicThesis
      ? '<div class="tb-position-reason"><b>Why:</b> ' + esc(publicThesis) + "</div>"
      : '<div class="tb-position-reason tb-muted"><b>Why:</b> No clean position-specific note recorded.</div>';
    var invalidation = publicInvalidation
      ? '<div class="tb-position-invalidation"><b>Invalidation:</b> ' + esc(publicInvalidation) + "</div>"
      : "";
    var hedge = "";
    if (pos.hedge_of) {
      var hedgeHuman = humaniseInstrument(pos.hedge_of);
      hedge = '<div class="tb-position-link">Hedge of ' +
        (hedgeHuman && hedgeHuman !== String(pos.hedge_of) ? esc(hedgeHuman) + " " : "") +
        '<span class="mw-raw">' + esc(pos.hedge_of) + "</span></div>";
    }
    var opened = pos.opened_at ? '<div class="mw-asof">Opened ' + esc(formatStamp(pos.opened_at, true)) + "</div>" : "";
    var pid = pos.position_id ? '<span class="mw-raw">' + esc(pos.position_id) + "</span>" : "";
    return '<div class="tb-position-card' + (kind ? " tb-side-" + kind : "") +
      '"><div class="tb-position-head"><div class="tb-position-trade">' +
      dirHtml + '<b class="tb-instrument" title="' + esc(pos.instrument) + '">' + esc(human) +
      '</b><span class="mw-raw">' + esc(pos.instrument) + '</span><span class="tb-asset">' +
      esc(humaniseAssetClass(pos.asset_class)) + "</span>" + pid +
      '</div><div class="tb-position-risk"><b class="mw-num">' + money(pos.notional_usd) +
      "</b><span>Notional</span><span>Risk " + money(pos.risk_capital_usd) +
      '</span><span class="' + toneClass(pos.unrealized_pnl_usd) + '">' +
      signedMoney(pos.unrealized_pnl_usd) + " P&amp;L</span></div></div>" +
      opened + markLine + thesis + invalidation + hedge + "</div>";
  }

  function decisionLabel(status) {
    var map = {
      awaiting_chatgpt_decision: "awaiting ChatGPT decision",
      awaiting_automated_pm_review: "awaiting automated PM review",
      no_trade: "explicit NO TRADE",
      hold: "explicit HOLD",
      active: "active",
      risk_stopped: "RISK STOPPED"
    };
    return map[status] || status || "awaiting";
  }

  function statusLabel(status, review) {
    if (review === "stale") return "stale vs latest review packet";
    return decisionLabel(status);
  }

  function statusClass(status, review) {
    if (review === "stale") return "stale";
    if (status === "active") return "active";
    if (status === "risk_stopped") return "stale";
    if (status === "no_trade" || status === "hold") return "";
    return "awaiting";
  }

  function convictionText(value) {
    if (!finite(value)) return "—";
    return String(value) + " / 100";
  }

  function pctText(part, whole) {
    if (!finite(part) || !finite(whole) || whole === 0) return "—";
    return (part / whole * 100).toFixed(1) + "%";
  }

  function barHtml(part, whole) {
    var ratioPct = finite(part) && finite(whole) && whole !== 0 ? (part / whole * 100) : 0;
    var width = Math.max(0, Math.min(100, ratioPct));
    return '<div class="tb-meter"><div class="tb-bar" aria-hidden="true"><span style="width:' +
      width.toFixed(1) + '%"></span></div><span class="mw-num">' + pctText(part, whole) + "</span></div>";
  }

  var api = {
    humaniseInstrument: humaniseInstrument,
    humaniseAssetClass: humaniseAssetClass,
    humaniseBlockedSources: humaniseBlockedSources,
    humaniseWatch: humaniseWatch,
    classifyAlert: classifyAlert,
    bookFlagCount: bookFlagCount,
    isChanged: isChanged,
    fleetFlags: fleetFlags,
    describeFunding: describeFunding,
    fleetSnapshot: fleetSnapshot,
    latestTicketDate: latestTicketDate,
    latestTickets: latestTickets,
    groupTickets: groupTickets,
    compareRows: compareRows,
    filteredSorted: filteredSorted,
    sumKnownPnl: sumKnownPnl,
    pmNetPnl: pmNetPnl,
    money: money,
    displayName: displayName,
    formatStamp: formatStamp,
    permissionSentence: permissionSentence
  };

  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  var root = document.getElementById("trader-book-root");
  var meta = document.getElementById("tb-meta");
  var traderTotalEl = document.getElementById("tb-trader-total");
  var pmTotalEl = document.getElementById("tb-pm-total");
  if (!root || !meta) return;

  var traderTotalPnl = null;
  var pmTotalPnl = null;
  var traderPacket = null;
  var pmPacket = null;
  var traderView = { sortKey: "rank", sortDir: 1, filter: "all", query: "", open: {} };
  var pmView = { sortKey: "net", sortDir: -1, filter: "all", query: "", open: {} };
  var bound = false;

  function renderSystemSummary() {
    if (traderTotalEl) {
      traderTotalEl.textContent = money(traderTotalPnl);
      traderTotalEl.className = "mw-num " + toneClass(traderTotalPnl);
    }
    if (pmTotalEl) {
      pmTotalEl.textContent = money(pmTotalPnl);
      pmTotalEl.className = "mw-num " + toneClass(pmTotalPnl);
    }
  }

  function chip(kind, label) {
    var name = kind === "ok" ? "mw-chip--ok" : kind === "bad" ? "mw-chip--bad" : kind === "info" ? "mw-chip--info" : "mw-chip--warn";
    return '<span class="mw-chip ' + name + '">' + esc(label) + "</span>";
  }

  function reviewKind(status) {
    if (status === "fresh" || status === "ok") return "ok";
    if (status === "failed" || status === "bad") return "bad";
    return "warn";
  }

  function actionChip(action) {
    var raw = String(action || "HOLD");
    var label = raw.replace(/_/g, " ");
    var extra = "";
    if (raw === "REDUCE" || raw === "CLOSE") extra = " mw-chip--warn is-active";
    else if (raw !== "HOLD" && raw !== "NO_TRADE") extra = " mw-chip--info is-active";
    else if (raw === "NO_TRADE") extra = " is-active";
    return '<span class="mw-chip' + extra + '" title="' + esc(raw) + '">' + esc(label) + "</span>";
  }

  function priorHtml(row) {
    var last = String((row && row.last_action) || "HOLD");
    var prior = row ? row.prior_action : null;
    if (prior === undefined || prior === null || prior === "" || String(prior) === last) return "";
    return '<span class="tb-prior">was ' + esc(String(prior).replace(/_/g, " ")) + "</span>";
  }

  function meterSub(used, limit) {
    return '<div class="tb-meter-sub mw-num">' + money(used) + " / " + money(limit) + "</div>";
  }

  function kpi(label, body, wide) {
    return '<div class="tb-kpi' + (wide ? " tb-kpi-wide" : "") + '"><span class="mw-label">' + label + "</span>" + body + "</div>";
  }

  function fleetKpiHtml(seats) {
    var snap = fleetSnapshot(seats);
    var bestName = snap.best ? displayName(snap.best.seat) : "—";
    var worstName = snap.worst ? displayName(snap.worst.seat) : "—";
    var dd = snap.largestDrawdown;
    var ddName = dd ? displayName(dd.seat) : "—";
    var primary = '<div class="tb-kpis">' +
      kpi("Winners / losers / flat", '<b class="mw-num"><span class="mw-up">' + snap.winners + ' winners</span> · <span class="mw-down">' + snap.losers + ' losers</span> · <span class="mw-flat">' + snap.flatPnl + " flat</span></b>") +
      kpi("Open risk vs flat", '<b class="mw-num">' + snap.openRisk + " open risk · " + snap.flatSeats + " flat</b>") +
      kpi("Risk used", '<b class="mw-num">' + money(snap.riskUsed) + " / " + money(snap.riskLimit) + "</b>" + barHtml(snap.riskUsed, snap.riskLimit), true) +
      kpi("Largest drawdown", '<b>' + esc(ddName) + '</b><span class="mw-num mw-down">' + (dd ? money(dd.drawdown_usd) + " · " + pctText(dd.drawdown_usd, dd.max_drawdown_usd) + " of max" : "—") + "</span>") +
      kpi("Best seat", '<b>' + esc(bestName) + '</b><span class="mw-num ' + toneClass(snap.best && snap.best.net_pnl_usd) + '">' + signedMoney(snap.best && snap.best.net_pnl_usd) + "</span>") +
      kpi("Worst seat", '<b>' + esc(worstName) + '</b><span class="mw-num ' + toneClass(snap.worst && snap.worst.net_pnl_usd) + '">' + signedMoney(snap.worst && snap.worst.net_pnl_usd) + "</span>") +
      "</div>";
    var secondary = '<div class="tb-kpis tb-kpis-secondary">' +
      kpi("Combined NAV", '<b class="mw-num">' + money(snap.nav) + "</b>") +
      kpi("Funding costs", '<b class="mw-num mw-down">' + ("-" + money(snap.funding).replace("-", "")) + "</b>") +
      kpi("Net financing", '<b class="mw-num ' + toneClass(snap.netFinancing) + '">' + money(snap.netFinancing) + "</b>") +
      kpi("Open sleeves", '<b class="mw-num">' + snap.openSleeves + "</b>") +
      "</div>";
    return '<h3 class="tb-section-title">Fleet overview</h3>' + primary + secondary;
  }

  function namesOf(rows) {
    return (rows || []).map(function (row) { return esc(row.label || displayName(row.id || row.seat)); }).join(", ");
  }

  function flagHtml(flags) {
    var items = [];
    if (flags.funding && (flags.funding.seatCount || flags.funding.pmCount)) {
      items.push('<li><span class="mw-chip mw-chip--bad">Funding accrual failed closed</span><p>' +
        esc(describeFunding(flags.funding)) + "</p><p class=\"tb-flag-note\">Seat flag counts omit this shared failure.</p></li>");
    }
    if (flags.paperMarks.length) {
      var marks = flags.paperMarks.map(function (row) {
        var times = row.count > 1 ? " · recorded " + row.count + " times" : "";
        return "<li>" + esc(row.label) + " · " + esc(row.human) + ' <span class="mw-raw">' + esc(row.instrument) +
          "</span> · " + esc(row.reason) + esc(times) + "</li>";
      }).join("");
      items.push('<li><span class="mw-chip mw-chip--bad">Paper mark unavailable</span><ul>' + marks + "</ul></li>");
    }
    if (flags.reducedWithoutPrice.length) {
      var reduced = flags.reducedWithoutPrice.map(function (row) {
        return "<li>" + esc(row.label) + " · " + esc(row.positionId || row.text) + " reduced without a price; realized P&amp;L left at 0</li>";
      }).join("");
      items.push('<li><span class="mw-chip mw-chip--bad">Reduced without a price</span><ul>' + reduced + "</ul></li>");
    }
    if (flags.riskStopped.length) {
      items.push('<li><span class="mw-chip mw-chip--bad">Risk stopped</span><p>' + namesOf(flags.riskStopped) + "</p></li>");
    }
    if (flags.riskStopPending.length) {
      items.push('<li><span class="mw-chip mw-chip--warn">Risk stop pending</span><p>' + namesOf(flags.riskStopPending) + "</p></li>");
    }
    if (flags.pnlUnavailable.length) {
      items.push('<li><span class="mw-chip mw-chip--bad">Unavailable</span><p>P&amp;L unavailable: ' + namesOf(flags.pnlUnavailable) + "</p></li>");
    }
    var restriction = flags.restriction || {};
    var restrictedState = (restriction.restricted || []).length || restriction.blockedLabel || (restriction.quarantined || []).length;
    if (restriction.sentence || restrictedState) {
      var extra = "";
      if (restriction.blockedLabel) extra += " Blocked sources: " + restriction.blockedLabel + ".";
      var quarantine = (restriction.quarantined || []).map(function (row) {
        return "<li>" + esc(row.label) + " · " + esc(row.human || row.instrument) +
          (row.instrument ? ' <span class="mw-raw">' + esc(row.instrument) + "</span>" : "") +
          (row.reason ? " · " + esc(row.reason) : "") + "</li>";
      }).join("");
      var gateChip = restrictedState ? "mw-chip--warn" : "mw-chip--info";
      var gateText = restrictedState ? "New risk restricted" : "New risk eligible";
      items.push('<li><span class="mw-chip ' + gateChip + '">' + gateText + "</span><p>" +
        esc(restriction.sentence || "") + esc(extra) + "</p>" +
        (quarantine ? "<ul>" + quarantine + "</ul>" : "") + "</li>");
    }
    if (flags.staleReviews.length) {
      var stale = flags.staleReviews.map(function (row) {
        return "<li>" + esc(row.label) + ": " + esc(statusLabel("", "stale")) + "</li>";
      }).join("");
      items.push('<li><span class="mw-chip mw-chip--warn">Stale</span><ul>' + stale + "</ul></li>");
    }
    var body = items.length ? '<ul class="tb-flag-list">' + items.join("") + "</ul>" : '<p class="tb-empty">No fleet flags on this book.</p>';
    return '<h3 class="tb-section-title">Fleet flags</h3>' + body;
  }

  function currentFlags() {
    var seats = (traderPacket && traderPacket.seats) || [];
    var pms = (pmPacket && pmPacket.pms) || [];
    var permissions = (traderPacket && traderPacket.trade_permissions) || {};
    return fleetFlags(seats, pms, permissions);
  }

  function placeFleet() {
    var seats = (traderPacket && traderPacket.seats) || [];
    var kpiHtml = fleetKpiHtml(seats);
    var flags = flagHtml(currentFlags());
    var kpiMount = document.getElementById("tb-fleet-kpis");
    var flagMount = document.getElementById("tb-fleet-flags");
    if (kpiMount) kpiMount.innerHTML = kpiHtml;
    if (flagMount) flagMount.innerHTML = flags;
    var inlineKpi = document.getElementById("tb-fleet-kpis-inline");
    var inlineFlags = document.getElementById("tb-fleet-flags-inline");
    if (inlineKpi) inlineKpi.innerHTML = kpiHtml;
    if (inlineFlags) inlineFlags.innerHTML = flags;
  }

  function safeId(value) {
    return String(value || "row").replace(/[^A-Za-z0-9_-]/g, "");
  }

  function discloseButton(id, name, kind, open) {
    var control = "tb-drawer-" + kind + "-" + safeId(id);
    return '<button type="button" class="tb-disclose" data-disclose="' + esc(id) + '" data-kind="' + kind +
      '" aria-expanded="' + (open ? "true" : "false") + '" aria-controls="' + control + '" aria-label="' +
      esc((open ? "Hide " : "Show ") + name) + '">' + (open ? "Hide" : "Show") + "</button>";
  }

  function proseBlock(label, text, limit) {
    var clean = cleanBlurb(text, "", limit);
    if (!clean) return "";
    return '<p class="tb-thesis"><b>' + label + "</b> " + esc(clean) + "</p>";
  }

  function pitchHtml(value) {
    if (!value) return "";
    var text = typeof value === "string" ? value : JSON.stringify(value);
    return '<div class="tb-pitch"><b>Required pitch (not necessarily risked):</b> ' + esc(text) + "</div>";
  }

  function formatRate(row) {
    if (!row) return "";
    if (finite(row.funding_percent_rate)) return row.funding_percent_rate.toFixed(2) + "%";
    if (finite(row.funding_rate_annual)) return (row.funding_rate_annual * 100).toFixed(2) + "%";
    return "";
  }

  function fundingDetail(row) {
    var bits = [];
    var rate = formatRate(row);
    if (rate) bits.push("Rate " + esc(rate));
    if (row.funding_convention) bits.push(esc(row.funding_convention));
    if (finite(row.funding_day_count)) bits.push("Day count " + esc(String(row.funding_day_count)));
    if (row.funding_source) {
      bits.push("Source " + esc(humaniseSource(row.funding_source)) + ' <span class="mw-raw">' + esc(row.funding_source) + "</span>");
    }
    if (row.funding_effective_date) bits.push("Effective " + esc(formatStamp(row.funding_effective_date, false)));
    if (!bits.length && !finite(row.funding_cost_usd)) return "";
    var cost = finite(row.funding_cost_usd)
      ? '<b class="mw-num ' + (row.funding_cost_usd ? "mw-down" : "mw-flat") + '">' + costMoney(row.funding_cost_usd) + "</b> "
      : "";
    return '<div class="tb-block"><span class="mw-label">Funding</span><p>' + cost + bits.join(" · ") + "</p></div>";
  }

  function alertBuckets(row) {
    var flags = [];
    var watches = [];
    var seenFlag = {};
    var seenWatch = {};
    ((row && row.alerts) || []).forEach(function (alert) {
      var item = classifyAlert(alert);
      if (item.kind === "watch") {
        if (seenWatch[alert]) return;
        seenWatch[alert] = true;
        watches.push({ text: humaniseWatch(alert), raw: String(alert) });
        return;
      }
      var key = item.kind + "|" + (item.instrument || item.positionId || "") + "|" + (item.reason || "");
      if (seenFlag[key]) {
        seenFlag[key].count += 1;
        return;
      }
      var line = item.text;
      if (item.kind === "funding") line = "Funding accrual failed closed. " + item.reason;
      if (item.kind === "paper_mark") line = "Paper mark unavailable for " + humaniseInstrument(item.instrument) + ": " + item.reason;
      seenFlag[key] = { line: line, raw: item.instrument || item.positionId || "", count: 1 };
      flags.push(seenFlag[key]);
    });
    if (row && row.risk_stopped) flags.push({ line: "Risk stopped", raw: "", count: 1 });
    if (row && row.risk_stop_pending) flags.push({ line: "Risk stop pending", raw: "", count: 1 });
    if (row && row.pnl_unavailable) flags.push({ line: "P&L unavailable", raw: "", count: 1 });
    return { flags: flags, watches: watches };
  }

  function listHtml(items, empty) {
    if (!items.length) return '<p class="tb-empty">' + empty + "</p>";
    return "<ul>" + items.map(function (item) {
      var title = item.raw && item.text !== item.raw ? ' title="' + esc(item.raw) + '"' : "";
      var times = item.count > 1 ? " (recorded " + item.count + " times)" : "";
      var raw = item.raw && item.line ? ' <span class="mw-raw">' + esc(item.raw) + "</span>" : "";
      return "<li" + title + ">" + esc(item.line || item.text) + raw + esc(times) + "</li>";
    }).join("") + "</ul>";
  }

  function metric(label, inner) {
    return '<div><span class="mw-label">' + label + "</span>" + inner + "</div>";
  }

  function traderDrawer(seat) {
    var positions = seat.positions || [];
    var posHtml = positions.length ? positions.map(renderPosition).join("") : '<p class="tb-empty">No open risk</p>';
    var buckets = alertBuckets(seat);
    var open = !!traderView.open[seat.seat];
    var id = "tb-drawer-trader-" + safeId(seat.seat);
    return '<tr class="tb-drawer-row" id="' + id + '"' + (open ? "" : " hidden") + '><td colspan="11" data-col="drawer">' +
      '<div class="tb-drawer"><div class="tb-block"><span class="mw-label">Positions</span><div class="tb-positions">' + posHtml + "</div></div>" +
      '<div class="tb-metrics">' +
      metric("Risk limit", '<b class="mw-num">' + money(seat.risk_capital_limit_usd) + " / 1% move</b>") +
      metric("Net P&amp;L", '<b class="mw-num ' + toneClass(seat.net_pnl_usd) + '">' + signedMoney(seat.net_pnl_usd) + "</b>") +
      metric("Gross P&amp;L", '<b class="mw-num ' + toneClass(seat.gross_pnl_usd) + '">' + signedMoney(seat.gross_pnl_usd) + "</b>") +
      metric("Risk used", '<b class="mw-num">' + money(seat.risk_capital_usd) + "</b>") +
      metric("Drawdown", '<b class="mw-num ' + (seat.risk_stopped || (finite(seat.drawdown_usd) && seat.drawdown_usd > 0) ? "mw-down" : "mw-flat") + '">' + money(seat.drawdown_usd) + " / " + money(seat.max_drawdown_usd) + "</b>") +
      metric("Funding", '<b class="mw-num ' + (seat.funding_cost_usd ? "mw-down" : "mw-flat") + '">' + costMoney(seat.funding_cost_usd) + "</b>") +
      metric("Net financing", '<b class="mw-num ' + toneClass(seat.net_financing_pnl_usd) + '">' + signedMoney(seat.net_financing_pnl_usd) + "</b>") +
      metric("Recorded conviction", '<b class="mw-num">' + convictionText(seat.conviction) + "</b>") +
      metric("NAV", '<b class="mw-num">' + money(seat.nav_usd) + "</b>") +
      (seat.expression_rule ? metric("Expression", "<b>" + esc(humaniseRule(seat.expression_rule)) + "</b>") : "") +
      "</div>" +
      (seat.remit ? '<p class="tb-thesis"><b>Remit:</b> ' + esc(seat.remit) + "</p>" : "") +
      proseBlock("Current book view:", seat.thesis, 700) +
      proseBlock("Book invalidation:", seat.invalidation, 500) +
      '<div class="tb-block"><span class="mw-label">Watch items</span>' + listHtml(buckets.watches, "No watch items.") + "</div>" +
      '<div class="tb-block"><span class="mw-label">Risk flags</span>' + listHtml(buckets.flags, "No risk flags on this seat.") + "</div>" +
      pitchHtml(seat.required_pitch) +
      fundingDetail(seat) +
      "</div></td></tr>";
  }

  function traderRow(seat) {
    var positions = seat.positions || [];
    var emptyLabel = seat.risk_stopped ? "FLAT" : emptyTradeLabel(seat.last_action);
    var name = displayName(seat.seat);
    var open = !!traderView.open[seat.seat];
    var rank = finite(seat.competition_rank) ? String(seat.competition_rank) : "—";
    var unavailable = seat.pnl_unavailable ? '<span class="mw-chip mw-chip--bad">Unavailable</span>' : "";
    var stopped = "";
    if (seat.risk_stopped) stopped = '<span class="mw-chip mw-chip--bad">Risk stopped</span>';
    else if (seat.risk_stop_pending) stopped = '<span class="mw-chip mw-chip--warn">Risk stop pending</span>';
    return '<tr class="tb-main">' +
      '<td data-col="rank" class="mw-num">' + esc(rank) + "</td>" +
      '<td data-col="seat"><div class="tb-seat-line"><div><span class="tb-rank-inline mw-num">#' + esc(rank) + '</span><b class="tb-seat-name">' +
      esc(name) + '</b><div class="tb-remit" title="' + esc(seat.remit || "") + '">' + esc(seat.remit || "") + "</div></div>" +
      discloseButton(seat.seat, name, "trader", open) + "</div></td>" +
      '<td data-col="action"><span class="tb-cell-label mw-label">Action</span><div class="tb-action-cell">' +
      actionChip(seat.last_action) + priorHtml(seat) + stopped + "</div></td>" +
      '<td data-col="positions"><span class="tb-cell-label mw-label">Positions</span>' + renderTradeScan(positions, emptyLabel) + "</td>" +
      '<td data-col="net"><span class="tb-cell-label mw-label">Net P&amp;L</span><b class="mw-num ' + toneClass(seat.net_pnl_usd) + '">' +
      signedMoney(seat.net_pnl_usd) + "</b>" + unavailable + "</td>" +
      '<td data-col="gross"><b class="mw-num ' + toneClass(seat.gross_pnl_usd) + '">' + signedMoney(seat.gross_pnl_usd) + "</b></td>" +
      '<td data-col="funding"><b class="mw-num ' + (seat.funding_cost_usd ? "mw-down" : "mw-flat") + '">' + costMoney(seat.funding_cost_usd) + "</b></td>" +
      '<td data-col="risk"><span class="tb-cell-label mw-label">Risk</span>' + barHtml(seat.risk_capital_usd, seat.risk_capital_limit_usd) + meterSub(seat.risk_capital_usd, seat.risk_capital_limit_usd) + "</td>" +
      '<td data-col="drawdown">' + barHtml(seat.drawdown_usd, seat.max_drawdown_usd) + meterSub(seat.drawdown_usd, seat.max_drawdown_usd) + "</td>" +
      '<td data-col="conviction" class="mw-num" title="Recorded conviction, 0–100">' + esc(convictionText(seat.conviction)) + "</td>" +
      '<td data-col="flags" class="mw-num">' + bookFlagCount(seat) + "</td></tr>";
  }

  function traderBodies(seats) {
    if (!seats.length) return '<tbody class="tb-empty-body"><tr><td colspan="11" class="tb-empty">No seats match this filter.</td></tr></tbody>';
    return seats.map(function (seat) {
      return '<tbody class="tb-seat" data-seat="' + esc(seat.seat) + '">' + traderRow(seat) + traderDrawer(seat) + "</tbody>";
    }).join("");
  }

  function headerButton(key, label, title) {
    var pressed = traderView.sortKey === key ? (traderView.sortDir < 0 ? "descending" : "ascending") : "none";
    var tip = title ? ' title="' + esc(title) + '"' : "";
    return '<th scope="col" data-sort="' + key + '" aria-sort="' + pressed + '"' + tip + '><button type="button" class="tb-sort" data-sort="' +
      key + '">' + label + "</button></th>";
  }

  function filterButtons(view, counts, kind) {
    var specs = [
      ["all", "All"],
      ["open", "Open risk"],
      ["flat", "Flat"],
      ["changed", "Changed"],
      ["winners", "Winners"],
      ["losers", "Losers"],
      ["flagged", "Flagged"]
    ];
    return specs.map(function (spec) {
      var on = view.filter === spec[0];
      return '<button type="button" class="tb-filter" data-filter="' + spec[0] + '" data-kind="' + kind + '" aria-pressed="' +
        (on ? "true" : "false") + '">' + spec[1] + ' <span class="mw-num" data-count="' + spec[0] + '">' + counts[spec[0]] + "</span></button>";
    }).join("");
  }

  function expandLabel(rows, view, idKey) {
    if (!rows.length) return "Expand all";
    for (var i = 0; i < rows.length; i++) {
      if (!view.open[rows[i][idKey]]) return "Expand all";
    }
    return "Collapse all";
  }

  function traderSection(seats) {
    var visible = filteredSorted(seats, traderView, "trader");
    var counts = countFilters(seats, traderView.query, "trader");
    return '<section class="tb-panel" id="tb-seat-section"><div class="tb-panel-head"><h3>Seat comparison</h3><p>Each trader has a $10m risk limit per 1% standard move and a $5m max drawdown. A breached book is forcibly flattened and marked RISK_STOPPED.</p></div>' +
      '<div class="tb-toolbar" id="tb-trader-filters">' + filterButtons(traderView, counts, "trader") +
      '<label class="tb-search"><span class="mw-label" for="tb-seat-query">Seat or instrument</span><input id="tb-seat-query" data-query="trader" type="search" value="' +
      esc(traderView.query) + '" autocomplete="off"></label>' +
      '<button type="button" class="tb-expand" data-expand="trader">' + expandLabel(visible, traderView, "seat") + "</button></div>" +
      '<div class="tb-table-wrap"><table class="tb-table tb-table-traders" id="tb-trader-table" data-book="trader">' +
      '<caption>Official SOFR is the zero-return benchmark. Competition P&amp;L subtracts SOFR only on standard-shock risk capital; flat books earn zero financing P&amp;L. Notional is descriptive; the hard drawdown stop is separate.</caption>' +
      '<colgroup><col style="width:4%"><col style="width:17%"><col style="width:9%"><col style="width:16%"><col style="width:8%"><col style="width:8%"><col style="width:7%"><col style="width:11%"><col style="width:11%"><col style="width:6%"><col style="width:3%"></colgroup>' +
      "<thead><tr>" +
      headerButton("rank", "Rank") +
      headerButton("name", "Seat") +
      headerButton("action", "Action") +
      headerButton("positions", "Positions") +
      headerButton("net", "Net P&amp;L") +
      headerButton("gross", "Gross P&amp;L") +
      headerButton("funding", "Funding") +
      headerButton("risk", "Risk") +
      headerButton("drawdown", "Drawdown") +
      headerButton("conviction", "Conviction", "Recorded conviction, 0–100") +
      headerButton("flags", "Flags", "Risk flags other than the shared funding failure") +
      "</tr></thead>" + traderBodies(visible) + "</table></div></section>";
  }

  function ticketRow(row) {
    return '<div class="tb-ticket"><span class="mw-asof">' + esc(formatTime(row.at)) + "</span><span>" +
      esc(displayName(row.seat)) + "</span>" + actionChip(row.action) + "<span>" +
      esc(humaniseInstrument(row.instrument)) + (row.instrument ? ' <span class="mw-raw">' + esc(row.instrument) + "</span>" : "") +
      '</span><span class="mw-num">' + money(row.notional_usd) + "</span></div>";
  }

  function historySince(changes) {
    var dates = [];
    (changes || []).forEach(function (row) {
      var day = ticketDate(row);
      if (day) dates.push(day);
    });
    dates.sort();
    return dates.length ? formatStamp(dates[0], false) : "";
  }

  function ticketsSection(changes) {
    var all = changes || [];
    if (!all.length) {
      return '<section class="tb-panel"><div class="tb-panel-head"><h3>Latest dated tickets</h3></div><p class="tb-empty">No applied tickets.</p></section>';
    }
    var latest = latestTickets(all);
    var day = latestTicketDate(all);
    var since = historySince(all);
    var groups = groupTickets(all).map(function (group) {
      var label = group.date === "undated" ? "Date not recorded" : formatStamp(group.date, false);
      return '<h4 class="mw-asof">' + esc(label) + " (" + group.rows.length + ")</h4>" + group.rows.map(ticketRow).join("");
    }).join("");
    return '<section class="tb-panel"><div class="tb-panel-head"><h3>Tickets dated ' + esc(formatStamp(day, false)) +
      " (" + latest.length + ")</h3><p>Applied OPEN, ADD, REDUCE, HEDGE and CLOSE tickets. The latest book date is shown first; earlier tickets stay in the history.</p></div>" +
      latest.map(ticketRow).join("") +
      '<details class="tb-history"><summary>Full ticket history — ' + all.length + " applied tickets" +
      (since ? " since " + esc(since) : "") + "</summary>" + groups + "</details></section>";
  }

  function researchSection(research) {
    if (!research) return "";
    var news = research.news || [];
    var banks = research.central_bank_research || [];
    function row(item, kicker) {
      var title = item.headline || item.title || item.name || "Research item";
      var note = item.summary || item.market_read || item.note || "";
      var when = item.published_at ? '<span class="mw-asof">' + esc(formatStamp(item.published_at, true)) + "</span>" : "";
      var assets = item.transmission && item.transmission.affected_assets;
      var assetLine = assets && assets.length ? '<span class="tb-assets">Assets: ' + esc(assets.join(", ")) + "</span>" : "";
      return '<article class="tb-research-row"><div class="tb-research-headline"><span class="mw-label">' + esc(kicker) +
        "</span><h4>" + esc(title) + "</h4>" + when + '</div><div class="tb-research-note"><p>' + esc(note) + "</p>" + assetLine + "</div></article>";
    }
    var rows = news.map(function (item) { return row(item, "News"); }).join("") +
      banks.map(function (item) { return row(item, "Central bank"); }).join("");
    var sources = (research.sources || []).filter(function (item) { return typeof item === "string"; });
    var sourceLine = sources.length ? '<p class="tb-sources">Sources: ' + esc(sources.join(", ")) + "</p>" : "";
    return '<details class="tb-research"><summary>Overnight research (' + (news.length + banks.length) +
      ")</summary><p class=\"tb-research-summary\">" + esc(cleanResearchSummary(research.summary)) + "</p>" +
      '<div class="tb-research-list">' + (rows || '<p class="tb-empty">No additional overnight research items</p>') +
      "</div>" + sourceLine + "</details>";
  }

  function pmDrawer(pm) {
    var positions = pm.positions || [];
    var posHtml = positions.length ? positions.map(renderPosition).join("") : '<p class="tb-empty">No open risk</p>';
    var buckets = alertBuckets(pm);
    var open = !!pmView.open[pm.pm_id];
    var id = "tb-drawer-pm-" + safeId(pm.pm_id);
    var review = pm.review_status && pm.review_status !== "stale"
      ? '<p class="tb-thesis"><b>Review:</b> ' + esc(pm.review_status) + "</p>"
      : "";
    return '<tr class="tb-drawer-row" id="' + id + '"' + (open ? "" : " hidden") + '><td colspan="10" data-col="drawer"><div class="tb-drawer">' +
      '<div class="tb-block"><span class="mw-label">Positions</span><div class="tb-positions">' + posHtml + "</div></div>" +
      '<div class="tb-metrics">' +
      metric("Risk limit", '<b class="mw-num">' + money(pm.risk_capital_limit_usd) + " / 1% move</b>") +
      metric("Paper P&amp;L", '<b class="mw-num ' + toneClass(pm.total_pnl_usd) + '">' + signedMoney(pm.total_pnl_usd) + "</b>") +
      metric("Net after funding", '<b class="mw-num ' + toneClass(pmNetPnl(pm)) + '">' + signedMoney(pmNetPnl(pm)) + "</b>") +
      metric("Risk used", '<b class="mw-num">' + money(pm.risk_capital_usd) + "</b>") +
      metric("Drawdown", '<b class="mw-num">' + money(pm.drawdown_usd) + " / " + money(pm.max_drawdown_usd) + "</b>") +
      metric("Recorded conviction", '<b class="mw-num">' + convictionText(pm.conviction) + "</b>") +
      metric("Last action", "<b>" + esc(String(pm.last_action || "—").replace(/_/g, " ")) + "</b>") +
      metric("Decision", "<b>" + esc(decisionLabel(pm.decision_status)) + "</b>") +
      "</div>" +
      (pm.mandate ? '<p class="tb-thesis"><b>Mandate:</b> ' + esc(pm.mandate) + "</p>" : "") +
      proseBlock("Current book view:", pm.thesis, 700) +
      proseBlock("Book invalidation:", pm.invalidation, 500) +
      review +
      '<div class="tb-block"><span class="mw-label">Watch items</span>' + listHtml(buckets.watches, "No watch items.") + "</div>" +
      '<div class="tb-block"><span class="mw-label">Risk flags</span>' + listHtml(buckets.flags, "No risk flags on this book.") + "</div>" +
      fundingDetail(pm) +
      "</div></td></tr>";
  }

  function pmRow(pm) {
    var positions = pm.positions || [];
    var emptyLabel = pm.risk_stopped ? "FLAT" : emptyTradeLabel(pm.decision_status || pm.last_action);
    var name = pm.label || displayName(pm.pm_id);
    var open = !!pmView.open[pm.pm_id];
    var statusKind = statusClass(pm.decision_status, pm.review_status);
    var statusChip = statusKind === "stale" ? "mw-chip--warn" : statusKind === "active" ? "mw-chip--ok" : statusKind === "awaiting" ? "mw-chip--warn" : "";
    var net = pmNetPnl(pm);
    return '<tr class="tb-main"><td data-col="seat"><div class="tb-seat-line"><div><b class="tb-seat-name">' + esc(name) +
      '</b><div class="tb-remit" title="' + esc(pm.mandate || "") + '">' + esc(pm.mandate || "") + "</div></div>" +
      discloseButton(pm.pm_id, name, "pm", open) + "</div></td>" +
      '<td data-col="status"><span class="tb-cell-label mw-label">Status</span><span class="mw-chip ' + statusChip + ' tb-status">' +
      esc(statusLabel(pm.decision_status, pm.review_status)) + "</span></td>" +
      '<td data-col="action"><span class="tb-cell-label mw-label">Last action</span>' + actionChip(pm.last_action) + "</td>" +
      '<td data-col="positions"><span class="tb-cell-label mw-label">Positions</span>' + renderTradeScan(positions, emptyLabel) + "</td>" +
      '<td data-col="paper"><b class="mw-num ' + toneClass(pm.total_pnl_usd) + '">' + signedMoney(pm.total_pnl_usd) + "</b></td>" +
      '<td data-col="net"><span class="tb-cell-label mw-label">Net after funding</span><b class="mw-num ' + toneClass(net) + '">' + signedMoney(net) + "</b>" +
      (pm.pnl_unavailable ? '<span class="mw-chip mw-chip--bad">Unavailable</span>' : "") + "</td>" +
      '<td data-col="risk"><span class="tb-cell-label mw-label">Risk</span>' + barHtml(pm.risk_capital_usd, pm.risk_capital_limit_usd) + meterSub(pm.risk_capital_usd, pm.risk_capital_limit_usd) + "</td>" +
      '<td data-col="drawdown">' + barHtml(pm.drawdown_usd, pm.max_drawdown_usd) + meterSub(pm.drawdown_usd, pm.max_drawdown_usd) + "</td>" +
      '<td data-col="conviction" class="mw-num" title="Recorded conviction, 0–100">' + esc(convictionText(pm.conviction)) + "</td>" +
      '<td data-col="flags" class="mw-num">' + bookFlagCount(pm) + "</td></tr>";
  }

  function pmBodies(pms) {
    if (!pms.length) return '<tbody class="tb-empty-body"><tr><td colspan="10" class="tb-empty">No portfolio managers match this filter.</td></tr></tbody>';
    return pms.map(function (pm) {
      return '<tbody class="tb-pm" data-pm="' + esc(pm.pm_id) + '">' + pmRow(pm) + pmDrawer(pm) + "</tbody>";
    }).join("");
  }

  function pmHeader(key, label, title) {
    var pressed = pmView.sortKey === key ? (pmView.sortDir < 0 ? "descending" : "ascending") : "none";
    var tip = title ? ' title="' + esc(title) + '"' : "";
    return '<th scope="col" data-sort="' + key + '" aria-sort="' + pressed + '"' + tip + '><button type="button" class="tb-sort" data-sort="' + key + '">' + label + "</button></th>";
  }

  function renderPMs(packet) {
    var mount = document.getElementById("tb-pm-root");
    if (!mount) return;
    pmPacket = packet;
    var pms = packet.pms || [];
    pmTotalPnl = sumKnownPnl(pms, pmNetPnl);
    renderSystemSummary();
    placeFleet();
    var visible = filteredSorted(pms, pmView, "pm");
    var counts = countFilters(pms, pmView.query, "pm");
    var comparison = (packet.comparison || []).map(function (row) {
      return "<li><b>" + esc(row.label || row.pm_id) + '</b> <span class="' + toneClass(row.total_pnl_usd) + '">' +
        money(row.total_pnl_usd) + "</span> · " + esc(statusLabel(row.decision_status, row.review_status)) +
        " · Risk " + money(row.risk_capital_usd) + " / " + money(row.risk_capital_limit_usd) + "</li>";
    }).join("");
    var requests = ((packet.data_requests || {}).requests) || [];
    var reqHtml = requests.length ? requests.map(function (row) {
      return '<div class="tb-req-row"><b>' + esc((row.originating_pms || []).join(", ")) + "</b><span>" +
        esc(row.request || "Request recorded without a public description") +
        (row.reason ? " — " + esc(row.reason) : "") + "</span><span>" + esc(row.priority || "") +
        " · ×" + esc(row.repeat_count || 1) + "</span></div>";
    }).join("") : '<p class="tb-empty">No future data requests. Requests never break the current evidence freeze.</p>';
    mount.innerHTML = '<section class="tb-panel"><div class="tb-panel-head"><h3>Portfolio Managers</h3><p>ChatGPT, Swinger, Pragmatist and Grinder each have a $100m risk limit per 1% standard move and a $50m max drawdown. Gross notional is descriptive.</p></div>' +
      '<div class="tb-toolbar" id="tb-pm-filters">' + filterButtons(pmView, counts, "pm") +
      '<label class="tb-search"><span class="mw-label" for="tb-pm-query">PM or instrument</span><input id="tb-pm-query" data-query="pm" type="search" value="' +
      esc(pmView.query) + '" autocomplete="off"></label>' +
      '<button type="button" class="tb-expand" data-expand="pm">' + expandLabel(visible, pmView, "pm_id") + "</button></div>" +
      '<div class="tb-table-wrap"><table class="tb-table tb-table-pms" id="tb-pm-table" data-book="pm"><caption>Paper P&amp;L after deterministic packet marks. Comparison is allowed only after decisions are committed.</caption>' +
      '<colgroup><col style="width:15%"><col style="width:13%"><col style="width:8%"><col style="width:13%"><col style="width:9%"><col style="width:10%"><col style="width:11%"><col style="width:10%"><col style="width:8%"><col style="width:3%"></colgroup><thead><tr>' +
      pmHeader("name", "PM") +
      pmHeader("status", "Status") +
      pmHeader("action", "Last action") +
      pmHeader("positions", "Positions") +
      pmHeader("paper", "Paper P&amp;L") +
      pmHeader("net", "Net after funding") +
      pmHeader("risk", "Risk") +
      pmHeader("drawdown", "Drawdown") +
      pmHeader("conviction", "Conviction", "Recorded conviction, 0–100") +
      pmHeader("flags", "Flags", "Risk flags other than the shared funding failure") +
      "</tr></thead>" + pmBodies(visible) + "</table></div>" +
      (comparison ? '<div class="tb-block"><span class="mw-label">Four-PM comparison</span><ul class="tb-compare">' + comparison + "</ul></div>" : "") +
      "</section>" +
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
        var mount = document.getElementById("tb-pm-root");
        if (!mount) return;
        mount.innerHTML = '<section class="tb-panel"><div class="tb-panel-head"><h3>Portfolio Managers</h3><p>PM public state is not on this build yet.</p></div></section>';
      });
  }

  function replaceBodies(tableId, html) {
    var table = document.getElementById(tableId);
    if (!table || !table.querySelectorAll || !table.insertAdjacentHTML) return;
    var nodes = table.querySelectorAll("tbody");
    for (var i = nodes.length - 1; i >= 0; i--) nodes[i].parentNode.removeChild(nodes[i]);
    table.insertAdjacentHTML("beforeend", html);
  }

  function markSort(tableId, view) {
    var table = document.getElementById(tableId);
    if (!table || !table.querySelectorAll) return;
    var headers = table.querySelectorAll("th[data-sort]");
    for (var i = 0; i < headers.length; i++) {
      var key = headers[i].getAttribute("data-sort");
      headers[i].setAttribute("aria-sort", key === view.sortKey ? (view.sortDir < 0 ? "descending" : "ascending") : "none");
    }
  }

  function markFilters(boxId, view, rows, kind, idKey) {
    var box = document.getElementById(boxId);
    if (!box || !box.querySelectorAll) return;
    var counts = countFilters(rows, view.query, kind);
    var buttons = box.querySelectorAll("[data-filter]");
    for (var i = 0; i < buttons.length; i++) {
      var key = buttons[i].getAttribute("data-filter");
      buttons[i].setAttribute("aria-pressed", key === view.filter ? "true" : "false");
      var num = buttons[i].querySelector("[data-count]");
      if (num && counts[key] !== undefined) num.textContent = String(counts[key]);
    }
    var expand = box.querySelector("[data-expand]");
    if (expand) expand.textContent = expandLabel(filteredSorted(rows, view, kind), view, idKey);
  }

  function refillTraders() {
    var seats = (traderPacket && traderPacket.seats) || [];
    replaceBodies("tb-trader-table", traderBodies(filteredSorted(seats, traderView, "trader")));
    markSort("tb-trader-table", traderView);
    markFilters("tb-trader-filters", traderView, seats, "trader", "seat");
  }

  function refillPms() {
    var pms = (pmPacket && pmPacket.pms) || [];
    replaceBodies("tb-pm-table", pmBodies(filteredSorted(pms, pmView, "pm")));
    markSort("tb-pm-table", pmView);
    markFilters("tb-pm-filters", pmView, pms, "pm", "pm_id");
  }

  function defaultDir(key) {
    if (key === "rank" || key === "name" || key === "action" || key === "status") return 1;
    return -1;
  }

  function onSort(kind, key) {
    var view = kind === "pm" ? pmView : traderView;
    if (view.sortKey === key) view.sortDir = view.sortDir < 0 ? 1 : -1;
    else {
      view.sortKey = key;
      view.sortDir = defaultDir(key);
    }
    if (kind === "pm") refillPms();
    else refillTraders();
  }

  function toggleDrawer(button) {
    var id = button.getAttribute("data-disclose");
    var kind = button.getAttribute("data-kind") || "trader";
    var view = kind === "pm" ? pmView : traderView;
    view.open[id] = !view.open[id];
    var panel = document.getElementById(button.getAttribute("aria-controls"));
    if (panel) panel.hidden = !view.open[id];
    var name = (button.getAttribute("aria-label") || "").replace(/^(Show|Hide)\s+/, "");
    button.setAttribute("aria-expanded", view.open[id] ? "true" : "false");
    button.setAttribute("aria-label", (view.open[id] ? "Hide " : "Show ") + name);
    button.textContent = view.open[id] ? "Hide" : "Show";
    var rows = kind === "pm" ? ((pmPacket && pmPacket.pms) || []) : ((traderPacket && traderPacket.seats) || []);
    markFilters(kind === "pm" ? "tb-pm-filters" : "tb-trader-filters", view, rows, kind, kind === "pm" ? "pm_id" : "seat");
  }

  function toggleAll(kind) {
    var view = kind === "pm" ? pmView : traderView;
    var rows = filteredSorted(kind === "pm" ? ((pmPacket && pmPacket.pms) || []) : ((traderPacket && traderPacket.seats) || []), view, kind);
    var idKey = kind === "pm" ? "pm_id" : "seat";
    var opening = expandLabel(rows, view, idKey) === "Expand all";
    rows.forEach(function (row) { view.open[row[idKey]] = opening; });
    if (kind === "pm") refillPms();
    else refillTraders();
  }

  function onClick(event) {
    var target = event.target;
    if (!target || !target.closest || !target.closest(".traderbook")) return;
    var sortBtn = target.closest("button[data-sort]");
    if (sortBtn) {
      var table = sortBtn.closest("table");
      onSort(table && table.getAttribute("data-book") === "pm" ? "pm" : "trader", sortBtn.getAttribute("data-sort"));
      return;
    }
    var filterBtn = target.closest("button[data-filter]");
    if (filterBtn) {
      var kind = filterBtn.getAttribute("data-kind") === "pm" ? "pm" : "trader";
      var view = kind === "pm" ? pmView : traderView;
      view.filter = filterBtn.getAttribute("data-filter") || "all";
      if (kind === "pm") refillPms();
      else refillTraders();
      return;
    }
    var disclose = target.closest("button[data-disclose]");
    if (disclose) {
      toggleDrawer(disclose);
      return;
    }
    var expand = target.closest("button[data-expand]");
    if (expand) toggleAll(expand.getAttribute("data-expand") === "pm" ? "pm" : "trader");
  }

  function onInput(event) {
    var input = event.target;
    if (!input || !input.getAttribute) return;
    var which = input.getAttribute("data-query");
    if (which === "trader") {
      traderView.query = input.value || "";
      refillTraders();
    } else if (which === "pm") {
      pmView.query = input.value || "";
      refillPms();
    }
  }

  function renderMeta(packet) {
    var pub = packet.publication || {};
    var status = pub.trader_books_status || packet.review_status || "stale";
    var pmStatus = pub.pm_books_status;
    var core = pub.core_status || "";
    var asOf = packet.books_as_of || packet.as_of || "";
    var runId = packet.books_run_id || packet.overnight_run_id || "";
    var coreLabel = core === "ok" ? "Core checks passed" : core === "failed" ? "Core checks failed" : "Core: " + (core || "not recorded");
    var bits = [
      '<span class="mw-asof">Books as of ' + esc(formatStamp(asOf, true)) + "</span>",
      chip(reviewKind(status), "Trader review: " + status)
    ];
    if (pmStatus) bits.push(chip(reviewKind(pmStatus), "PM review: " + pmStatus));
    if (packet.evidence_cutoff) bits.push('<span class="mw-asof">Evidence cutoff ' + esc(formatStamp(packet.evidence_cutoff, true)) + "</span>");
    if (core) bits.push(chip(reviewKind(core), coreLabel));
    if (runId) bits.push('<details class="tb-run"><summary>Book run</summary><span class="mw-raw" title="' + esc(runId) + '">' + esc(runId) + "</span></details>");
    meta.innerHTML = bits.join("");
    return status;
  }

  function render(packet) {
    traderPacket = packet;
    var seats = packet.seats || [];
    traderTotalPnl = sumKnownPnl(seats, function (seat) { return seat.net_pnl_usd; });
    renderSystemSummary();
    var status = renderMeta(packet);
    var pub = packet.publication || {};
    var stale = "";
    if (status !== "fresh") {
      stale = '<div class="tb-stale" role="status"><b>Stale or failed trader review.</b> ' +
        esc(pub.reason || "Publishing last successful books rather than blocking the website.") +
        (pub.last_successful_review_run_id ? ' Last successful review: <span class="mw-raw">' + esc(pub.last_successful_review_run_id) + "</span>." : "") +
        "</div>";
    }
    var externalFleet = !!document.getElementById("tb-fleet-kpis");
    var inline = externalFleet ? "" :
      '<div id="tb-fleet-kpis-inline">' + fleetKpiHtml(seats) + '</div><div id="tb-fleet-flags-inline">' + flagHtml(currentFlags()) + "</div>";
    root.innerHTML = stale + inline + traderSection(seats) + ticketsSection(packet.overnight_changes || []) +
      '<div id="tb-pm-root"></div>' + researchSection(packet.overnight_research || null);
    placeFleet();
    if (!bound && document.addEventListener) {
      bound = true;
      document.addEventListener("click", onClick);
      document.addEventListener("input", onInput);
    }
    loadPMs();
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
