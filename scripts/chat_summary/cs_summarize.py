"""Summary, status tag and sentiment for every pending row in one Claude call
(pipeline.js summarizeRows).

Claude has no response schema, so every cell is validated here. A cell that is
omitted, duplicated, unknown, or carries an invalid tag, sentiment or summary is
dropped: its row stays unprocessed (counted in the email, retried next run).
A ClaudeError propagates and aborts the build; translations already written stay.
"""
from dataclasses import dataclass, field
import re

import claude_api
from cs_translate import TRANSLATED, SUMMARY, TRANSLATION_ERROR, cell_text

MAX_TOKENS = 16384
TAGS = ("answered", "forwarded", "unanswered", "abandoned")
SENTIMENTS = ("positive", "neutral", "negative")


@dataclass
class SummaryResult:
    items: list = field(default_factory=list)   # [{cell_ref, row, summary, tag, sentiment}] in model order


def summary_prompt(support_contact):
    return "\n".join([
        'You will receive multiple customer chats. Each chat belongs to a spreadsheet cell like "C2", "C3" etc.',
        "",
        "Return STRICT JSON only (no markdown, no extra text) matching this schema:",
        "{",
        '  "items": [',
        '    { "cell": "C2", "real_question": true, "summary": "...", "tag": "answered|forwarded|unanswered|abandoned", "sentiment": "positive|neutral|negative" }',
        "  ]",
        "}",
        "",
        "REAL_QUESTION RULE (look ONLY at what the user wrote, ignore the AI's replies):",
        '- false = greetings like "hi", random words or characters, a lone name or word with no clear request, or anything with no understandable question or request.',
        '- true = the user asked something or requested something understandable (a ship name with a clear ask like "where is X" counts).',
        "",
        "SUMMARY RULE:",
        "- One concise sentence capturing what the user asked + what the AI replied (not just the issue).",
        "",
        "TAG RULES (strict, check in this order):",
        '- abandoned = the user never asked a real question (greetings like "hi", random words or characters, a lone name or word with no clear request), '
        "OR the AI asked a follow-up clarification and the user did not continue. This applies NO MATTER what the AI replied, even if it pointed to support.",
        "- answered = user asked a real question and the AI gave a clear and correct answer in the chat.",
        '- forwarded = user asked a real question and the AI asked them to email/contact support (e.g. "mail us", "contact '
        + (support_contact or "support") + '") instead of answering.',
        "- unanswered = user asked a real question, but the AI did not answer AND did not forward to support.",
        "",
        "SENTIMENT RULES (the USER's mood, not the AI's):",
        "- positive = user is happy, thankful, complimentary, or excited about the app.",
        "- negative = user is frustrated, angry, disappointed, complaining, reporting a bug, or asking for a refund/cancellation.",
        "- neutral = plain question or request with no clear emotion, or too short to tell.",
        "",
        "CHATS:",
        "",
        "",
    ])


def pending_cells(rows):
    """{"C<n>": translated text} for rows with a usable translation and no summary, in sheet order."""
    pending = {}
    for index, row in enumerate(rows):
        text = cell_text(row[TRANSLATED])
        if not text or text == TRANSLATION_ERROR or cell_text(row[SUMMARY]):
            continue
        pending[f"C{index + 2}"] = text
    return pending


def _validated(item):
    """(summary, tag, sentiment) for a well-formed item, else None."""
    tag, sentiment, summary = item.get("tag"), item.get("sentiment"), item.get("summary")
    if not isinstance(tag, str) or tag.strip().lower() not in TAGS:
        return None
    if not isinstance(sentiment, str) or sentiment.strip().lower() not in SENTIMENTS:
        return None
    if summary is not None and not isinstance(summary, str):
        return None
    tag = "abandoned" if item.get("real_question") is False else tag.strip().lower()   # whatever the AI replied
    return (summary or "").strip() or "(No summary)", tag, sentiment.strip().lower()


def summarize(rows, product, *, generate=None):
    """One call for all pending rows; returns only the valid, unambiguous cells."""
    pending = pending_cells(rows)
    if not pending:
        return SummaryResult()
    generate = generate or claude_api.generate_json
    prompt = summary_prompt(product.get("support_contact")) + "".join(
        f"{cell}: {text}\n\n" for cell, text in pending.items())
    parsed = generate(prompt, max_tokens=MAX_TOKENS)
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return SummaryResult()
    entries = [item for item in items if isinstance(item, dict) and isinstance(item.get("cell"), str)]
    cells = [item["cell"].strip() for item in entries]
    result = SummaryResult()
    for cell, item in zip(cells, entries):
        if not re.fullmatch(r"C[0-9]+", cell) or cell not in pending or cells.count(cell) > 1:
            continue
        valid = _validated(item)
        if valid is None:
            continue
        summary, tag, sentiment = valid
        result.items.append({"cell_ref": cell, "row": int(cell[1:]), "summary": summary, "tag": tag,
                             "sentiment": sentiment})
    return result
