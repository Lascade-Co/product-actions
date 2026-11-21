#!/usr/bin/env python3
"""Send one ad-spend variant through the shared frozen-envelope delivery.

  adspend_send.py --variant A|B --ad-date AD [--out-dir out] [--mail-to LIST]

Reads <out-dir>/email-<V>.{html,txt,subject}. MAIL_TO (or --mail-to) is one or
more comma-separated addresses ("Name <address>" works) and defaults to
cherian@lascade.com. The key includes the recipient list, so a resend to a
different address is not mistaken for the original. Only HTTP 200 is accepted.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sys

import delivery

SENDER = "Lascade Ad Spend <noreply@metrics.lascade.com>"
DEFAULT_TO = "cherian@lascade.com"


def key_for(variant, ad_date, mail_to):
    return f"ad-spend-{variant}-{ad_date}-{hashlib.sha1(mail_to.encode('utf-8')).hexdigest()[:8]}"


def recipients(mail_to):
    return [p.strip() for p in mail_to.split(",") if p.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", required=True, choices=("A", "B"))
    ap.add_argument("--ad-date", required=True)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--mail-to", default=None)
    ap.add_argument("--frozen", default=None)
    a = ap.parse_args(argv)
    mail_to = a.mail_to or os.environ.get("MAIL_TO") or DEFAULT_TO
    frozen = a.frozen or f"{a.out_dir}/frozen-ad-spend-{a.variant}.json"
    try:
        read = lambda ext: (Path(a.out_dir) / f"email-{a.variant}.{ext}").read_text(encoding="utf-8")
        payload = {"from": SENDER, "to": recipients(mail_to), "subject": read("subject"),
                   "html": read("html"), "text": read("txt")}
        delivery.freeze_envelope(frozen, key_for(a.variant, a.ad_date, mail_to), payload)
        delivery.send_frozen(frozen, os.environ.get("RESEND_API_KEY", ""))
    except delivery.DeliveryError as exc:
        raise SystemExit(f"variant {a.variant}: {exc}") from None
    except Exception as exc:
        raise SystemExit(f"variant {a.variant}: delivery failed ({type(exc).__name__})") from None
    print(f"variant {a.variant}: sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
