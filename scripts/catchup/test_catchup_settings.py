import datetime as dt

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
