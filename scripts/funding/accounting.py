"""Zero-return SOFR benchmark for competition / financing P&L.

Official NY Fed SOFR is the zero-return hurdle, not free alpha. Paper NAV
may be described as earning SOFR, but the same capital is benchmarked at
SOFR so those flows cancel. Competition P&L only subtracts official SOFR
ACT/360 charged on current standard-shock risk capital.
"""

from __future__ import annotations

from typing import Any

FUNDING_REGIME_ZERO_BENCHMARK = "sofr_zero_benchmark"
LEGACY_RISK_CAPITAL_REGIME = "sofr_risk_capital_1pct"


def _money(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def competition_net_pnl(
    gross: float,
    *,
    funding_cost_usd: float,
    cash_yield_usd: float,
    benchmark_cost_usd: float,
) -> float:
    """Trading P&L minus risk-capital SOFR after baseline SOFR flows cancel."""
    return round(float(gross) - float(funding_cost_usd) + float(cash_yield_usd) - float(benchmark_cost_usd), 2)


def net_financing_pnl(
    *,
    funding_cost_usd: float,
    cash_yield_usd: float,
    benchmark_cost_usd: float,
) -> float:
    return round(float(cash_yield_usd) - float(benchmark_cost_usd) - float(funding_cost_usd), 2)


def paper_nav_principal(book: dict[str, Any]) -> float:
    if book.get("starting_nav_usd") not in (None, ""):
        return _money(book.get("starting_nav_usd"))
    if book.get("cash_capital_usd") not in (None, ""):
        return _money(book.get("cash_capital_usd"))
    if book.get("seat"):
        return 100_000_000.0
    if book.get("pm_id"):
        return 1_000_000_000.0
    return 0.0


def _nav_principal_funding(book: dict[str, Any], *, paper_nav: float) -> float:
    """Sum of historical FUNDING charges that used paper NAV as the principal.

    Those rows are the old flat-book vig. Under the zero-return contract they
    are the matching benchmark cost, not shocked-risk financing.
    """
    if paper_nav <= 0:
        return 0.0
    total = 0.0
    for row in book.get("history") or []:
        if row.get("action") != "FUNDING":
            continue
        base = _money(row.get("funding_base_usd"))
        cost = _money(row.get("funding_cost_usd"))
        if cost and abs(base - paper_nav) <= 0.01:
            total = round(total + cost, 2)
    return total


def apply_zero_return_sofr_migration(book: dict[str, Any], *, paper_nav: float | None = None) -> bool:
    """Neutralize prior baseline SOFR cash yield in the competition metric.

    Does not rewrite realized/unrealized trading P&L or historical trade marks.
    Idempotent once ``funding_regime`` is ``sofr_zero_benchmark``.
    """
    nav = float(paper_nav) if paper_nav is not None else paper_nav_principal(book)
    if (
        book.get("funding_regime") == FUNDING_REGIME_ZERO_BENCHMARK
        and book.get("benchmark_cost_usd") is not None
    ):
        book.setdefault("benchmark_cost_usd", round(_money(book.get("cash_yield_usd")), 2))
        return False

    cash_yield = round(_money(book.get("cash_yield_usd")), 2)
    funding = round(_money(book.get("funding_cost_usd")), 2)
    nav_charged = _nav_principal_funding(book, paper_nav=nav)
    new_funding = round(max(0.0, funding - nav_charged), 2)

    # Old financing contribution to NAV/net: cash_yield - funding
    # New contribution: cash_yield - cash_yield - new_funding = -new_funding
    # High-water must move by the same NAV delta so drawdown is not fabricated.
    delta_nav = round(nav_charged - cash_yield, 2)
    high = _money(book.get("high_water_nav_usd")) if book.get("high_water_nav_usd") not in (None, "") else nav
    book["funding_cost_usd"] = new_funding
    book["cash_yield_usd"] = cash_yield
    book["benchmark_cost_usd"] = cash_yield
    book["funding_regime"] = FUNDING_REGIME_ZERO_BENCHMARK
    book["high_water_nav_usd"] = round(high + delta_nav, 2)
    book["net_financing_pnl_usd"] = net_financing_pnl(
        funding_cost_usd=new_funding,
        cash_yield_usd=cash_yield,
        benchmark_cost_usd=cash_yield,
    )
    history = book.setdefault("history", [])
    already = any(row.get("action") == "FUNDING_BENCHMARK_MIGRATION" for row in history)
    if not already and (abs(delta_nav) > 0.0 or abs(nav_charged) > 0.0 or abs(cash_yield) > 0.0):
        history.append(
            {
                "action": "FUNDING_BENCHMARK_MIGRATION",
                "result": "applied",
                "note": (
                    "Official SOFR is the zero-return competition benchmark. "
                    "Prior baseline paper-NAV cash yield is neutralized; "
                    "realized/unrealized trading P&L and trade marks are unchanged."
                ),
                "cash_yield_usd": cash_yield,
                "benchmark_cost_usd": cash_yield,
                "reclassified_nav_funding_usd": nav_charged,
                "funding_cost_usd": new_funding,
            }
        )
    return True


def attach_financing_fields(book: dict[str, Any], *, gross: float | None, missing: bool) -> None:
    """Stamp net P&L after the zero-return SOFR contract."""
    apply_zero_return_sofr_migration(book)
    funding = round(_money(book.get("funding_cost_usd")), 2)
    cash_yield = round(_money(book.get("cash_yield_usd")), 2)
    benchmark = round(_money(book.get("benchmark_cost_usd")), 2)
    book["funding_cost_usd"] = funding
    book["cash_yield_usd"] = cash_yield
    book["benchmark_cost_usd"] = benchmark
    book["funding_regime"] = FUNDING_REGIME_ZERO_BENCHMARK
    financing = net_financing_pnl(
        funding_cost_usd=funding,
        cash_yield_usd=cash_yield,
        benchmark_cost_usd=benchmark,
    )
    book["net_financing_pnl_usd"] = None if missing else financing
    if missing or gross is None:
        return
    net = competition_net_pnl(
        float(gross),
        funding_cost_usd=funding,
        cash_yield_usd=cash_yield,
        benchmark_cost_usd=benchmark,
    )
    if "net_pnl_usd" in book or book.get("seat"):
        book["net_pnl_usd"] = net
    book["net_after_funding_pnl_usd"] = net
