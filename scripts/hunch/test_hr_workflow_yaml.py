"""Static wiring checks for the hunch retention workflow."""
from pathlib import Path

import yaml

import workflow as W

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".github/workflows/daily-hunch-retention.yml"
FLOW = yaml.load(PATH.read_text(), Loader=yaml.BaseLoader)


def runs(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_every_job_is_sealed_first_and_last():
    for job in FLOW["jobs"].values():
        assert job["steps"][0]["uses"] == "Lascade-Co/actions/actions/seal@seal-v1"
        assert job["steps"][-1]["uses"] == "Lascade-Co/actions/actions/seal-upload@seal-v1"


def test_gates_use_the_new_marker_and_shared_gate():
    prefix = W.sent_prefix("hunch retention", "")
    assert prefix == "Deliver hunch retention for "
    for name in ("gate", "gate2"):
        text = runs(FLOW["jobs"][name])
        assert "scripts/common/gate.py" in text and f'--sent-step "{prefix}"' in text
        assert "--target 05:05" in text and "catchup" not in text


def test_hold_is_between_build_and_dedupe_then_deliver():
    steps = FLOW["jobs"]["email"]["steps"]
    index = lambda pred: next(i for i, step in enumerate(steps) if pred(step))
    build = index(lambda s: s.get("name") == "Build the email")
    hold = index(lambda s: "hold.py" in s.get("run", ""))
    dedupe = index(lambda s: s.get("id") == "dedupe")
    send = index(lambda s: "hr_send.py" in s.get("run", ""))
    assert build < hold < dedupe < send
    assert ('python3 scripts/common/hold.py --report-date "$REPORT_DATE" --tz America/Los_Angeles '
            '--target 05:55') in steps[hold]["run"]
    assert steps[send]["name"] == "${{ steps.dates.outputs.send_step }}"


def test_no_scheduled_at_legacy_sender_catchup_or_inline_curl_alert():
    text = PATH.read_text()
    for gone in ("scheduled_at", "send_resend_hr", "catchup", "api.telegram.org"):
        assert gone not in text


def test_notify_uses_the_shared_telegram_sender():
    notify = FLOW["jobs"]["notify"]
    assert "hr_workflow.py notify" in runs(notify)
    assert notify["environment"] == "production"
