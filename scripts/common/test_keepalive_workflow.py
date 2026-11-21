"""keepalive.yml re-enables every scheduled workflow, so GitHub's 60-day inactivity rule never disables one."""
import os
from pathlib import Path
import shutil
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
FLOW = yaml.load((WORKFLOWS / "keepalive.yml").read_text(), Loader=yaml.BaseLoader)


def scheduled_workflows():
    names = set()
    for path in WORKFLOWS.glob("*.yml"):
        on = yaml.load(path.read_text(), Loader=yaml.BaseLoader).get("on")
        if isinstance(on, dict) and "schedule" in on:
            names.add(path.name)
    return names


def test_keepalive_is_scheduled_weekly_and_least_privilege():
    assert set(FLOW["on"]) == {"schedule", "workflow_dispatch"}
    assert len(FLOW["on"]["schedule"]) == 1
    assert FLOW["permissions"] == {"actions": "write", "contents": "read"}
    assert "secrets." not in (WORKFLOWS / "keepalive.yml").read_text()
    job = FLOW["jobs"]["keepalive"]
    assert job["steps"][0]["uses"] == "Lascade-Co/actions/actions/seal@seal-v1"
    assert job["steps"][-1]["uses"] == "Lascade-Co/actions/actions/seal-upload@seal-v1"


def run_enable_step(tmp_path, failing=()):
    step = next(s for s in FLOW["jobs"]["keepalive"]["steps"] if "gh api" in s.get("run", ""))
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    shutil.copytree(WORKFLOWS, tmp_path / ".github" / "workflows")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.txt"
    fails = "|".join(f"/{name}/" for name in failing) or "^$"
    (bin_dir / "gh").write_text(
        f'#!/bin/bash\necho "$*" >> "{log}"\nif echo "$*" | grep -qE "{fails}"; then exit 1; fi\n')
    (bin_dir / "gh").chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GITHUB_REPOSITORY": "Lascade-Co/product-actions"}
    result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_every_scheduled_workflow_is_enabled(tmp_path):
    result, calls = run_enable_step(tmp_path)
    assert result.returncode == 0, result.stderr
    prefix = "api -X PUT repos/Lascade-Co/product-actions/actions/workflows/"
    assert all(c.startswith(prefix) and c.endswith("/enable") for c in calls)
    enabled = {c[len(prefix):-len("/enable")] for c in calls}
    assert enabled == scheduled_workflows()
    assert "keepalive.yml" in enabled and "chat-summary.yml" in enabled and "_digest.yml" not in enabled


def test_one_failure_does_not_skip_the_rest(tmp_path):
    result, calls = run_enable_step(tmp_path, failing=("chat-summary.yml",))
    assert result.returncode != 0
    assert len(calls) == len(scheduled_workflows())


def test_no_workflow_keeps_its_own_keepalive_job():
    for path in WORKFLOWS.glob("*.yml"):
        if path.name != "keepalive.yml":
            assert "/enable" not in path.read_text(), path.name
