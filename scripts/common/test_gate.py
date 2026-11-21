"""Timing gate and delivery-history dedupe; no network or clock waits."""
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

import gate as g
import workflow


PT = "America/Los_Angeles"
REPO = "Lascade-Co/product-actions"


def U(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("NOW", raising=False)


# --- plan / target / phase 2 -------------------------------------------------

def check(now, rd, wait_min, ok=True):
    d, w, p = g.plan(U(now), PT, (5, 45))
    assert (str(d), round(w / 60), p) == (rd, wait_min, ok), (now, d, w / 60, p)


def test_plan():
    # PDT (UTC-7): crons 03:17/06:17/09:17 UTC = 20:17/23:17/02:17 local
    check("2026-09-24T03:17:00+00:00", "2026-09-24", 568)   # 20:17 -> 05:45 next = 9h28
    check("2026-09-24T06:17:00+00:00", "2026-09-24", 388)   # 23:17 -> 6h28
    check("2026-09-24T09:17:00+00:00", "2026-09-24", 208)   # 02:17 -> 3h28
    # PST (UTC-8), 2026-01-15
    check("2026-01-15T03:17:00+00:00", "2026-01-15", 628)   # 19:17 Jan14 -> 10h28
    check("2026-01-15T06:17:00+00:00", "2026-01-15", 448)
    check("2026-01-15T09:17:00+00:00", "2026-01-15", 268)
    # midnight rollover
    check("2026-09-24T06:59:00+00:00", "2026-09-24", 346)   # 23:59
    check("2026-09-24T07:01:00+00:00", "2026-09-24", 344)   # 00:01
    # exact / +-1min
    check("2026-09-24T12:45:00+00:00", "2026-09-24", 0)
    check("2026-09-24T12:44:00+00:00", "2026-09-24", 1)
    check("2026-09-24T12:46:00+00:00", "2026-09-24", 0)
    # +8h edge: 15:59 local -> today; 16:01 -> tomorrow (wait ~13h44 > cap -> declines)
    check("2026-09-24T22:59:00+00:00", "2026-09-24", 0)
    check("2026-09-24T23:01:00+00:00", "2026-09-25", 824, False)
    # late arrival 09:00 local proceeds immediately
    check("2026-09-24T16:00:00+00:00", "2026-09-24", 0)
    # DST: spring forward 2026-03-08 (02:00 -> 03:00); target 05:45 PDT = 12:45 UTC
    check("2026-03-08T06:17:00+00:00", "2026-03-08", 388)   # 22:17 PST -> 05:45 PDT
    check("2026-03-08T09:17:00+00:00", "2026-03-08", 208)   # 01:17 PST -> 05:45 PDT: 3h28 real
    # fall back 2026-11-01 (02:00 PDT -> 01:00 PST); target 05:45 PST = 13:45 UTC
    check("2026-11-01T06:17:00+00:00", "2026-11-01", 448)   # 23:17 PDT Oct31 -> 7h28
    check("2026-11-01T09:17:00+00:00", "2026-11-01", 268)   # 01:17 PST (2nd) -> 4h28


def test_plan_dst_spring():
    now = U("2026-03-08T12:00:00+00:00")
    report_date, wait, proceed = g.plan(now, PT, (5, 5))
    target = g.target_for(report_date, PT, (5, 5))
    assert report_date == date(2026, 3, 8)
    assert target == datetime.fromisoformat("2026-03-08T05:05:00-07:00")
    assert target.utcoffset() == timedelta(hours=-7)
    assert (wait, proceed) == (300, True)


def test_plan_dst_fall():
    now = U("2026-11-01T12:00:00+00:00")
    report_date, wait, proceed = g.plan(now, PT, (5, 5))
    target = g.target_for(report_date, PT, (5, 5))
    assert report_date == date(2026, 11, 1)
    assert target == datetime.fromisoformat("2026-11-01T05:05:00-08:00")
    assert target.utcoffset() == timedelta(hours=-8)
    assert (wait, proceed) == (3900, True)


def test_phase2_wait_is_absolute():
    # gate2 queued 60 min after gate finished: it must not sleep the stale `remaining`
    rd = date(2026, 9, 24)
    target = datetime(2026, 9, 24, 5, 45, tzinfo=ZoneInfo(PT)).astimezone(timezone.utc)
    assert g.phase2_wait(rd, target - timedelta(minutes=30), PT, (5, 45)) == 30 * 60
    assert g.phase2_wait(rd, target + timedelta(minutes=60), PT, (5, 45)) == 0
    far = target - timedelta(hours=10)
    assert g.phase2_wait(rd, far, PT, (5, 45)) == g.MAX_SLEEP


def test_second_gate_recomputes_remaining_wait_after_queue_delay():
    now = datetime(2026, 3, 8, 11, 35, tzinfo=timezone.utc)
    assert g.phase2_wait(date(2026, 3, 8), now, PT, "05:05") == 1800


@pytest.mark.parametrize("hour,wait_minutes", [(13, 628), (16, 448), (19, 268)])
def test_ist_crons_wait_until_next_local_report_day(hour, wait_minutes):
    now = U(f"2026-10-20T{hour}:07:00+00:00")
    rd, wait, proceed = g.plan(now, "Asia/Kolkata", "05:05")
    assert (rd, wait, proceed) == (date(2026, 10, 21), wait_minutes * 60, True)
    assert g.target_for(rd, "Asia/Kolkata", "05:05").astimezone(timezone.utc) == U(
        "2026-10-20T23:35:00+00:00")
    assert wait <= g.MAX_WAIT


@pytest.mark.parametrize("report_day,now,target,wait_minutes", [
    ("2026-03-08", "2026-03-08T09:17:00+00:00", "2026-03-08T12:05:00+00:00", 168),
    ("2026-11-01", "2026-11-01T08:17:00+00:00", "2026-11-01T13:05:00+00:00", 288),
])
def test_pt_target_across_dst(report_day, now, target, wait_minutes):
    rd = date.fromisoformat(report_day)
    assert g.target_for(rd, PT, (5, 5)).astimezone(timezone.utc) == U(target)
    assert g.plan(U(now), PT, (5, 5)) == (rd, wait_minutes * 60, True)
    assert g.phase2_wait(rd, U(now), PT, (5, 5)) == wait_minutes * 60
    # A caller with an already-local clock must still get elapsed, not wall-clock, time.
    assert g.plan(U(now).astimezone(ZoneInfo(PT)), PT, (5, 5)) == (rd, wait_minutes * 60, True)


def test_phase2_ist_target_is_absolute_and_clamped():
    rd = date(2026, 10, 21)
    assert g.phase2_wait(rd, U("2026-10-20T23:05:00+00:00"), "Asia/Kolkata", "05:05") == 1800
    assert g.phase2_wait(rd, U("2026-10-20T23:40:00+00:00"), "Asia/Kolkata", "05:05") == 0
    assert g.phase2_wait(rd, U("2026-10-20T13:07:00+00:00"), "Asia/Kolkata", "05:05") == g.MAX_SLEEP


def test_all_digest_crons_fit_gate_cap_and_target_intended_day():
    # PT's UTC cron day is the target local date; IST's is the day before.
    for report_day in (date(2026, 3, 7), date(2026, 3, 8), date(2026, 10, 31), date(2026, 11, 1)):
        for zone, minutes, hours, day_offset in (
            (PT, (45, 47, 49, 51), (3, 6, 9), 0),
            ("Asia/Kolkata", (11, 13, 15, 17), (13, 16, 19), -1),
        ):
            cron_day = report_day + timedelta(days=day_offset)
            for minute in minutes:
                for hour in hours:
                    now = datetime(cron_day.year, cron_day.month, cron_day.day, hour, minute, tzinfo=timezone.utc)
                    actual_date, wait, proceed = g.plan(now, zone, "05:05")
                    assert actual_date == report_day, now
                    assert proceed and 0 < wait <= g.MAX_WAIT, now
                    release = (now + timedelta(seconds=wait)).astimezone(ZoneInfo(zone))
                    assert release.isoformat()[:16] == f"{report_day}T05:05"


# --- delivery-history dedupe ---------------------------------------------------

def _trusted_run(run_id, **changes):
    return dict(id=run_id, event="schedule", head_branch="main", run_attempt=1,
                head_repository={"full_name": REPO}, **changes)


def _sent_job(step="Deliver install paid PT for 2026-10-21", **changes):
    return {"name": "send", "conclusion": "success", "completed_at": "2026-10-21T12:20:00Z",
            "steps": [{"name": step, "conclusion": "success"}], **changes}


def _attempt_fetcher(runs, jobs_by_attempt):
    def f(path):
        if "/jobs" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            attempt = int(path.split("/attempts/")[1].split("/")[0]) if "/attempts/" in path else "latest"
            return {"jobs": jobs_by_attempt.get((run_id, attempt), [])}
        return {"workflow_runs": runs}
    return f


PREFIX = "Deliver install paid PT for "
RD, NOW = date(2026, 10, 21), U("2026-10-21T14:00:00+00:00")


def sent(fetch, prefix=PREFIX, **kwargs):
    return g.already_sent(RD, NOW, workflow="daily-install-paid.yml", sent_step=prefix, fetch=fetch, **kwargs)


def test_already_sent_requires_sent_step():
    def fetch(path):
        raise AssertionError("no history lookup without a marker")
    for empty in ("", None):
        with pytest.raises(ValueError):
            g.already_sent(RD, NOW, workflow="daily-install-paid.yml", sent_step=empty, fetch=fetch)


def test_already_sent_requires_a_repository(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY")
    with pytest.raises(ValueError):
        sent(lambda path: {"workflow_runs": []})


def test_already_sent_uses_explicit_repo_over_environment():
    seen = []

    def fetch(path):
        seen.append(path)
        return {"workflow_runs": []}
    assert not sent(fetch, repo="Lascade-Co/other")
    assert seen[0].startswith("repos/Lascade-Co/other/actions/workflows/daily-install-paid.yml/runs?")


def test_matrix_and_reusable_job_names_match_dated_step():
    for name in ("email (survey_marine)", "send / email (survey_marine)", "anything"):
        fetch = _attempt_fetcher([_trusted_run(2)], {(2, 1): [_sent_job(name=name)]})
        assert sent(fetch)


def test_dated_dedupe_counts_successful_step_despite_job_failure():
    job = dict(_sent_job(), conclusion="failure", completed_at=None)
    assert sent(_attempt_fetcher([_trusted_run(2)], {(2, 1): [job], (2, "latest"): [job]}))


def test_dated_dedupe_checks_earlier_attempt_of_current_run(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "2")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    runs = [dict(_trusted_run(2), run_attempt=3)]
    assert sent(_attempt_fetcher(runs, {(2, 1): [_sent_job()], (2, 2): [], (2, 3): []}))


def test_dated_dedupe_paginates_runs_and_attempt_jobs():
    def fetch(path):
        query = parse_qs(urlsplit(path).query)
        page = int(query.get("page", [1])[0])
        per_page = int(query["per_page"][0])
        if "/jobs" in path:
            assert "/runs/800/attempts/2/jobs" in path or "/runs/800/attempts/1/jobs" in path
            if "/attempts/1/" in path:
                return {"jobs": []}
            jobs = ([{"name": "other", "conclusion": "success"}] * per_page) if page == 1 else [_sent_job()]
            return {"jobs": jobs, "total_count": per_page + 1}
        runs = (([dict(_trusted_run(99), head_branch="untrusted")] * per_page) if page == 1
                else [dict(_trusted_run(800), run_attempt=2)])
        return {"workflow_runs": runs, "total_count": per_page + 1}

    assert sent(fetch)


def test_dated_dedupe_created_window_is_anchored_to_report_date():
    seen = []

    def fetch(path):
        seen.append(path)
        if "/jobs" in path:
            return {"jobs": [_sent_job()]}
        if parse_qs(urlsplit(path).query).get("created") != [">=2026-10-18T00:00:00Z"]:
            return {"workflow_runs": []}
        return {"workflow_runs": [_trusted_run(2)]}

    assert g.already_sent(RD, U("2026-11-21T14:00:00+00:00"), workflow="daily-install-paid.yml",
                          sent_step=PREFIX, fetch=fetch)
    query = parse_qs(urlsplit(seen[0]).query)
    assert query == {"created": [">=2026-10-18T00:00:00Z"], "per_page": ["100"], "page": ["1"]}


@pytest.mark.parametrize("kind", ["runs", "jobs"])
def test_dated_dedupe_rejects_endless_run_or_job_pages_after_five(kind):
    seen = []

    def fetch(path):
        seen.append(path)
        if len(seen) > 7:
            raise RuntimeError("synthetic pagination guard")
        if "/jobs" in path:
            return {"jobs": [{"name": "other", "conclusion": "success"}] * 100}
        if kind == "runs":
            return {"workflow_runs": [dict(_trusted_run(2), event="push")] * 100}
        return {"workflow_runs": [_trusted_run(2)]}

    with pytest.raises(g.DedupeUnavailable):
        sent(fetch)
    assert len(seen) == (5 if kind == "runs" else 6)


@pytest.mark.parametrize("acceptance", [False, True])
def test_dated_dedupe_global_budget_covers_trusted_run_attempts(acceptance):
    seen = []

    def fetch(path):
        seen.append(path)
        if "/jobs" in path:
            if acceptance and "/runs/33/attempts/3/jobs" in path:
                return {"jobs": [_sent_job()]}
            return {"jobs": []}
        return {"workflow_runs": [dict(_trusted_run(i), run_attempt=3) for i in range(1, 51)]}

    if acceptance:
        assert sent(fetch)
    else:
        with pytest.raises(g.DedupeUnavailable):
            sent(fetch)
    assert len(seen) == 100


def test_dated_dedupe_success_on_fifth_job_page_is_within_limits():
    seen = []

    def fetch(path):
        seen.append(path)
        if "/jobs" not in path:
            return {"workflow_runs": [_trusted_run(2)]}
        page = int(parse_qs(urlsplit(path).query)["page"][0])
        if page == 5:
            return {"jobs": [_sent_job()]}
        return {"jobs": [{"name": "other", "conclusion": "success"}] * 100}

    assert sent(fetch)
    assert len(seen) == 6


def test_pagination_rejects_a_short_page_when_total_shows_missing_history():
    with pytest.raises(g.DedupeUnavailable):
        list(g.paginated(lambda _: {"jobs": [], "total_count": 1}, "synthetic/jobs", "jobs"))


def test_pagination_accepts_a_complete_full_fifth_page():
    seen = []

    def fetch(path):
        seen.append(path)
        return {"jobs": [{"name": "other"}] * 100, "total_count": 500}

    assert len(list(g.paginated(fetch, "synthetic/jobs", "jobs"))) == 500
    assert len(seen) == 5


def test_incomplete_history_fails_closed():
    with pytest.raises(g.DedupeUnavailable):
        sent(lambda path: {"total_count": 2, "workflow_runs": []})


@pytest.mark.parametrize("change", [
    {"event": "pull_request"}, {"head_branch": "feature"},
    {"head_repository": {"full_name": "fork/product-actions"}}, {"head_repository": None},
])
def test_dated_dedupe_rejects_untrusted_runs(change):
    run = dict(_trusted_run(2), **change)
    assert not sent(_attempt_fetcher([run], {(2, 1): [_sent_job()], (2, "latest"): [_sent_job()]}))


@pytest.mark.parametrize("prefix,other_step,conclusion", [
    ("Deliver install paid PT for ", "Deliver install paid IST for 2026-10-21", "success"),
    ("Deliver install paid IST for ", "Deliver install paid PT for 2026-10-21", "success"),
    ("Deliver install paid PT for ", "Test send install paid PT for 2026-10-21", "success"),
    ("Deliver install paid PT for ", "Dry run install paid PT for 2026-10-21", "success"),
    ("Deliver install paid PT for ", "Deliver install paid PT for 2026-10-20", "success"),
    ("Deliver install paid PT for ", "Deliver install paid PT for 2026-10-21", "failure"),
    ("Deliver hunch retention for ", "Deliver hunch retention PT for 2026-10-21", "success"),
])
def test_dated_dedupe_isolates_edition_date_mode_and_result(prefix, other_step, conclusion):
    job = dict(_sent_job(other_step), steps=[{"name": other_step, "conclusion": conclusion}])
    assert not sent(_attempt_fetcher([_trusted_run(2)], {(2, 1): [job]}), prefix=prefix)


@pytest.mark.parametrize("label,edition_label", [("install paid", "PT"), ("hunch retention", "")])
def test_step_name_round_trips_through_dedupe(label, edition_label):
    prefix = workflow.sent_prefix(label, edition_label)
    for mode, expected in (("real", True), ("test", False), ("dry", False)):
        step = workflow.step_name(label, edition_label, RD, mode)
        assert sent(_attempt_fetcher([_trusted_run(2)], {(2, 1): [_sent_job(step)]}), prefix=prefix) is expected


@pytest.mark.parametrize("fail_at", ["runs", "jobs"])
def test_dated_dedupe_failure_stops_sending_without_logging_api_body(capsys, fail_at):
    def fetch(path):
        if fail_at == "jobs" and "/jobs" not in path:
            return {"workflow_runs": [_trusted_run(2)]}
        raise RuntimeError("private response body")

    with pytest.raises(RuntimeError) as exc:
        sent(fetch)
    assert type(exc.value) is g.DedupeUnavailable
    assert str(exc.value) == "delivery history unavailable"
    captured = capsys.readouterr()
    trace = "".join(traceback.format_exception(exc.value))
    assert "private response body" not in captured.out + captured.err + trace


# --- CLI ---------------------------------------------------------------------

BASE = ["--workflow", "daily-install-paid.yml", "--sent-step", PREFIX]


def run_cli(monkeypatch, argv, now):
    monkeypatch.setenv("NOW", now)
    monkeypatch.setattr(sys, "argv", ["gate.py", *argv])
    sleeps = []
    monkeypatch.setattr(g.time, "sleep", sleeps.append)
    g.main()
    return sleeps


def test_first_gate_keeps_the_date_frozen_by_settings(monkeypatch, capsys):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: False)
    sleeps = run_cli(monkeypatch, ["--phase", "1", "--event", "schedule", "--report-date", "2026-10-21",
                                   "--tz", PT, "--target", "05:05", *BASE], "2026-10-21T23:00:00+00:00")
    assert sleeps == [0]
    assert "proceed=true\nreport_date=2026-10-21\nremaining=0\n" in capsys.readouterr().out


def test_cli_routes_zone_and_target_and_ignores_remaining(monkeypatch, capsys):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: False)
    sleeps = run_cli(monkeypatch, ["--phase", "2", "--event", "schedule", "--report-date", "2026-10-21",
                                   "--remaining", "999999", "--tz", "Asia/Kolkata", "--target", "05:05", *BASE],
                     "2026-10-20T23:20:00+00:00")
    assert sleeps == [900]
    assert "proceed=true\nreport_date=2026-10-21\n" in capsys.readouterr().out


def test_cli_phase1_uses_ist_report_date_and_sleep_cap(monkeypatch, capsys):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: False)
    sleeps = run_cli(monkeypatch, ["--phase", "1", "--event", "schedule", "--tz", "Asia/Kolkata",
                                   "--target", "05:05", *BASE], "2026-10-20T13:07:00+00:00")
    assert sleeps == [20400]
    assert "proceed=true\nreport_date=2026-10-21\nremaining=17280\n" in capsys.readouterr().out


def test_cli_phase1_declines_waits_beyond_the_cap(monkeypatch, capsys):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: pytest.fail("no dedupe when declining"))
    sleeps = run_cli(monkeypatch, ["--phase", "1", "--event", "schedule", "--tz", PT, "--target", "05:45",
                                   *BASE], "2026-09-24T23:01:00+00:00")
    assert sleeps == []
    assert "proceed=false\nreport_date=2026-09-25\n" in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["1", "2"])
def test_cli_schedule_stops_when_already_sent(monkeypatch, capsys, phase):
    calls = []
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: calls.append(k) or True)
    run_cli(monkeypatch, ["--phase", phase, "--event", "schedule", "--report-date", "2026-10-21",
                          "--tz", PT, "--target", "05:05", *BASE], "2026-10-21T14:00:00+00:00")
    assert "proceed=false" in capsys.readouterr().out
    assert calls and calls[-1]["sent_step"] == PREFIX and calls[-1]["workflow"] == "daily-install-paid.yml"


@pytest.mark.parametrize("phase", ["1", "2"])
def test_cli_manual_skips_dedupe_and_sleep(monkeypatch, capsys, phase):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: pytest.fail("manual runs skip dedupe"))
    sleeps = run_cli(monkeypatch, ["--phase", phase, "--event", "workflow_dispatch", "--report-date", "2026-10-21",
                                   "--tz", PT, "--target", "05:05", *BASE], "2026-10-21T02:00:00+00:00")
    assert sleeps == []
    assert "proceed=true\nreport_date=2026-10-21\n" in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["1", "2"])
def test_cli_schedule_continues_on_shared_key_when_dated_dedupe_is_unavailable(monkeypatch, capsys, phase):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private response body")

    monkeypatch.setattr(g, "sent_step_succeeded", unavailable)
    run_cli(monkeypatch, ["--phase", phase, "--event", "schedule", "--report-date", "2026-10-21",
                          "--tz", PT, "--target", "05:05", *BASE], "2026-10-21T14:00:00+00:00")
    captured = capsys.readouterr()
    assert "proceed=true" in captured.out
    assert captured.err == "delivery history unavailable; proceeding on scheduled key\n"
    assert "private response body" not in captured.out + captured.err


@pytest.mark.parametrize("phase", ["1", "2"])
def test_cli_non_schedule_propagates_dated_dedupe_failure(monkeypatch, capsys, phase):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private response body")

    monkeypatch.setattr(g, "sent_step_succeeded", unavailable)
    with pytest.raises(RuntimeError) as exc:
        run_cli(monkeypatch, ["--phase", phase, "--event", "repository_dispatch", "--report-date", "2026-10-21",
                              "--tz", PT, "--target", "05:05", *BASE], "2026-10-21T14:00:00+00:00")
    assert type(exc.value) is g.DedupeUnavailable
    captured = capsys.readouterr()
    assert "proceed=true" not in captured.out
    assert "private response body" not in captured.out + captured.err


@pytest.mark.parametrize("missing", ["--event", "--tz", "--target", "--workflow", "--sent-step"])
def test_cli_requires_every_routing_argument(monkeypatch, missing):
    values = {"--event": "schedule", "--tz": PT, "--target": "05:05",
              "--workflow": "daily-install-paid.yml", "--sent-step": PREFIX}
    argv = ["--phase", "1"] + [part for key, value in values.items() if key != missing for part in (key, value)]
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, argv, "2026-10-21T12:00:00+00:00")
    assert exc.value.code == 2


@pytest.mark.parametrize("now,tz,expected", [
    ("2026-10-21T02:00:00+00:00", PT, "2026-10-20"),             # 19:00 PT on the 20th
    ("2026-10-21T11:59:59+00:00", PT, "2026-10-20"),             # 04:59:59 PT
    ("2026-10-21T12:00:00+00:00", PT, "2026-10-21"),             # 05:00 PT cutoff
    ("2026-10-20T23:30:00+00:00", "Asia/Kolkata", "2026-10-21"),  # 05:00 IST cutoff
])
@pytest.mark.parametrize("blank", [False, True])
def test_cli_manual_default_is_latest_completed_cutoff(monkeypatch, capsys, now, tz, expected, blank):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: pytest.fail("manual runs skip dedupe"))
    extra = ["--report-date", ""] if blank else []
    sleeps = run_cli(monkeypatch, ["--phase", "1", "--event", "workflow_dispatch", "--tz", tz,
                                   "--target", "05:05", *extra, *BASE], now)
    assert sleeps == []
    assert f"proceed=true\nreport_date={expected}\nremaining=0\n" in capsys.readouterr().out


def test_cli_blank_report_date_means_absent_for_schedule(monkeypatch, capsys):
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: False)
    run_cli(monkeypatch, ["--phase", "1", "--event", "schedule", "--report-date", " ", "--tz", "Asia/Kolkata",
                          "--target", "05:05", *BASE], "2026-10-20T13:07:00+00:00")
    assert "proceed=true\nreport_date=2026-10-21\nremaining=17280\n" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["", "2026-13-01", "21-10-2026"])
def test_cli_phase2_rejects_blank_or_invalid_report_date(monkeypatch, value):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["--phase", "2", "--event", "schedule", "--report-date", value, "--tz", PT,
                              "--target", "05:05", *BASE], "2026-10-21T12:00:00+00:00")
    assert exc.value.code == 2


def test_cli_phase2_requires_report_date(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["--phase", "2", "--event", "schedule", "--tz", PT, "--target", "05:05", *BASE],
                "2026-10-21T12:00:00+00:00")
    assert exc.value.code == 2


def test_cli_rejects_blank_sent_step(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["--phase", "1", "--event", "schedule", "--tz", PT, "--target", "05:05",
                              "--workflow", "daily-install-paid.yml", "--sent-step", ""],
                "2026-10-21T12:00:00+00:00")
    assert exc.value.code == 2


@pytest.mark.parametrize("argument,value", [
    ("--tz", "Unknown/Timezone"), ("--target", "25:05"), ("--target", "05:60"),
    ("--target", "5:05"), ("--target", " 5:05"), ("--target", "aa:bb"),
])
def test_cli_rejects_invalid_timezone_or_target(monkeypatch, argument, value):
    values = {"--event": "schedule", "--tz": PT, "--target": "05:05", argument: value}
    argv = ["--phase", "1", *[part for item in values.items() for part in item], *BASE]
    monkeypatch.setattr(g, "already_sent", lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, argv, "2026-10-21T12:05:00+00:00")
    assert exc.value.code == 2


def test_emit_appends_to_github_output(monkeypatch, tmp_path, capsys):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    g.emit(proceed="true", report_date=date(2026, 10, 21))
    assert out.read_text() == "proceed=true\nreport_date=2026-10-21\n"
    assert capsys.readouterr().out == "proceed=true\nreport_date=2026-10-21\n"


def test_now_override_accepts_z_suffix(monkeypatch):
    monkeypatch.setenv("NOW", "2026-10-21T12:00:00Z")
    assert g.now_utc() == datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
