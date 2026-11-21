"""Telegram Bot API transport shared by report notifications.

Every call makes at most 3 attempts with backoff 2**attempt seconds (1, 2),
a 30 s timeout, and counts only HTTP 200 as delivered. Errors name the method
and the last status or exception with the bot token redacted; Telegram's
response text is never included. Rendering (and Telegram's 4096-character
limit) is the caller's job.
"""
from __future__ import annotations

import json
import mimetypes
import time
from typing import Callable, Optional
from urllib.parse import quote

import requests

API = "https://api.telegram.org/bot{token}/{method}"
RETRIES = 3
TIMEOUT = 30


class NotifyError(RuntimeError):
    """A Telegram call failed; the message never contains the bot token."""


def escape(text: str) -> str:
    """Escape the three characters Telegram's HTML parser chokes on.

    Ampersand first, or the escapes themselves get double-escaped. Quotes need
    no handling: this text sits in element content, never in an attribute.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def redact(text: str, token: str) -> str:
    if not token:
        return text
    for form in {token, quote(token, safe="")}:
        text = text.replace(form, "<redacted>")
    return text


def _deliver(token: str, method: str, call: Callable, sleep: Optional[Callable]) -> None:
    """Retry ``call`` and raise ``NotifyError`` if it never returns HTTP 200."""
    sleep = sleep or time.sleep
    last = ""
    for attempt in range(RETRIES):
        try:
            response = call()
            status = getattr(response, "status_code", None)
            if status == 200:
                return
            last = f"status {status if isinstance(status, int) else '?'}"
        except Exception as exc:  # transport errors retry
            last = redact(f"{type(exc).__name__}: {exc}", token)
        if attempt < RETRIES - 1:
            sleep(2 ** attempt)
    raise NotifyError(redact(f"Telegram {method} failed after {RETRIES} attempts: {last}", token)) from None


def _url(token: str, method: str) -> str:
    return API.format(token=token, method=method)


def telegram_send(token: str, chat_id: str, text: str, *, parse_mode: Optional[str] = None,
                  post: Optional[Callable] = None, sleep: Optional[Callable] = None) -> None:
    """sendMessage. Pass parse_mode="HTML" for escaped HTML text."""
    post = post or requests.post
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    url = _url(token, "sendMessage")
    _deliver(token, "sendMessage", lambda: post(url, json=payload, timeout=TIMEOUT), sleep)


def telegram_send_document(token: str, chat_id: str, filename: str, data: bytes, caption: Optional[str] = None,
                           *, post: Optional[Callable] = None, sleep: Optional[Callable] = None) -> None:
    """sendDocument with an in-memory file; the MIME type follows the extension."""
    post = post or requests.post
    form = {"chat_id": chat_id}
    if caption is not None:
        form["caption"] = caption
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    files = {"document": (filename, data, mime)}
    url = _url(token, "sendDocument")
    _deliver(token, "sendDocument", lambda: post(url, data=form, files=files, timeout=TIMEOUT), sleep)


def telegram_send_photo(token: str, chat_id: str, png: bytes, *, filename: str = "photo.png",
                        caption: Optional[str] = None, post: Optional[Callable] = None,
                        sleep: Optional[Callable] = None) -> None:
    """sendPhoto with one PNG."""
    post = post or requests.post
    form = {"chat_id": chat_id}
    if caption is not None:
        form["caption"] = caption
    files = {"photo": (filename, png, "image/png")}
    url = _url(token, "sendPhoto")
    _deliver(token, "sendPhoto", lambda: post(url, data=form, files=files, timeout=TIMEOUT), sleep)


def telegram_send_media_group(token: str, chat_id: str, images: list[tuple[str, bytes]], *,
                              post: Optional[Callable] = None, sleep: Optional[Callable] = None) -> None:
    """Send 2-10 PNGs, given as (filename, bytes), as one Telegram album."""
    if not 2 <= len(images) <= 10:
        raise NotifyError("Telegram sendMediaGroup requires 2-10 images")
    post = post or requests.post
    media = [{"type": "photo", "media": f"attach://photo{index}"} for index in range(len(images))]
    files = {f"photo{index}": (filename, png, "image/png") for index, (filename, png) in enumerate(images)}
    form = {"chat_id": chat_id, "media": json.dumps(media)}
    url = _url(token, "sendMediaGroup")
    _deliver(token, "sendMediaGroup", lambda: post(url, data=form, files=files, timeout=TIMEOUT), sleep)
