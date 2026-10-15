"""Issue-triggered one-shot September 2026 PPI recalculation."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts.core_pce_release.cli import main
from scripts.core_pce_release.oneshot import (
    AVAILABILITY_ERROR,
    AVAILABILITY_FRESH,
    AVAILABILITY_NOT_YET,
    EXACT_ISSUE_TITLE,
    authorize_from_environment,
    authorize_run_ppi_issue,
    lookup_repository_permission,
    run_oneshot,
)
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "run-ppi-oneshot.yml"
MODEL_SPEC = json.loads((ROOT / "data" / "core_pce_release" / "model_spec.json").read_text(encoding="utf-8"))
G0 = MODEL_SPEC["g0_reference_post_cpi_pre_ppi"]
THRESHOLDS = MODEL_SPEC["unchanged_momentum_mom_percent"]
HOSPITAL = "PCU622---622---"
SECRET = "test-registration-key-not-for-logs"


def _clear_keys() -> None:
    for name in ("BLS_API_KEY", "BLS_REGISTRATION_KEY"):
        os.environ.pop(name, None)


def _row(year: str, period: str, value: str, *, code: str | None = None) -> dict:
    footnotes = []
    if code:
        footnotes.append({"code": code, "text": "Preliminary"})
    return {"year": year, "period": period, "value": value, "footnotes": footnotes}


def _document(series: list[dict], *, status: str = "REQUEST_SUCCEEDED", message: list[str] | None = None) -> dict:
    return {"status": status, "message": list(message or []), "Results": {"series": series}}


def _hospital_series(*, september: bool, wild_august: bool = False, invalid: bool = False) -> dict:
    august = "15000" if wild_august else "10100"
    rows = [
        _row("2026", "M07", "10000"),
        _row("2026", "M08", august),
    ]
    if invalid:
        rows.append(_row("2026", "M09", "20000", code="P"))
    elif september:
        rows.append(_row("2026", "M09", "10251.5", code="P"))
    return {"seriesID": HOSPITAL, "data": rows}


class OneShotPpiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())
        self.out = self.tempdir / "out"
        _clear_keys()

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)
        _clear_keys()

    def _run(self, document: dict, *, raises: Exception | None = None) -> tuple[dict, list[list[str]]]:
        calls: list[list[str]] = []

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            calls.append(list(series_ids))
            self.assertEqual(start_year, "2026")
            self.assertEqual(end_year, "2026")
            self.assertLessEqual(timeout, 8)
            if raises is not None:
                raise raises
            return document

        with (
            mock.patch("scripts.core_pce_release.listener.run_listener", side_effect=AssertionError("listener")),
            mock.patch("scripts.core_pce_release.cli._run_live_arm", side_effect=AssertionError("arm")),
            mock.patch(
                "scripts.core_pce_release.acquire.acquire_official",
                side_effect=AssertionError("second fetch"),
            ),
        ):
            result = run_oneshot(self.out, poster=poster)
        return result, calls

    def _assert_baseline_preserved(self, result: dict) -> None:
        self.assertEqual(result["offline_baseline"]["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(result["offline_baseline"]["headline"], "HOT")
        self.assertEqual(result["revised"]["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(result["revised"]["low_mom_percent"], G0["low_mom_percent"])
        self.assertEqual(result["revised"]["high_mom_percent"], G0["high_mom_percent"])
        self.assertEqual(result["revised"]["headline"], "HOT")
        self.assertEqual(result["estimate"], "unchanged")
        self.assertFalse(result["revised"]["changed"])
        self.assertEqual(result["revised"]["information_stage"], "post_cpi_pre_ppi")
        self.assertEqual(result["usable_observation_count"], 0)
        self.assertEqual(result["retries_scheduled"], 0)
        self.assertFalse(result["listener_invoked"])
        self.assertFalse(result["arm_invoked"])
        for months in ("3", "6", "9"):
            row = result["revised"]["horizons"][months]
            self.assertEqual(row["before"], G0["horizons_before_annualized_percent"][months])
            self.assertEqual(row["after"], G0["horizons_after_annualized_percent"][months])
            self.assertEqual(row["unchanged_momentum_mom_percent"], THRESHOLDS[months])
        comment = (self.out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("offline baseline: HOT +0.3688405280179773205064998201%", comment)
        self.assertIn("availability: " + result["availability"], comment)
        self.assertNotIn("availability: FRESH", comment)
        self.assertNotIn("PPI updated", comment)
        self.assertIn("3-month annualized", comment)
        self.assertIn("6-month annualized", comment)
        self.assertIn("9-month annualized", comment)
        self.assertIn("attribution: none", comment)
        self.assertIn("listener: not_invoked", comment)
        self.assertIn("arm: not_invoked", comment)
        self.assertIn("retries_scheduled: 0", comment)
        packet = json.loads((self.out / "pre_release_state.json").read_text(encoding="utf-8"))
        self.assertEqual(packet["listener"], "not_armed")
        self.assertFalse((self.out / "listener_result.json").exists())
        self.assertFalse((self.out / "bls_quota.json").exists())

    def test_live_default_poster_is_not_overridden_by_none(self) -> None:
        document = _document([_hospital_series(september=True)])
        calls = []

        def fake_fetch(series_ids, **kwargs):
            self.assertNotIn("poster", kwargs)
            calls.append(list(series_ids))
            return {
                "points": {HOSPITAL: {"2026-07": "10000", "2026-08": "10100", "2026-09": "10251.5"}},
                "latest": {HOSPITAL: "2026-09"},
                "footnotes": {},
                "errors": [],
                "raw_documents": [document],
                "source_latency_seconds": 0.01,
                "requested": list(series_ids),
                "requests_made": 1,
                "budget_exhausted": False,
                "key_present": False,
            }

        with mock.patch("scripts.core_pce_release.oneshot.fetch_series", side_effect=fake_fetch):
            result = run_oneshot(self.out)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_FRESH)

    def test_stale_august_ppi_is_not_fresh_and_preserves_baseline(self) -> None:
        document = _document([_hospital_series(september=False, wild_august=True)])
        result, calls = self._run(document)
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(len(calls[0]), 25)
        self.assertIn(HOSPITAL, calls[0])
        self.assertEqual(result["availability"], AVAILABILITY_NOT_YET)
        self.assertEqual(result["reason"], "stale_september_ppi")
        self.assertEqual(result["http"]["requests_made"], 1)
        self.assertEqual(result["http"]["retry_sleeps"], 0)
        self.assertEqual(result["series"]["fresh"], [])
        stale = next(row for row in result["series"]["not_yet_available"] if row["series_id"] == HOSPITAL)
        self.assertEqual(stale["latest"], "2026-08")
        self.assertEqual(stale["reason"], "stale_period")
        self._assert_baseline_preserved(result)

    def test_missing_september_ppi_is_not_yet_available(self) -> None:
        document = _document([{"seriesID": HOSPITAL, "data": []}])
        result, calls = self._run(document)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_NOT_YET)
        self.assertEqual(result["reason"], "september_ppi_unpublished")
        self.assertEqual(result["series"]["fresh"], [])
        self._assert_baseline_preserved(result)

    def test_unpublished_empty_response_is_not_yet_available(self) -> None:
        result, calls = self._run(_document([]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_NOT_YET)
        self.assertEqual(result["reason"], "september_ppi_unpublished")
        self._assert_baseline_preserved(result)

    def test_new_september_ppi_revises_estimate_momentum_and_attribution(self) -> None:
        result, calls = self._run(_document([_hospital_series(september=True)]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["http"]["requests_made"], 1)
        self.assertEqual(result["http"]["max_requests"], 1)
        self.assertEqual(result["http"]["max_attempts_per_request"], 1)
        self.assertEqual(result["availability"], AVAILABILITY_FRESH)
        self.assertEqual(result["reason"], "september_ppi_validated")
        self.assertEqual(result["estimate"], "revised")
        self.assertTrue(result["revised"]["changed"])
        self.assertEqual(result["offline_baseline"]["central_mom_percent"], G0["central_mom_percent"])
        self.assertNotEqual(result["revised"]["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(result["revised"]["information_stage"], "ppi_partial")
        self.assertIn(HOSPITAL, result["series"]["fresh"])
        self.assertGreater(result["usable_observation_count"], 0)
        baseline = json.loads((self.out / "baseline_detailed.json").read_text(encoding="utf-8"))
        by_line = {int(row["line"]): row for row in baseline["components"]}
        expected_delta = (Decimal(by_line[185]["weight_share"]) + Decimal(by_line[186]["weight_share"])) * Decimal("0.5")
        actual_delta = Decimal(result["revised"]["central_mom_percent"]) - Decimal(G0["central_mom_percent"])
        self.assertEqual(format(actual_delta, "f"), "0.0141643839524976602723058002")
        self.assertAlmostEqual(actual_delta, expected_delta, places=25)
        attribution = result["revised"]["attribution"]
        self.assertTrue(attribution)
        touched = {row["line"] for row in attribution}
        self.assertIn(185, touched)
        self.assertIn(186, touched)
        for row in attribution:
            if row["series_id"] == HOSPITAL:
                self.assertEqual(row["method"], "source_news_bridge")
        for months in ("3", "6", "9"):
            self.assertEqual(
                result["revised"]["horizons"][months]["before"],
                G0["horizons_before_annualized_percent"][months],
            )
            self.assertNotEqual(
                result["revised"]["horizons"][months]["after"],
                G0["horizons_after_annualized_percent"][months],
            )
            self.assertEqual(
                result["offline_baseline"]["horizons"][months]["unchanged_momentum_mom_percent"],
                THRESHOLDS[months],
            )
        detailed = json.loads((self.out / "detailed.json").read_text(encoding="utf-8"))
        updated = {row["line"]: row for row in detailed["components"]}
        self.assertEqual(updated[185]["seasonal_status_output"], "modeled_not_bea_sa")
        self.assertNotEqual(updated[185]["seasonal_status_output"], "BEA_SA")
        self.assertEqual(baseline["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(updated[346]["mom_percent"], next(row["mom_percent"] for row in baseline["components"] if row["line"] == 346))
        codes = {row["period"]: row["code"] for row in result["footnotes"] if row["series_id"] == HOSPITAL}
        self.assertEqual(codes.get("2026-09"), "P")
        comment = (self.out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("availability: FRESH", comment)
        self.assertIn("offline baseline: HOT +0.3688405280179773205064998201%", comment)
        self.assertIn("PPI updated", comment)
        self.assertIn(f"series {HOSPITAL}", comment)
        self.assertIn("3-month annualized", comment)
        self.assertIn("6-month annualized", comment)
        self.assertIn("9-month annualized", comment)
        self.assertIn("listener: not_invoked", comment)
        self.assertFalse((self.out / "listener_result.json").exists())
        revisions = (self.out / "revisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(revisions), 2)
        self.assertEqual(json.loads(revisions[0])["central_mom_percent"], G0["central_mom_percent"])

    def test_quota_message_with_september_points_is_not_fresh(self) -> None:
        document = _document(
            [_hospital_series(september=True)],
            status="REQUEST_SUCCEEDED",
            message=["Request could not be serviced, as the daily threshold for total requests has been reached."],
        )
        result, calls = self._run(document)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "bls_throttled")
        self._assert_baseline_preserved(result)

    def test_http_429_is_one_attempt_and_preserves_baseline(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b""),
        )
        result, calls = self._run(_document([]), raises=error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "bls_throttled")
        self.assertEqual(result["http"]["retry_sleeps"], 0)
        self._assert_baseline_preserved(result)

    def test_transport_error_does_not_retry_or_invent_a_change(self) -> None:
        result, calls = self._run(_document([]), raises=TimeoutError("offline"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "transport_error")
        self.assertEqual(result["http"]["retry_sleeps"], 0)
        self._assert_baseline_preserved(result)

    def test_invalid_september_mom_is_an_error(self) -> None:
        result, calls = self._run(_document([_hospital_series(september=False, invalid=True)]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "invalid_september_observation")
        self.assertEqual(result["series"]["fresh"], [])
        self._assert_baseline_preserved(result)

    def test_retry_sleep_discards_fresh_points(self) -> None:
        def fake_fetch(*_args, **kwargs):
            kwargs["sleep"](0)
            return {
                "points": {HOSPITAL: {"2026-09": "10251.5", "2026-08": "10100", "2026-07": "10000"}},
                "latest": {HOSPITAL: "2026-09"},
                "footnotes": {},
                "errors": [],
                "raw_documents": [_document([_hospital_series(september=True)])],
                "source_latency_seconds": 0.1,
                "requested": [HOSPITAL],
                "requests_made": 1,
                "budget_exhausted": False,
                "key_present": False,
            }

        with mock.patch("scripts.core_pce_release.oneshot.fetch_series", side_effect=fake_fetch):
            result = run_oneshot(self.out, poster=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("poster")))
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "attempt_budget")
        self.assertEqual(result["http"]["retry_sleeps"], 1)
        self._assert_baseline_preserved(result)

    def test_registration_key_is_not_in_comment_or_audit(self) -> None:
        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            self.assertEqual(registration_key, SECRET)
            raise TimeoutError(SECRET)

        with mock.patch.dict(os.environ, {"BLS_API_KEY": SECRET}, clear=False):
            result = run_oneshot(self.out, poster=poster)
        blob = (self.out / "comment.md").read_text(encoding="utf-8") + (self.out / "audit.json").read_text(encoding="utf-8")
        blob += json.dumps(result)
        self.assertNotIn(SECRET, blob)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertTrue(result["http"]["key_present"])

    def test_unexpected_series_is_rejected(self) -> None:
        document = _document(
            [
                _hospital_series(september=True),
                {"seriesID": "NOT-IN-PLAN", "data": [_row("2026", "M09", "101"), _row("2026", "M08", "100")]},
            ]
        )
        result, _calls = self._run(document)
        self.assertEqual(result["availability"], AVAILABILITY_ERROR)
        self.assertEqual(result["reason"], "source_validation_failed")
        self._assert_baseline_preserved(result)

    def test_only_2026_09_release_is_accepted(self) -> None:
        with self.assertRaises(ValueError):
            run_oneshot(self.out, release="2026-08", poster=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fetch")))


class IssueAuthorizationTests(unittest.TestCase):
    def _env(self, **overrides) -> dict:
        env = {
            "ISSUE_TITLE": EXACT_ISSUE_TITLE,
            "ISSUE_AUTHOR_LOGIN": "analyst",
            "ISSUE_AUTHOR_TYPE": "User",
            "ISSUE_SENDER_LOGIN": "analyst",
            "ISSUE_SENDER_TYPE": "User",
            "GITHUB_REPOSITORY": "McCabeAI/market-watch-public-dashboard",
            "GH_TOKEN": "github-token-not-for-logs",
        }
        env.update(overrides)
        return env

    def test_write_maintain_and_admin_are_authorized(self) -> None:
        for permission in ("admin", "maintain", "write"):
            decision = authorize_run_ppi_issue(
                title=EXACT_ISSUE_TITLE,
                author_login="analyst",
                author_type="User",
                sender_login="analyst",
                sender_type="User",
                permission=permission,
            )
            self.assertTrue(decision["authorized"], permission)
            self.assertEqual(decision["reason"], "authorized")

    def test_unrelated_title_bot_sender_and_read_permission_are_rejected(self) -> None:
        cases = [
            ("[run-ppi] 2026-10", "analyst", "User", "analyst", "User", "write", "unrelated_title"),
            ("[run-ppi] 2026-09 ", "analyst", "User", "analyst", "User", "write", "unrelated_title"),
            ("Run PPI", "analyst", "User", "analyst", "User", "admin", "unrelated_title"),
            (EXACT_ISSUE_TITLE, "dependabot[bot]", "Bot", "dependabot[bot]", "Bot", "admin", "not_human"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "other", "User", "admin", "sender_mismatch"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "analyst", "Bot", "write", "not_human"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "analyst", "User", "read", "untrusted_permission"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "analyst", "User", "triage", "untrusted_permission"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "analyst", "User", None, "untrusted_permission"),
            (EXACT_ISSUE_TITLE, "analyst", "User", "analyst", "User", "none", "untrusted_permission"),
        ]
        for title, author, author_type, sender, sender_type, permission, reason in cases:
            decision = authorize_run_ppi_issue(
                title=title,
                author_login=author,
                author_type=author_type,
                sender_login=sender,
                sender_type=sender_type,
                permission=permission,
            )
            self.assertFalse(decision["authorized"], reason)
            self.assertEqual(decision["reason"], reason)

    def test_unrelated_issue_does_not_call_permission_api(self) -> None:
        def opener(request, timeout=10):  # noqa: ANN001
            raise AssertionError(request.full_url)

        decision = authorize_from_environment(self._env(ISSUE_TITLE="Something else"), opener=opener)
        self.assertFalse(decision["authorized"])
        self.assertEqual(decision["reason"], "unrelated_title")

    def test_permission_lookup_fail_closed_and_does_not_echo_token(self) -> None:
        token = "github-token-not-for-logs"

        def forbidden(request, timeout=10):  # noqa: ANN001
            self.assertNotIn(token, request.full_url)
            self.assertIn(token, request.get_header("Authorization"))
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=io.BytesIO(b""))

        self.assertIsNone(
            lookup_repository_permission(
                "McCabeAI/market-watch-public-dashboard",
                "analyst",
                token,
                opener=forbidden,
            )
        )

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"permission": "write"}).encode("utf-8")

        def allowed(request, timeout=10):  # noqa: ANN001
            self.assertTrue(request.full_url.endswith("/collaborators/analyst/permission"))
            return _Response()

        decision = authorize_from_environment(self._env(), opener=allowed)
        self.assertTrue(decision["authorized"])
        self.assertNotIn(token, json.dumps(decision))

    def test_cli_authorization_output_omits_token(self) -> None:
        output = self._output_path()
        env = self._env()
        env["GITHUB_OUTPUT"] = str(output)
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch("scripts.core_pce_release.oneshot.lookup_repository_permission", return_value="maintain"),
        ):
            code = main(["authorize-ppi-issue"])
        self.assertEqual(code, 0)
        written = output.read_text(encoding="utf-8")
        self.assertIn("authorized=true", written)
        self.assertNotIn("github-token-not-for-logs", written)

    def _output_path(self) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        return directory / "github_output"


class OneShotCliAndWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())
        self.out = self.tempdir / "out"
        _clear_keys()

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)
        _clear_keys()

    def test_cli_run_ppi_writes_comment_for_unpublished_response(self) -> None:
        def fake_fetch(*_args, **_kwargs):
            return {
                "points": {},
                "latest": {},
                "footnotes": {},
                "errors": [],
                "raw_documents": [{"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}}],
                "source_latency_seconds": 0.0,
                "requested": [],
                "requests_made": 1,
                "budget_exhausted": False,
                "key_present": False,
            }

        with mock.patch("scripts.core_pce_release.oneshot.fetch_series", side_effect=fake_fetch):
            code = main(["run-ppi", "--out", str(self.out)])
        self.assertEqual(code, 0)
        audit = json.loads((self.out / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["availability"], AVAILABILITY_NOT_YET)
        self.assertEqual(audit["revised"]["central_mom_percent"], G0["central_mom_percent"])
        self.assertIn("+0.3688405280179773205064998201%", (self.out / "comment.md").read_text(encoding="utf-8"))

    def test_cli_refuses_other_releases_without_fetching(self) -> None:
        with mock.patch(
            "scripts.core_pce_release.oneshot.fetch_series",
            side_effect=AssertionError("fetch"),
        ):
            code = main(["run-ppi", "--release", "2026-08", "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertFalse((self.out / "audit.json").exists())

    def test_cli_crash_comment_has_no_exception_text(self) -> None:
        secret = "crash-secret-not-for-comment"

        def explode(*_args, **_kwargs):
            raise RuntimeError(secret)

        with mock.patch("scripts.core_pce_release.cli.run_oneshot", side_effect=explode):
            code = main(["run-ppi", "--out", str(self.out)])
        self.assertEqual(code, 1)
        comment = (self.out / "comment.md").read_text(encoding="utf-8")
        self.assertIn("availability: ERROR", comment)
        self.assertIn("reason: unexpected_error", comment)
        self.assertIn("+0.3688405280179773205064998201%", comment)
        self.assertNotIn(secret, comment)
        self.assertNotIn(secret, (self.out / "audit.json").read_text(encoding="utf-8"))

    def test_workflow_is_issue_triggered_one_shot(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issues:", text)
        self.assertIn("opened", text)
        self.assertIn("'[run-ppi] 2026-09'", text)
        self.assertIn("github.event.sender.login == github.event.issue.user.login", text)
        self.assertIn("github.event.issue.user.type == 'User'", text)
        self.assertIn("github.event.sender.type == 'User'", text)
        self.assertIn("authorize-ppi-issue", text)
        self.assertIn("run-ppi", text)
        self.assertIn("contents: read", text)
        self.assertIn("issues: write", text)
        self.assertIn("actions: write", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("run-ppi-2026-09-${{ github.run_id }}", text)
        self.assertIn("gh issue comment", text)
        self.assertIn("timeout-minutes: 5", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("+0.3688405280179773205064998201%", text)
        for banned in (
            "schedule:",
            "cron:",
            "workflow_dispatch",
            "pull_request",
            "repository_dispatch",
            "run_listener",
            "core_pce_release arm",
            "cursor",
            "openai",
            "anthropic",
            "deploy-pages",
        ):
            self.assertNotIn(banned, text)
        source = (ROOT / "scripts" / "core_pce_release" / "oneshot.py").read_text(encoding="utf-8")
        self.assertNotIn("run_listener", source)
        self.assertNotIn("workflow_dispatch", source)
        self.assertNotIn("acquire_official", source)
        self.assertIn(G0["central_mom_percent"], text)


if __name__ == "__main__":
    unittest.main()
