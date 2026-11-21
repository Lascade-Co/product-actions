#!/usr/bin/env python3
"""Run settings and the locked dedupe for the catchup and ad-spend workflows.

  settings  classify the run (real | test | dry) and refuse an unsafe production
            send before any secret job; env EVENT, RECOVERY, DRY_RUN. The test
            recipient is read from the event file (inputs.to) unless TEST_TO is
            set, so it never appears in a public step header. Ad spend passes
            --variants, which must be a comma-separated subset of A and B.
  dedupe    real sends only: has "<sent-step><report-date>" already succeeded?

Both are keyed to the 05:00 America/Los_Angeles report-day cutoff. Output goes to
GITHUB_OUTPUT; errors are fixed public-safe strings.
"""
import argparse
import datetime as dt
import json
import os
import sys

import dates
import gate
import workflow

TZ = "America/Los_Angeles"
VARIANTS = ("A", "B")


def to_input(env):
    """The `to` input, from TEST_TO when set, else from the workflow_dispatch event file."""
    if "TEST_TO" in env:
        return env["TEST_TO"]
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as source:
            inputs = json.load(source).get("inputs") or {}
    except (OSError, ValueError, AttributeError):
        raise workflow.SettingsError("unreadable event file") from None
    return str(inputs.get("to") or "")


def parse_variants(raw):
    """Same split as adspend_main; every part must be exactly A or B, and at least one is needed."""
    parts = [v.strip() for v in str(raw).split(",") if v.strip()]
    if not parts or any(v not in VARIANTS for v in parts):
        raise workflow.SettingsError("invalid variants: use A, B or A,B")
    return parts


def settings(env, now, report_date=None, variants=None):
    event = env.get("EVENT") or env.get("GITHUB_EVENT_NAME") or ""
    if event not in ("schedule", "workflow_dispatch"):
        raise workflow.SettingsError("unsupported event")
    if variants is not None:
        parse_variants(variants)
    mode = workflow.run_mode(event, env.get("RECOVERY", ""), to_input(env), env.get("DRY_RUN", ""))
    if mode == "real":
        latest = dates.report_date_for(now, TZ)
        workflow.guard_real_run({**env, "EVENT": event}, report_date or latest, latest, now)
    return {"mode": mode}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("settings", "dedupe"))
    ap.add_argument("--report-date", type=dt.date.fromisoformat)
    ap.add_argument("--workflow")
    ap.add_argument("--sent-step")
    ap.add_argument("--variants", help="ad spend only: the variants the email job will build")
    a = ap.parse_args(argv)
    env = os.environ
    try:
        if a.command == "settings":
            gate.emit(**settings(env, gate.now_utc(), a.report_date, a.variants))
        else:
            if not (a.report_date and a.workflow and a.sent_step):
                ap.error("dedupe needs --report-date, --workflow and --sent-step")
            event = env.get("EVENT") or env.get("GITHUB_EVENT_NAME") or ""
            gate.emit(sent=workflow.dedupe(a.workflow, a.sent_step, a.report_date, event))
        return 0
    except workflow.SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except gate.DedupeUnavailable:
        print("delivery history unavailable; refusing to send", file=sys.stderr)
        return 3
    except (ValueError, OSError):
        print("invalid workflow settings", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
