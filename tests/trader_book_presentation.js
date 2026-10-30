"use strict";

const fs = require("fs");
const api = require("../patch_v13/trader-book.js");

function fail(message) {
  console.error("FAIL: " + message);
  process.exit(1);
}

function check(cond, message) {
  if (!cond) fail(message);
}

const human = {
  "CORRA_2027-03": "CORRA Mar 2027",
  "SOFR_2027-09": "SOFR Sep 2027",
  "CORRA_2027H-Z": "CORRA 2027 H\u2013Z",
  "SOFR-CORRA_2Y_2027H1": "SOFR\u2013CORRA 2Y 2027H1",
  "NZ-US_10Y": "NZ\u2013US 10Y",
  "US_10Y": "US 10Y",
  USDCAD: "USD/CAD",
  foo_bar: "foo bar",
};

Object.keys(human).forEach(function (key) {
  const got = api.humaniseInstrument(key);
  check(got === human[key], key + " => " + got + " expected " + human[key]);
});

check(api.humaniseAssetClass("rates") === "Rates", "rates");
check(api.humaniseAssetClass("rates_rv") === "Rates RV", "rates rv");
check(api.humaniseAssetClass("spot_fx") === "Spot FX", "spot fx");
check(
  api.humaniseBlockedSources(["NZ.Inflation.headline", "NZ.Inflation.underlying"]) ===
    "NZ inflation (headline, underlying)",
  "blocked sources"
);

const paper = api.classifyAlert(
  "Paper mark unavailable for NZ-US_10Y: NZ rates are unavailable (latest_observation=None)"
);
check(paper.kind === "paper_mark", "paper kind");
check(paper.instrument === "NZ-US_10Y", "paper instrument");
check(paper.reason === "NZ rates are unavailable (latest_observation=None)", "paper reason");
check(api.humaniseInstrument(paper.instrument) === "NZ\u2013US 10Y", "paper human");

const fundingAlert =
  "funding_accrual_failed_closed: official NY Fed SOFR history is missing; funding accrual failed closed";
const seats = [];
for (let i = 0; i < 14; i += 1) {
  seats.push({
    seat: "seat-" + String(i).padStart(2, "0"),
    net_pnl_usd: i === 0 ? 10000 : i === 1 ? -2500 : 0,
    alerts: [fundingAlert],
    positions: i === 3 ? [{ instrument: "USDCAD", side: "long", mark_price: 1.4166 }] : [],
    risk_capital_usd: 0,
    risk_capital_limit_usd: 10000000,
    drawdown_usd: i === 2 ? 800 : 0,
    max_drawdown_usd: 5000000,
    last_action: i === 4 ? "REDUCE" : "HOLD",
    prior_action: "HOLD",
    pnl_unavailable: false,
  });
}
seats[5].alerts.push(
  "Paper mark unavailable for SOFR_2027-09: tradable SOFR curve unavailable"
);
seats[5].alerts.push(
  "Paper mark unavailable for SOFR_2027-09: tradable SOFR curve unavailable"
);
seats[5].positions = [
  {
    instrument: "SOFR_2027-09",
    mark_status: "unavailable",
    mark_price: null,
    mark_unavailable_reason: "tradable SOFR curve unavailable",
  },
];
const flags = api.fleetFlags(seats, [], {});
check(flags.funding.seatCount === 14, "funding seats " + flags.funding.seatCount);
check(flags.funding.seatTotal === 14, "funding total");
check(flags.paperMarks.length === 1, "paper aggregated " + flags.paperMarks.length);
check(flags.paperMarks[0].count === 2, "duplicate paper count");
check(flags.paperMarks[0].instrument === "SOFR_2027-09", "paper id");
const fundingText = api.describeFunding(flags.funding);
check(
  fundingText.indexOf("14 of 14 seats") === 0,
  "funding text " + fundingText
);
check(fundingText.indexOf("Official NY Fed SOFR history is missing") !== -1, "funding reason");

const recoveredFundingSeat = {
  seat: "recovered-funding",
  alerts: [fundingAlert],
  positions: [],
  funding_accrual_status: "applied",
  unresolved_funding_positions: [],
};
check(
  api.fleetFlags([recoveredFundingSeat], [], {}).funding.seatCount === 0,
  "recovered funding seatCount"
);
check(recoveredFundingSeat.alerts.indexOf(fundingAlert) !== -1, "funding alert preserved");

const failedFunding = {
  seat: "failed-funding",
  alerts: [],
  positions: [],
  funding_accrual_status: "failed_closed",
};
check(api.fleetFlags([failedFunding], [], {}).funding.seatCount === 1, "failed_closed counts");

const unknownFunding = {
  seat: "unknown-funding",
  alerts: [],
  positions: [],
  funding_accrual_status: "unknown",
};
check(api.fleetFlags([unknownFunding], [], {}).funding.seatCount === 1, "unknown funding counts");

const blankFunding = {
  seat: "blank-funding",
  alerts: [],
  positions: [],
  funding_accrual_status: "",
};
check(api.fleetFlags([blankFunding], [], {}).funding.seatCount === 1, "blank funding status counts");

const alertOnlyFunding = {
  seat: "alert-funding",
  alerts: [fundingAlert],
  positions: [],
};
check(api.fleetFlags([alertOnlyFunding], [], {}).funding.seatCount === 1, "alert-only funding counts");

const unresolvedApplied = {
  seat: "unresolved-applied",
  alerts: [fundingAlert],
  positions: [],
  funding_accrual_status: "applied",
  unresolved_funding_positions: ["pos-abc"],
};
const unresolvedFlags = api.fleetFlags([unresolvedApplied], [], {});
check(unresolvedFlags.funding.seatCount === 1, "unresolved with applied counts");
check(
  unresolvedFlags.funding.reason.indexOf("unresolved funding positions remain") !== -1,
  "unresolved reason not SOFR history"
);

const sofrRecovered = {
  seat: "sofr-recovered",
  alerts: ["Paper mark unavailable for SOFR_2027-03: tradable SOFR curve unavailable"],
  positions: [
    { instrument: "SOFR_2027-03", mark_status: "ok", mark_price: 4.39 },
  ],
};
const sofrFleet = api.fleetFlags([sofrRecovered], [], {});
check(sofrFleet.paperMarks.length === 0, "recovered SOFR not in fleet");
check(api.bookFlagCount(sofrRecovered) === 0, "recovered SOFR bookFlagCount");

const nzReason = "NZ rates are unavailable (latest_observation=None)";
const nzAlert = "Paper mark unavailable for NZ-US_10Y: " + nzReason;
const nzBook = {
  seat: "nz-miss",
  alerts: [nzAlert, nzAlert, nzAlert],
  positions: [
    {
      instrument: "NZ-US_10Y",
      mark_status: "unavailable",
      mark_price: null,
      mark_unavailable_reason: nzReason,
    },
  ],
};
const nzFleet = api.fleetFlags([nzBook], [], {});
check(nzFleet.paperMarks.length === 1, "nz one fleet row");
check(nzFleet.paperMarks[0].count === 3, "nz duplicate count");
check(api.bookFlagCount(nzBook) > 0, "nz flagged filter");

const closedPaper = {
  seat: "closed-paper",
  alerts: [nzAlert],
  positions: [],
};
check(api.fleetFlags([closedPaper], [], {}).paperMarks.length === 0, "closed paper fleet");
check(closedPaper.alerts.indexOf(nzAlert) !== -1, "closed paper alert preserved");

const missingStatusAlert = {
  seat: "missing-status-alert",
  alerts: ["Paper mark unavailable for SOFR_2027-03: tradable SOFR curve unavailable"],
  positions: [{ instrument: "SOFR_2027-03", mark_price: 4.39 }],
};
check(api.bookFlagCount(missingStatusAlert) === 1, "missing status with alert flagged");

const missingStatusClean = {
  seat: "missing-status-clean",
  alerts: [],
  positions: [{ instrument: "SOFR_2027-03", mark_price: 4.39 }],
};
check(api.bookFlagCount(missingStatusClean) === 0, "legacy healthy not flagged");

const missingPrice = {
  seat: "missing-price",
  alerts: [],
  positions: [{ instrument: "SOFR_2027-03", mark_price: null }],
};
check(api.bookFlagCount(missingPrice) === 1, "missing price flagged");

const multiLegBad = {
  seat: "multi-leg-bad",
  alerts: [],
  positions: [
    {
      instrument: "SOFR-CORRA_2Y_2027H1",
      mark_status: "ok",
      mark_price: 140.0,
      legs: [
        { instrument: "SOFR_2027-03", mark_status: "ok", mark_rate: 4.4 },
        { instrument: "CORRA_2027-03", mark_status: "unavailable", mark_rate: null },
      ],
    },
  ],
};
check(api.bookFlagCount(multiLegBad) === 1, "multi-leg bad leg flagged");

const multiLegOk = {
  seat: "multi-leg-ok",
  alerts: [],
  positions: [
    {
      instrument: "SOFR-CORRA_2Y_2027H1",
      mark_status: "ok",
      mark_price: 140.0,
      legs: [
        { instrument: "SOFR_2027-03", mark_status: "ok", mark_rate: 4.4 },
        { instrument: "CORRA_2027-03", mark_status: "ok", mark_rate: 3.0 },
      ],
    },
  ],
};
check(api.bookFlagCount(multiLegOk) === 0, "multi-leg all ok not flagged");

function seatRows(raw) {
  return Object.keys(raw.seats).map(function (key) {
    const row = raw.seats[key];
    return Object.assign({ seat: row.seat || key }, row);
  });
}

function pmRows(raw) {
  return Object.keys(raw.pms).map(function (key) {
    const row = raw.pms[key];
    return Object.assign({ pm_id: row.pm_id || key }, row);
  });
}

const overnightRaw = JSON.parse(fs.readFileSync("data/overnight/books/latest.json", "utf8"));
const pmRaw = JSON.parse(fs.readFileSync("data/pm/books/latest.json", "utf8"));
const canonicalSeats = seatRows(overnightRaw);
const canonicalPms = pmRows(pmRaw);
const oct30 = api.fleetFlags(canonicalSeats, canonicalPms, {});
check(oct30.funding.seatCount === 0, "oct30 funding seats " + oct30.funding.seatCount);
check(oct30.funding.pmCount === 0, "oct30 funding pms " + oct30.funding.pmCount);
check(oct30.paperMarks.length === 1, "oct30 paper rows " + oct30.paperMarks.length);
check(oct30.paperMarks[0].id === "pragmatist", "oct30 paper book");
check(oct30.paperMarks[0].instrument === "NZ-US_10Y", "oct30 paper instrument");
check(oct30.paperMarks[0].count === 10, "oct30 paper count " + oct30.paperMarks[0].count);
check(oct30.paperMarks[0].reason.indexOf("NZ rates are unavailable") !== -1, "oct30 paper reason");

canonicalSeats.forEach(function (seat) {
  check(seat.funding_accrual_status === "applied", seat.seat + " funding applied");
});
canonicalPms.forEach(function (pm) {
  check(pm.funding_accrual_status === "applied", pm.pm_id + " funding applied");
});

function findSeat(id) {
  return canonicalSeats.find(function (row) { return row.seat === id; });
}

["mean-reverter", "perma-bull", "rate-hawk"].forEach(function (id) {
  const seat = findSeat(id);
  const sofr = (seat.positions || []).find(function (p) {
    return p.instrument === "SOFR_2027-03" || p.instrument === "SOFR_2027-09";
  });
  check(sofr && sofr.mark_status === "ok", id + " SOFR mark ok");
});

const traderFlagged = canonicalSeats.filter(function (seat) {
  return api.bookFlagCount(seat) > 0;
});
check(traderFlagged.length === 1 && traderFlagged[0].seat === "value-guy", "oct30 trader flagged");
check(api.bookFlagCount(traderFlagged[0]) === 1, "value-guy flag count");

const pmFlagged = canonicalPms.filter(function (pm) {
  return api.bookFlagCount(pm) > 0;
});
check(pmFlagged.length === 1 && pmFlagged[0].pm_id === "pragmatist", "oct30 pm flagged");
check(api.bookFlagCount(pmFlagged[0]) === 2, "pragmatist flag count");

const changes = [
  { at: "2026-09-19T22:36:50.082404-04:00", instrument: "CORRA_2027-03", seat: "a", action: "OPEN" },
  { at: "2026-10-23T01:00:00-04:00", instrument: "USDCAD", seat: "b", action: "ADD" },
  { at: "2026-10-23T15:46:45.247147-04:00", instrument: "SOFR_2027-03", seat: "c", action: "REDUCE" },
];
check(api.latestTicketDate(changes) === "2026-10-23", "latest date");
const latest = api.latestTickets(changes);
check(latest.length === 2, "latest count " + latest.length);
check(latest.every(function (row) { return String(row.at).indexOf("2026-10-23") === 0; }), "latest only newest");

const sorted = [
  { seat: "b", net_pnl_usd: 5, positions: [] },
  { seat: "a", net_pnl_usd: null, positions: [] },
  { seat: "c", net_pnl_usd: 20, positions: [] },
].slice().sort(function (a, b) { return api.compareRows(a, b, "net", -1, "trader"); });
check(sorted.map(function (row) { return row.seat; }).join(",") === "c,b,a", "nulls sort last");

const raw = fs.readFileSync(0, "utf8");
const fixture = JSON.parse(raw);
const traderTotal = api.sumKnownPnl(fixture.seats, function (seat) { return seat.net_pnl_usd; });
const pmTotal = api.sumKnownPnl(fixture.pms, api.pmNetPnl);
const snap = api.fleetSnapshot(fixture.seats);
check(snap.netPnl === traderTotal, "snapshot matches sumKnownPnl");
process.stdout.write(JSON.stringify({ traderTotal: traderTotal, pmTotal: pmTotal, fundingText: fundingText }));
console.log("");
console.log("trader_book_presentation ok");
