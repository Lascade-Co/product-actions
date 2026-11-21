"""Telegram transport: retries, HTTP 200 only, and no token in errors."""
import json

import pytest

import notify
from notify import (
    NotifyError,
    escape,
    redact,
    telegram_send,
    telegram_send_document,
    telegram_send_media_group,
    telegram_send_photo,
)

TOKEN = "123:ABC"


class Response:
    def __init__(self, status_code=200, text="secret detail"):
        self.status_code = status_code
        self.text = text


def recorder(*responses):
    calls = []
    queue = list(responses)

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item
    return post, calls


def test_escapes_the_three_html_entities():
    assert escape("<urllib3.HTTPSConnection object> a&b") == "&lt;urllib3.HTTPSConnection object&gt; a&amp;b"
    assert escape("<a>") == "&lt;a&gt;"


def test_redact_removes_plain_and_url_encoded_token():
    message = "failed https://api.telegram.org/bot123:ABC/sendMessage and bot123%3AABC"
    assert "123:ABC" not in redact(message, TOKEN)
    assert "123%3AABC" not in redact(message, TOKEN)
    assert redact("unchanged", "") == "unchanged"


def test_send_posts_json_without_parse_mode_by_default():
    post, calls = recorder(Response())
    telegram_send(TOKEN, "-1", "hello", post=post, sleep=pytest.fail)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert calls[0]["json"] == {"chat_id": "-1", "text": "hello"}
    assert calls[0]["timeout"] == 30


def test_send_passes_parse_mode_when_given():
    post, calls = recorder(Response())
    telegram_send(TOKEN, "-1", "<b>x</b>", parse_mode="HTML", post=post)
    assert calls[0]["json"] == {"chat_id": "-1", "text": "<b>x</b>", "parse_mode": "HTML"}


def test_send_options_are_keyword_only():
    post, _ = recorder(Response())
    with pytest.raises(TypeError):
        telegram_send(TOKEN, "-1", "x", "HTML", post)


def test_raises_after_three_attempts_with_exponential_backoff():
    post, calls = recorder(OSError("connection reset"))
    sleeps = []
    with pytest.raises(NotifyError):
        telegram_send(TOKEN, "-1", "x", post=post, sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_only_http_200_counts_and_response_text_is_never_shown():
    post, calls = recorder(Response(202), Response(500), Response(400))
    with pytest.raises(NotifyError) as caught:
        telegram_send(TOKEN, "-1", "x", post=post, sleep=lambda _: None)
    assert len(calls) == 3
    assert "status 400" in str(caught.value)
    assert "secret detail" not in str(caught.value)


def test_retry_then_success():
    post, calls = recorder(Response(429), Response(200))
    sleeps = []
    telegram_send(TOKEN, "-1", "x", post=post, sleep=sleeps.append)
    assert len(calls) == 2
    assert sleeps == [1]


def test_delivery_error_does_not_leak_the_token():
    post, _ = recorder(OSError("failed at https://api.telegram.org/bot123:ABC/sendMessage"))
    with pytest.raises(NotifyError) as caught:
        telegram_send(TOKEN, "-1", "x", post=post, sleep=lambda _: None)
    assert "123:ABC" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_telegram_send_document_redacts_token():
    post, calls = recorder(OSError("POST https://api.telegram.org/bot123:ABC/sendDocument failed"))
    with pytest.raises(NotifyError) as caught:
        telegram_send_document(TOKEN, "-100", "report.html", b"<html></html>", caption="Report",
                               post=post, sleep=lambda _: None)
    assert "123:ABC" not in str(caught.value)
    assert "sendDocument" in str(caught.value)
    assert len(calls) == 3


def test_send_document_uploads_bytes_with_caption():
    post, calls = recorder(Response())
    telegram_send_document(TOKEN, "-100", "report.html", b"<html></html>", "Ship Accuracy Report", post=post)
    call = calls[0]
    assert call["url"].endswith("/sendDocument")
    assert call["data"] == {"chat_id": "-100", "caption": "Ship Accuracy Report"}
    assert call["files"] == {"document": ("report.html", b"<html></html>", "text/html")}
    assert call["timeout"] == 30


def test_send_document_without_caption_omits_it():
    post, calls = recorder(Response())
    telegram_send_document(TOKEN, "-100", "data.bin", b"\x00", post=post)
    assert calls[0]["data"] == {"chat_id": "-100"}
    assert calls[0]["files"]["document"][2] == "application/octet-stream"


def test_send_photo_uploads_png():
    post, calls = recorder(Response())
    telegram_send_photo(TOKEN, "-1", b"png", filename="marketing-net.png", post=post)
    assert calls[0]["url"].endswith("/sendPhoto")
    assert calls[0]["data"] == {"chat_id": "-1"}
    assert calls[0]["files"] == {"photo": ("marketing-net.png", b"png", "image/png")}


def test_sends_three_photos_as_one_media_group():
    post, calls = recorder(Response())
    telegram_send_media_group(TOKEN, "-1", [("summary.png", b"one"), ("line.png", b"two"), ("bar.png", b"three")],
                              post=post)
    call = calls[0]
    assert call["url"].endswith("/sendMediaGroup")
    media = json.loads(call["data"]["media"])
    assert [item["media"] for item in media] == ["attach://photo0", "attach://photo1", "attach://photo2"]
    assert set(call["files"]) == {"photo0", "photo1", "photo2"}


@pytest.mark.parametrize("count", [1, 11])
def test_media_group_rejects_telegram_invalid_item_count(count):
    with pytest.raises(NotifyError):
        telegram_send_media_group(TOKEN, "-1", [("p.png", b"x")] * count, post=pytest.fail)


def test_default_transport_is_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.requests, "post", lambda url, **kw: calls.append(url) or Response())
    telegram_send(TOKEN, "-1", "x")
    assert calls == ["https://api.telegram.org/bot123:ABC/sendMessage"]
