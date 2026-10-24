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
    positions: i === 3 ? [{ instrument: "USDCAD", side: "long" }] : [],
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
