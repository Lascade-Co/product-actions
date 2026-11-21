"""Port of pipeline.test.js plus the chat-summary key cases of delivery.test.js.

The remaining delivery.test.js cases (envelope permissions, retries, statuses,
diagnostics) now belong to scripts/common/delivery.py and its test_delivery.py.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

import pytest

from claude_api import ClaudeError
import cs_pipeline
from cs_errors import DigestError
from cs_pipeline import PRODUCTS, build, idempotency_key, send
from cs_translate import TRANSLATION_ERROR
from delivery import DeliveryError

PRODUCT = {"slug": "travel-animator", "name": "Travel Animator", "sheet_id_env": "TRAVEL_ANIMATOR_SHEET_ID",
           "support_contact": "connect@travelanimator.com", "sentiment_col": "G"}
SAVED_ROW = [46315.5, "private subject", "private transcript", "private translation", "Saved customer summary",
             "answered", "positive"]
NOW = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)


class FakeSheets:
    def __init__(self, rows, tabs=None):
        self.rows = rows
        self.tab_list = tabs if tabs is not None else [{"title": "2026-10-22", "sheetId": 123}]
        self.reads, self.writes = [], []

    def tabs(self, sheet_id):
        return self.tab_list() if callable(self.tab_list) else self.tab_list

    def read_tab(self, sheet_id, tab):
        self.reads.append(tab)
        return [list(r) for r in self.rows]

    def batch_write(self, sheet_id, data):
        self.writes.append(list(data))


class Fixture:
    def __init__(self, tmp_path, rows=(SAVED_ROW,), **overrides):
        self.output_dir = tmp_path / "out"
        self.logs = []
        self.env = {"TRAVEL_ANIMATOR_SHEET_ID": "sheet-private", "EDITION": "pt", "REPORT_DATE": "2026-10-21",
                    "DRY_RUN": "true", **overrides}
        self.sheets = FakeSheets(list(rows))
        self.now = NOW
        self.sleeps = []
        self.generate = lambda *_, **__: pytest.fail("must not re-summarize saved rows")

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)

    def build(self, product=PRODUCT):
        return build(product, env=self.env, sheets=self.sheets, generate=self.generate, now=lambda: self.now,
                     sleep=self.sleep, log=self.logs.append, output_dir=self.output_dir)

    def listing(self):
        return sorted(os.listdir(self.output_dir)) if self.output_dir.exists() else []


def frozen(result):
    return json.loads(Path(result["frozen_path"]).read_text(encoding="utf-8"))


def test_pt_preview_reads_saved_summaries_from_current_ist_tab(tmp_path):
    f = Fixture(tmp_path)
    result = f.build()
    assert result["count"] == 1
    assert f.sheets.reads == ["2026-10-22"]
    assert "Saved customer summary" in (f.output_dir / "travel-animator-pt.html").read_text(encoding="utf-8")
    subject = (f.output_dir / "travel-animator-pt.subject.txt").read_text(encoding="utf-8")
    assert subject == "Travel Animator chats · Wed, Oct 21 — 1 chats\n"
    assert f.sheets.writes == []
    assert f.listing() == ["travel-animator-pt.html", "travel-animator-pt.subject.txt"]
    assert result["frozen_path"] is None
    logs = "\n".join(f.logs)
    for secret in ("Saved customer summary", "private transcript", "private subject", subject.strip(),
                   "sheet-private"):
        assert secret not in logs
    assert re.search(r"subject_sha256=[a-f0-9]{8}", logs)


def test_production_combines_saved_and_new_and_freezes_pt_recipients(tmp_path):
    f = Fixture(tmp_path, [SAVED_ROW, [46315.6, "", "new chat", "new chat"]], DRY_RUN="false",
                MAIL_FROM="Chat Digest <digest@example.test>", MAIL_TO="ist@example.test",
                MAIL_TO_PT="pt@example.test, ,second@example.test")
    calls = []

    def generate(prompt, **_):
        calls.append(prompt)
        assert "Saved customer summary" not in prompt
        return {"items": [{"cell": "C3", "real_question": True, "summary": "Fresh summary", "tag": "forwarded",
                           "sentiment": "negative"}]}

    f.generate = generate
    result = f.build()
    assert result["count"] == 2
    assert len(calls) == 1
    assert len(f.sheets.writes) == 1
    assert f.sheets.writes[0] == [("'2026-10-22'!G1", [["Sentiment"]]),
                                  ("'2026-10-22'!E3:F3", [["Fresh summary", "forwarded"]]),
                                  ("'2026-10-22'!G3", [["negative"]])]
    envelope = frozen(result)
    assert envelope["key"] == "chat-summary/TRAVEL_ANIMATOR_SHEET_ID/pt/2026-10-21"
    payload = json.loads(envelope["body"])
    assert list(payload) == ["from", "to", "subject", "html", "text"]
    assert envelope["body"].startswith('{"from":"Chat Digest <digest@example.test>","to":["pt@example.test",')
    assert payload["to"] == ["pt@example.test", "second@example.test"]
    assert payload["subject"] == "Travel Animator chats · Wed, Oct 21 — 2 chats"
    assert "Saved customer summary" in payload["html"] and "Fresh summary" in payload["html"]
    assert "Fresh summary" in payload["text"]
    assert "scheduled_at" not in payload
    assert "pt@example.test" not in "\n".join(f.logs)
    assert (os.stat(result["frozen_path"]).st_mode & 0o777) == 0o600
    assert (os.stat(result["html_path"]).st_mode & 0o777) == 0o600


def test_failed_translation_and_skipped_summaries_do_not_block_and_retry(tmp_path):
    rows = [SAVED_ROW, [46315.6, "", "private translation failure", TRANSLATION_ERROR],
            [46315.7, "", "private skipped chat", "private skipped translation"]]
    for run in range(2):
        f = Fixture(tmp_path / str(run), rows, DRY_RUN="false", MAIL_FROM="digest@example.test",
                    MAIL_TO_PT="pt@example.test")
        attempts = {"translate": 0, "summary": 0}

        def generate(prompt, **_):
            if "TRANSCRIPTS:" in prompt:
                attempts["translate"] += 1
                assert "C3:\nprivate translation failure" in prompt
                raise RuntimeError("private upstream error")
            attempts["summary"] += 1
            assert "C4: private skipped translation" in prompt
            return {"items": []}

        f.generate = generate
        result = f.build()
        assert result["count"] == 1
        assert attempts == {"translate": 1, "summary": 1}
        payload = json.loads(frozen(result)["body"])
        assert "Saved customer summary" in payload["html"]
        for body in (payload["html"], payload["text"]):
            assert "2 chats could not be processed and are not shown." in body
            assert not re.search(r"private translation failure|private skipped chat|private skipped translation", body)
        assert f.sheets.writes[0] == [("'2026-10-22'!D3", [[TRANSLATION_ERROR]])]
        logs = "\n".join(f.logs)
        assert "unprocessed=2" in logs
        assert not re.search(r"Saved customer summary|private|pt@example", logs)


def test_test_send_is_read_only_and_freezes_an_isolated_key(tmp_path):
    f = Fixture(tmp_path, DRY_RUN="0", TEST_EMAIL_TO="tester@example.test", GITHUB_RUN_ID="5678",
                MAIL_FROM="digest@example.test")
    result = f.build()
    envelope = frozen(result)
    assert envelope["key"] == "chat-summary/test/TRAVEL_ANIMATOR_SHEET_ID/pt/2026-10-21/5678"
    assert json.loads(envelope["body"])["to"] == ["tester@example.test"]
    assert f.sheets.writes == []


def test_a_different_source_tab_keeps_the_report_days_production_key(tmp_path):
    env = {"DRY_RUN": "false", "MAIL_FROM": "digest@example.test", "MAIL_TO": "ist@example.test",
           "MAIL_TO_PT": "pt@example.test"}
    keys = []
    for tab in (None, "2026-10-23"):
        f = Fixture(tmp_path / str(tab), **(dict(env, TAB_NAME=tab) if tab else env))
        if tab:
            f.sheets.tab_list = [{"title": tab, "sheetId": 124}]
        keys.append(frozen(f.build())["key"])
    assert keys == ["chat-summary/TRAVEL_ANIMATOR_SHEET_ID/pt/2026-10-21"] * 2


def test_empty_tabs_still_render_a_zero_chat_digest(tmp_path):
    f = Fixture(tmp_path, [])
    result = f.build()
    assert result["count"] == 0
    assert "0 chats" in Path(result["html_path"]).read_text(encoding="utf-8")


def test_missing_tab_polls_once_per_minute_until_it_appears(tmp_path):
    f = Fixture(tmp_path, TAB_NAME="2026-10-21", TAB_DEADLINE="2026-10-21T12:40:00Z")
    f.now = datetime(2026, 10, 21, 12, 5, tzinfo=timezone.utc)
    attempts = []
    f.sheets.tab_list = lambda: attempts.append(1) or (
        [{"title": "2026-10-21", "sheetId": 123}] if len(attempts) == 3 else [])
    f.build()
    assert len(attempts) == 3
    assert f.sleeps == [60, 60]
    assert f.logs[:2] == ["Waiting for source tab; attempts=1", "Waiting for source tab; attempts=2"]


@pytest.mark.parametrize("deadline,sleeps", [("2026-10-21T12:06:30Z", [60, 30]), ("", [])])
def test_missing_tab_fails_at_the_deadline_and_manual_fails_immediately(tmp_path, deadline, sleeps):
    f = Fixture(tmp_path, [], TAB_DEADLINE=deadline)
    f.now = datetime(2026, 10, 21, 12, 5, tzinfo=timezone.utc)
    f.sheets.tab_list = []
    with pytest.raises(DigestError) as caught:
        f.build()
    assert str(caught.value) == "Source tab unavailable at deadline"
    assert f.sleeps == sleeps
    assert f.listing() == []


def test_wait_for_tab_never_sleeps_a_negative_interval():
    # The clock passes the deadline between the deadline check and the sleep calculation.
    end = datetime(2026, 10, 21, 12, 6, tzinfo=timezone.utc)
    clock = iter([end - timedelta(seconds=1), end + timedelta(seconds=5), end + timedelta(seconds=6)])
    sleeps = []

    class Sheets:
        def tabs(self, sheet_id):
            return []

    with pytest.raises(DigestError, match="^Source tab unavailable at deadline$"):
        cs_pipeline._wait_for_tab(Sheets(), "sheet", "tab", "2026-10-21T12:06:00Z", lambda: next(clock),
                                  sleeps.append, lambda message: None)
    assert sleeps and all(seconds >= 0 for seconds in sleeps)


@pytest.mark.parametrize("deadline", ["2026-10-21T12:40:00", "PRIVATE"])
def test_tab_deadline_needs_an_explicit_timezone(tmp_path, deadline):
    f = Fixture(tmp_path, TAB_DEADLINE=deadline)
    f.sheets.tab_list = []
    with pytest.raises(DigestError, match="^Invalid TAB_DEADLINE$"):
        f.build()


def test_marine_radar_reads_sentiment_from_h_not_the_g_message_id(tmp_path):
    f = Fixture(tmp_path, [SAVED_ROW[:6] + ["message-123", "negative"]])
    result = f.build(dict(PRODUCT, sentiment_col="H"))
    assert "Negative · 1 chat" in Path(result["html_path"]).read_text(encoding="utf-8")
    assert result["count"] == 1


def test_whitespace_test_override_fails_before_recipients_or_sheet_data(tmp_path):
    f = Fixture(tmp_path, DRY_RUN="false", TEST_EMAIL_TO="  ", MAIL_FROM="digest@example.test",
                MAIL_TO_PT="production@example.test")
    with pytest.raises(DigestError, match="(?i)test recipient"):
        f.build()
    assert f.sheets.reads == []
    assert f.listing() == []


# --- Review Focus 5 at the build level -------------------------------------------

def test_summarize_claude_error_aborts_build_after_writing_translations(tmp_path):
    f = Fixture(tmp_path, [SAVED_ROW, [46315.6, "", "hola", ""]], DRY_RUN="false",
                MAIL_FROM="digest@example.test", MAIL_TO_PT="pt@example.test")

    def generate(prompt, **_):
        if "TRANSCRIPTS:" in prompt:
            return {"items": [{"cell": "C3", "english": "hello"}]}
        raise ClaudeError("rate-limit")

    f.generate = generate
    with pytest.raises(ClaudeError):
        f.build()
    assert f.sheets.writes == [[("'2026-10-22'!D3", [["hello"]])]]
    assert f.listing() == []


def test_malformed_summary_cells_still_build_the_email(tmp_path):
    rows = [SAVED_ROW] + [[46315.6, "", f"chat {n}", f"chat {n}"] for n in range(3)]
    f = Fixture(tmp_path, rows, DRY_RUN="false", MAIL_FROM="digest@example.test", MAIL_TO_PT="pt@example.test")
    f.generate = lambda *_, **__: {"items": [
        {"cell": "C3", "real_question": True, "summary": "Good", "tag": "answered", "sentiment": "neutral"},
        {"cell": "C4", "real_question": True, "summary": "Bad tag", "tag": "resolved", "sentiment": "neutral"}]}
    result = f.build()
    assert result["count"] == 2
    assert f.sheets.writes[0] == [("'2026-10-22'!G1", [["Sentiment"]]), ("'2026-10-22'!E3:F3", [["Good", "answered"]]),
                                  ("'2026-10-22'!G3", [["neutral"]])]
    payload = json.loads(frozen(result)["body"])
    assert "2 chats could not be processed and are not shown." in payload["text"]
    assert "unprocessed=2" in "\n".join(f.logs)


def test_stored_rows_with_invalid_status_fail_the_build(tmp_path):
    f = Fixture(tmp_path, [SAVED_ROW[:5] + ["resolved", "positive"]])
    with pytest.raises(DigestError, match="^Stored summary is missing a valid status or sentiment$"):
        f.build()


# --- defaults and settings -------------------------------------------------------

@pytest.mark.parametrize("edition,now,expected", [
    ("pt", datetime(2026, 10, 22, 1, tzinfo=timezone.utc), "Wed, Oct 21"),
    ("ist", datetime(2026, 10, 22, 1, tzinfo=timezone.utc), "Thu, Oct 22"),
    ("ist", datetime(2026, 10, 21, 23, tzinfo=timezone.utc), "Wed, Oct 21"),
])
def test_default_report_date_is_the_latest_passed_0500_cutoff(tmp_path, edition, now, expected):
    f = Fixture(tmp_path, EDITION=edition)
    del f.env["REPORT_DATE"]
    f.now = now
    f.sheets.tab_list = [{"title": now.astimezone(cs_pipeline.KOLKATA).date().isoformat(), "sheetId": 1}]
    f.build()
    assert expected in (f.output_dir / f"travel-animator-{edition}.subject.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("overrides,message", [
    ({"EDITION": "both"}, "Invalid EDITION"),
    ({"TRAVEL_ANIMATOR_SHEET_ID": ""}, "Missing env var TRAVEL_ANIMATOR_SHEET_ID"),
    ({"REPORT_DATE": "2026-02-30"}, "Invalid report date"),
    ({"DRY_RUN": "false"}, "Missing env var MAIL_FROM"),
    ({"DRY_RUN": "false", "MAIL_FROM": "a@b.test"}, "Missing env var MAIL_TO_PT"),
    ({"DRY_RUN": "false", "MAIL_FROM": "a@b.test", "MAIL_TO_PT": " , "}, "No recipients configured"),
])
def test_settings_fail_with_fixed_messages_before_reading(tmp_path, overrides, message):
    f = Fixture(tmp_path, **overrides)
    with pytest.raises(DigestError) as caught:
        f.build()
    assert str(caught.value) == message
    assert f.sheets.reads == []


def test_invalid_product_settings_are_rejected(tmp_path):
    for product, message in [(dict(PRODUCT, slug="../x"), "Invalid product slug"),
                             (dict(PRODUCT, sentiment_col="F"), "Invalid sentiment column")]:
        with pytest.raises(DigestError, match=f"^{message}$"):
            Fixture(tmp_path).build(product)


def test_an_existing_envelope_is_never_replaced(tmp_path):
    env = dict(DRY_RUN="false", MAIL_FROM="digest@example.test", MAIL_TO_PT="pt@example.test")
    Fixture(tmp_path, **env).build()
    with pytest.raises(DeliveryError, match="already exists"):
        Fixture(tmp_path, **env).build()


def test_products_match_the_js_configs():
    assert PRODUCTS == {
        "travel-animator": {"slug": "travel-animator", "name": "Travel Animator",
                            "sheet_id_env": "TRAVEL_ANIMATOR_SHEET_ID",
                            "support_contact": "connect@travelanimator.com", "sentiment_col": "G"},
        "marine-radar": {"slug": "marine-radar", "name": "MarineRadar", "sheet_id_env": "MARINE_RADAR_SHEET_ID",
                         "support_contact": "connect@marineradar.com", "sentiment_col": "H"},
    }


# --- send ------------------------------------------------------------------------

class ResendSession:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.posts = []

    def post(self, url, headers, data, timeout):
        self.posts.append({"url": url, "headers": dict(headers), "data": data})
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status

        class Response:
            status_code = status

            @staticmethod
            def json():
                return {}
        return Response()


def test_send_posts_the_frozen_bytes_once_accepted(tmp_path):
    env = dict(DRY_RUN="false", MAIL_FROM="digest@example.test", MAIL_TO_PT="pt@example.test")
    f = Fixture(tmp_path, **env)
    result = f.build()
    session = ResendSession(RuntimeError("private transport"), 200)
    logs = []
    outcome = send(PRODUCT, env=dict(f.env, RESEND_API_KEY="re_test"), output_dir=f.output_dir, log=logs.append,
                   session=session, sleep_fn=lambda _: None)
    assert outcome == {"accepted": True, "status": 200, "attempts": 2}
    envelope = frozen(result)
    assert [p["data"] for p in session.posts] == [envelope["body"]] * 2
    assert {p["headers"]["Idempotency-Key"] for p in session.posts} == {envelope["key"]}
    assert logs == ["Accepted emails=1"]


def test_send_refuses_dry_run_and_needs_the_resend_key(tmp_path):
    with pytest.raises(DigestError, match="^Sending is disabled in dry-run mode$"):
        send(PRODUCT, env={"DRY_RUN": "true", "EDITION": "pt"}, output_dir=tmp_path)
    with pytest.raises(DigestError, match="^Missing env var RESEND_API_KEY$"):
        send(PRODUCT, env={"DRY_RUN": "false", "EDITION": "pt"}, output_dir=tmp_path)


# --- delivery.test.js key cases --------------------------------------------------

def test_production_and_test_keys_are_isolated():
    base = {"sheet_id_env": "TA_SHEET_ID", "edition": "pt", "report_date": "2026-10-21"}
    assert idempotency_key(**base) == "chat-summary/TA_SHEET_ID/pt/2026-10-21"
    assert idempotency_key(**dict(base, edition="ist")) == "chat-summary/TA_SHEET_ID/ist/2026-10-21"
    assert idempotency_key(**dict(base, sheet_id_env="MARINE_SHEET_ID")) == "chat-summary/MARINE_SHEET_ID/pt/2026-10-21"
    assert idempotency_key(**base, test_to="test@example.test", run_id="123") == \
        "chat-summary/test/TA_SHEET_ID/pt/2026-10-21/123"
    assert idempotency_key(**base, test_to="changed@example.test", run_id="123") == \
        "chat-summary/test/TA_SHEET_ID/pt/2026-10-21/123"
    for run_id in ("", 123, "123\n456"):
        with pytest.raises(DigestError, match="(?i)run id"):
            idempotency_key(**base, test_to="test@example.test", run_id=run_id)
    for report_date in (None, "", "2026-10-2", "2026-10-21\n", "Private subject", "２０２６-10-21"):
        with pytest.raises(DigestError, match="(?i)idempotency key"):
            idempotency_key(**dict(base, report_date=report_date))
    for bad in ({"edition": "both"}, {"sheet_id_env": ""}, {"sheet_id_env": "A\nB"}):
        with pytest.raises(DigestError, match="^Invalid idempotency key settings$"):
            idempotency_key(**dict(base, **bad))


def test_key_follows_the_report_day_not_the_tab(tmp_path):
    env = {"DRY_RUN": "false", "MAIL_FROM": "digest@example.test", "MAIL_TO_PT": "pt@example.test"}
    keys = {}
    for report_date, tab in [("2026-10-22", "2026-10-23"), ("2026-10-23", "2026-10-23"), ("2026-10-23", "2026-10-24")]:
        f = Fixture(tmp_path / f"{report_date}-{tab}", **dict(env, REPORT_DATE=report_date, TAB_NAME=tab))
        f.sheets.tab_list = [{"title": tab, "sheetId": 1}]
        keys[(report_date, tab)] = frozen(f.build())["key"]
    assert keys[("2026-10-22", "2026-10-23")] != keys[("2026-10-23", "2026-10-23")]
    assert keys[("2026-10-23", "2026-10-23")] == keys[("2026-10-23", "2026-10-24")]


def test_local_test_sends_freeze_the_epoch_millisecond_fallback_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cs_pipeline.time, "time", lambda: 1792587300.0)
    key = idempotency_key("TA_SHEET_ID", "pt", "2026-10-21", test_to="test@example.test")
    assert key == "chat-summary/test/TA_SHEET_ID/pt/2026-10-21/1792587300000"
    f = Fixture(tmp_path, DRY_RUN="false", MAIL_FROM="digest@example.test", TEST_EMAIL_TO="test@example.test")
    result = f.build()
    key = "chat-summary/test/TRAVEL_ANIMATOR_SHEET_ID/pt/2026-10-21/1792587300000"
    assert frozen(result)["key"] == key
    monkeypatch.setattr(cs_pipeline.time, "time", lambda: 1792587301.0)
    session = ResendSession(RuntimeError("Connection interrupted"), 200)
    send(PRODUCT, env=dict(f.env, RESEND_API_KEY="re_test"), output_dir=f.output_dir, log=lambda _: None,
         session=session, sleep_fn=lambda _: None)
    assert [p["headers"]["Idempotency-Key"] for p in session.posts] == [key, key]
