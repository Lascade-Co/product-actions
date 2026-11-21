#!/usr/bin/env python3
"""Timing gate: hold a scheduled report until its local target time.

GitHub's cron scheduler fires late, so a report is scheduled several times the
evening before and each run waits here until the target. Two chained jobs are
used because a single job is capped at 6h.

  phase 1: compute report_date (or take --report-date), dedupe, sleep
           min(wait, MAX_SLEEP), emit remaining
  phase 2: sleep until the absolute target again (recomputed, not `remaining`),
           dedupe again

Delivery is identified only by a successful step named exactly
``<--sent-step><report_date>`` in a trusted run of ``--workflow``. A manual
(workflow_dispatch) run skips both dedupe and sleep, and without --report-date
uses the latest day whose 05:00 local cutoff has passed (dates.report_date_for).
A scheduled run proceeds on its shared Resend key when history is unavailable;
any other event fails. A blank --report-date counts as absent.

Outputs (GITHUB_OUTPUT): proceed, report_date, remaining (seconds; phase 1).
Env NOW (ISO) overrides the clock for tests.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dates

PT = ZoneInfo("America/Los_Angeles")
MAX_SLEEP = 340 * 60           # per-job cap is 6h; leave headroom
MAX_WAIT = 2 * MAX_SLEEP       # two chained sleep jobs
HISTORY_MAX_PAGES = 5
HISTORY_MAX_REQUESTS = 100


class DedupeUnavailable(RuntimeError):
    """Delivery history could not be verified."""


class InvalidSetting(argparse.ArgumentTypeError, ValueError):
    """A rejected CLI or library setting: argparse reports it, callers may catch ValueError."""


def now_utc():
    value = os.environ.get("NOW")
    if not value:
        return datetime.now(timezone.utc)
    now = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def parse_zone(value):
    if isinstance(value, ZoneInfo):
        return value
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise InvalidSetting("timezone must be a valid IANA name") from exc


def parse_target(value):
    """Return (hour, minute) for a strict 24-hour "HH:MM" string."""
    if (not isinstance(value, str) or len(value) != 5 or value[2] != ":"
            or not value[:2].isascii() or not value[3:].isascii()
            or not value[:2].isdigit() or not value[3:].isdigit()):
        raise InvalidSetting("target must be HH:MM in 24-hour time")
    hour, minute = int(value[:2]), int(value[3:])
    if hour > 23 or minute > 59:
        raise InvalidSetting("target must be HH:MM in 24-hour time")
    return hour, minute


def _hm(target):
    return parse_target(target) if isinstance(target, str) else tuple(target)


def target_for(report_date, tz, target):
    """Local wall-clock target on report_date; DST-aware via the zone."""
    return datetime(report_date.year, report_date.month, report_date.day,
                    *_hm(target), tzinfo=parse_zone(tz))


def _seconds_until(report_date, now, tz, target):
    return max(0.0, (target_for(report_date, tz, target).astimezone(timezone.utc)
                     - now.astimezone(timezone.utc)).total_seconds())


def plan(now, tz, target):
    """Return (report_date, wait_seconds, proceed).

    A run before 16:00 local plans for today, otherwise for tomorrow.
    """
    report_date = (now.astimezone(parse_zone(tz)) + timedelta(hours=8)).date()
    wait = _seconds_until(report_date, now, tz, target)
    return report_date, wait, wait <= MAX_WAIT


def phase2_wait(report_date, now, tz, target):
    """Seconds phase 2 should sleep, from the absolute target rather than the
    `remaining` phase 1 computed: gate2 can queue behind gate for an hour."""
    return min(MAX_SLEEP, _seconds_until(report_date, now, tz, target))


def gh_json(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def budgeted_fetch(fetch):
    """Share one request allowance across a scan's run pages and attempt jobs."""
    used = 0

    def bounded(path):
        nonlocal used
        if used >= HISTORY_MAX_REQUESTS:
            raise DedupeUnavailable("delivery history unavailable")
        used += 1
        return fetch(path)

    return bounded


def paginated(fetch, path, key):
    """Yield bounded API pages; incomplete history must never look like no send."""
    separator = "" if path.endswith(("?", "&")) else ("&" if "?" in path else "?")
    received = 0
    for page in range(1, HISTORY_MAX_PAGES + 1):
        result = fetch(f"{path}{separator}per_page=100&page={page}")
        rows = result[key]
        received += len(rows)
        yield from rows
        total = result.get("total_count")
        if total is not None and received >= total:
            return
        if len(rows) < 100:
            if total is not None:
                raise DedupeUnavailable("delivery history unavailable")
            return
    raise DedupeUnavailable("delivery history unavailable")


def trusted_run(run, repo):
    """Only main's cron and maintainer dispatch runs can record a delivery."""
    return (run.get("event") in ("schedule", "workflow_dispatch")
            and run.get("head_branch") == "main"
            and (run.get("head_repository") or {}).get("full_name") == repo)


def sent_step_succeeded(report_date, fetch, repo, workflow, sent_step):
    """A successful delivery step is acceptance, even if another step failed.

    Search runs created since report_date minus three days at midnight UTC, with
    a shared request budget. Earlier attempts of matching runs remain included.
    Workflow settings refuse production reruns and runs over 36h old, keeping
    new delivery markers inside this creation-date search window. Any job name
    matches (matrix and reusable-workflow jobs included).
    """
    fetch = budgeted_fetch(fetch)
    marker = f"{sent_step}{report_date}"
    since = f"{report_date - timedelta(days=3)}T00:00:00Z"
    runs = paginated(fetch, f"repos/{repo}/actions/workflows/{workflow}/runs?created=>={since}", "workflow_runs")
    for run in runs:
        if not trusted_run(run, repo):
            continue
        for attempt in range(1, int(run.get("run_attempt", 1)) + 1):
            path = f"repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs"
            for job in paginated(fetch, path, "jobs"):
                if any(step.get("name") == marker and step.get("conclusion") == "success"
                       for step in job.get("steps") or []):
                    return True
    return False


def already_sent(report_date, now, *, workflow: str, sent_step: str, repo: str | None = None,
                 fetch=gh_json) -> bool:
    """True when a trusted run recorded ``<sent_step><report_date>`` as successful.

    ``now`` is accepted for call-site symmetry; the search window is anchored to
    report_date. Raises ValueError for a missing marker, workflow or repository
    (configuration errors are never treated as "not sent") and
    DedupeUnavailable when history cannot be read completely.
    """
    if not isinstance(sent_step, str) or not sent_step.strip():
        raise ValueError("a dated delivery-step prefix is required")
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValueError("a workflow file name is required")
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise ValueError("a repository is required (GITHUB_REPOSITORY)")
    try:
        return sent_step_succeeded(report_date, fetch, repo, workflow, sent_step)
    except Exception:
        raise DedupeUnavailable("delivery history unavailable") from None


def emit(**kv):
    line = "".join(f"{k}={v}\n" for k, v in kv.items())
    print(line, end="")
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            f.write(line)


def _nonblank(value):
    if not value.strip():
        raise InvalidSetting("must not be blank")
    return value


def _optional_date(value):
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidSetting("report date must be YYYY-MM-DD") from None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", type=int, choices=[1, 2], required=True)
    ap.add_argument("--event", type=_nonblank, required=True)
    ap.add_argument("--tz", type=parse_zone, required=True, help="IANA timezone")
    ap.add_argument("--target", type=parse_target, required=True, help="local HH:MM target")
    ap.add_argument("--workflow", type=_nonblank, required=True)
    ap.add_argument("--sent-step", type=_nonblank, required=True,
                    help="dedupe on a successful step named <sent-step><report_date>")
    ap.add_argument("--report-date", type=_optional_date)
    ap.add_argument("--remaining", type=float, default=0)  # unused; phase 2 recomputes
    a = ap.parse_args(argv)
    if a.phase == 2 and a.report_date is None:
        ap.error("--report-date is required for phase 2")
    manual = a.event == "workflow_dispatch"
    now = now_utc()

    def delivered(report_date, checked_at):
        try:
            return already_sent(report_date, checked_at, workflow=a.workflow, sent_step=a.sent_step)
        except DedupeUnavailable:
            if a.event != "schedule":
                raise
            print("delivery history unavailable; proceeding on scheduled key", file=sys.stderr)
            return False

    if a.phase == 1:
        if manual:
            report_date = a.report_date or dates.report_date_for(now, a.tz)
            return emit(proceed="true", report_date=report_date, remaining=0)
        if a.report_date:
            report_date = a.report_date
            wait = _seconds_until(report_date, now, a.tz, a.target)
            ok = wait <= MAX_WAIT
        else:
            report_date, wait, ok = plan(now, a.tz, a.target)
        if not ok:
            print(f"wait {wait/60:.0f}m exceeds cap; a later cron handles it")
            return emit(proceed="false", report_date=report_date, remaining=0)
        if delivered(report_date, now):
            print("already sent for", report_date)
            return emit(proceed="false", report_date=report_date, remaining=0)
        nap = min(wait, MAX_SLEEP)
        print(f"report_date={report_date} wait={wait/60:.0f}m sleeping {nap/60:.0f}m")
        time.sleep(nap)
        return emit(proceed="true", report_date=report_date, remaining=int(wait - nap))

    report_date = a.report_date
    if manual:
        return emit(proceed="true", report_date=report_date)
    time.sleep(phase2_wait(report_date, now_utc(), a.tz, a.target))
    if delivered(report_date, now_utc()):
        print("already sent for", report_date)
        return emit(proceed="false", report_date=report_date)
    emit(proceed="true", report_date=report_date)


if __name__ == "__main__":
    main()
