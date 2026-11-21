"""Port of gate.test.js onto scripts/common (gate, workflow, dates, hold).

PT has no cron any more (cron-job.org dispatches it with edition=pt and
recovery=true), so the PT cron-plan half of the DST test is dropped; the gate,
dedupe and phase tests now exercise scripts/common/gate.py with chat-summary's
markers.
"""
from datetime import date, datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

import cs_editions as E
import gate as G
import hold
import workflow

NOW = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)


def trusted(now=NOW, **env):
    """A fresh main run created just now, as guard_real_run requires."""
    base = {"GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1",
            "RUN_CREATED_AT": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")}
    base.update(env)
    return base


def test_ist_cron_instants_fit_both_sleeping_jobs_across_dst():
    for day in (date(2026, 3, 7), date(2026, 3, 8), date(2026, 10, 31), date(2026, 11, 1)):
        for hour in (13, 16, 19):
            now = datetime.combine(day - timedelta(days=1), datetime.min.time(), timezone.utc).replace(hour=hour, minute=9)
            report, wait, ok = G.plan(now, "Asia/Kolkata", "05:05")
            assert report == day, (now, report)
            assert ok and 0 <= wait <= 680 * 60, (now, wait, ok)


def test_only_the_ist_cron_resolves():
    assert E.resolve_daily_schedule("9 13,16,19 * * *") == "ist"
    with pytest.raises(ValueError):
        E.resolve_daily_schedule("43 3,6,9 * * *")


@pytest.mark.parametrize("day,send,deadline", [("2026-03-07", "13:55", "13:40"), ("2026-03-08", "12:55", "12:40"),
                                               ("2026-10-31", "12:55", "12:40"), ("2026-11-01", "13:55", "13:40")])
def test_settings_derive_dst_safe_delivery_and_tab_deadlines(day, send, deadline):
    now = datetime.fromisoformat(day + "T06:00:00+00:00")
    pt = E.settings(trusted(now, EVENT="schedule", EDITION="pt", REPORT_DATE=day, PRODUCT="travel-animator"), now=now)
    assert pt["tab_deadline"] == f"{day}T{deadline}:00Z"
    assert hold.target_for(day, pt["timezone"]).astimezone(timezone.utc).isoformat() == f"{day}T{send}:00+00:00"
    ist = E.settings(trusted(now, EVENT="schedule", SCHEDULE="9 13,16,19 * * *", REPORT_DATE=day,
                             PRODUCT="travel-animator"), now=now)
    assert ist["tab_deadline"] == f"{day}T00:10:00Z"
    assert hold.target_for(day, ist["timezone"]).astimezone(timezone.utc).isoformat() == f"{day}T00:25:00+00:00"


def test_manual_both_edition_previews_resolve_individual_dates_without_deadlines():
    settings = E.settings({"EVENT": "workflow_dispatch", "INPUT_EDITION": "both", "DRY_RUN": "true"},
                          now=datetime(2026, 10, 21, 2, tzinfo=timezone.utc))
    matrix = json.loads(settings["matrix"])["include"]
    assert len(matrix) == 4
    assert {(r["edition"], r["report_date"]) for r in matrix} == {("pt", "2026-10-20"), ("ist", "2026-10-21")}
    assert [r["product"] for r in matrix] == ["travel-animator", "marine-radar"] * 2
    assert json.loads(settings["edition_matrix"])["include"] == [
        {"edition": "pt", "label": "PT", "report_date": "2026-10-20"},
        {"edition": "ist", "label": "IST", "report_date": "2026-10-21"}]
    assert settings["tab_deadline"] == ""
    # The manual default is the latest passed 05:00 cutoff (dates.report_date_for):
    # 03:00 PDT on Oct 21 still reports Oct 20 (the JS app said Oct 21).
    early = E.settings({"EVENT": "workflow_dispatch", "INPUT_EDITION": "pt", "DRY_RUN": "true"},
                       now=datetime(2026, 10, 21, 10, tzinfo=timezone.utc))
    assert early["report_date"] == "2026-10-20"
    later = E.settings({"EVENT": "workflow_dispatch", "INPUT_EDITION": "pt", "DRY_RUN": "true"},
                       now=datetime(2026, 10, 21, 12, 45, tzinfo=timezone.utc))
    assert later["report_date"] == "2026-10-21"
    fixed = E.settings({"EVENT": "workflow_dispatch", "INPUT_EDITION": "both", "DRY_RUN": "true",
                        "INPUT_DATE": "2026-11-01"}, now=NOW)
    assert {r["report_date"] for r in json.loads(fixed["matrix"])["include"]} == {"2026-11-01"}
    assert fixed["mode"] == "dry"


def test_manual_production_requires_recovery_and_previews_never_get_deliver_names():
    base = {"EVENT": "workflow_dispatch", "EDITION": "pt", "PRODUCT": "travel-animator", "REPORT_DATE": "2026-11-01"}
    for extra, mode, prefix in [({"DRY_RUN": "true"}, "dry", "Dry run "),
                                ({"TEST_EMAIL_TO": "test@example.invalid"}, "test", "Test send "),
                                ({"RECOVERY": "true", "TEST_EMAIL_TO": "test@example.invalid"}, "test", "Test send "),
                                (trusted(RECOVERY="true"), "real", "Deliver ")]:
        settings = E.settings(dict(base, **extra), now=NOW)
        assert settings["mode"] == mode
        assert settings["send_step"] == prefix + "travel-animator PT for 2026-11-01"
        assert settings["sent_step"] == "Delivered PT for "
        assert settings["product_sent_step"] == "Deliver travel-animator PT for "
    with pytest.raises(workflow.SettingsError, match="recovery=true"):
        E.settings(trusted(**base), now=NOW)


def test_dated_dedupe_works_across_matrix_names_partial_failure_and_attempts():
    repo = "Lascade-Co/product-actions"

    def history(step, conclusion="success", branch="main", attempts=1):
        def fetch(path):
            if "/workflows/" in path:
                return {"total_count": 1, "workflow_runs": [{
                    "id": 23, "event": "workflow_dispatch", "head_branch": branch,
                    "head_repository": {"full_name": repo}, "run_attempt": attempts, "conclusion": "failure"}]}
            return {"total_count": 1, "jobs": [{"name": "email (travel-animator, pt)", "conclusion": "failure",
                                                "steps": [{"name": step, "conclusion": conclusion}]}]}
        return fetch

    day = date(2026, 11, 1)
    prefix = workflow.sent_prefix("travel-animator", "PT")
    assert prefix == "Deliver travel-animator PT for "
    assert G.sent_step_succeeded(day, history(prefix + str(day), attempts=2), repo, "chat-summary.yml", prefix)
    for step, outcome in [("Test send travel-animator PT for 2026-11-01", "success"),
                          ("Dry run travel-animator PT for 2026-11-01", "success"),
                          ("Deliver marine-radar PT for 2026-11-01", "success"),
                          (prefix + "2026-10-31", "success"), (prefix + str(day), "failure")]:
        assert not G.sent_step_succeeded(day, history(step, outcome), repo, "chat-summary.yml", prefix), step
    assert not G.sent_step_succeeded(day, history(prefix + str(day), branch="feature"), repo, "chat-summary.yml", prefix)
    assert not G.sent_step_succeeded(day, history("Delivered PT for 2026-11-01"), repo, "chat-summary.yml", prefix)
    aggregate = "Delivered PT for "
    assert G.sent_step_succeeded(day, history("Delivered PT for 2026-11-01"), repo, "chat-summary.yml", aggregate)


def test_dedupe_fails_closed_when_paginated_history_is_incomplete():
    with pytest.raises(G.DedupeUnavailable):
        G.already_sent(date(2026, 11, 1), NOW, fetch=lambda path: {"total_count": 2, "workflow_runs": []},
                       workflow="chat-summary.yml", sent_step="Deliver travel-animator PT for ",
                       repo="Lascade-Co/product-actions")


@pytest.mark.parametrize("recovery", ["false", "true"])
def test_a_whitespace_test_recipient_cannot_become_a_production_send(recovery):
    with pytest.raises(ValueError):
        E.settings(trusted(EVENT="workflow_dispatch", EDITION="pt", PRODUCT="travel-animator",
                           TEST_EMAIL_TO="   ", RECOVERY=recovery), now=NOW)


def test_production_stays_on_main_and_fresh_runs_while_previews_can_rerun_on_branches():
    base = trusted(EVENT="workflow_dispatch", EDITION="pt", PRODUCT="travel-animator", RECOVERY="true")
    assert E.settings(base, now=NOW)["mode"] == "real"
    for change in ({"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_REF": "refs/tags/main"},
                   {"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_RUN_ATTEMPT": ""},
                   {"RUN_CREATED_AT": (NOW - timedelta(hours=37)).isoformat()}):
        with pytest.raises(workflow.SettingsError):
            E.settings(dict(base, **change), now=NOW)
        assert E.settings(dict(base, **change, DRY_RUN="true"), now=NOW)["mode"] == "dry"
        assert E.settings(dict(base, **change, TEST_EMAIL_TO="test@example.invalid"), now=NOW)["mode"] == "test"


def test_scheduled_production_also_requires_a_fresh_run():
    env = trusted(EVENT="schedule", SCHEDULE="9 13,16,19 * * *", GITHUB_RUN_ATTEMPT="2")
    with pytest.raises(workflow.SettingsError):
        E.settings(env, now=NOW)


def test_manual_recovery_cannot_send_a_future_report_day():
    now = datetime(2026, 10, 21, 15, tzinfo=timezone.utc)
    base = trusted(now, EVENT="workflow_dispatch", EDITION="pt", PRODUCT="travel-animator", RECOVERY="true",
                   REPORT_DATE="2026-11-01")
    with pytest.raises(workflow.SettingsError, match="future"):
        E.settings(base, now=now)
    assert E.settings(dict(base, DRY_RUN="true"), now=now)["mode"] == "dry"
    assert E.settings(dict(base, TEST_EMAIL_TO="test@example.invalid"), now=now)["mode"] == "test"
    assert E.settings(dict(base, REPORT_DATE="2026-10-21"), now=now)["mode"] == "real"
    assert E.settings(dict(base, REPORT_DATE="2026-10-20"), now=now)["mode"] == "real"


def test_manual_phases_skip_sleep_and_phase_two_recomputes_the_target():
    assert G.phase2_wait(date(2026, 11, 1), datetime(2026, 11, 1, 12, 35, tzinfo=timezone.utc),
                         "America/Los_Angeles", "05:05") == 1800
    assert G.phase2_wait(date(2026, 11, 1), datetime(2026, 11, 1, 14, tzinfo=timezone.utc),
                         "America/Los_Angeles", "05:05") == 0
    for phase in ("1", "2"):
        argv = ["--phase", phase, "--event", "workflow_dispatch", "--report-date", "2026-11-01",
                "--tz", "America/Los_Angeles", "--target", "05:05", "--workflow", "chat-summary.yml",
                "--sent-step", "Delivered PT for "]
        with patch.object(G.time, "sleep") as sleep, patch.object(G, "emit"), \
                patch.object(G, "already_sent", side_effect=AssertionError("manual gate must skip dedupe")):
            G.main(argv)
            assert not sleep.called


def test_phase_one_honors_the_report_date_frozen_into_the_matrix():
    argv = ["--phase", "1", "--event", "schedule", "--report-date", "2026-10-21", "--tz", "America/Los_Angeles",
            "--target", "05:05", "--workflow", "chat-summary.yml", "--sent-step", "Delivered PT for "]
    with patch.object(G, "now_utc", return_value=datetime(2026, 10, 21, 23, tzinfo=timezone.utc)), \
            patch.object(G, "already_sent", return_value=False), patch.object(G.time, "sleep") as sleep, \
            patch.object(G, "emit") as emit:
        G.main(argv)
    assert emit.call_args.kwargs["report_date"] == date(2026, 10, 21)
    assert emit.call_args.kwargs["proceed"] == "true"
    sleep.assert_called_once_with(0)


# --- settings/dedupe CLI ---------------------------------------------------------

def test_settings_reject_unknown_editions_products_and_events():
    for env in ({"EVENT": "workflow_dispatch", "INPUT_EDITION": "eu", "DRY_RUN": "true"},
                {"EVENT": "workflow_dispatch", "INPUT_PRODUCT": "other", "DRY_RUN": "true"},
                {"EVENT": "push"}, {"EVENT": "schedule", "SCHEDULE": "43 3,6,9 * * *"},
                {"EVENT": "workflow_dispatch", "DRY_RUN": "true", "INPUT_DATE": "2026-2-1"}):
        with pytest.raises(ValueError):
            E.settings(env, now=NOW)


def test_settings_read_dispatch_inputs_from_the_event_payload(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"edition": "ist", "product": "marine-radar", "dry_run": True,
                                            "test_email_to": ""}}))
    settings = E.settings({"EVENT": "workflow_dispatch", "GITHUB_EVENT_PATH": str(event)}, now=NOW)
    assert settings["mode"] == "dry"
    assert json.loads(settings["matrix"])["include"] == [
        {"product": "marine-radar", "edition": "ist", "report_date": "2026-11-01"}]


def test_settings_mask_test_recipients_from_the_event_payload(tmp_path, monkeypatch, capsys):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"test_email_to": " a@example.test, b@example.test "}}))
    out = tmp_path / "out.txt"
    for key in ("TEST_EMAIL_TO", "DRY_RUN", "RECOVERY", "EDITION", "PRODUCT", "REPORT_DATE", "SCHEDULE",
                "INPUT_EDITION", "INPUT_PRODUCT", "INPUT_DATE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("NOW", NOW.isoformat())
    assert E.main(["settings"]) == 0
    printed = capsys.readouterr().out
    masks = printed.splitlines()[:3]
    assert sorted(masks) == sorted(["::add-mask::a@example.test, b@example.test", "::add-mask::a@example.test",
                                    "::add-mask::b@example.test"])
    assert "mode=test" in out.read_text()
    assert "a@example.test" not in out.read_text()


def test_dedupe_checks_the_product_marker_for_real_sends_only(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(E.workflow, "dedupe", lambda *args: calls.append(args) or True)
    env = trusted(EVENT="workflow_dispatch", EDITION="pt", PRODUCT="marine-radar", RECOVERY="true",
                  REPORT_DATE="2026-11-01")
    assert E.dedupe(env, now=NOW) is True
    assert calls == [("chat-summary.yml", "Deliver marine-radar PT for ", "2026-11-01", "workflow_dispatch")]
    assert E.dedupe(dict(env, DRY_RUN="true"), now=NOW) is False
    assert E.dedupe(dict(env, TEST_EMAIL_TO="t@example.test"), now=NOW) is False
    assert len(calls) == 1


def test_dedupe_cli_exits_3_when_recovery_history_is_unavailable(monkeypatch, tmp_path):
    def unavailable(*args):
        raise G.DedupeUnavailable("delivery history unavailable")

    monkeypatch.setattr(E.workflow, "dedupe", unavailable)
    for key, value in trusted(EVENT="workflow_dispatch", EDITION="pt", PRODUCT="marine-radar", RECOVERY="true",
                              REPORT_DATE="2026-11-01", NOW=NOW.isoformat()).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    assert E.main(["dedupe"]) == 3


def test_settings_cli_reports_a_rejected_dispatch_with_exit_2(monkeypatch, capsys):
    for key in ("TEST_EMAIL_TO", "DRY_RUN", "RECOVERY", "GITHUB_EVENT_PATH", "INPUT_EDITION", "INPUT_PRODUCT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EVENT", "workflow_dispatch")
    monkeypatch.setenv("NOW", NOW.isoformat())
    assert E.main(["settings"]) == 2
    assert capsys.readouterr().err == "manual production sends require recovery=true\n"
