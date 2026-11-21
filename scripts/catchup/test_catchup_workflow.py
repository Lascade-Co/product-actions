"""Static wiring checks: catchup, ad spend and hunch keep test recipients out of public step headers."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest
import yaml

import adspend_send

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SEAL = "Lascade-Co/actions/actions/seal@seal-v1"
# The scheduled ad-spend list. Its sha1 is part of the Resend idempotency key, so it must not change.
AD_SPEND_TO = "cherian@lascade.com, Jishnu M M <jishnu@lascade.com>"


def load(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def header_text(node, key=None):
    """Every string in the workflow except `if:` conditions (which never reach a step header)."""
    if isinstance(node, dict):
        return "\n".join(header_text(v, k) for k, v in node.items() if k != "if")
    if isinstance(node, list):
        return "\n".join(header_text(v) for v in node)
    return node if isinstance(node, str) else ""


@pytest.mark.parametrize("name", ["daily-catchup.yml", "daily-ad-spend.yml", "daily-hunch-retention.yml"])
def test_test_recipient_never_reaches_a_step_header(name):
    text = header_text(load(name))
    assert not re.search(r"\$\{\{[^}]*\binputs\.to\b", text)      # no expression expands it
    assert "outputs.recipient" not in text
    assert "INPUT_TO" not in text


def mask_step(job):
    steps = job["steps"]
    assert steps[0]["uses"] == SEAL
    assert steps[1]["name"] == "Mask test recipient"
    return steps[1]


@pytest.mark.parametrize("name,jobs", [("daily-catchup.yml", ["settings", "email"]),
                                       ("daily-ad-spend.yml", ["settings", "email"])])
def test_jobs_that_read_the_recipient_mask_it_first(name, jobs, tmp_path):
    flow = load(name)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"to": "Tester One <one@example.com>, two@example.com"}}))
    for job in jobs:
        step = mask_step(flow["jobs"][job])
        assert "env" not in step
        result = subprocess.run(["bash", "-e", "-c", step["run"]], env={"GITHUB_EVENT_PATH": str(event),
                                "PATH": "/usr/bin:/bin:/usr/local/bin"}, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert sorted(result.stdout.splitlines()) == sorted([
            "::add-mask::Tester One <one@example.com>, two@example.com",
            "::add-mask::Tester One <one@example.com>", "::add-mask::two@example.com"])
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({}))
    result = subprocess.run(["bash", "-e", "-c", mask_step(flow["jobs"][jobs[0]])["run"]],
                            env={"GITHUB_EVENT_PATH": str(empty), "PATH": "/usr/bin:/bin:/usr/local/bin"},
                            capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == ""


def test_test_sends_read_the_address_from_the_event_file():
    for name, script in (("daily-catchup.yml", "catchup_send.py"), ("daily-ad-spend.yml", "adspend_send.py")):
        steps = [s for s in load(name)["jobs"]["email"]["steps"] if s.get("name", "").startswith("Test send")]
        assert steps
        for step in steps:
            run = step["run"]
            assert "jq -r '.inputs.to // \"\"' \"$GITHUB_EVENT_PATH\"" in run
            assert 'test -n "$TEST_TO"' in run and script in run
            assert run.index('test -n "$TEST_TO"') < run.index(script)


def test_ad_spend_real_list_and_key_are_unchanged():
    email = load("daily-ad-spend.yml")["jobs"]["email"]
    assert email["env"]["MAIL_TO"] == AD_SPEND_TO
    assert hashlib.sha1(AD_SPEND_TO.encode()).hexdigest()[:8] == "48abe527"
    assert adspend_send.key_for("A", "2026-11-20", AD_SPEND_TO) == "ad-spend-A-2026-11-20-48abe527"
    for step in email["steps"]:
        if step.get("name", "").startswith("Test send"):
            assert '--mail-to "$TEST_TO"' in step["run"]
        elif "adspend_send.py" in step.get("run", ""):
            assert "--mail-to" not in step["run"]


def test_ad_spend_settings_validate_the_variants_the_email_job_uses():
    flow = load("daily-ad-spend.yml")
    settings = next(s for s in flow["jobs"]["settings"]["steps"] if s.get("id") == "settings")
    assert '--variants "$VARIANTS"' in settings["run"]
    assert settings["env"]["VARIANTS"] == flow["jobs"]["email"]["env"]["VARIANTS"] == "${{ inputs.variants || 'A' }}"
