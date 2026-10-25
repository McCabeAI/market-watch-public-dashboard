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

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
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
    day_count="30/365 quotation basis",
    period="published_30_day_bpv",
    source=(
        "ASX 30 Day Interbank Cash Rate futures (IB): notional A$3,000,000; "
        "published value of a 0.01 price move is A$24.66 per lot on a fixed "
        "30/365 basis. The settlement rate is the monthly average OCR, which "
        "is a separate reference period and does not change the futures BPV. "
        "https://www.asx.com.au/markets/trade-our-derivatives-market/overview/interest-rate-derivatives/short-term-derivatives"
    ),
)

# ASX states "1 basis point move of 0.01% = A$24.66". The unrounded 30/365
# identity is 3,000,000 × 0.0001 × 30/365 = 24.6575..., which the exchange
# publishes as A$24.66. Valuation uses the published figure for every month.
IB_PUBLISHED_BPV_AUD = 24.66
IB_BPV_REFERENCE_DAYS = 30
IB_BPV_YEAR_DAYS = 365
IB_UNROUNDED_30_365_BPV_AUD = 3_000_000 * 0.0001 * IB_BPV_REFERENCE_DAYS / IB_BPV_YEAR_DAYS
LOT_ROUNDING_POLICY = "floor_toward_zero"
HEDGE_LOT_ROUNDING_POLICY = "nearest_integer_half_up"
_FX_BLOCKING_STATUSES = frozenset({"stale", "missing", "unavailable", "invalid"})

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
    because the quoted index is 100 minus the rate. IB uses the published
    A$24.66 basis-point value for every expiry month. ``year`` and ``month``
    identify the contract; they do not change the IB BPV.
    """
    del year, month
    if spec.product_code == "SR3":
        return 25.0
    if spec.product_code == "CRA":
        return 25.0
    if spec.product_code == "IB":
        return IB_PUBLISHED_BPV_AUD
    return None


def whole_lots(raw: float, *, policy: str = LOT_ROUNDING_POLICY) -> int:
    """Exchange lot count. Never returns a fraction."""
    if raw <= 0:
        return 0
    quantized = Decimal(str(round(float(raw), 10)))
    rounding = ROUND_HALF_UP if policy == HEDGE_LOT_ROUNDING_POLICY else ROUND_FLOOR
    return int(quantized.to_integral_value(rounding=rounding))


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


def fx_usd_per_unit(
    currency: str,
    market_state: Mapping[str, Any] | None = None,
    position: Mapping[str, Any] | None = None,
) -> tuple[float | None, str | None]:
    """Current USD value of one unit of ``currency`` from the frozen market.

    Stored entry FX on ``position`` is ignored. A missing or stale fixing
    returns ``(None, pair)`` rather than reusing an older vintage.
    """
    del position
    quote = current_fx_quote(currency, market_state)
    if quote.get("status") != "ok":
        return None, quote.get("pair")
    return quote.get("usd_per_unit"), quote.get("pair")


def current_fx_quote(currency: str, market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One frozen FX observation. Entry snapshots must be copied by the caller."""
    if currency == "USD":
        return {
            "status": "ok",
            "usd_per_unit": 1.0,
            "pair": None,
            "as_of": None,
            "source": "usd_identity",
        }
    pair = {"CAD": "USDCAD", "AUD": "AUDUSD"}.get(currency)
    if pair is None:
        return {"status": "unavailable", "usd_per_unit": None, "pair": None, "as_of": None, "source": None}
    if not isinstance(market_state, Mapping):
        return {"status": "unavailable", "usd_per_unit": None, "pair": pair, "as_of": None, "source": None}
    fx = market_state.get("fx")
    if not isinstance(fx, Mapping):
        return {"status": "unavailable", "usd_per_unit": None, "pair": pair, "as_of": None, "source": None}
    if str(fx.get("status") or "") in _FX_BLOCKING_STATUSES:
        return {
            "status": str(fx.get("status")),
            "usd_per_unit": None,
            "pair": pair,
            "as_of": fx.get("source_observation"),
            "source": "market_state.fx",
        }
    pairs = fx.get("pairs") if isinstance(fx.get("pairs"), Mapping) else fx
    if not isinstance(pairs, Mapping):
        return {"status": "unavailable", "usd_per_unit": None, "pair": pair, "as_of": None, "source": None}
    row = pairs.get(pair)
    if isinstance(row, Mapping) and str(row.get("status") or "") in _FX_BLOCKING_STATUSES:
        return {
            "status": str(row.get("status")),
            "usd_per_unit": None,
            "pair": pair,
            "as_of": row.get("as_of"),
            "source": f"market_state.fx.{pair}",
        }
    spot = row.get("spot") if isinstance(row, Mapping) else row
    try:
        spot_f = float(spot)
    except (TypeError, ValueError):
        return {"status": "unavailable", "usd_per_unit": None, "pair": pair, "as_of": None, "source": f"market_state.fx.{pair}"}
    if spot_f <= 0:
        return {"status": "unavailable", "usd_per_unit": None, "pair": pair, "as_of": None, "source": f"market_state.fx.{pair}"}
    usd_per_unit = (1.0 / spot_f) if currency == "CAD" else spot_f
    as_of = row.get("as_of") if isinstance(row, Mapping) else fx.get("source_observation")
    return {
        "status": "ok",
        "usd_per_unit": usd_per_unit,
        "pair": pair,
        "spot": spot_f,
        "as_of": as_of,
        "source": f"market_state.fx.{pair}.spot",
    }


def contracts_from_face_usd(spec: ContractSpec, notional_usd: float, fx_usd_per_unit_value: float) -> float | None:
    """Continuous face equivalent. Bookings must convert this with ``whole_lots``."""
    face_usd = spec.face_notional * fx_usd_per_unit_value
    if face_usd <= 0:
        return None
    return notional_usd / face_usd


def lots_from_face_usd(spec: ContractSpec, notional_usd: float, fx_usd_per_unit_value: float) -> dict[str, Any] | None:
    raw = contracts_from_face_usd(spec, notional_usd, fx_usd_per_unit_value)
    if raw is None:
        return None
    lots = whole_lots(raw, policy=LOT_ROUNDING_POLICY)
    return {
        "contracts": lots,
        "contracts_unrounded": raw,
        "residual_contracts": raw - lots,
        "rounding_policy": LOT_ROUNDING_POLICY,
    }
