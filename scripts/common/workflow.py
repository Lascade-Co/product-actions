"""Figure-free workflow settings and Resend delivery dedupe.

Generic helpers every report uses:

* run_mode(event, recovery, to, dry_run) -> "real" | "test" | "dry"
* guard_real_run(env, report_date, latest_report_date, now) refuses an unsafe
  production send (rerun, manual run without recovery=true or off main, future
  day on a manual run, run created more than 36 h ago)
* step_name / sent_prefix build the "Deliver <label>[ <PT|IST>] for <D>" markers
* dedupe(workflow, sent_step, report_date, event) with gate semantics

The digest-specific part (WORKFLOWS, data/email_config.json, settings,
digest_args, digest_dedupe and the CLI) runs from a checkout or from a
SHA-pinned download with only the JSON config beside it. The final dedupe
command runs inside the send job's lock, after the hold; the frozen envelope and
Resend idempotency key guard against duplicates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import gate as G


MAX_RUN_AGE = dt.timedelta(hours=36)
PREFIXES = {"dry": "Dry run", "test": "Test send", "real": "Deliver"}

WORKFLOWS = {
    "daily-revenue.yml": (45, 11, ("revenue",)),
    "daily-reviews.yml": (47, 13, ("reviews",)),
    "daily-survey.yml": (49, 15, ("survey_marine", "survey_measure", "survey_geo")),
    "daily-conversion.yml": (51, 17, ("conversion",)),
    "daily-container-credits.yml": (53, 19, ("container_credits",)),
}


class SettingsError(ValueError):
    """A fixed, public-safe explanation for a rejected delivery."""


def truth(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "1")


# --- generic report helpers ----------------------------------------------------

def run_mode(event, recovery, to, dry_run) -> str:
    """Classify a run. Scheduled runs are always real (they have no inputs).

    A dispatch is "dry" when dry_run is set, "test" when a test recipient (or a
    truthy test flag) is given, and otherwise "real", which requires recovery.
    """
    if event == "schedule":
        return "real"
    if truth(dry_run):
        return "dry"
    if isinstance(to, str) and to and not to.strip():
        raise SettingsError("blank test recipient")
    if to:
        return "test"
    if not truth(recovery):
        raise SettingsError("manual production sends require recovery=true")
    return "real"


def _event(env) -> str:
    return env.get("EVENT") or env.get("GITHUB_EVENT_NAME") or ""


def run_created_at(env) -> dt.datetime:
    """Read this run's creation time, never the repository's creation time.

    Sources in order: RUN_CREATED_AT / GITHUB_RUN_CREATED_AT, the event payload's
    workflow_run (only when it is this run), then `gh api .../runs/<id>`.
    """
    try:
        timestamp = env.get("RUN_CREATED_AT") or env.get("GITHUB_RUN_CREATED_AT")
        run_id = env.get("GITHUB_RUN_ID", "")
        if not timestamp and env.get("GITHUB_EVENT_PATH"):
            with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as source:
                metadata = json.load(source).get("workflow_run") or {}
            if run_id and str(metadata.get("id")) == run_id:
                timestamp = metadata.get("created_at")
        if not timestamp:
            repo = env.get("GITHUB_REPOSITORY", "")
            if not repo or not run_id:
                raise ValueError
            metadata = G.gh_json(f"repos/{repo}/actions/runs/{run_id}")
            if str(metadata.get("id")) != run_id:
                raise ValueError
            timestamp = metadata["created_at"]
        created = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if created.utcoffset() is None:
            raise ValueError
        return created.astimezone(dt.timezone.utc)
    except Exception:
        # GitHub errors and event payloads must never reach public logs.
        raise SettingsError("run creation time unavailable") from None


def guard_real_run(env, report_date, latest_report_date, now) -> None:
    """Raise SettingsError unless a production send is safe.

    Env-only checks run first, so an off-main dispatch fails before any lookup.
    The event comes from EVENT (or GITHUB_EVENT_NAME); anything other than
    "schedule" is a manual run. Only manual runs are bound to a completed day:
    a scheduled gate plans the upcoming morning.
    """
    if env.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SettingsError("production delivery requires a fresh run; re-runs are not allowed, "
                            "dispatch recovery instead")
    if _event(env) != "schedule":
        if not truth(env.get("RECOVERY", "")):
            raise SettingsError("manual production sends require recovery=true")
        # History trusts only main. A branch send would be invisible to future
        # dedupe scans even though it used the same event-independent lock.
        if env.get("GITHUB_REF") != "refs/heads/main":
            raise SettingsError("production recovery must run from main")
        # A future report day can put an earlier recovery outside the history
        # scan's date window. Only completed cutoffs are safe for recovery.
        if report_date > latest_report_date:
            raise SettingsError("production recovery cannot target a future report day")
    if now - run_created_at(env) > MAX_RUN_AGE:
        raise SettingsError("run is older than 36 hours; dispatch recovery instead")


def step_name(label, edition_label, report_date, mode) -> str:
    """"Deliver|Test send|Dry run <label>[ <PT|IST>] for <YYYY-MM-DD>"."""
    if mode not in PREFIXES:
        raise ValueError("unknown run mode")
    return f"{PREFIXES[mode]} {_marker(label, edition_label)}{report_date}"


def sent_prefix(label, edition_label) -> str:
    """The real-send marker without its date: what the gate and dedupe match on."""
    return f"{PREFIXES['real']} {_marker(label, edition_label)}"


def _marker(label, edition_label):
    return f"{label} {edition_label} for " if edition_label else f"{label} for "


def dedupe(workflow, sent_step, report_date, event) -> bool:
    """Gate semantics: a manual dispatch skips history; a scheduled run proceeds
    on its shared key when history is unavailable; any other event fails closed.
    """
    if event == "workflow_dispatch":
        return False
    day = dt.date.fromisoformat(report_date) if isinstance(report_date, str) else report_date
    try:
        return G.already_sent(day, G.now_utc(), workflow=workflow, sent_step=sent_step)
    except G.DedupeUnavailable:
        if event != "schedule":
            raise
        print("delivery history unavailable; proceeding on scheduled key", file=sys.stderr)
        return False


# --- digest settings (data/email_config.json) ----------------------------------

def load_config():
    root = Path(__file__).resolve().parents[2]
    path = root / "data/email_config.json"
    if not path.is_file():
        path = Path("email_config.json")
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def resolve_schedule(workflow, schedule):
    pt, ist, _ = WORKFLOWS[workflow]
    if schedule == f"{pt} 3,6,9 * * *":
        return "pt"
    if schedule == f"{ist} 13,16,19 * * *":
        return "ist"
    raise ValueError("unknown daily schedule")


def workflow_for(digest):
    for workflow, (_, _, digests) in WORKFLOWS.items():
        if digest in digests:
            return workflow
    raise ValueError("unknown digest")


def settings(env=None, now=None):
    env = os.environ if env is None else env
    now = G.now_utc() if now is None else now
    config = load_config()
    event = env.get("EVENT", "workflow_dispatch")
    workflow = env.get("WORKFLOW", "")
    if event not in ("schedule", "workflow_dispatch") or workflow not in WORKFLOWS:
        raise ValueError("unsupported workflow or event")
    digest = env.get("DIGEST", "")
    if digest and (digest not in config["digests"] or workflow_for(digest) != workflow):
        raise ValueError("digest does not belong to workflow")
    edition = (resolve_schedule(workflow, env.get("SCHEDULE", ""))
               if event == "schedule" else env.get("INPUT_EDITION") or "both")
    if edition not in ("pt", "ist", "both") or (digest and edition == "both"):
        raise ValueError("invalid edition")
    editions = ["pt", "ist"] if edition == "both" else [edition]
    zone = config["editions"][editions[0]]["tz"]
    mode = run_mode(event, env.get("RECOVERY", ""),
                    env.get("TEST_TO") or env.get("TEST_MODE") == "true",
                    env.get("DRY_RUN") == "true")
    # Gate settings have no DIGEST and resolve every edition once. Reusable
    # send jobs must consume that frozen date, even when they start after 05:00.
    if digest and mode in ("real", "test") and not env.get("REPORT_DATE"):
        raise SettingsError("REPORT_DATE is required for production and test delivery")
    supplied = env.get("REPORT_DATE") or (env.get("INPUT_DATE", "") if event != "schedule" else "")
    supplied_date = None
    if supplied:
        supplied_date = dt.date.fromisoformat(supplied)
        if supplied_date.isoformat() != supplied:
            raise ValueError("report date must be YYYY-MM-DD")
    matrix = []
    for local_edition in editions:
        local_zone = config["editions"][local_edition]["tz"]
        local = now.astimezone(ZoneInfo(local_zone))
        latest_report_date = local.date() - dt.timedelta(days=local.time() < dt.time(5))
        if supplied_date:
            report_date = supplied_date
        elif event == "schedule":
            report_date = G.plan(now, local_zone, (5, 5))[0]
        else:
            report_date = latest_report_date
        if mode == "real":
            guard_real_run({**env, "EVENT": event}, report_date, latest_report_date, now)
        matrix.append({"edition": local_edition, "report_date": report_date.isoformat()})
    date = matrix[0]["report_date"] if len(matrix) == 1 else supplied
    return {
        "edition": edition,
        "editions": json.dumps(matrix, separators=(",", ":")),
        "timezone": zone,
        "report_date": date,
        "sent_step": f"Delivered {edition.upper()} for ",
        "send_step": step_name(digest, edition.upper(), date, mode) if digest else "",
        "mode": mode,
    }


def digest_args(digest, resolved):
    entry = load_config()["digests"][digest]
    if resolved["edition"] not in ("pt", "ist") or not resolved["report_date"]:
        raise ValueError("build requires one edition and report date")
    return ["-m", entry["module"], *entry["extra_args"],
            "--edition", resolved["edition"], "--report-date", resolved["report_date"], "--dry-run"]


def digest_dedupe(resolved, digest):
    """The digest send job's locked check: real sends only, fail closed."""
    if resolved["mode"] != "real":
        return False
    if resolved["edition"] not in ("pt", "ist"):
        raise ValueError("dedupe requires one edition")
    return G.already_sent(
        dt.date.fromisoformat(resolved["report_date"]), G.now_utc(),
        workflow=workflow_for(digest),
        sent_step=sent_prefix(digest, resolved["edition"].upper()),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("settings", "dedupe", "digest-args"))
    args = parser.parse_args(argv)
    try:
        resolved = settings()
        if args.command == "settings":
            G.emit(**resolved)
        elif args.command == "dedupe":
            G.emit(sent=str(digest_dedupe(resolved, os.environ["DIGEST"])))
        else:
            G.emit(argv=json.dumps(digest_args(os.environ["DIGEST"], resolved)))
        return 0
    except G.DedupeUnavailable:
        print("delivery history unavailable; refusing to send", file=sys.stderr)
        return 3
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError):
        print("invalid digest workflow settings; production recovery requires recovery=true on main; "
              "branch runs require dry_run=true or to", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
