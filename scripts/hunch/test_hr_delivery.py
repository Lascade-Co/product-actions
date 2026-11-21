"""Delivery contracts, with the network replaced at its HTTP boundary."""
import datetime as dt
import importlib
import json
from pathlib import Path

import pytest
import requests


UTC = dt.timezone.utc
REPORT_DATE = dt.date(2026, 11, 19)


def sender():
    return importlib.import_module("hr_send")


def workflow():
    return importlib.import_module("hr_workflow")


@pytest.fixture(autouse=True)
def fresh_main_run(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("RUN_CREATED_AT", "2099-01-01T00:00:00Z")


def write_email(path, subject="TreasureHunch retention"):
    (path / "email.json").write_text(json.dumps({
        "subject": subject, "html": "<p>private-metric-value</p>",
        "text": "private-metric-value",
    }))


@pytest.mark.parametrize("event,recovery,want", [
    ("schedule", False, "hunch-retention-2026-11-19"),
    ("workflow_dispatch", False, "hunch-retention-2026-11-19-manual-12345"),
    ("workflow_dispatch", True, "hunch-retention-2026-11-19"),
])
def test_send_keys_separate_tests_from_real_delivery(event, recovery, want):
    assert sender().send_key(REPORT_DATE, event, "12345", recovery) == want


@pytest.mark.parametrize("event,recovery", [("schedule", False), ("workflow_dispatch", True)])
def test_real_sends_reject_an_alternate_recipient(event, recovery):
    with pytest.raises(ValueError):
        sender().recipient(event, recovery, "someone@example.com")


def test_manual_test_can_override_the_recipient():
    assert sender().recipient("workflow_dispatch", False, "someone@example.com") == "someone@example.com"


def test_no_scheduled_at_in_payload(tmp_path):
    write_email(tmp_path)
    body = sender().build_payload(tmp_path, REPORT_DATE, "12345", "schedule")
    assert "scheduled_at" not in body
    assert body["from"] == "Lascade Games <noreply@metrics.lascade.com>"
    assert body["to"] == [sender().TO]
    assert set(body) == {"from", "to", "subject", "html", "text"}


def test_hunch_key_scheduled_and_manual():
    s = sender()
    assert s.send_key(REPORT_DATE, "schedule", "9") == "hunch-retention-2026-11-19"
    assert s.send_key(REPORT_DATE, "workflow_dispatch", "9") == "hunch-retention-2026-11-19-manual-9"
    assert s.send_key(REPORT_DATE, "workflow_dispatch", "9", recovery=True) == "hunch-retention-2026-11-19"


def test_cli_freezes_then_sends_the_same_envelope_with_the_old_key(tmp_path, monkeypatch):
    s = sender()
    write_email(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "synthetic")
    sent = []
    monkeypatch.setattr(s.delivery, "send_frozen", lambda path, api_key: sent.append((path, api_key)) or {"accepted": True})
    assert s.main(["--report-date", "2026-11-19", "--event", "schedule", "--run-id", "12345",
                   "--out", str(tmp_path)]) == 0
    (path, api_key), = sent
    envelope = json.loads(Path(path).read_text())
    assert envelope["key"] == "hunch-retention-2026-11-19" and api_key == "synthetic"
    assert "scheduled_at" not in envelope["body"]
    write_email(tmp_path, subject="Changed")
    assert s.main(["--report-date", "2026-11-19", "--event", "schedule", "--run-id", "12345",
                   "--out", str(tmp_path)]) == 0
    assert json.loads(Path(path).read_text())["body"] == envelope["body"]


def test_cli_failure_is_generic(tmp_path, monkeypatch, capsys):
    s = sender()
    write_email(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "synthetic")

    def refuse(path, api_key):
        raise s.delivery.DeliveryError("Resend delivery failed: HTTP 400 (HTTP error)")

    monkeypatch.setattr(s.delivery, "send_frozen", refuse)
    assert s.main(["--report-date", "2026-11-19", "--event", "schedule", "--run-id", "1",
                   "--out", str(tmp_path)]) == 1
    assert "private" not in capsys.readouterr().err


@pytest.mark.parametrize("subject,want", [
    ("TreasureHunch retention", "[Test 7] TreasureHunch retention"),
    ("[Test 7] TreasureHunch retention", "[Test 7] TreasureHunch retention"),
])
def test_manual_payload_always_has_one_test_prefix(tmp_path, monkeypatch, subject, want):
    write_email(tmp_path, subject=subject)
    monkeypatch.setenv("HR_TEST_NUMBER", "7")
    body = sender().build_payload(tmp_path, REPORT_DATE, "12345", "workflow_dispatch",
                                  to="someone@example.com")
    assert body["subject"] == want
    assert body["to"] == ["someone@example.com"]
    assert "scheduled_at" not in body


@pytest.mark.parametrize("event,recovery,want", [
    ("schedule", False, "Deliver hunch retention for 2026-11-19"),
    ("workflow_dispatch", True, "Deliver hunch retention for 2026-11-19"),
    ("workflow_dispatch", False, "Test send hunch retention for 2026-11-19"),
])
def test_delivery_step_records_only_real_sends(event, recovery, want):
    w = workflow()
    assert w.delivery_step(REPORT_DATE, w.delivery_mode(event, recovery)) == want


@pytest.mark.parametrize("now,want", [
    ("2026-11-19T12:59:00+00:00", dt.date(2026, 11, 18)),
    ("2026-11-19T13:00:00+00:00", dt.date(2026, 11, 19)),
])
def test_manual_blank_date_uses_newest_pacific_date_past_0500(monkeypatch, now, want):
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("NOW", now)
    monkeypatch.delenv("REPORT_DATE", raising=False)
    monkeypatch.delenv("INPUT_DATE", raising=False)
    monkeypatch.delenv("RECOVERY", raising=False)
    date, mode, to = workflow().settings()
    assert date == want
    assert mode == "test"
    assert to == workflow().TO


def test_settings_write_outputs_without_logging_dates(tmp_path, monkeypatch, capsys):
    output = tmp_path / "github-output"
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("INPUT_DATE", "2026-11-19")
    monkeypatch.setenv("RECOVERY", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert workflow().main(["settings"]) == 0
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert outputs["report_date"] == "2026-11-19"
    assert outputs["send_step"] == "Deliver hunch retention for 2026-11-19"
    assert capsys.readouterr().out == "settings-ok\n"


def test_dedupe_uses_bare_delivery_prefix_and_skips_already_sent(tmp_path, monkeypatch):
    w = workflow()
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("INPUT_DATE", "2026-11-19")
    monkeypatch.setenv("RECOVERY", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    history = []

    def already_sent(date, now, **kwargs):
        history.append((date, kwargs))
        return True

    monkeypatch.setattr(w.G, "already_sent", already_sent)
    assert w.main(["dedupe"]) == 0
    assert history == [(REPORT_DATE, {"workflow": "daily-hunch-retention.yml", "sent_step": "Deliver hunch retention for "})]
    assert (tmp_path / "outputs").read_text() == "sent=True\n"


def test_history_unavailable_refuses_recovery(tmp_path, monkeypatch, capsys):
    w = workflow()
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("INPUT_DATE", "2026-11-19")
    monkeypatch.setenv("RECOVERY", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))

    def unavailable(*a, **kw):
        raise w.G.DedupeUnavailable("private-body")

    monkeypatch.setattr(w.G, "already_sent", unavailable)
    assert w.main(["dedupe"]) == 3
    assert not (tmp_path / "outputs").exists()
    assert capsys.readouterr().err == "history-unavailable\n"


@pytest.mark.parametrize("env,code", [
    ({"GITHUB_REF": "refs/heads/feature"}, 2),
    ({"GITHUB_RUN_ATTEMPT": "2"}, 2),
])
def test_real_recovery_settings_refuse_a_branch_or_a_rerun(tmp_path, monkeypatch, env, code):
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("INPUT_DATE", "2026-11-19")
    monkeypatch.setenv("RECOVERY", "true")
    monkeypatch.setenv("NOW", "2026-11-19T14:00:00+00:00")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert workflow().main(["settings"]) == code
    assert not (tmp_path / "out").exists()


def test_failure_notify_command_uses_notify(monkeypatch):
    import notify
    sent = []
    monkeypatch.setattr(notify, "telegram_send", lambda token, chat, text: sent.append((token, chat, text)))
    for key, value in (("EVENT", "workflow_dispatch"), ("REPORT_DATE", "2026-11-19"), ("TOKEN", "t"),
                       ("CHAT", "c"), ("RUN_URL", "https://example.invalid/run")):
        monkeypatch.setenv(key, value)
    assert workflow().main(["notify"]) == 0
    assert sent == [("t", "c", "TreasureHunch retention for 2026-11-19 failed. Run: https://example.invalid/run")]


def dispatch_event(tmp_path, monkeypatch, to, recovery=False):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"to": to}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("INPUT_DATE", "2026-11-19")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    if recovery:
        monkeypatch.setenv("RECOVERY", "true")
    else:
        monkeypatch.delenv("RECOVERY", raising=False)


def test_test_recipient_comes_from_the_event_file_and_is_masked(tmp_path, monkeypatch, capsys):
    dispatch_event(tmp_path, monkeypatch, "tester@example.com")
    assert workflow().main(["settings"]) == 0
    assert capsys.readouterr().out == "::add-mask::tester@example.com\nsettings-ok\n"
    outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
    assert "recipient" not in outputs and "tester@example.com" not in (tmp_path / "outputs").read_text()
    assert workflow().main(["recipient"]) == 0
    assert capsys.readouterr().out == "tester@example.com\n"


@pytest.mark.parametrize("to", ["", "cherian@lascade.com"])
def test_default_recipient_is_public_and_not_masked(tmp_path, monkeypatch, capsys, to):
    dispatch_event(tmp_path, monkeypatch, to)
    assert workflow().main(["settings"]) == 0
    assert capsys.readouterr().out == "settings-ok\n"
    assert workflow().main(["recipient"]) == 0
    assert capsys.readouterr().out == "cherian@lascade.com\n"


def test_recovery_refuses_an_event_recipient_override(tmp_path, monkeypatch):
    dispatch_event(tmp_path, monkeypatch, "tester@example.com", recovery=True)
    assert workflow().main(["settings"]) == 2
    assert workflow().main(["recipient"]) == 2
