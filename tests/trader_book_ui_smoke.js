"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const repo = path.resolve(__dirname, "..");
const js = fs.readFileSync(path.join(repo, "patch_v13", "trader-book.js"), "utf8");

function el(id) {
  return {
    id: id,
    innerHTML: "",
    textContent: "—",
    className: "",
  };
}

const els = {
  "trader-book-root": el("trader-book-root"),
  "tb-meta": el("tb-meta"),
  "tb-trader-total": el("tb-trader-total"),
  "tb-pm-total": el("tb-pm-total"),
  "tb-pm-root": el("tb-pm-root"),
};

const document = {
  getElementById: function (id) {
    if (id === "tb-pm-root") {
      return String(els["trader-book-root"].innerHTML).indexOf('id="tb-pm-root"') !== -1
        ? els["tb-pm-root"]
        : null;
    }
    return els[id] || null;
  },
};

const traderPacket = {
  as_of: "2026-09-20T00:00:00Z",
  evidence_cutoff: "2026-09-20T02:08:18Z",
  overnight_run_id: "tr-ui-smoke",
  review_status: "fresh",
  seat_count: 2,
  publication: { core_status: "ok", trader_books_status: "fresh" },
  seats: [
    {
      seat: "dollar-king",
      competition_rank: 2,
      last_action: "OPEN",
      remit: "USD spot",
      net_pnl_usd: -10000,
      realized_pnl_usd: 0,
      unrealized_pnl_usd: 0,
      funding_cost_usd: 10000,
      cash_yield_usd: 0,
      nav_usd: 99990000,
      risk_capital_limit_usd: 10000000,
      risk_capital_usd: 5500000,
      drawdown_usd: 0,
      max_drawdown_usd: 5000000,
      positions: [
        {
          instrument: "USDCAD",
          asset_class: "spot_fx",
          side: "long",
          notional_usd: 55000000,
          risk_capital_usd: 5500000,
          unrealized_pnl_usd: 999999,
          entry_price: 1.4,
          mark_price: 1.4,
          thesis: "USD vs CAD",
        },
      ],
    },
    {
      seat: "no-trade-skeptic",
      competition_rank: 1,
      last_action: "HOLD",
      remit: "may submit no-trade",
      net_pnl_usd: 0,
      realized_pnl_usd: 0,
      unrealized_pnl_usd: 0,
      funding_cost_usd: 0,
      cash_yield_usd: 5000,
      benchmark_cost_usd: 5000,
      net_financing_pnl_usd: 0,
      nav_usd: 100000000,
      risk_capital_limit_usd: 10000000,
      risk_capital_usd: 0,
      drawdown_usd: 0,
      max_drawdown_usd: 5000000,
      positions: [],
    },
  ],
};

const pmPacket = {
  pm_count: 2,
  pms: [
    {
      pm_id: "chatgpt",
      label: "ChatGPT",
      decision_status: "active",
      review_status: "fresh",
      last_action: "OPEN",
      mandate: "Final synthesis",
      net_after_funding_pnl_usd: 2000,
      total_pnl_usd: 3000,
      risk_capital_limit_usd: 100000000,
      risk_capital_usd: 50000000,
      drawdown_usd: 0,
      max_drawdown_usd: 50000000,
      positions: [
        {
          instrument: "CORRA_2027-03",
          asset_class: "rates",
          side: "long",
          notional_usd: 500000000,
          risk_capital_usd: 50000000,
          unrealized_pnl_usd: 888888,
        },
      ],
    },
    {
      pm_id: "grinder",
      label: "Grinder",
      decision_status: "no_trade",
      review_status: "fresh",
      last_action: "NO_TRADE",
      mandate: "Preservation first",
      net_after_funding_pnl_usd: 0,
      total_pnl_usd: 0,
      risk_capital_limit_usd: 100000000,
      risk_capital_usd: 0,
      drawdown_usd: 0,
      max_drawdown_usd: 50000000,
      positions: [],
    },
  ],
};

function fetch(url) {
  const packet = String(url).indexOf("pm-books") !== -1 ? pmPacket : traderPacket;
  return Promise.resolve({
    ok: true,
    json: function () {
      return Promise.resolve(packet);
    },
  });
}

function fail(message) {
  console.error("FAIL: " + message);
  process.exit(1);
}

function check(cond, message) {
  if (!cond) fail(message);
}

vm.runInNewContext(js, {
  document: document,
  fetch: fetch,
  console: console,
  Number: Number,
  String: String,
  Math: Math,
  JSON: JSON,
});

async function flush() {
  for (let i = 0; i < 12; i += 1) {
    await Promise.resolve();
  }
}

flush().then(function () {
  const root = els["trader-book-root"].innerHTML;
  const pms = els["tb-pm-root"].innerHTML;
  const traderTotal = els["tb-trader-total"].textContent;
  const pmTotal = els["tb-pm-total"].textContent;

  check(root.indexOf("id=\"tb-pm-root\"") !== -1, "PM mount is rendered after trader books");
  check(traderTotal === "-$10.0k", "trader total is seat net P&L only, got " + traderTotal);
  check(pmTotal === "$2.0k", "PM total uses net-after-funding, not paper total or position P&L, got " + pmTotal);
  check(traderTotal !== pmTotal, "trader and PM totals stay separate");

  const seatCards = root.split('<article class="tb-seat">').slice(1);
  const dollar = seatCards.find(function (card) { return card.indexOf("Dollar King") !== -1; });
  const skeptic = seatCards.find(function (card) { return card.indexOf("No Trade Skeptic") !== -1; });
  check(Boolean(dollar), "Dollar King card is titled from the seat id");
  check(dollar.indexOf("Long USDCAD") !== -1, "Dollar King Long USDCAD is on the card");
  check(dollar.indexOf('tb-trade-line') !== -1, "active trader card has a scan-line trade");
  check(dollar.indexOf("Punchline") !== -1 && dollar.indexOf("Support") !== -1 && dollar.indexOf("Take profit") !== -1 && dollar.indexOf("Invalidation") !== -1, "active trader card uses the four-part trade story");
  check(Boolean(skeptic), "No Trade Skeptic card is titled from the seat id");
  check(skeptic.indexOf("FLAT") !== -1, "flat trader card is labeled FLAT");
  check(skeptic.indexOf("LONG") === -1 && skeptic.indexOf("SHORT") === -1, "flat trader card has no fake LONG/SHORT");
  check(skeptic.indexOf("USDCAD") === -1, "flat trader card does not inherit another seat instrument");

  const pmCards = pms.split('<article class="tb-pm">').slice(1);
  const chatgpt = pmCards.find(function (card) { return card.indexOf("ChatGPT") !== -1; });
  const grinder = pmCards.find(function (card) { return card.indexOf("Grinder") !== -1; });
  check(Boolean(chatgpt) && chatgpt.indexOf("Receive H7 CORRA") !== -1, "active PM card uses receive/pay market shorthand");
  check(chatgpt.indexOf("CORRA_2027-03") === -1, "active PM card hides normalized internal contract IDs");
  check(Boolean(grinder) && grinder.indexOf("NO TRADE") !== -1, "no-trade PM card is labeled NO TRADE");
  check(grinder.indexOf("LONG") === -1 && grinder.indexOf("SHORT") === -1, "no-trade PM card has no fake LONG/SHORT");

  check(root.indexOf("Net financing") !== -1, "trader KPI uses net financing, not cash-yield alpha");
  check(root.indexOf("zero-return") !== -1, "leaderboard copy states SOFR is the zero-return benchmark");
  check(root.indexOf("Cash yield") === -1, "flat-book cash yield is not shown as alpha");
  check(pms.indexOf("$100m risk limit per 1% standard move") !== -1, "PM risk-limit wording is preserved");
  check(root.indexOf("999999") === -1 && pms.indexOf("888888") === -1, "position P&L is not used as the book total");
  console.log("trader_book_ui_smoke ok");
}).catch(function (error) {
  fail(error && error.stack ? error.stack : String(error));
});
