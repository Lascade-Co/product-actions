"""Sheet -> translate -> summarise -> email, for one product and edition
(port of chat-summary src/pipeline.js and the key half of src/delivery.js).

The product's Apps Script (apps_script/<product>/extract.gs) fills a date-named
tab with SalesIQ chats. build() translates column C into D, writes summary and
status to E/F and sentiment to the product's sentiment column (G or H), renders
the digest and freezes the Resend envelope. send() posts that envelope once the
workflow's hold and locked dedupe have passed. Columns:

  Travel Animator: A Date | B Subject | C Transcript | D Translated | E Summary | F Tag | G Sentiment
  MarineRadar:     A Date | B Subject | C Transcript | D Translated | E Summary | F Tag | G Message ID | H Sentiment

Customer data stays on the runner's disk; logs carry counts and a subject hash only.

Env: EDITION (pt|ist, default ist), REPORT_DATE (default: latest passed 05:00
cutoff, dates.report_date_for), TAB_NAME (default: today in Asia/Kolkata),
TAB_DEADLINE (UTC ISO with explicit zone), DRY_RUN, TEST_EMAIL_TO, GITHUB_RUN_ID,
MAIL_FROM, MAIL_TO, MAIL_TO_PT, <PRODUCT>_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON,
CLAUDE_API_KEY, RESEND_API_KEY (send).
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

import dates
import delivery
import editions
from cs_errors import DigestError
from cs_render import build_digest_email, subject
from cs_sheets import KOLKATA, SheetsClient, serial_to_wall_clock, tab_name_for, tab_range
from cs_summarize import TAGS, SENTIMENTS, summarize
from cs_translate import CHAT, SUMMARY, TRANSLATED, cell_text, translate_rows

DATE, TAG = 0, 5
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
__all__ = ["KOLKATA", "PRODUCTS", "build", "idempotency_key", "send"]


def load_products(path=Path(__file__).with_name("products.json")):
    with open(path, encoding="utf-8") as source:
        return {slug: {"slug": slug, **config} for slug, config in json.load(source).items()}


PRODUCTS = load_products()


def _valid_key(value):
    return isinstance(value, str) and len(value) > 0 and not re.search(r"[\r\n\x00]", value)


def idempotency_key(sheet_id_env, edition, report_date, test_to="", run_id=None):
    """chat-summary/<SHEET_ID_ENV>/<edition>/<D>, or .../test/.../<D>/<run id> for test sends.

    One key per email: product, edition and report day. The tab is left out so a
    recovery for the same day keeps its key whichever tab it reads. Test sends are
    stable within one run and never consume a production key; a missing run id
    falls back to epoch milliseconds (local runs).
    """
    if (not _valid_key(sheet_id_env) or edition not in ("pt", "ist")
            or not isinstance(report_date, str) or not DATE_PATTERN.fullmatch(report_date)):
        raise DigestError("Invalid idempotency key settings")
    suffix = f"{sheet_id_env}/{edition}/{report_date}"
    if not test_to:
        return f"chat-summary/{suffix}"
    test_run_id = str(int(time.time() * 1000)) if run_id is None else run_id
    if not _valid_key(test_run_id):
        raise DigestError("Test delivery requires a run id")
    return f"chat-summary/test/{suffix}/{test_run_id}"


def _enabled(value):
    return value in ("1", "true")


def _require_env(name, env):
    value = env.get(name)
    if not value:
        raise DigestError(f"Missing env var {name}")
    return value


def _edition(env):
    name = env.get("EDITION") or "ist"
    if name not in ("pt", "ist"):
        raise DigestError("Invalid EDITION")
    return name, editions.get_edition(name).timezone


def _paths(product, edition, output_dir):
    if not isinstance(product.get("slug"), str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", product["slug"]):
        raise DigestError("Invalid product slug")
    directory = Path(output_dir)
    stem = f"{product['slug']}-{edition}"
    return (directory / f"{stem}.html", directory / f"{stem}.subject.txt", directory / f"frozen-{stem}.json")


def _deadline(value):
    if not value:
        return None
    if not isinstance(value, str) or not re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", value):
        raise DigestError("Invalid TAB_DEADLINE")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DigestError("Invalid TAB_DEADLINE") from None


def _wait_for_tab(sheets, sheet_id, tab, deadline, now, sleep, log):
    end = _deadline(deadline)
    attempts = 0
    while True:
        props = next((p for p in sheets.tabs(sheet_id) if p.get("title") == tab), None)
        if props is not None:
            return props
        if end is None or now() >= end:
            raise DigestError("Source tab unavailable at deadline")
        attempts += 1
        log(f"Waiting for source tab; attempts={attempts}")
        sleep(min(60, (end - now()).total_seconds()))


def _saved_items(rows, sentiment_index, base_url):
    items = []
    for index, row in enumerate(rows):
        if not cell_text(row[SUMMARY]):
            continue
        tag, sentiment = cell_text(row[TAG]).lower(), cell_text(row[sentiment_index]).lower()
        if tag not in TAGS or sentiment not in SENTIMENTS:
            raise DigestError("Stored summary is missing a valid status or sentiment")
        cell_ref = f"C{index + 2}"
        items.append({"cell_ref": cell_ref, "row": index + 2, "link": base_url + cell_ref,
                      "summary": cell_text(row[SUMMARY]), "tag": tag, "sentiment": sentiment,
                      "when": serial_to_wall_clock(row[DATE])})
    return items


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(path, 0o600)


def build(product, *, env=None, sheets=None, generate=None, now=None, sleep=None, log=print, output_dir="out"):
    """Build once; return {count, subject_hash, html_path, subject_path, frozen_path (None on dry run)}."""
    env = os.environ if env is None else env
    now = now or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    edition, tz = _edition(env)
    html_path, subject_path, frozen_path = _paths(product, edition, output_dir)
    sheet_id = _require_env(product["sheet_id_env"], env)
    started = now()
    report_date = env.get("REPORT_DATE") or dates.report_date_for(started, tz).isoformat()
    tab = env.get("TAB_NAME") or tab_name_for(started)
    dry_run = _enabled(env.get("DRY_RUN"))
    test_to = (env.get("TEST_EMAIL_TO") or "").strip()
    if env.get("TEST_EMAIL_TO") and not test_to:
        raise DigestError("Invalid test recipient")
    read_only = dry_run or bool(test_to)
    # Validate the date before making any changes to the source sheet.
    subject(f"{product['name']} chats", report_date, tz, "0 chats")
    key = None if dry_run else idempotency_key(product["sheet_id_env"], edition, report_date, test_to,
                                               env.get("GITHUB_RUN_ID"))
    sender = None if dry_run else _require_env("MAIL_FROM", env)
    recipients = [] if dry_run else [value.strip() for value in (
        test_to or _require_env("MAIL_TO_PT" if edition == "pt" else "MAIL_TO", env)).split(",") if value.strip()]
    if not dry_run and not recipients:
        raise DigestError("No recipients configured")
    column = product.get("sentiment_col")
    if column not in ("G", "H"):
        raise DigestError("Invalid sentiment column")
    sentiment_index = ord(column) - 65
    sheets = sheets or SheetsClient.from_env(env)

    props = _wait_for_tab(sheets, sheet_id, tab, env.get("TAB_DEADLINE"), now, sleep, log)
    prefix = tab_range(tab)
    rows = [[row[i] if i < len(row) and row[i] is not None else "" for i in range(8)]
            for row in sheets.read_tab(sheet_id, tab)]

    def write(data):
        if not read_only:
            sheets.batch_write(sheet_id, [(prefix + range_a1, values) for range_a1, values in data])

    translations = translate_rows(rows, generate=generate, log=log)
    if translations.updates:
        write([(cell, [[value]]) for cell, value in translations.updates])
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={props.get('sheetId')}"
    new_items = summarize(rows, product, generate=generate).items
    if new_items:
        data = [(f"{column}1", [["Sentiment"]])]
        for item in new_items:
            data += [(f"E{item['row']}:F{item['row']}", [[item["summary"], item["tag"]]]),
                     (f"{column}{item['row']}", [[item["sentiment"]]])]
        write(data)
        for item in new_items:
            row = rows[item["row"] - 2]
            row[SUMMARY], row[TAG], row[sentiment_index] = item["summary"], item["tag"], item["sentiment"]
    # A bad chat must not block the digest; its summary stays empty for a later retry.
    unprocessed = sum(1 for row in rows
                      if (cell_text(row[CHAT]) or cell_text(row[TRANSLATED])) and not cell_text(row[SUMMARY]))
    items = _saved_items(rows, sentiment_index, sheet_url + "&range=")
    html, text = build_digest_email(items, report_date, sheet_url, product["name"], unprocessed)
    email_subject = subject(f"{product['name']} chats", report_date, tz, f"{len(items)} chats")

    Path(output_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_private(html_path, html)
    _write_private(subject_path, email_subject + "\n")
    if not dry_run:
        delivery.freeze_envelope(str(frozen_path), key, {"from": sender, "to": recipients, "subject": email_subject,
                                                         "html": html, "text": text})
    subject_hash = hashlib.sha256(email_subject.encode("utf-8")).hexdigest()[:8]
    log(f"Built chats={len(items)} summarized={len(new_items)} translated={len(translations.updates)} "
        f"unprocessed={unprocessed} subject_sha256={subject_hash}")
    return {"count": len(items), "subject_hash": subject_hash, "html_path": str(html_path),
            "subject_path": str(subject_path), "frozen_path": None if dry_run else str(frozen_path)}


def send(product, *, env=None, output_dir="out", log=print, session=None, sleep_fn=None):
    """Post the frozen envelope; only HTTP 200 counts (scripts/common/delivery.py)."""
    env = os.environ if env is None else env
    if _enabled(env.get("DRY_RUN")):
        raise DigestError("Sending is disabled in dry-run mode")
    edition, _ = _edition(env)
    _, _, frozen_path = _paths(product, edition, output_dir)
    api_key = _require_env("RESEND_API_KEY", env)
    options = {key: value for key, value in (("session", session), ("sleep_fn", sleep_fn)) if value is not None}
    result = delivery.send_frozen(str(frozen_path), api_key, **options)
    log("Accepted emails=1")
    return result
