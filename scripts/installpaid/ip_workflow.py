"""Figure-free workflow settings, dedupe and failure notification text."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import dates
import gate as G
import workflow
from ip_editions import LABEL, get_edition, resolve_daily_schedule


def delivery_mode(event, recovery=False, force=False):
    if event == "schedule":
        return "real"
    return "forced" if force else "real" if recovery else "test"


def delivery_step(edition, date, mode):
    label = get_edition(edition).label
    if mode == "forced":
        return f"Forced send {LABEL} {label} for {date}"
    return workflow.step_name(LABEL, label, date, mode)


def settings(notification=False):
    event = os.environ.get("EVENT", "schedule")
    name = (resolve_daily_schedule(os.environ["SCHEDULE"]) if event == "schedule"
            else os.environ.get("INPUT_EDITION") or "pt")
    edition = get_edition(name)
    mode = delivery_mode(event, os.environ.get("RECOVERY") == "true", os.environ.get("FORCE_RESEND") == "true")
    supplied = os.environ.get("REPORT_DATE") or (os.environ.get("INPUT_DATE") if event != "schedule" else "")
    date = None
    if supplied:
        try:
            date = dt.date.fromisoformat(supplied)
        except ValueError:
            if not notification:
                raise
    now = G.now_utc()
    latest = dates.report_date_for(now, edition.zone)
    if date is None and event == "schedule":
        date = G.plan(now, tz=edition.zone, target=(5, 5))[0]
    elif date is None:
        date = latest
    return edition, date, mode, latest, now


def guard(edition, date, mode, latest, now):
    """A production send (cron, recovery or forced) must come from a fresh run on main."""
    if mode in ("real", "forced"):
        env = dict(os.environ)
        env["EVENT"] = env.get("EVENT", "schedule")
        if mode == "forced":
            env["RECOVERY"] = "true"
        workflow.guard_real_run(env, date, latest, now)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("settings", "dedupe", "failure-message", "notify"))
    args = ap.parse_args(argv)
    try:
        notification = args.command in ("failure-message", "notify")
        edition, date, mode, latest, now = settings(notification=notification)
        if notification:
            message = (f"Install→paid {edition.label} edition for {date} failed. "
                       f"Run workflow → edition={edition.name}, report_date={date}, recovery ✓. "
                       f"Workflow: {os.environ.get('WF_URL', '')} Failed run: {os.environ.get('RUN_URL', '')}")
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
        elif args.command == "dedupe":
            # Only real (scheduled or recovery) sends consult history. An explicit
            # manual forced send skips dedupe entirely, as the plan's override.
            accepted = mode == "real" and G.already_sent(
                date, now, workflow="daily-install-paid.yml", sent_step=edition.sent_step)
            G.emit(sent=str(accepted))
        else:
            guard(edition, date, mode, latest, now)
            if edition.name == "ist" and mode == "test" and os.environ.get("DRY_RUN") != "true":
                raise ValueError("IST tests must be dry runs")
            G.emit(edition=edition.name, timezone=edition.timezone, sent_step=edition.sent_step,
                   report_date=date, mode=mode, send_step=delivery_step(edition.name, date, mode))
        return 0
    except G.DedupeUnavailable:
        if args.command == "dedupe" and os.environ.get("EVENT", "schedule") == "schedule":
            print("delivery history unavailable; proceeding on scheduled key", file=sys.stderr)
            G.emit(sent="False")
            return 0
        print("delivery history unavailable; refusing to send", file=sys.stderr)
        return 3
    except workflow.SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, KeyError):
        print("invalid install-paid workflow settings", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
