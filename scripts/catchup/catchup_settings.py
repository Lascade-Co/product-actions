#!/usr/bin/env python3
"""Run settings and the locked dedupe for the catchup and ad-spend workflows.

  settings  classify the run (real | test | dry) and refuse an unsafe production
            send before any secret job; env EVENT, RECOVERY, TEST_TO, DRY_RUN
  dedupe    real sends only: has "<sent-step><report-date>" already succeeded?

Both are keyed to the 05:00 America/Los_Angeles report-day cutoff. Output goes to
GITHUB_OUTPUT; errors are fixed public-safe strings.
"""
import argparse
import datetime as dt
import os
import sys

import dates
import gate
import workflow

TZ = "America/Los_Angeles"


def settings(env, now, report_date=None):
    event = env.get("EVENT") or env.get("GITHUB_EVENT_NAME") or ""
    if event not in ("schedule", "workflow_dispatch"):
        raise workflow.SettingsError("unsupported event")
    mode = workflow.run_mode(event, env.get("RECOVERY", ""), env.get("TEST_TO", ""), env.get("DRY_RUN", ""))
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
    a = ap.parse_args(argv)
    env = os.environ
    try:
        if a.command == "settings":
            gate.emit(**settings(env, gate.now_utc(), a.report_date))
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
