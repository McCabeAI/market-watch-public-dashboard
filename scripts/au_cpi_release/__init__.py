"""Australian CPI pre-release nowcast data layer.

Shadow-only. This package does not schedule runs or write Market Watch,
temperature history, or macro-ingestion catalogs.
"""

SCHEMA_VERSION = "au_cpi_snapshot_v1"
ARCHIVE_MANIFEST_SCHEMA = "au_cpi_nowcast_archive_manifest_v1"
TRIM_REPORT_SCHEMA = "au_cpi_trim_verification_v1"
NOWCAST_SCHEMA = "au_cpi_nowcast_v1"
BACKTEST_SCHEMA = "au_cpi_backtest_v1"
BACKTEST_ARCHIVE_MANIFEST_SCHEMA = "au_cpi_backtest_archive_manifest_v1"
