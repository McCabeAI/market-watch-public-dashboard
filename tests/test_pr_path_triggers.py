"""Contract tests for GitHub Actions pull_request path filters on workflow YAML."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

JSON = "data/overnight/inbox/overnight-20261015/scheduled_output.json"
JSON2 = "data/overnight/inbox/overnight-20261014/scheduled_output.json"

PROTECTED_SHA256 = {
    ".github/workflows/run-ppi-oneshot.yml": (
        "4fa82f5c2e83729fff8f92630619b5f3807d0faf5b80a757b0eb1e81b5eeb1f2"
    ),
    ".github/workflows/overnight-scheduled-output.yml": (
        "59855e7f0a5ae79393392b28f29ef93c1181acf79b881fc3ac0324219111fa40"
    ),
}


def _strip_yaml_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _leading_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_on_event_blocks(text: str) -> dict[str, dict[str, List[str]]]:
    """Parse pull_request / pull_request_target path lists from workflow YAML."""
    events: dict[str, dict[str, List[str]]] = {}
    lines = text.splitlines()
    on_indent: Optional[int] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "on:" or stripped.startswith("on:"):
            on_indent = _leading_indent(line)
            i += 1
            break
        i += 1
    if on_indent is None:
        return events

    event_names = ("pull_request", "pull_request_target")
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        indent = _leading_indent(line)
        if indent <= on_indent and line.strip() and not line.strip().startswith("#"):
            break
        for event in event_names:
            if re.match(rf"^{' ' * (on_indent + 2)}{event}:\s*$", line):
                block: dict[str, List[str]] = {}
                j = i + 1
                event_indent = on_indent + 2
                while j < len(lines):
                    inner = lines[j]
                    if not inner.strip() or inner.lstrip().startswith("#"):
                        j += 1
                        continue
                    inner_indent = _leading_indent(inner)
                    if inner_indent <= event_indent:
                        break
                    for key in ("paths", "paths-ignore"):
                        key_prefix = f"{' ' * (event_indent + 2)}{key}:"
                        if inner.strip() == f"{key}:" or inner.startswith(key_prefix):
                            items: List[str] = []
                            k = j + 1
                            list_indent = event_indent + 2
                            while k < len(lines):
                                item_line = lines[k]
                                if not item_line.strip() or item_line.lstrip().startswith("#"):
                                    k += 1
                                    continue
                                item_indent = _leading_indent(item_line)
                                if item_indent <= list_indent:
                                    break
                                m = re.match(r"^\s*-\s+(.+?)\s*$", item_line)
                                if m:
                                    items.append(_strip_yaml_quotes(m.group(1)))
                                k += 1
                            block[key] = items
                            j = k
                            continue
                    j += 1
                events[event] = block
                break
        i += 1
    return events


def parse_pull_request_trigger(text: str) -> dict[str, List[str]]:
    return parse_on_event_blocks(text).get("pull_request", {})


def parse_pull_request_target_trigger(text: str) -> dict[str, List[str]]:
    return parse_on_event_blocks(text).get("pull_request_target", {})


def assert_no_paths_and_paths_ignore(trigger: dict[str, List[str]], label: str) -> None:
    if trigger.get("paths") and trigger.get("paths-ignore"):
        raise AssertionError(f"{label}: pull_request defines both paths and paths-ignore")


def _glob_segment_to_regex(segment: str) -> str:
    """Convert one path segment's glob (no slashes) to a regex fragment."""
    out: List[str] = []
    i = 0
    n = len(segment)
    while i < n:
        ch = segment[i]
        if ch == "[":
            j = i + 1
            if j < n and segment[j] == "!":
                j += 1
            if j < n and segment[j] == "]":
                out.append(re.escape("[]"))
                i = j + 1
                continue
            while j < n and segment[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(ch))
                i += 1
                continue
            out.append(segment[i : j + 1])
            i = j + 1
            continue
        if ch == "*":
            out.append("[^/]*")
            i += 1
            continue
        if ch in ".^$|(){}\\":
            out.append(re.escape(ch))
            i += 1
            continue
        if ch in "?+":
            if not out:
                out.append(re.escape(ch))
                i += 1
                continue
            prev = out.pop()
            if prev == "[^/]*":
                out.append("[^/]*" if ch == "?" else "[^/]+")
            elif prev.endswith("*") or prev.endswith("+") or prev.startswith("("):
                quant = "?" if ch == "?" else "+"
                out.append(prev + quant)
            else:
                quant = "?" if ch == "?" else "+"
                out.append(prev + quant)
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def _match_glob_segment(segment: str, pattern: str) -> bool:
    if pattern == "**":
        return True
    regex = "^" + _glob_segment_to_regex(pattern) + "$"
    return re.match(regex, segment) is not None


def _match_parts(path_parts: Sequence[str], pat_parts: Sequence[str], pi: int, pj: int) -> bool:
    while pj < len(pat_parts):
        pat = pat_parts[pj]
        if pat == "**":
            if pj == len(pat_parts) - 1:
                return True
            for skip in range(0, len(path_parts) - pi + 1):
                if _match_parts(path_parts, pat_parts, pi + skip, pj + 1):
                    return True
            return False
        if pi >= len(path_parts):
            return False
        if not _match_glob_segment(path_parts[pi], pat):
            return False
        pi += 1
        pj += 1
    return pi == len(path_parts)


def path_matches_glob(path: str, pattern: str) -> bool:
    """Return whether repo-root ``path`` matches a GitHub-style glob pattern."""
    path = path.lstrip("./")
    pattern = pattern.lstrip("./")
    if not pattern:
        return path == ""
    return _match_parts(path.split("/"), pattern.split("/"), 0, 0)


def file_included_by_paths(path: str, patterns: Sequence[str]) -> bool:
    """Ordered paths list with optional ``!`` negation (last match wins)."""
    included = False
    matched = False
    for raw in patterns:
        negate = raw.startswith("!")
        pat = raw[1:] if negate else raw
        if path_matches_glob(path, pat):
            matched = True
            included = not negate
    return included if matched else False


def workflow_runs_for_changes(
    changed_files: Sequence[str],
    paths: Optional[Sequence[str]] = None,
    paths_ignore: Optional[Sequence[str]] = None,
) -> bool:
    if paths and paths_ignore:
        raise ValueError("paths and paths-ignore cannot both be set")
    if not changed_files:
        return False
    if paths is None and paths_ignore is None:
        return True
    if paths_ignore is not None:
        for fpath in changed_files:
            ignored = any(path_matches_glob(fpath, p) for p in paths_ignore)
            if not ignored:
                return True
        return False
    assert paths is not None
    for fpath in changed_files:
        if file_included_by_paths(fpath, paths):
            return True
    return False


def read_workflow(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def sha256_file(rel_path: str) -> str:
    data = (REPO_ROOT / rel_path).read_bytes()
    return hashlib.sha256(data).hexdigest()


class TestGitHubPathGlobSemantics(unittest.TestCase):
    """Self-tests for glob rules used in workflow path filters."""

    def test_star_does_not_cross_slashes(self) -> None:
        self.assertTrue(path_matches_glob("docs/README.md", "docs/*"))
        self.assertFalse(path_matches_glob("docs/mona/octocat.txt", "docs/*"))

    def test_double_star_directory_wildcard(self) -> None:
        self.assertTrue(path_matches_glob("docs/README.md", "docs/**"))
        self.assertTrue(path_matches_glob("docs/mona/octocat.txt", "docs/**"))

    def test_docs_recursive_md(self) -> None:
        pat = "docs/**/*.md"
        self.assertTrue(path_matches_glob("docs/README.md", pat))
        self.assertTrue(path_matches_glob("docs/mona/hello-world.md", pat))
        self.assertTrue(path_matches_glob("docs/a/markdown/file.md", pat))
        self.assertFalse(path_matches_glob("docs/README.txt", pat))
        self.assertFalse(path_matches_glob("other/README.md", pat))

    def test_jsx_optional_extension(self) -> None:
        pat = "*.jsx?"
        self.assertTrue(path_matches_glob("page.js", pat))
        self.assertTrue(path_matches_glob("page.jsx", pat))
        self.assertFalse(path_matches_glob("dir/page.js", pat))

    def test_plus_quantifier(self) -> None:
        self.assertTrue(path_matches_glob("aaa", "a+"))
        self.assertFalse(path_matches_glob("b", "a+"))

    def test_dot_is_literal(self) -> None:
        self.assertTrue(path_matches_glob("file.txt", "file.txt"))
        self.assertFalse(path_matches_glob("fileXtxt", "file.txt"))

    def test_character_class(self) -> None:
        self.assertTrue(path_matches_glob("a1", "a[0-9]"))
        self.assertFalse(path_matches_glob("ab", "a[0-9]"))

    def test_ordered_paths_negation(self) -> None:
        patterns = ["data/overnight/**", "!data/overnight/inbox/**/scheduled_output.json"]
        self.assertTrue(path_matches_glob(JSON, "data/overnight/**"))
        self.assertTrue(path_matches_glob("data/overnight/books/latest.json", "data/overnight/**"))
        self.assertFalse(
            file_included_by_paths(JSON, patterns),
            "inbox JSON excluded by trailing negation",
        )
        self.assertTrue(
            file_included_by_paths("data/overnight/books/latest.json", patterns),
        )
        self.assertTrue(
            file_included_by_paths(
                "data/overnight/inbox/overnight-20261015/notes.json", patterns
            ),
        )
        self.assertFalse(
            path_matches_glob(
                "data/overnight/inbox/overnight-20261015/notes.json",
                "!data/overnight/inbox/**/scheduled_output.json",
            )
        )


class TestWorkflowPathContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launch_text = read_workflow(".github/workflows/launch-market-watch.yml")
        cls.macro_text = read_workflow(".github/workflows/macro-ingestion.yml")
        cls.overnight_text = read_workflow(".github/workflows/overnight-pipeline.yml")
        cls.pages_text = read_workflow(".github/workflows/deploy-pages.yml")
        cls.acceptance_text = read_workflow(
            ".github/workflows/overnight-scheduled-output.yml"
        )
        cls.ppi_text = read_workflow(".github/workflows/run-ppi-oneshot.yml")

        cls.launch_pr = parse_pull_request_trigger(cls.launch_text)
        cls.macro_pr = parse_pull_request_trigger(cls.macro_text)
        cls.overnight_pr = parse_pull_request_trigger(cls.overnight_text)
        cls.pages_pr = parse_pull_request_trigger(cls.pages_text)
        cls.acceptance_pr = parse_pull_request_target_trigger(cls.acceptance_text)

    def test_protected_workflow_bytes(self) -> None:
        for rel, expected in PROTECTED_SHA256.items():
            self.assertEqual(sha256_file(rel), expected, rel)

    def test_pull_request_never_has_paths_and_paths_ignore(self) -> None:
        for name, text in (
            ("launch", self.launch_text),
            ("macro", self.macro_text),
            ("overnight", self.overnight_text),
            ("pages", self.pages_text),
        ):
            with self.subTest(workflow=name):
                assert_no_paths_and_paths_ignore(parse_pull_request_trigger(text), name)

    def test_paths_ignore_only_on_launch_and_macro(self) -> None:
        expected_ignore = ["data/overnight/inbox/**/scheduled_output.json"]
        for name, trigger in (("launch", self.launch_pr), ("macro", self.macro_pr)):
            with self.subTest(workflow=name):
                assert_no_paths_and_paths_ignore(trigger, name)
                self.assertEqual(trigger.get("paths-ignore"), expected_ignore)
                self.assertNotIn("paths", trigger)

    def test_overnight_and_pages_paths_with_trailing_negation(self) -> None:
        neg = "!data/overnight/inbox/**/scheduled_output.json"
        overnight_paths = self.overnight_pr.get("paths") or []
        pages_paths = self.pages_pr.get("paths") or []
        for name, trigger, paths in (
            ("overnight", self.overnight_pr, overnight_paths),
            ("deploy-pages", self.pages_pr, pages_paths),
        ):
            with self.subTest(workflow=name):
                assert_no_paths_and_paths_ignore(trigger, name)
                self.assertNotIn("paths-ignore", trigger)
                self.assertIn("data/overnight/**", paths)
                idx_pos = paths.index("data/overnight/**")
                self.assertEqual(paths[-1], neg)
                self.assertLess(idx_pos, paths.index(neg))

    def test_workflow_dispatch_present(self) -> None:
        for text in (
            self.launch_text,
            self.macro_text,
            self.overnight_text,
            self.pages_text,
        ):
            self.assertIn("workflow_dispatch:", text)

    def test_launch_guard_and_unit_tests(self) -> None:
        self.assertIn("issues:", self.launch_text)
        self.assertIn("types: [opened]", self.launch_text)
        self.assertIn(
            "github.event_name == 'workflow_dispatch' || github.event_name == 'issues'",
            self.launch_text,
        )
        self.assertIn("tests.test_mw_launch_persist_boundary", self.launch_text)
        self.assertIn("tests.test_mw_launch_lineage", self.launch_text)
        self.assertIn("tests.test_pr_path_triggers", self.launch_text)

    def test_macro_validate_unittest_command(self) -> None:
        self.assertIn("unittest discover -s tests/macro_ingestion", self.macro_text)
        self.assertIn("tests.test_temperature_scores", self.macro_text)
        self.assertIn("tests.test_overnight_pipeline", self.macro_text)
        self.assertIn("tests.test_overnight_scheduled_output", self.macro_text)

    def test_overnight_job_names_and_fail_closed(self) -> None:
        self.assertIn("Overnight unit contracts", self.overnight_text)
        self.assertIn("Zero-model dry-run", self.overnight_text)
        self.assertIn("Overnight contracts and dry-run", self.overnight_text)
        self.assertIn("unit-contracts=$UNIT_RESULT", self.overnight_text)

    def test_deploy_pages_skips_deploy_on_pr(self) -> None:
        self.assertIn("github.event_name != 'pull_request'", self.pages_text)

    def test_acceptance_pull_request_target_contract(self) -> None:
        paths = self.acceptance_pr.get("paths") or []
        self.assertIn("data/overnight/inbox/**/scheduled_output.json", paths)
        self.assertIn("pull_request_target:", self.acceptance_text)
        self.assertIn("ref: main", self.acceptance_text)
        self.assertIn("scheduled_output.py validate", self.acceptance_text)

    def test_ppi_has_no_pull_request(self) -> None:
        self.assertNotIn("pull_request:", self.ppi_text)


class TestChangedFileTriggerMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launch_pr = parse_pull_request_trigger(
            read_workflow(".github/workflows/launch-market-watch.yml")
        )
        cls.macro_pr = parse_pull_request_trigger(
            read_workflow(".github/workflows/macro-ingestion.yml")
        )
        cls.overnight_pr = parse_pull_request_trigger(
            read_workflow(".github/workflows/overnight-pipeline.yml")
        )
        cls.pages_pr = parse_pull_request_trigger(
            read_workflow(".github/workflows/deploy-pages.yml")
        )
        cls.acceptance_pr = parse_pull_request_target_trigger(
            read_workflow(".github/workflows/overnight-scheduled-output.yml")
        )

    def _runs(
        self,
        files: Sequence[str],
        launch: bool,
        macro: bool,
        overnight: bool,
        pages: bool,
        acceptance: bool,
    ) -> None:
        cases = (
            ("launch", self.launch_pr, launch),
            ("macro", self.macro_pr, macro),
            ("overnight", self.overnight_pr, overnight),
            ("pages", self.pages_pr, pages),
            ("acceptance", self.acceptance_pr, acceptance),
        )
        for name, trigger, expected in cases:
            with self.subTest(workflow=name, files=list(files)):
                if name == "acceptance":
                    got = workflow_runs_for_changes(files, paths=trigger.get("paths"))
                else:
                    got = workflow_runs_for_changes(
                        files,
                        paths=trigger.get("paths"),
                        paths_ignore=trigger.get("paths-ignore"),
                    )
                self.assertEqual(got, expected, f"{name}: files={files!r}")

    def test_case_01_json_only(self) -> None:
        self._runs([JSON], False, False, False, False, True)

    def test_case_02_two_inbox_json(self) -> None:
        self._runs([JSON, JSON2], False, False, False, False, True)

    def test_case_03_mixed_overnight(self) -> None:
        self._runs([JSON, "scripts/overnight/scheduled_output.py"], True, True, True, True, True)

    def test_case_04_mixed_launch_only_code(self) -> None:
        self._runs(
            [JSON, "scripts/market_watch_launch/lineage.py"],
            True,
            True,
            False,
            False,
            True,
        )

    def test_case_05_code_overnight_pipeline(self) -> None:
        self._runs(["scripts/overnight_pipeline.py"], True, True, True, True, False)

    def test_case_06_code_macro(self) -> None:
        self._runs(["scripts/macro_ingestion/runner.py"], True, True, False, False, False)

    def test_case_07_code_launch(self) -> None:
        self._runs(["scripts/market_watch_launch/lineage.py"], True, True, False, False, False)

    def test_case_08_workflow_overnight(self) -> None:
        self._runs([".github/workflows/overnight-pipeline.yml"], True, True, True, False, False)

    def test_case_09_workflow_pages(self) -> None:
        # overnight-pipeline.yml already lists deploy-pages.yml, so a Pages
        # workflow edit keeps the overnight regression suite.
        self._runs([".github/workflows/deploy-pages.yml"], True, True, True, True, False)

    def test_case_10_workflow_launch(self) -> None:
        self._runs([".github/workflows/launch-market-watch.yml"], True, True, False, False, False)

    def test_case_11_workflow_macro(self) -> None:
        self._runs([".github/workflows/macro-ingestion.yml"], True, True, False, False, False)

    def test_case_12_workflow_acceptance(self) -> None:
        self._runs(
            [".github/workflows/overnight-scheduled-output.yml"],
            True,
            True,
            True,
            True,
            False,
        )

    def test_case_13_rendered_temperature(self) -> None:
        self._runs(["data/temperature_scores.json"], True, True, False, True, False)

    def test_case_14_rendered_overnight_book(self) -> None:
        self._runs(["data/overnight/books/latest.json"], True, True, True, True, False)

    def test_case_15_other_inbox_file(self) -> None:
        self._runs(
            ["data/overnight/inbox/overnight-20261015/notes.json"],
            True,
            True,
            True,
            True,
            False,
        )

    def test_case_16_docs_only(self) -> None:
        self._runs(
            ["docs/US_CPI_CORE_PCE_RELEASE_POSTMORTEM_2026-10-14.md"],
            True,
            True,
            False,
            False,
            False,
        )

    def test_empty_change_list_does_not_run_filtered(self) -> None:
        for trigger in (
            self.launch_pr,
            self.macro_pr,
            self.overnight_pr,
            self.pages_pr,
        ):
            self.assertFalse(
                workflow_runs_for_changes(
                    [],
                    paths=trigger.get("paths"),
                    paths_ignore=trigger.get("paths-ignore"),
                )
            )


if __name__ == "__main__":
    unittest.main()
