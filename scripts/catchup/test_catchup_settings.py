import datetime as dt
import json

import pytest

import catchup_settings as cset
import workflow

NOW = dt.datetime(2026, 11, 21, 14, 0, tzinfo=dt.timezone.utc)  # 06:00 PT on the 21st
BASE = {"GITHUB_RUN_ATTEMPT": "1", "RUN_CREATED_AT": "2026-11-21T13:59:00Z", "GITHUB_REF": "refs/heads/main"}


def test_schedule_is_real():
    assert cset.settings({**BASE, "EVENT": "schedule"}, NOW) == {"mode": "real"}


def test_dispatch_without_recovery_fails():
    with pytest.raises(workflow.SettingsError):
        cset.settings({**BASE, "EVENT": "workflow_dispatch"}, NOW)


def test_real_send_requires_main():
    env = {**BASE, "EVENT": "workflow_dispatch", "RECOVERY": "true", "GITHUB_REF": "refs/heads/feat"}
    with pytest.raises(workflow.SettingsError):
        cset.settings(env, NOW)


def test_dry_and_test_modes_need_no_recovery():
    assert cset.settings({**BASE, "EVENT": "workflow_dispatch", "DRY_RUN": "true"}, NOW)["mode"] == "dry"
    assert cset.settings({**BASE, "EVENT": "workflow_dispatch", "TEST_TO": "a@b.c"}, NOW)["mode"] == "test"


def test_rerun_refused():
    with pytest.raises(workflow.SettingsError):
        cset.settings({**BASE, "EVENT": "schedule", "GITHUB_RUN_ATTEMPT": "2"}, NOW)


def test_future_report_day_refused():
    env = {**BASE, "EVENT": "workflow_dispatch", "RECOVERY": "true"}
    with pytest.raises(workflow.SettingsError):
        cset.settings(env, NOW, report_date=dt.date(2026, 11, 23))


def event_file(tmp_path, inputs):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"inputs": inputs}))
    return str(path)


def test_test_recipient_is_read_from_the_event_file(tmp_path):
    env = {**BASE, "EVENT": "workflow_dispatch", "GITHUB_EVENT_PATH": event_file(tmp_path, {"to": "a@b.c"})}
    assert cset.settings(env, NOW)["mode"] == "test"
    env["GITHUB_EVENT_PATH"] = event_file(tmp_path, {"to": ""})
    with pytest.raises(workflow.SettingsError):
        cset.settings(env, NOW)


@pytest.mark.parametrize("raw,want", [("A", ["A"]), ("A,B", ["A", "B"]), (" B ", ["B"]), ("A, B", ["A", "B"])])
def test_valid_variants(raw, want):
    assert cset.parse_variants(raw) == want
    assert cset.settings({**BASE, "EVENT": "schedule"}, NOW, variants=raw) == {"mode": "real"}


@pytest.mark.parametrize("raw", ["", " ", ",", "C", "a", "AB", "A,C", "A;B"])
def test_invalid_variants_fail_settings(raw):
    with pytest.raises(workflow.SettingsError, match="^invalid variants"):
        cset.settings({**BASE, "EVENT": "workflow_dispatch", "DRY_RUN": "true"}, NOW, variants=raw)


def test_cli_rejects_invalid_variants(monkeypatch, tmp_path, capsys):
    for key, value in {**BASE, "EVENT": "workflow_dispatch", "DRY_RUN": "true"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert cset.main(["settings", "--variants", "C"]) == 2
    assert not (tmp_path / "out").exists()
    assert "invalid variants" in capsys.readouterr().err
    assert cset.main(["settings", "--variants", "A,B"]) == 0
    assert (tmp_path / "out").read_text() == "mode=dry\n"
