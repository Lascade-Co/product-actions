"""Sender wrapper checks with synthetic private content and no external requests."""
import json

import pytest


def sources(out):
    for name, value in (("email-A.html", "<p>private synthetic body</p>"),
                        ("email-A.txt", "private synthetic text"),
                        ("subject-A.txt", "private synthetic subject\n")):
        (out / name).write_text(value)


def run_cli(send, tmp_path, monkeypatch, *argv, edition="pt", event="workflow_dispatch", day="2030-01-12"):
    monkeypatch.setenv("RESEND_API_KEY", "synthetic")
    calls = []
    monkeypatch.setattr(send.delivery, "send_frozen", lambda path, api_key: calls.append((path, api_key)) or {"accepted": True})
    code = send.main(["--edition", edition, "--report-date", day, "--event", event,
                      "--run-id", "synthetic", "--out", str(tmp_path), *argv])
    return code, calls


class TestSender:
    def test_ip_key_formats(self):
        from ip_editions import get_edition
        import datetime as dt
        day = dt.date(2030, 1, 12)
        assert get_edition("pt").send_key(day, "schedule", "9") == "install-paid-pt-2030-01-12-scheduled"
        assert get_edition("ist").send_key(day, "schedule", "9") == "install-paid-ist-2030-01-12-scheduled"
        assert get_edition("pt").send_key(day, "workflow_dispatch", "9") == "install-paid-pt-2030-01-12-manual-9"
        assert get_edition("ist").send_key(day, "workflow_dispatch", "9") == "install-paid-ist-2030-01-12-manual-9"

    def test_no_scheduled_at_in_payload(self, tmp_path):
        import ip_send as send
        from ip_editions import get_edition
        sources(tmp_path)
        body = send.build_payload(tmp_path, "pt")
        assert "scheduled_at" not in body
        assert set(body) == {"from", "to", "subject", "html", "text"}
        assert body["to"] == [get_edition("pt").recipient]
        assert body["subject"] == "private synthetic subject"

    def test_sender_has_no_deadline_or_schedule_surface(self):
        import ip_send as send
        for name in ("scheduled_time", "validate_timing", "send_payload", "freeze_payload"):
            assert not hasattr(send, name)

    def test_cli_freezes_one_envelope_with_the_edition_key_and_reuses_it(self, tmp_path, monkeypatch):
        import ip_send as send
        sources(tmp_path)
        code, calls = run_cli(send, tmp_path, monkeypatch, event="schedule")
        assert code == 0
        (path, api_key), = calls
        envelope = json.loads(open(path).read())
        assert envelope["key"] == "install-paid-pt-2030-01-12-scheduled" and api_key == "synthetic"
        assert "scheduled_at" not in envelope["body"]
        (tmp_path / "subject-A.txt").write_text("changed source")
        code, calls = run_cli(send, tmp_path, monkeypatch, event="schedule")
        assert code == 0 and json.loads(open(calls[0][0]).read())["body"] == envelope["body"]

    @pytest.mark.parametrize("extra", [[], ["--test-tag", "synthetic"]])
    def test_cli_forbids_ist_test_send(self, tmp_path, monkeypatch, extra):
        import ip_send as send
        sources(tmp_path)
        code, calls = run_cli(send, tmp_path, monkeypatch, *extra, edition="ist")
        assert code != 0 and calls == []

    @pytest.mark.parametrize("flag", ["--recovery", "--force-resend"])
    def test_cli_permits_ist_recovery_and_force_with_edition_key(self, tmp_path, monkeypatch, flag):
        import ip_send as send
        from ip_editions import get_edition
        sources(tmp_path)
        code, calls = run_cli(send, tmp_path, monkeypatch, flag, edition="ist")
        assert code == 0
        envelope = json.loads(open(calls[0][0]).read())
        assert envelope["key"] == "install-paid-ist-2030-01-12-manual-synthetic"
        body = json.loads(envelope["body"])
        assert body["to"] == [get_edition("ist").recipient]
        assert not body["subject"].startswith("[Test")

    def test_cli_tags_plain_manual_pt_subject_without_changing_source(self, tmp_path, monkeypatch):
        import ip_send as send
        sources(tmp_path)
        code, calls = run_cli(send, tmp_path, monkeypatch, "--test-tag", "example")
        assert code == 0
        body = json.loads(json.loads(open(calls[0][0]).read())["body"])
        assert body["subject"] == "[Test example] private synthetic subject"
        assert (tmp_path / "subject-A.txt").read_text() == "private synthetic subject\n"

    def test_cli_ignores_force_on_cron(self, tmp_path, monkeypatch):
        import ip_send as send
        sources(tmp_path)
        code, calls = run_cli(send, tmp_path, monkeypatch, "--force-resend", event="schedule")
        assert code == 0
        assert json.loads(open(calls[0][0]).read())["key"] == "install-paid-pt-2030-01-12-scheduled"

    def test_schedule_in_min_flag_is_gone(self, tmp_path, monkeypatch):
        import ip_send as send
        sources(tmp_path)
        monkeypatch.setenv("RESEND_API_KEY", "synthetic")
        with pytest.raises(SystemExit):
            send.main(["--edition", "pt", "--report-date", "2030-01-12", "--event", "workflow_dispatch",
                       "--run-id", "synthetic", "--out", str(tmp_path), "--schedule-in-min", "3"])

    def test_cli_failure_is_generic(self, tmp_path, monkeypatch, capsys):
        import ip_send as send
        sources(tmp_path)

        def refuse(path, api_key):
            raise send.delivery.DeliveryError("Resend delivery failed: HTTP 400 (HTTP error)")

        monkeypatch.setenv("RESEND_API_KEY", "synthetic")
        monkeypatch.setattr(send.delivery, "send_frozen", refuse)
        assert send.main(["--edition", "pt", "--report-date", "2030-01-12", "--event", "schedule",
                          "--run-id", "synthetic", "--out", str(tmp_path)]) == 1
        assert "private" not in capsys.readouterr().err
