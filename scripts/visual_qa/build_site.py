"""Reproduce the deploy-pages.yml build locally for visual QA.

Runs each ``run:`` step of the Pages build job in order with
``GITHUB_EVENT_NAME=pull_request`` (dispatch binding and ``uses:`` steps are
skipped). Not used by CI.

    python3 scripts/visual_qa/build_site.py                 # full build, with tests
    python3 scripts/visual_qa/build_site.py --skip-tests    # no unittest / pip lines
    python3 scripts/visual_qa/build_site.py --checkpoint DIR
        # stop before "Apply Country Detail" and save _site to DIR
    python3 scripts/visual_qa/build_site.py --from-checkpoint DIR --market-state FILE
        # fast offline replay of the late presentation stages: restore DIR into
        # _site, copy FILE to _site/market-state.json instead of regenerating
        # it, skip the live policy refresh and the live schedule fetch
    --site-dir _site_NAME   build into another top-level directory (parallel QA)

The live policy refresh may rewrite data/policy_state.json; restore it with
``git checkout data/policy_state.json`` before committing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_STAGE = "Apply Country Detail"


def main(argv: list[str]) -> int:
    skip_tests = "--skip-tests" in argv
    checkpoint = None
    if "--checkpoint" in argv:
        checkpoint = Path(argv[argv.index("--checkpoint") + 1])
    site_name = "_site"
    if "--site-dir" in argv:
        site_name = argv[argv.index("--site-dir") + 1]
        if "/" in site_name or not site_name.startswith("_site"):
            raise SystemExit("--site-dir must be a top-level name starting with _site")
    resume = None
    if "--from-checkpoint" in argv:
        resume = Path(argv[argv.index("--from-checkpoint") + 1])
        skip_tests = True
        site = ROOT / site_name
        if site.exists():
            shutil.rmtree(site)
        shutil.copytree(resume, site)
        if "--market-state" in argv:
            shutil.copy(Path(argv[argv.index("--market-state") + 1]), site / "market-state.json")
    started = resume is None
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-pages.yml").read_text())
    shim = Path(tempfile.mkdtemp())
    python = shutil.which("python3") or sys.executable
    (shim / "python").symlink_to(python)
    env = dict(os.environ, GITHUB_EVENT_NAME="pull_request", PYTHONPATH=".")
    env["PATH"] = f"{shim}{os.pathsep}{env.get('PATH', '')}"
    for step in workflow["jobs"]["build"]["steps"]:
        name = step.get("name")
        if checkpoint and name == CHECKPOINT_STAGE:
            if checkpoint.exists():
                shutil.rmtree(checkpoint)
            shutil.copytree(ROOT / site_name, checkpoint)
            print(f"checkpoint saved to {checkpoint}")
            return 0
        if not started:
            if name != CHECKPOINT_STAGE:
                continue
            started = True
        run = step.get("run")
        if not run or step.get("if"):
            print(f"-- skip {name}")
            continue
        if resume is not None:
            if name == "Generate market-state JSON for Pages":
                print(f"-- reuse market-state.json for {name}")
                continue
            run = run.replace("python3 scripts/policy_state.py --refresh", "false")
            run = run.replace(" --fetch-schedules --schedule-timeout 6", "")
        if site_name != "_site":
            run = run.replace("_site", site_name)
        if skip_tests:
            run = "\n".join(
                line for line in run.splitlines() if "-m unittest" not in line and "pip install" not in line
            )
        print(f"== {name}", flush=True)
        result = subprocess.run(["bash", "-c", run], cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout[-4000:])
            print(result.stderr[-4000:])
            if step.get("continue-on-error"):
                print(f"!! continue-on-error: {name}")
                continue
            print(f"step failed: {name}")
            return 1
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
