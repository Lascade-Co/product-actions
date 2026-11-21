"""Workflow settings and delivery-history checks without public metric logs."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

import dates
import gate as G
import workflow

PT = ZoneInfo("America/Los_Angeles")
TO = "cherian@lascade.com"
LABEL = "hunch retention"
SENT_STEP = workflow.sent_prefix(LABEL, "")


def delivery_mode(event, recovery=False):
    if event not in ("schedule", "workflow_dispatch"):
        raise ValueError("invalid-event")
    return "real" if event == "schedule" or recovery else "test"


def delivery_step(date, mode):
    return workflow.step_name(LABEL, "", date, mode)


def event_to():
    """The workflow_dispatch `to` input, read from the event file so it never reaches a step header."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return ""
    with open(path, encoding="utf-8") as source:
        return str((json.load(source).get("inputs") or {}).get("to") or "")


def mask(to):
    # The default recipient is public; a manual test address is masked for later steps of this job.
    if to != TO:
        print("::add-mask::" + to.replace("%", "%25"))


def settings(notification=False):
    event = os.environ.get("EVENT", "schedule")
    mode = delivery_mode(event, os.environ.get("RECOVERY") == "true")
    supplied = os.environ.get("REPORT_DATE") or (os.environ.get("INPUT_DATE") if event != "schedule" else "")
    date = None
    if supplied:
        try:
            date = dt.date.fromisoformat(supplied)
        except ValueError:
            if not notification:
                raise
    now = G.now_utc()
    latest = dates.report_date_for(now, PT)
    if date is None and event == "schedule":
        date = G.plan(now, tz=PT, target=(5, 5))[0]
    elif date is None:
        date = latest
    to = (event_to() or TO) if not notification else TO
    if (not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", to)
            or (mode != "test" and to != TO)):
        raise ValueError("invalid-recipient")
    return date, mode, to


def emit(**values):
    # File only: public-safe logs name no dates.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("settings", "recipient", "dedupe", "failure-message", "notify"))
    args = parser.parse_args(argv)
    try:
        notification = args.command in ("failure-message", "notify")
        date, mode, to = settings(notification=notification)
        if notification:
            # Public run metadata only; the token and chat id come from the environment.
            message = f"TreasureHunch retention for {date} failed. Run: {os.environ.get('RUN_URL', '')}"
            if args.command == "failure-message":
                print(message)
            else:
                import notify  # needs requests; the gate jobs do not
                try:
                    notify.telegram_send(os.environ["TOKEN"], os.environ["CHAT"], message)
                except (notify.NotifyError, KeyError):
                    print("alert-failed", file=sys.stderr)
                    return 1
                print("alert-sent")
        elif args.command == "recipient":
            # Captured by the send step's shell; never written to GITHUB_OUTPUT.
            print(to)
        elif args.command == "dedupe":
            accepted = mode == "real" and G.already_sent(
                date, G.now_utc(), workflow="daily-hunch-retention.yml", sent_step=SENT_STEP)
            emit(sent=str(accepted))
            print("dedupe-ok")
        else:
            if mode == "real":
                now = G.now_utc()
                workflow.guard_real_run(dict(os.environ), date, dates.report_date_for(now, PT), now)
            mask(to)
            emit(report_date=date, mode=mode, send_step=delivery_step(date, mode))
            print("settings-ok")
        return 0
    except G.DedupeUnavailable:
        if args.command == "dedupe" and os.environ.get("EVENT", "schedule") == "schedule":
            # A scheduled retry retains the same key even if history is unavailable.
            emit(sent="False")
            print("history-unavailable", file=sys.stderr)
            return 0
        print("history-unavailable", file=sys.stderr)
        return 3
    except workflow.SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError):
        print("settings-invalid", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
