#!/usr/bin/env python3
"""Build the retention email payload and hand it to the shared Resend delivery.

The workflow holds until 05:55 Pacific and runs the delivery check first."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys

import delivery


FROM = "Lascade Games <noreply@metrics.lascade.com>"
TO = "cherian@lascade.com"


def safe_suffix(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(value)):
        raise ValueError("invalid-run-id")
    return str(value)


def manual_test(event, recovery=False):
    if event not in ("schedule", "workflow_dispatch"):
        raise ValueError("invalid-event")
    return event == "workflow_dispatch" and not recovery


def send_key(date, event, run_id, recovery=False):
    suffix = f"-manual-{safe_suffix(run_id)}" if manual_test(event, recovery) else ""
    return f"hunch-retention-{date}{suffix}"


def recipient(event, recovery=False, to=None):
    to = to or TO
    if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", to):
        raise ValueError("invalid-recipient")
    if not manual_test(event, recovery) and to != TO:
        raise ValueError("recipient-override-forbidden")
    return to


def build_payload(out, date, run_id, event, recovery=False, to=None):
    """The Resend body for this run, built from out/email.json."""
    to = recipient(event, recovery, to)
    email = json.loads((Path(out) / "email.json").read_text())
    body = {"from": FROM, "to": [to],
            **{field: email[field] for field in ("subject", "html", "text")}}
    if any(not isinstance(body[field], str) for field in ("subject", "html", "text")):
        raise ValueError("invalid-email")
    if manual_test(event, recovery) and not re.match(r"^\[Test [A-Za-z0-9_-]+\] ", body["subject"]):
        tag = safe_suffix(os.environ.get("HR_TEST_NUMBER") or run_id)
        body["subject"] = f"[Test {tag}] {body['subject']}"
    return body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--event", choices=("schedule", "workflow_dispatch"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--to")
    args = parser.parse_args(argv)
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("resend-key-missing", file=sys.stderr)
        return 2
    try:
        key = send_key(args.report_date, args.event, args.run_id, args.recovery)
        path = args.out / f"frozen-hunch-{args.report_date}-{safe_suffix(args.run_id)}.json"
        if not path.exists():
            body = build_payload(args.out, args.report_date, args.run_id, args.event,
                                 recovery=args.recovery, to=args.to)
            delivery.freeze_envelope(path, key, body)
        delivery.send_frozen(path, api_key)
        print("accepted")
        return 0
    except Exception:
        print("send-failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
