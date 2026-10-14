"""Persistent BLS daily quota ledger and arm lock for one release packet."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.core_pce_release.snapshot import REPO_ROOT

EASTERN = ZoneInfo("America/New_York")
SCHEMA = "core_pce_bls_quota_v1"
MAX_ATTEMPTS_LOG = 50

EARLY_CLUSTER = 3
EARLY_WINDOW_SECONDS = 60.0
RELEASE_TAIL_SECONDS = 1500.0

_BLS_QUOTA_PHRASES = (
    "daily threshold",
    "too many requests",
    "exceeded your daily",
    "query limit",
)

_MODEL_SPEC_PATH = REPO_ROOT / "data" / "core_pce_release" / "model_spec.json"


def earliest_request_offset_seconds(request_number: int, ceiling: int) -> float:
    if request_number <= 1 or ceiling <= 1:
        return 0.0
    early = min(EARLY_CLUSTER, ceiling)
    if request_number <= early:
        return (request_number - 1) * (EARLY_WINDOW_SECONDS / early)
    rest = ceiling - early
    if rest <= 0:
        return EARLY_WINDOW_SECONDS
    slot = request_number - early
    span = RELEASE_TAIL_SECONDS - EARLY_WINDOW_SECONDS
    return EARLY_WINDOW_SECONDS + span * (slot / rest)


def _load_model_bls_budget() -> dict:
    try:
        document = json.loads(_MODEL_SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(document.get("bls_budget") or {})


def key_present_in_env(budget: dict | None = None) -> bool:
    names = (budget or _load_model_bls_budget()).get("env_key_names") or ("BLS_API_KEY", "BLS_REGISTRATION_KEY")
    for name in names:
        if os.environ.get(name):
            return True
    return False


def default_daily_ceiling(key_present: bool, budget: dict | None = None, override: int | None = None) -> int:
    if override is not None:
        return max(0, int(override))
    spec = budget or _load_model_bls_budget()
    if key_present:
        return int(spec.get("packet_daily_ceiling_registered") or 24)
    return int(spec.get("packet_daily_ceiling_unregistered") or 8)


def default_not_before(release: str, kind: str, budget: dict | None = None) -> datetime | None:
    if kind == "ppi" and release == "2026-09":
        spec = budget or _load_model_bls_budget()
        raw = spec.get("ppi_pilot_not_before") or "2026-10-15T08:30:00-04:00"
        parsed = datetime.fromisoformat(str(raw))
        if parsed.tzinfo is None:
            zone = spec.get("ppi_pilot_not_before_zone") or "America/New_York"
            parsed = parsed.replace(tzinfo=ZoneInfo(str(zone)))
        return parsed
    return None


def eastern_date(dt: datetime) -> str:
    aware = dt.astimezone(EASTERN) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(EASTERN)
    return aware.date().isoformat()


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".bls_quota.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def bls_message_indicates_quota(messages: object) -> bool:
    if not messages:
        return False
    if isinstance(messages, str):
        blob = messages.lower()
        return any(phrase in blob for phrase in _BLS_QUOTA_PHRASES)
    parts: list[str] = []
    for item in messages:
        parts.append(str(item).lower())
    blob = " ".join(parts)
    return any(phrase in blob for phrase in _BLS_QUOTA_PHRASES)


def redact_registration_key(text: str, key: str | None) -> str:
    if not key or not text:
        return text
    return text.replace(key, "<redacted>")


class PacketArmLock:
    def __init__(self, packet_dir: Path) -> None:
        self.path = packet_dir / "bls_quota.lock"
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> PacketArmLock:
        if not self.acquire():
            raise ConcurrentArmBlocked()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ConcurrentArmBlocked(Exception):
    pass


class BLSQuotaLedger:
    def __init__(
        self,
        path: Path,
        *,
        release: str,
        kind: str,
        ceiling: int,
        not_before: datetime | None,
        key_present: bool,
        wall_clock,
        budget_spec: dict | None = None,
    ) -> None:
        self.path = path
        self.release = release
        self.kind = kind
        self.ceiling = max(0, int(ceiling))
        self.not_before = not_before
        self.key_present = key_present
        self.wall_clock = wall_clock
        self.budget_spec = budget_spec or _load_model_bls_budget()
        self._blocked_reason: str | None = None
        self._document = self._load_or_create()

    def _public_allowances(self) -> tuple[int, int]:
        unreg = int(self.budget_spec.get("public_unregistered_daily_queries") or 25)
        reg = int(self.budget_spec.get("public_registered_daily_queries") or 500)
        return unreg, reg

    def _fresh_document(self) -> dict:
        unreg, reg = self._public_allowances()
        now = self.wall_clock()
        edate = eastern_date(now)
        return {
            "schema": SCHEMA,
            "release": self.release,
            "kind": self.kind,
            "key_present": self.key_present,
            "packet_daily_ceiling": self.ceiling,
            "public_unregistered_daily_queries": unreg,
            "public_registered_daily_queries": reg,
            "other_programs_quota_unknown": True,
            "not_before": self.not_before.isoformat() if self.not_before else None,
            "eastern_date": edate,
            "utc_date": now.astimezone(timezone.utc).date().isoformat(),
            "requests_today": 0,
            "per_day_requests": {edate: 0},
            "throttled_days": {},
            "pacing_anchor_by_day": {},
            "attempts": [],
        }

    def _load_or_create(self) -> dict:
        if self.path.exists():
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                self._blocked_reason = "ledger_unreadable"
                return self._fresh_document()
            if not isinstance(document, dict) or document.get("schema") != SCHEMA or "requests_today" not in document:
                self._blocked_reason = "ledger_unreadable"
                return self._fresh_document()
        else:
            document = self._fresh_document()
        if self._blocked_reason:
            return document
        self._sync_day(document)
        self._persist(document)
        return document

    def _sync_day(self, document: dict) -> None:
        now = self.wall_clock()
        edate = eastern_date(now)
        per_day = dict(document.get("per_day_requests") or {})
        if document.get("eastern_date") == edate:
            recorded = max(int(document.get("requests_today") or 0), int(per_day.get(edate) or 0))
            document["requests_today"] = recorded
            per_day[edate] = recorded
            document["per_day_requests"] = per_day
            return
        document["eastern_date"] = edate
        document["utc_date"] = now.astimezone(timezone.utc).date().isoformat()
        document["requests_today"] = int(per_day.get(edate) or 0)

    def _persist(self, document: dict | None = None) -> None:
        if self._blocked_reason:
            return
        payload = document if document is not None else self._document
        _atomic_write(self.path, payload)

    def _is_throttled(self, document: dict, edate: str) -> bool:
        throttled = document.get("throttled_days") or {}
        return bool(throttled.get(edate))

    def _mark_throttled(self, document: dict, edate: str) -> None:
        throttled = dict(document.get("throttled_days") or {})
        throttled[edate] = True
        document["throttled_days"] = throttled

    def _pacing_anchor(self, document: dict, edate: str, now: datetime) -> datetime:
        anchors = document.get("pacing_anchor_by_day") or {}
        if self.not_before is not None:
            nb_eastern = eastern_date(self.not_before)
            if nb_eastern == edate:
                return self.not_before
        raw = anchors.get(edate)
        if raw:
            return datetime.fromisoformat(str(raw))
        return now

    def _set_first_attempt_anchor(self, document: dict, edate: str, now: datetime) -> None:
        anchors = dict(document.get("pacing_anchor_by_day") or {})
        if edate in anchors:
            return
        if self.not_before is not None and eastern_date(self.not_before) == edate:
            anchors[edate] = self.not_before.isoformat()
        else:
            anchors[edate] = now.isoformat()
        document["pacing_anchor_by_day"] = anchors

    def _trim_attempts(self, document: dict) -> None:
        attempts = list(document.get("attempts") or [])
        if len(attempts) > MAX_ATTEMPTS_LOG:
            document["attempts"] = attempts[-MAX_ATTEMPTS_LOG:]

    def _append_attempt(self, document: dict, edate: str, series_count: int) -> dict:
        now = self.wall_clock()
        row = {
            "at_utc": now.astimezone(timezone.utc).isoformat(),
            "eastern_date": edate,
            "outcome": "pending",
            "status_code": None,
            "series_count": series_count,
        }
        attempts = list(document.get("attempts") or [])
        attempts.append(row)
        document["attempts"] = attempts
        self._trim_attempts(document)
        return row

    def _finish_attempt(self, document: dict, row: dict, outcome: str, status_code: int | None) -> None:
        row["outcome"] = outcome
        row["status_code"] = status_code
        self._persist(document)

    def status_dict(self, reason: str | None = None) -> dict:
        if self._blocked_reason:
            now = self.wall_clock()
            return {
                "reason": reason or self._blocked_reason,
                "requests_today": None,
                "ceiling": self.ceiling,
                "eastern_date": eastern_date(now),
                "other_programs_quota_unknown": True,
                "key_present": self.key_present,
                "throttled": False,
                "not_before": self.not_before.isoformat() if self.not_before else None,
            }
        self._sync_day(self._document)
        edate = self._document["eastern_date"]
        return {
            "reason": reason,
            "requests_today": int(self._document.get("requests_today") or 0),
            "ceiling": self.ceiling,
            "eastern_date": edate,
            "other_programs_quota_unknown": True,
            "key_present": self.key_present,
            "throttled": self._is_throttled(self._document, edate),
            "not_before": self._document.get("not_before"),
        }

    def format_status_line(self, reason: str | None) -> str:
        status = self.status_dict(reason)
        resolved = reason or status.get("reason") or "ok"
        return (
            f"bls_quota: {resolved} requests_today={status['requests_today']} "
            f"ceiling={status['ceiling']} eastern_date={status['eastern_date']} "
            f"other_programs_quota_unknown=true"
        )

    def network_permitted(self, now: datetime | None = None) -> tuple[bool, str | None]:
        now = now or self.wall_clock()
        if self._blocked_reason:
            return False, self._blocked_reason
        self._sync_day(self._document)
        edate = self._document["eastern_date"]
        if self._is_throttled(self._document, edate):
            return False, "bls_throttled"
        if int(self._document.get("requests_today") or 0) >= self.ceiling:
            return False, "ceiling"
        if self.not_before is not None and now < self.not_before:
            return False, "before_release"
        anchor = self._pacing_anchor(self._document, edate, now)
        next_request = int(self._document.get("requests_today") or 0) + 1
        offset = earliest_request_offset_seconds(next_request, self.ceiling)
        earliest = anchor.timestamp() + offset
        if now.timestamp() < earliest:
            return False, "pacing"
        return True, None

    def begin_attempt(self, now: datetime | None = None, series_count: int = 0) -> tuple[bool, str | None, dict | None]:
        now = now or self.wall_clock()
        if self._blocked_reason:
            return False, self._blocked_reason, None
        self._sync_day(self._document)
        edate = self._document["eastern_date"]
        if self._is_throttled(self._document, edate):
            return False, "bls_throttled", None
        if int(self._document.get("requests_today") or 0) >= self.ceiling:
            return False, "ceiling", None
        per_day = dict(self._document.get("per_day_requests") or {})
        count = int(self._document.get("requests_today") or 0) + 1
        self._document["requests_today"] = count
        per_day[edate] = count
        self._document["per_day_requests"] = per_day
        self._set_first_attempt_anchor(self._document, edate, now)
        row = self._append_attempt(self._document, edate, series_count)
        self._persist(self._document)
        return True, None, row

    def record_http_outcome(self, row: dict | None, outcome: str, status_code: int | None = None) -> None:
        if row is None:
            return
        edate = self._document.get("eastern_date") or eastern_date(self.wall_clock())
        if outcome in {"http_429", "bls_quota"}:
            self._mark_throttled(self._document, edate)
        self._finish_attempt(self._document, row, outcome, status_code)

    def mark_daily_throttled(self) -> None:
        self._sync_day(self._document)
        edate = self._document["eastern_date"]
        self._mark_throttled(self._document, edate)
        self._persist(self._document)

    @staticmethod
    def open_ledger(
        packet_dir: Path,
        *,
        release: str,
        kind: str,
        ceiling: int,
        not_before: datetime | None,
        key_present: bool,
        wall_clock,
    ) -> BLSQuotaLedger:
        path = packet_dir / "bls_quota.json"
        return BLSQuotaLedger(
            path,
            release=release,
            kind=kind,
            ceiling=ceiling,
            not_before=not_before,
            key_present=key_present,
            wall_clock=wall_clock,
        )
