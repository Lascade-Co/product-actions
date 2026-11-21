import json
from pathlib import Path

import pytest
import yaml

import catchup_send as cs
import delivery
import workflow

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "daily-catchup.yml"


def test_catchup_key_format():
    assert cs.key_for("2026-11-21") == "daily-report-2026-11-21"


def test_catchup_test_key_format():
    assert cs.key_for("2026-11-21", run_id="77", attempt="2") == "daily-report-test-77-2"


def test_catchup_sent_step_name():
    assert workflow.step_name("catchup", "", "2026-11-21", "real") == "Deliver catchup for 2026-11-21"
    jobs = yaml.safe_load(WF.read_text())["jobs"]
    names = [s.get("name") for s in jobs["email"]["steps"]]
    assert "Deliver catchup for ${{ needs.gate2.outputs.report_date }}" in names
    assert "Test send catchup for ${{ needs.gate2.outputs.report_date }}" in names
    assert "Dry run catchup for ${{ needs.gate2.outputs.report_date }}" in names
    text = WF.read_text()
    assert f'--sent-step "{workflow.sent_prefix("catchup", "")}"' in text
    assert "--tz America/Los_Angeles --target 05:45" in text


def test_workflow_has_no_raw_script_downloads():
    text = WF.read_text()
    assert "raw.githubusercontent.com/Lascade-Co/actions/${{ github.sha }}" not in text
    assert "$RAW" not in text


def _files(tmp_path):
    html = tmp_path / "email.html"
    subject = tmp_path / "email.subject"
    html.write_text("<p>hi</p>")
    subject.write_text("Engineering · Sat 21 Nov")
    return html, subject


def test_main_real_send_freezes_then_sends(tmp_path, monkeypatch):
    html, subject = _files(tmp_path)
    seen = {}
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setattr(delivery, "send_frozen", lambda path, key: seen.update(path=path, api=key))
    frozen = tmp_path / "frozen.json"
    cs.main(["--report-date", "2026-11-21", "--html", str(html), "--subject", str(subject),
             "--frozen", str(frozen)])
    env = json.loads(frozen.read_text())
    assert env["key"] == "daily-report-2026-11-21"
    body = json.loads(env["body"])
    assert body["to"] == ["cherian@lascade.com", "rohit@lascade.com"]
    assert body["subject"] == "Engineering · Sat 21 Nov"
    assert list(body) == ["from", "to", "subject", "html"]
    assert seen["api"] == "k"


def test_main_test_send_goes_to_one_address(tmp_path, monkeypatch):
    html, subject = _files(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(delivery, "send_frozen", lambda path, key: None)
    frozen = tmp_path / "frozen.json"
    cs.main(["--report-date", "2026-11-21", "--html", str(html), "--subject", str(subject),
             "--to", "a@b.c", "--frozen", str(frozen)])
    env = json.loads(frozen.read_text())
    body = json.loads(env["body"])
    assert env["key"] == "daily-report-test-9-1"
    assert body["to"] == ["a@b.c"]
    assert body["subject"] == "[TEST] Engineering · Sat 21 Nov (test run 9)"


def test_main_fails_closed_without_api_key(tmp_path, monkeypatch):
    html, subject = _files(tmp_path)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        cs.main(["--report-date", "2026-11-21", "--html", str(html), "--subject", str(subject),
                 "--frozen", str(tmp_path / "f.json")])
