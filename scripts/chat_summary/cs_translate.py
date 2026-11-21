"""Translate column C into column D with Claude (pipeline.js translateRows).

Rows are 8-cell lists (A Date | B Subject | C Transcript | D Translated | E Summary
| F Tag | G | H); D is updated in place. A failed chunk marks its rows
"Translation Error", which is retried on the next run. Never log prompts,
responses or exception messages: only row counts and ClaudeError reasons.
"""
from dataclasses import dataclass, field

import claude_api

TRANSLATION_ERROR = "Translation Error"
CHUNK_CHARS = 20000
CHAT_CHARS = 5000
MAX_TOKENS = 32000
CHAT, TRANSLATED, SUMMARY = 2, 3, 4

PROMPT_HEADER = [
    'You will receive customer support chat transcripts, each labelled with a spreadsheet cell like "C2".',
    "Translate each one into English, preserving speaker labels, line breaks and meaning.",
    'If a transcript is ALREADY entirely in English, return "english" as an empty string for it (do not repeat it).',
    'Return STRICT JSON: { "items": [ { "cell": "C2", "english": "..." } ] } with one item per cell.',
    # Claude has no response schema; generate_json parses one bare (or ```json-fenced) object.
    "Return only that JSON object, with no markdown fences or other text.",
    "",
    "TRANSCRIPTS:",
    "",
]


@dataclass
class TranslateResult:
    updates: list = field(default_factory=list)   # [("D<row>", value)] in sheet order of each chunk
    failed_chunks: int = 0


def cell_text(value):
    """String(value ?? "").trim() for a sheet cell."""
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"
    return str(value).strip()


def pending_chunks(rows):
    """[[(index, "C<n>", text)]]: eligible rows, cut to 5000 chars, greedily packed to 20000."""
    chunks, size = [[]], 0
    for index, row in enumerate(rows):
        translated = cell_text(row[TRANSLATED])
        if cell_text(row[SUMMARY]) or (translated and translated != TRANSLATION_ERROR):
            continue
        text = cell_text(row[CHAT])[:CHAT_CHARS]
        if not text:
            continue
        if size + len(text) > CHUNK_CHARS and chunks[-1]:
            chunks.append([])
            size = 0
        chunks[-1].append((index, f"C{index + 2}", text))
        size += len(text)
    return [chunk for chunk in chunks if chunk]


def translation_prompt(chunk):
    return "\n".join(PROMPT_HEADER + [f"{cell}:\n{text}\n" for _, cell, text in chunk])


def _english_by_cell(parsed):
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError("malformed translation response")
    english = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("cell"), str) and isinstance(item.get("english"), str):
            english[item["cell"].strip()] = item["english"]
    return english


def translate_rows(rows, *, generate=None, log=print):
    """Translate pending rows chunk by chunk; returns the D-cell updates (errors included)."""
    generate = generate or claude_api.generate_json
    result = TranslateResult()
    for chunk in pending_chunks(rows):
        english = {}
        try:
            english = _english_by_cell(generate(translation_prompt(chunk), max_tokens=MAX_TOKENS))
        except Exception as exc:  # any failure: mark this chunk, keep going, retry next run
            result.failed_chunks += 1
            reason = f" reason={exc.reason}" if isinstance(exc, claude_api.ClaudeError) else ""
            log(f"Translation failed; rows={len(chunk)}{reason}")
        for index, cell, text in chunk:
            value = TRANSLATION_ERROR if cell not in english else (english[cell].strip() or text)
            rows[index][TRANSLATED] = value
            result.updates.append((f"D{index + 2}", value))
    return result
