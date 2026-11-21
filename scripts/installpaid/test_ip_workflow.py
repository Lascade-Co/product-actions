"""Static wiring checks for the install-to-paid and watchdog workflows."""
from pathlib import Path

import pytest
import yaml

import workflow as W

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


DAILY = load("daily-install-paid.yml")
WATCH = load("install-paid-watchdog.yml")


def runs(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


class TestDailyWorkflow:
    def test_every_job_is_sealed_first_and_last(self):
        for workflow in (DAILY, WATCH):
            for job in workflow["jobs"].values():
                assert job["steps"][0]["uses"] == "Lascade-Co/actions/actions/seal@seal-v1"
                assert job["steps"][-1]["uses"] == "Lascade-Co/actions/actions/seal-upload@seal-v1"
                assert job["steps"][-1]["if"] == "always()"

    @pytest.mark.parametrize("name,edition", [("gate", None), ("gate2", None)])
    def test_gates_dedupe_on_the_edition_prefix_from_settings(self, name, edition):
        text = runs(DAILY["jobs"][name])
        assert "scripts/common/gate.py" in text and "--target 05:05" in text
        assert "catchup" not in text

    def test_hold_runs_between_build_and_dedupe_then_deliver(self):
        steps = [step.get("name", "") for step in DAILY["jobs"]["email"]["steps"]]
        build = steps.index("Build the email")
        hold = next(i for i, step in enumerate(DAILY["jobs"]["email"]["steps"]) if "hold.py" in step.get("run", ""))
        dedupe = next(i for i, step in enumerate(DAILY["jobs"]["email"]["steps"]) if step.get("id") == "dedupe")
        send = next(i for i, step in enumerate(DAILY["jobs"]["email"]["steps"]) if "ip_send.py" in step.get("run", ""))
        assert build < hold < dedupe < send
        run = DAILY["jobs"]["email"]["steps"][hold]["run"]
        assert 'python3 scripts/common/hold.py --report-date "$REPORT_DATE" --tz "$ZONE" --target 05:55' in run

    def test_deliver_steps_use_the_new_labels(self):
        steps = DAILY["jobs"]["email"]["steps"]
        send = next(step for step in steps if "ip_send.py" in step.get("run", ""))
        assert send["name"] == "${{ steps.dates.outputs.send_step }}"
        assert W.step_name("install paid", "PT", "2030-01-12", "real") == "Deliver install paid PT for 2030-01-12"

    def test_no_scheduled_at_or_legacy_senders_or_catchup(self):
        text = (ROOT / ".github/workflows/daily-install-paid.yml").read_text()
        for gone in ("scheduled_at", "schedule_in_min", "SCHEDULE_IN_MIN", "send_resend_ip", "catchup",
                     "curl -fsS --max-time", "api.telegram.org"):
            assert gone not in text

    def test_notify_uses_the_shared_telegram_sender(self):
        notify = DAILY["jobs"]["notify"]
        assert "ip_workflow.py notify" in runs(notify)
        assert notify["environment"] == "production"

    def test_secret_jobs_declare_production(self):
        for workflow in (DAILY, WATCH):
            for job in workflow["jobs"].values():
                if "secrets." in str(job):
                    assert job.get("environment") == "production"

    def test_crons_are_unchanged(self):
        assert [item["cron"] for item in DAILY["on"]["schedule"]] == [
            "41 3 * * *", "41 6 * * *", "41 9 * * *", "7 13 * * *", "7 16 * * *", "7 19 * * *"]
        assert [item["cron"] for item in WATCH["on"]["schedule"]] == [
            "30 12,13 * * *", "15 13-19 * * *", "0 0 * * *", "45 0-5 * * *"]


class TestWatchdogWorkflow:
    def test_edition_step_uses_the_shared_gate_emit(self):
        step = next(s for s in WATCH["jobs"]["watch"]["steps"] if s.get("id") == "edition")
        assert "from gate import emit" in step["run"] and "catchup" not in step["run"]

    def test_alert_uses_the_shared_telegram_sender(self):
        text = (ROOT / ".github/workflows/install-paid-watchdog.yml").read_text()
        assert "ip_alert.py" in text and "api.telegram.org" not in text


class TestNotifiers:
    def test_ip_alert_sends_message_and_url_through_notify(self, monkeypatch, capsys):
        import notify
        import ip_alert
        sent = []
        monkeypatch.setattr(notify, "telegram_send", lambda token, chat, text: sent.append((token, chat, text)))
        for key, value in (("TOKEN", "t"), ("CHAT", "c"), ("MESSAGE", "Install to paid PT missed"), ("URL", "https://example.invalid/w")):
            monkeypatch.setenv(key, value)
        assert ip_alert.main() == 0
        assert sent == [("t", "c", "Install to paid PT missed. https://example.invalid/w")]
        assert capsys.readouterr().out == "alert-sent\n"

    def test_ip_alert_failure_is_generic(self, monkeypatch, capsys):
        import notify
        import ip_alert

        def refuse(*args):
            raise notify.NotifyError("Telegram sendMessage failed after 3 attempts: status 500")

        monkeypatch.setattr(notify, "telegram_send", refuse)
        for key in ("TOKEN", "CHAT", "MESSAGE", "URL"):
            monkeypatch.setenv(key, "x")
        assert ip_alert.main() == 1
        assert "alert-failed" in capsys.readouterr().err

    def test_failure_notify_command_uses_notify(self, monkeypatch):
        import notify
        import ip_workflow
        sent = []
        monkeypatch.setattr(notify, "telegram_send", lambda token, chat, text: sent.append((token, chat, text)))
        for key, value in (("EVENT", "workflow_dispatch"), ("INPUT_EDITION", "ist"), ("REPORT_DATE", "2030-01-12"),
                           ("TOKEN", "t"), ("CHAT", "c"), ("RUN_URL", "https://example.invalid/run")):
            monkeypatch.setenv(key, value)
        assert ip_workflow.main(["notify"]) == 0
        (token, chat, text), = sent
        assert (token, chat) == ("t", "c") and "IST edition for 2030-01-12" in text


@pytest.mark.parametrize("edition,prefix", [("pt", "Deliver install paid PT for "), ("ist", "Deliver install paid IST for ")])
def test_dedupe_uses_only_the_selected_editions_marker(monkeypatch, tmp_path, edition, prefix):
    import ip_workflow
    seen = []
    monkeypatch.setattr(ip_workflow.G, "already_sent", lambda date, now, **kw: seen.append(kw) or True)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    for key, value in (("EVENT", "workflow_dispatch"), ("INPUT_EDITION", edition), ("REPORT_DATE", "2030-01-02"),
                       ("RECOVERY", "true")):
        monkeypatch.setenv(key, value)
    assert ip_workflow.main(["dedupe"]) == 0
    assert seen == [{"workflow": "daily-install-paid.yml", "sent_step": prefix}]


def test_real_recovery_from_a_branch_fails_in_settings(monkeypatch, tmp_path):
    import ip_workflow
    for key, value in (("EVENT", "workflow_dispatch"), ("RECOVERY", "true"), ("REPORT_DATE", "2030-01-02"),
                       ("NOW", "2030-01-13T02:00:00+00:00"), ("GITHUB_RUN_ATTEMPT", "1"),
                       ("GITHUB_REF", "refs/heads/feature"), ("RUN_CREATED_AT", "2030-01-13T01:59:00Z"),
                       ("GITHUB_OUTPUT", str(tmp_path / "out"))):
        monkeypatch.setenv(key, value)
    assert ip_workflow.main(["settings"]) == 2
    assert not (tmp_path / "out").exists()
