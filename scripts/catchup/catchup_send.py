#!/usr/bin/env python3
"""Send the rendered catchup email through the shared frozen-envelope delivery.

  catchup_send.py --report-date D --html email.html --subject email.subject [--to ADDR]

--subject is a file path (the subject is derived from private report text, so
it is never put on a command line); a value that is not a file is used as is.
Real sends use the key daily-report-<D>, so a resend after the switch from the
actions repo dedupes at Resend. A test send (--to) goes to that one address
with a [TEST] subject, a run-id suffix and a key of its own.
"""
import argparse
import os
from pathlib import Path
import sys

import delivery

SENDER = "Lascade Engineering <noreply@metrics.lascade.com>"
RECIPIENTS = ["cherian@lascade.com", "rohit@lascade.com"]


def key_for(report_date, run_id="", attempt=""):
    if run_id:
        return f"daily-report-test-{run_id}-{attempt}"
    return f"daily-report-{report_date}"


def _subject(value):
    path = Path(value)
    return path.read_text(encoding="utf-8") if path.is_file() else value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-date", required=True)
    ap.add_argument("--html", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--to", default="")
    ap.add_argument("--frozen", default="out/frozen-catchup.json")
    a = ap.parse_args(argv)
    try:
        api_key = os.environ.get("RESEND_API_KEY", "")
        subject = _subject(a.subject)
        if a.to:
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            if not run_id:
                raise delivery.DeliveryError("Test delivery requires a run id")
            subject = f"[TEST] {subject} (test run {run_id})"
            key = key_for(a.report_date, run_id, os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
            to = [a.to]
        else:
            key, to = key_for(a.report_date), RECIPIENTS
        payload = {"from": SENDER, "to": to, "subject": subject,
                   "html": Path(a.html).read_text(encoding="utf-8")}
        delivery.freeze_envelope(a.frozen, key, payload)
        delivery.send_frozen(a.frozen, api_key)
    except delivery.DeliveryError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        raise SystemExit(f"Delivery failed ({type(exc).__name__})") from None
    print(f"sent: recipients={len(to)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
