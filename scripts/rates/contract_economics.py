"""Verified STIR contract economics.

These are exchange contract conventions, not market data and not a trading view.
USD conversion uses a supplied FX observation. Missing FX stays unresolved.

CME Three-Month SOFR (SR3): IMM index = 100 - rate; USD 25 per basis point;
reference face USD 1,000,000 (0.01% × 90/360 × 1,000,000 = 25).

Montréal Exchange Three-Month CORRA (CRA): index = 100 - rate; CAD 25 per
basis point; reference face CAD 1,000,000.

ASX 30 Day Interbank Cash Rate futures (IB), settlement to the monthly average
of AONIA: price = 100 - rate. Variation on a 0.01 price move is
AUD 3,000,000 × 0.01% × (days in the contract month / 365).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ContractSpec:
    product_code: str
    venue: str
    curve_id: str
    currency: str
    quote: str
    canonical_mark: str
    bp_per_price_unit: float
    face_notional: float
    face_currency: str
    day_count: str
    period: str
    source: str


SR3 = ContractSpec(
    product_code="SR3",
    venue="CME",
    curve_id="SOFR",
    currency="USD",
    quote="imm_index_100_minus_rate",
    canonical_mark="implied_rate_percent",
    bp_per_price_unit=100.0,
    face_notional=1_000_000.0,
    face_currency="USD",
    day_count="ACT/360",
    period="3m_fixed",
    source=(
        "CME Three-Month SOFR futures (SR3): USD 25 per 0.01 IMM index point; "
        "index = 100 - rate; reference face USD 1,000,000"
    ),
)

CRA = ContractSpec(
    product_code="CRA",
    venue="MX",
    curve_id="CORRA",
    currency="CAD",
    quote="imm_index_100_minus_rate",
    canonical_mark="implied_rate_percent",
    bp_per_price_unit=100.0,
    face_notional=1_000_000.0,
    face_currency="CAD",
    day_count="90/360 basis-point value",
    period="3m_fixed",
    source=(
        "Montréal Exchange Three-Month CORRA futures (CRA): CAD 25 per 0.01 "
        "index point; index = 100 - rate; reference face CAD 1,000,000 "
        "(CAD 1,000,000 × 0.01% × 90/360 = CAD 25)"
    ),
)

IB = ContractSpec(
    product_code="IB",
    venue="ASX",
    curve_id="AONIA",
    currency="AUD",
    quote="imm_index_100_minus_rate",
    canonical_mark="implied_rate_percent",
    bp_per_price_unit=100.0,
    face_notional=3_000_000.0,
    face_currency="AUD",
    day_count="ACT/365",
    period="calendar_month",
    source=(
        "ASX 30 Day Interbank Cash Rate futures (IB), AONIA monthly average: "
        "AUD 3,000,000 × 0.01% × (days in contract month / 365) per 0.01 price point"
    ),
)

SPECS = {"SR3": SR3, "CRA": CRA, "IB": IB}
CURVE_SPEC = {"SOFR": SR3, "CORRA": CRA, "AONIA": IB}
ALIASES = {
    "SOFR": "SR3",
    "SR3": "SR3",
    "CORRA": "CRA",
    "CRA": "CRA",
    "AONIA": "IB",
    "IB": "IB",
}

_CME_MONTH = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}

_DATED = re.compile(r"^(SOFR|SR3|CORRA|CRA|AONIA|IB)[_-](20\d{2})-(\d{2})$")
_CODED = re.compile(r"^(SR3|CRA|IB)([FGHJKMNQUVXZ])(\d)$")

SOVEREIGN_RE = re.compile(
    r"^(US|CA|AU|NZ|EA|JP)[_\s-]?(2Y|5Y|10Y|30Y|LONG)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedContract:
    spec: ContractSpec
    year: int
    month: int
    expiry: str
    alias: str

    def as_dict(self) -> dict[str, Any]:
        dv01 = dv01_per_contract(self.spec, year=self.year, month=self.month)
        return {
            "product_code": self.spec.product_code,
            "venue": self.spec.venue,
            "curve_id": self.spec.curve_id,
            "currency": self.spec.currency,
            "quote": self.spec.quote,
            "canonical_mark": self.spec.canonical_mark,
            "price_unit": "implied_rate_percent",
            "bp_per_price_unit": self.spec.bp_per_price_unit,
            "face_notional": self.spec.face_notional,
            "face_currency": self.spec.face_currency,
            "day_count": self.spec.day_count,
            "period": self.spec.period,
            "source": self.spec.source,
            "expiry": self.expiry,
            "year": self.year,
            "month": self.month,
            "dv01_per_contract_local": dv01,
            "alias": self.alias,
        }


def dv01_per_contract(spec: ContractSpec, *, year: int | None = None, month: int | None = None) -> float | None:
    """Local-currency P&L for a one-basis-point futures price increase.

    A long futures position gains this amount when the implied rate falls 1bp,
    because the quoted index is 100 minus the rate.
    """
    if spec.product_code == "SR3":
        return 25.0
    if spec.product_code == "CRA":
        return 25.0
    if spec.product_code == "IB":
        if year is None or month is None:
            return None
        if month < 1 or month > 12:
            return None
        days = calendar.monthrange(year, month)[1]
        return spec.face_notional * 0.0001 * days / 365.0
    return None


def _expiry(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_contract_id(instrument: str | None) -> ParsedContract | None:
    if not instrument or not isinstance(instrument, str):
        return None
    raw = instrument.strip().upper().replace(" ", "")
    dated = _DATED.fullmatch(raw)
    if dated:
        code = ALIASES[dated.group(1)]
        year = int(dated.group(2))
        month = int(dated.group(3))
        if month < 1 or month > 12:
            return None
        spec = SPECS[code]
        expiry = _expiry(year, month)
        return ParsedContract(spec=spec, year=year, month=month, expiry=expiry, alias=f"{spec.curve_id}_{expiry}")
    coded = _CODED.fullmatch(raw)
    if coded:
        code = coded.group(1)
        month = _CME_MONTH[coded.group(2)]
        year = 2020 + int(coded.group(3))
        spec = SPECS[code]
        expiry = _expiry(year, month)
        return ParsedContract(spec=spec, year=year, month=month, expiry=expiry, alias=f"{spec.curve_id}_{expiry}")
    return None


def is_sovereign_instrument(instrument: str | None) -> bool:
    if not instrument or not isinstance(instrument, str):
        return False
    return SOVEREIGN_RE.fullmatch(instrument.strip().replace("-", "_").replace(" ", "_")) is not None


def fx_usd_per_unit(currency: str, market_state: Mapping[str, Any] | None = None, position: Mapping[str, Any] | None = None) -> tuple[float | None, str | None]:
    """USD value of one unit of ``currency``. Never invents a rate."""
    if currency == "USD":
        return 1.0, None
    if position is not None and position.get("contract_currency") in (None, currency):
        stored = position.get("fx_usd_per_unit")
        if stored not in (None, ""):
            try:
                rate = float(stored)
            except (TypeError, ValueError):
                rate = None
            if rate is not None and rate > 0:
                return rate, position.get("fx_pair")
    if not isinstance(market_state, Mapping):
        return None, None
    fx = market_state.get("fx")
    if not isinstance(fx, Mapping):
        return None, None
    pairs = fx.get("pairs") if isinstance(fx.get("pairs"), Mapping) else fx
    if not isinstance(pairs, Mapping):
        return None, None
    if currency == "CAD":
        row = pairs.get("USDCAD")
        spot = row.get("spot") if isinstance(row, Mapping) else row
        try:
            spot_f = float(spot)
        except (TypeError, ValueError):
            return None, "USDCAD"
        if spot_f <= 0:
            return None, "USDCAD"
        return 1.0 / spot_f, "USDCAD"
    if currency == "AUD":
        row = pairs.get("AUDUSD")
        spot = row.get("spot") if isinstance(row, Mapping) else row
        try:
            spot_f = float(spot)
        except (TypeError, ValueError):
            return None, "AUDUSD"
        if spot_f <= 0:
            return None, "AUDUSD"
        return spot_f, "AUDUSD"
    return None, None


def contracts_from_face_usd(spec: ContractSpec, notional_usd: float, fx_usd_per_unit_value: float) -> float | None:
    face_usd = spec.face_notional * fx_usd_per_unit_value
    if face_usd <= 0:
        return None
    return notional_usd / face_usd
