#!/usr/bin/env python3
"""Build one edition's email payload and hand it to the shared Resend delivery.

The workflow holds until 05:55 local and runs the delivery check before this
step; the frozen envelope and Resend key then guard against duplicates. Only
generic outcomes are logged. Acceptance is HTTP 200.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import sys

import delivery
from ip_editions import EDITIONS, get_edition, safe_suffix

FROM = "Lascade Product <noreply@metrics.lascade.com>"


def build_payload(out, edition, test_tag=None):
    """The Resend body for this edition, built from the rendered email files."""
    out = Path(out)
    body = {"from": FROM, "to": [get_edition(edition).recipient],
            "html": (out / "email-A.html").read_text(),
            "text": (out / "email-A.txt").read_text(),
            "subject": (out / "subject-A.txt").read_text().rstrip("\n")}
    if test_tag is not None:
        body["subject"] = f"[Test {safe_suffix(test_tag)}] {body['subject']}"
    return body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=EDITIONS, default="pt")
    parser.add_argument("--report-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--event", choices=("schedule", "workflow_dispatch"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--force-resend", action="store_true")
    parser.add_argument("--test-tag")
    args = parser.parse_args(argv)
    manual = args.event == "workflow_dispatch"
    plain_test = manual and not (args.recovery or args.force_resend)
    if manual and args.edition == "ist" and plain_test:
        print("IST tests must use the build-only dry run", file=sys.stderr)
        return 2
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("Resend API key is missing", file=sys.stderr)
        return 2
    try:
        edition = get_edition(args.edition)
        key = edition.send_key(args.report_date, args.event, args.run_id)
        tag = (args.test_tag or args.run_id) if plain_test else None
        path = args.out / f"frozen-{edition.payload_name(args.report_date, args.run_id)}"
        if not path.exists():
            delivery.freeze_envelope(path, key, build_payload(args.out, args.edition, tag))
        delivery.send_frozen(path, api_key)
        print("accepted")
        return 0
    except Exception:
        # Payloads, query results and API errors may contain private figures.
        print("email send failed; payload and response details withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
