"""Official source collectors for Canadian CPI release nowcast."""

from scripts.canadian_cpi_release.sources.acquire import fetch_live, load_snapshot, save_snapshot
from scripts.canadian_cpi_release.sources.cache import SourceError

__all__ = ["fetch_live", "load_snapshot", "save_snapshot", "SourceError"]
