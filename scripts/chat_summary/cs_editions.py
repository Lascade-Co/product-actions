#!/usr/bin/env python3
"""Resolve chat digest matrices, local deadlines and dated delivery checks.

  python3 cs_editions.py settings   # gate job and each email job; masks test recipients
  python3 cs_editions.py dedupe     # email job, after the hold, inside the send lock

Stdlib only (plus scripts/common gate, workflow, dates, editions), so the gate
jobs run without installing anything. Only metadata reaches Actions outputs.

* IST runs on the "9 13,16,19 * * *" cron; PT is dispatched by cron-job.org at
  05:45 America/Los_Angeles with edition=pt and recovery=true (a manual run).
* Manual runs default to the latest report day whose 05:00 cutoff has passed
  (dates.report_date_for); the sheet tab is still today in Asia/Kolkata.
* Real sends pass workflow.guard_real_run (fresh run on main, recovery=true for
  manual runs, no future day, run under 36 h old), so a branch dispatch with
  recovery=true fails here, before any secret job.
* Markers: "Deliver <product> <PT|IST> for <D>" per send, "Delivered <PT|IST> for
  <D>" for the aggregate job; the gate dedupes on the aggregate, the email job
  on its product marker via workflow.dedupe (schedule fails open on unavailable
  history, manual recovery fails closed with exit 3).
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

import dates
import editions
import gate as G
import workflow

WORKFLOW = "chat-summary.yml"
IST_CRON = "9 13,16,19 * * *"
TAB_DEADLINE = (5, 40)


def _products():
    with open(Path(__file__).with_name("products.json"), encoding="utf-8") as source:
        return tuple(json.load(source))


PRODUCTS = _products()


def resolve_daily_schedule(schedule):
    if schedule == IST_CRON:
        return "ist"
    raise ValueError("unknown chat-summary schedule")


def event_inputs(env):
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    with open(path, encoding="utf-8") as stream:
        return json.load(stream).get("inputs") or {}


def _supplied_date(value):
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError("report_date must be YYYY-MM-DD")
    return day


def settings(env=None, now=None):
    env = os.environ if env is None else env
    now = G.now_utc() if now is None else now
    event = env.get("EVENT", "schedule")
    if event not in ("schedule", "workflow_dispatch"):
        raise ValueError("unsupported workflow event")
    inputs = event_inputs(env) if event == "workflow_dispatch" else {}
    name = env.get("EDITION") or (resolve_daily_schedule(env.get("SCHEDULE", "")) if event == "schedule"
                                  else env.get("INPUT_EDITION") or inputs.get("edition") or "both")
    names = ("pt", "ist") if name == "both" else (name,)
    if any(item not in editions.EDITIONS for item in names):
        raise ValueError("unknown edition")
    product = env.get("PRODUCT") or env.get("INPUT_PRODUCT") or inputs.get("product") or "all"
    products = PRODUCTS if product == "all" else (product,)
    if any(item not in PRODUCTS for item in products):
        raise ValueError("unknown product")
    test_to = env.get("TEST_EMAIL_TO") or inputs.get("test_email_to") or ""
    mode = workflow.run_mode(event, env.get("RECOVERY", inputs.get("recovery", "")), test_to,
                             env.get("DRY_RUN", inputs.get("dry_run", "")))
    supplied = env.get("REPORT_DATE") or (env.get("INPUT_DATE") or inputs.get("report_date")
                                          if event != "schedule" else "")
    report_dates = {}
    for item in names:
        zone = editions.get_edition(item).zone
        latest = dates.report_date_for(now, zone)
        if supplied:
            day = _supplied_date(supplied)
        elif event == "schedule":
            day = G.plan(now, zone, (5, 5))[0]
        else:
            day = latest
        if mode == "real":
            workflow.guard_real_run({**env, "EVENT": event}, day, latest, now)
        report_dates[item] = day
    first = editions.get_edition(names[0])
    day = report_dates[first.name]
    return {
        "matrix": json.dumps({"include": [{"product": p, "edition": e, "report_date": str(report_dates[e])}
                                          for e in names for p in products]}, separators=(",", ":")),
        "edition_matrix": json.dumps({"include": [{"edition": e, "label": e.upper(), "report_date": str(report_dates[e])}
                                                  for e in names]}, separators=(",", ":")),
        "edition": first.name,
        "timezone": first.timezone,
        "report_date": str(day),
        "mode": mode,
        "sent_step": f"Delivered {first.label} for ",
        "product_sent_step": workflow.sent_prefix(products[0], first.label),
        "send_step": workflow.step_name(products[0], first.label, day, mode),
        "tab_deadline": first.at(day, *TAB_DEADLINE) if event == "schedule" else "",
    }


def dedupe(env=None, now=None):
    """True when this product/edition/day already has a successful Deliver step (real sends only)."""
    env = os.environ if env is None else env
    resolved = settings(env, now)
    if resolved["mode"] != "real":
        return False
    return workflow.dedupe(WORKFLOW, resolved["product_sent_step"], resolved["report_date"],
                           env.get("EVENT", "schedule"))


def mask_test_recipient(env):
    raw = env.get("TEST_EMAIL_TO") or event_inputs(env).get("test_email_to") or ""
    for value in {raw.strip(), *(item.strip() for item in raw.split(","))}:
        if value:
            escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::add-mask::{escaped}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("settings", "dedupe"))
    args = parser.parse_args(argv)
    try:
        if args.command == "settings":
            mask_test_recipient(os.environ)
            G.emit(**settings())
        else:
            G.emit(sent=str(dedupe()).lower())
        return 0
    except G.DedupeUnavailable:
        print("delivery history unavailable; refusing to send", file=sys.stderr)
        return 3
    except workflow.SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError):
        print("invalid chat-summary workflow settings", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
