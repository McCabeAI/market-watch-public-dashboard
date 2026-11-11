"""Constants and schema identifiers for Canada PRiMA transmission (v2)."""

from __future__ import annotations

TRANSMISSION_SCHEMA_VERSION = "canada_prima_transmission_v2"
TRANSMISSION_METHOD_VERSION = "ca_prima_tx_2026_11_v1"

TRANSMISSION_PROVENANCE_LIVE = "live_observed"
TRANSMISSION_PROVENANCE_RECON = "reconstructed_from_frozen_v1"

TRANSMISSION_CHANNEL_ENERGY = "energy_direct_fuel"
TRANSMISSION_CHANNEL_IMPORTED = "imported_non_energy_goods"
TRANSMISSION_CHANNEL_FOOD = "food_and_non_energy_inputs"

TRANSMISSION_CHANNELS = (
    TRANSMISSION_CHANNEL_ENERGY,
    TRANSMISSION_CHANNEL_IMPORTED,
    TRANSMISSION_CHANNEL_FOOD,
)

DISCLAIMER_TX = (
    "Deterministic Market Watch CPI-transmission view inspired by PRiMA concepts. "
    "It is not the Bank of Canada's proprietary PRiMA model."
)

# 2025 CPI basket (weights.py period 2025-01); not price-updated for transmission labels.
WEIGHT_GASOLINE_PCT = 4.01
WEIGHT_FUEL_OIL_PCT = 0.24
WEIGHT_FOOD_PCT = 16.93
WEIGHT_BASIS = "basket_2025_not_price_updated"

CRUDE_COST_SHARES = (0.35, 0.45, 0.55)
FUEL_OIL_COST_SHARES = (0.5, 0.6, 0.7)

TAX_PASS_THROUGH = 1.10
PUMP_PASS_THROUGH = 1.0

FX_LOOKUP_MAX_CALENDAR_DAYS = 5
CRUDE_REFINING_DIVERGENCE_CPL = 3.0

IMPORTED_FX_MATERIAL_3M_PCT = 2.0
IMPORTED_FX_MATERIAL_1M_PCT = 1.5

PP_NEUTRAL_ABS = 0.03

LITRES_PER_US_GALLON = 3.78541
LITRES_PER_BARREL = 158.987
