"""Front-page EA/JP mini-card values from live temperature component_state."""

from __future__ import annotations

from typing import Any

PLACEHOLDER_VALUES = frozenset({"", "—", "-", "context", "n/a"})


def _format_transform_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    rounded = round(float(value), 4)
    return f"{rounded:.4f}".rstrip("0").rstrip(".")

EA_HEADING = "EURO AREA"
JP_HEADING = "JAPAN"
EA_KEY = "ea"
JP_KEY = "jp"


def _observed_transform(component_state: dict[str, Any], name: str) -> float | None:
    component = component_state.get(name) or {}
    if not component.get("observed"):
        return None
    value = component.get("transform_value")
    if value is None:
        return None
    return float(value)


def _format_rate_percent(value: float) -> str:
    return f"{_format_transform_value(value)}%"


def _format_activity_value(name: str, value: float) -> str:
    if name == "business_surveys":
        return _format_transform_value(value)
    return _format_rate_percent(value)


def _activity_row(component_state: dict[str, Any]) -> tuple[str, str]:
    for name, label in (
        ("business_surveys", "Business surveys"),
        ("gdp_domestic_demand", "Domestic demand"),
    ):
        value = _observed_transform(component_state, name)
        if value is not None:
            return label, _format_activity_value(name, value)
    raise ValueError("no observed Activity field for mini card")


def mini_rows_for_country(state: dict[str, Any], country: str) -> list[tuple[str, str]]:
    countries = state.get("countries") or {}
    if country not in countries:
        raise ValueError(f"unknown country {country}")

    inflation_cs = (countries[country].get("Inflation") or {}).get("component_state") or {}
    labor_cs = (countries[country].get("Labor") or {}).get("component_state") or {}
    activity_cs = (countries[country].get("Activity") or {}).get("component_state") or {}

    headline = _observed_transform(inflation_cs, "headline")
    underlying = _observed_transform(inflation_cs, "underlying")
    if headline is None or underlying is None:
        raise ValueError(f"{country} inflation mini row missing observed headline/underlying")

    unemployment = _observed_transform(labor_cs, "unemployment")
    if unemployment is None:
        raise ValueError(f"{country} unemployment mini row missing observed unemployment")

    inflation_label = "HICP / core" if country == "EA" else "CPI / core"
    inflation_value = f"{_format_rate_percent(headline)} / {_format_rate_percent(underlying)}"
    activity_label, activity_value = _activity_row(activity_cs)

    return [
        (inflation_label, inflation_value),
        ("Unemployment", _format_rate_percent(unemployment)),
        (activity_label, activity_value),
    ]


def mini_html(rows: list[tuple[str, str]]) -> str:
    parts = [
        f'<div class="mrow"><span>{label}</span><b>{value}</b></div>'
        for label, value in rows
    ]
    return '<div class="mini">' + "".join(parts) + "</div>"


def _replace_country_mini(html: str, heading: str, key: str, block: str) -> str:
    anchor = f"<h3>{heading}</h3>"
    start = html.index(anchor)
    mini_start = html.index('<div class="mini">', start)
    jump = f'<label class="jump" for="c-{key}">'
    jump_at = html.index(jump, mini_start)
    mini_end = html.rindex("</div>", mini_start, jump_at) + len("</div>")
    return html[:mini_start] + block + html[mini_end:]


def patch_ea_jp_snapshot_minis(html: str, state: dict[str, Any]) -> str:
    for country, heading, key in (
        ("EA", EA_HEADING, EA_KEY),
        ("JP", JP_HEADING, JP_KEY),
    ):
        block = mini_html(mini_rows_for_country(state, country))
        try:
            html = _replace_country_mini(html, heading, key, block)
        except ValueError as exc:
            raise ValueError(f"could not patch mini card for {country}") from exc
    return html


def ea_jp_mini_shell_html(country: str) -> str:
    """Static labeled shell; values filled by patch_ea_jp_snapshot_minis."""
    if country == "EA":
        rows = [
            ("HICP / core", ""),
            ("Unemployment", ""),
            ("Business surveys", ""),
        ]
    elif country == "JP":
        rows = [
            ("CPI / core", ""),
            ("Unemployment", ""),
            ("Business surveys", ""),
        ]
    else:
        raise ValueError(country)
    return mini_html(rows)
