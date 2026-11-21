"""Digest email and subject (port of chat-summary src/email.js and src/subject.js).

render(args) -> (subject, html, text) is byte-identical to the JS app; the golden
fixture fixtures/email-golden.json pins it. Quirks kept on purpose:

* the subject tail is always "<n> chats" (pipeline passes it; even "1 chats")
* the "Since" line uses en-GB short months, so September is "Sept"
* the subject date uses en-US short months via dates.subject ("Sep")
* sheet timestamps are wall-clock: naive datetimes, never converted

Items are dicts with row, link, summary, tag, sentiment and when (a naive
datetime, an ISO string, or None).
"""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

import dates
from cs_errors import DigestError
from cs_shell import (GREEN, INK, MUTED, RED, badge, button, callout, cell, document, esc, footer, h2, masthead,
                      section_close, section_open, small, stat_grid, table)

SENTIMENT_SECTIONS = [
    ("negative", "Negative", "Frustrated, complaints, bugs"),
    ("neutral", "Neutral", "Plain questions & requests"),
    ("positive", "Positive", "Happy, thankful, excited"),
]
TAG_STYLE = {
    "unanswered": {"label": "Unanswered", "variant": "critical"},
    "forwarded": {"label": "Forwarded", "variant": "warning"},
    "answered": {"label": "Answered", "variant": "positive"},
    "abandoned": {"label": "Abandoned", "variant": "muted"},
}
TAG_ORDER = {"unanswered": 0, "forwarded": 1, "answered": 2, "abandoned": 3}
# en-GB short months as Node/ICU prints them; September is "Sept".
GB_SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]
# JavaScript's \s and trim() whitespace, for collapsing and trimming exactly as the JS app did.
JS_SPACE_CHARS = "\t\n\v\f\r " + "".join(map(chr, (0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F,
                                                    0x205F, 0x3000, 0xFEFF)))
JS_SPACE = re.escape(JS_SPACE_CHARS)
# Word boundaries avoid matching unrelated words such as "recharge". ASCII mode
# keeps \b and case folding as JavaScript's non-unicode /i regex has them.
ATTENTION_TERMS = re.compile(
    r"\b(?:refund(?:s|ed|ing)?|cancel(?:s|led|ed|ling|ing|lations?)?|charge(?:s|d|backs?)?|charging"
    rf"|scam(?:s|med|ming)?|legal|data[{JS_SPACE}-]+loss|safety)\b", re.IGNORECASE | re.ASCII)
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def js_trim(value):
    return value.strip(JS_SPACE_CHARS)


def parse_date(value):
    """A YYYY-MM-DD calendar day, or DigestError("Invalid report date")."""
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise DigestError("Invalid report date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DigestError("Invalid report date") from None


def parse_when(value):
    """A wall-clock datetime from a naive datetime or an ISO string; anything else is None."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def subject(name, report_date, tz, tail):
    """`<name> · <Ddd, Mon D> — <tail>` for a calendar report day, or an instant shown in tz."""
    if isinstance(report_date, datetime):
        if report_date.tzinfo is None:
            raise DigestError("Invalid report date")
        day = report_date.astimezone(ZoneInfo(tz)).date()
    else:
        day = parse_date(report_date)
    return dates.subject(name, day, tail)


def format_time(when):
    """en-US "h:mm AM" with an ASCII space, from the sheet's wall clock."""
    hour = when.hour % 12 or 12
    return f"{hour}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _needs_attention(item):
    return ((item["sentiment"] == "negative" and item["tag"] in ("unanswered", "forwarded"))
            or bool(ATTENTION_TERMS.search(item["summary"])))


def _attention_summary(summary):
    characters = js_trim(re.sub(f"[{JS_SPACE}]+", " ", summary))
    limit = 90
    if len(characters) <= limit:
        return characters
    excerpt = characters[:limit - 1]
    boundary = excerpt.rfind(" ")
    # Keep whole words when possible; Python strings are code points, so an
    # overlong token is bounded without splitting a surrogate pair.
    trimmed = excerpt if characters[limit - 1] == " " or boundary < 0 else excerpt[:boundary]
    return trimmed.rstrip(JS_SPACE_CHARS) + "\u2026"


def _status(item):
    return TAG_STYLE.get(item["tag"], TAG_STYLE["unanswered"])


def build_digest_email(items, report_date, sheet_url, product_name, unprocessed_count=0):
    """Return (html, text) for one product's digest."""
    abandoned = sorted((item for item in items if item["tag"] == "abandoned"), key=lambda item: item["row"])
    groups = {"negative": [], "neutral": [], "positive": []}
    for item in items:
        if item["tag"] != "abandoned":
            groups.get(item["sentiment"], groups["neutral"]).append(item)
    for entries in groups.values():
        entries.sort(key=lambda item: (TAG_ORDER.get(item["tag"], 0), item["row"]))
    stats = [
        (len(groups["negative"]), "Negative", RED),
        (len(groups["neutral"]), "Neutral", INK),
        (len(groups["positive"]), "Positive", GREEN),
        (len(abandoned), "Abandoned", MUTED),
    ]
    attention = sorted((item for item in items if _needs_attention(item)), key=lambda item: item["row"])
    attention_lines = [_attention_summary(item["summary"]) for item in attention[:5]]
    if len(attention) > 5:
        attention_lines.append(f"+{len(attention) - 5} more")

    long_date = dates.long_date(parse_date(report_date))
    times = sorted(when for when in (parse_when(item.get("when")) for item in items) if when is not None)
    since = (f"Since {times[0].day} {GB_SHORT_MONTHS[times[0].month - 1]} {format_time(times[0])}"
             if times else "")
    count = plural(len(items), "chat")
    unprocessed_note = (f"{plural(unprocessed_count, 'chat')} could not be processed and "
                        f"{'is' if unprocessed_count == 1 else 'are'} not shown." if unprocessed_count > 0 else "")

    def chat_table(entries):
        rows = []
        for item in entries:
            status = _status(item)
            rows.append([
                {"html": f'<a href="{esc(item["link"])}" style="color:{INK}; text-decoration:none;" '
                         f'class="email-link">{esc(item["summary"])}</a>'},
                {"html": f'<span style="white-space:nowrap;">{badge(status["label"], status["variant"])}</span>'},
            ])
        return table(["Summary", "Status"], rows, None, True, ["100%", "128"])

    sections = cell(stat_grid(stats))
    if attention_lines:
        sections += cell(callout("critical", "Needs your attention", attention_lines))
    for key, title, note in SENTIMENT_SECTIONS:
        entries = groups[key]
        if not entries:
            continue
        sections += (cell(h2(f"{title} · {plural(len(entries), 'chat')}"), "32px 40px 0 40px")
                     + cell(small(note)) + cell(chat_table(entries)))
    if abandoned:
        sections += cell(small(f"Abandoned · {plural(len(abandoned), 'chat')} · No real question or no reply."),
                         "32px 40px 0 40px")
    if unprocessed_note:
        sections += cell(small(unprocessed_note), "16px 40px 0 40px")
    if not items and not unprocessed_note:
        sections += cell(small("No chats for this report."), "32px 40px 0 40px")
    sections += cell(button("View all in Sheets", sheet_url), "32px 40px 0 40px")

    html = document(
        f"{product_name} chat summary", f"{product_name} · {long_date} · {count}",
        masthead("Daily chat digest", f"{product_name} chat summary",
                 f"{long_date} · {count}" + (f" · {since}" if since else ""))
        + section_open() + sections + section_close(),
        footer(f"{product_name} chats",
               ["Daily chat digest from SalesIQ", "Summaries and sentiment are generated automatically."],
               [["View all in Sheets", sheet_url]], [f"Report for {long_date}"]),
    )

    # Plain-text fallback preserves full summaries and sheet links.
    text = f"{product_name} Chat Summary\n{long_date} · {count}\n" + (f"{since}\n" if since else "")
    text += " · ".join(f"{label}: {value}" for value, label, _ in stats) + "\n"
    if attention_lines:
        text += "\nNeeds your attention\n" + "\n".join(attention_lines) + "\n"
    for key, title, _ in SENTIMENT_SECTIONS:
        entries = groups[key]
        if not entries:
            continue
        text += f"\n{title.upper()} ({len(entries)})\n"
        for item in entries:
            text += f"- [{_status(item)['label']}] {item['summary']} · {item['link']}\n"
    if abandoned:
        text += f"\nABANDONED: {plural(len(abandoned), 'chat')}\n"
    if unprocessed_note:
        text += f"\n{unprocessed_note}\n"
    if not items and not unprocessed_note:
        text += "\nNo chats for this report.\n"
    text += f"\nView all: {sheet_url}\n"
    return html, text


def render(args):
    """(subject, html, text) from {items, report_date, sheet_url, product_name, unprocessed[, timezone]}.

    The subject tail is "<len(items)> chats" whatever the count, as in the JS app.
    """
    items = [dict(item, when=parse_when(item.get("when"))) for item in args["items"]]
    html, text = build_digest_email(items, args["report_date"], args["sheet_url"], args["product_name"],
                                    args.get("unprocessed", 0))
    title = subject(f"{args['product_name']} chats", args["report_date"], args.get("timezone", "Asia/Kolkata"),
                    f"{len(items)} chats")
    return title, html, text
