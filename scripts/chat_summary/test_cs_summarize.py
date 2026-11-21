"""Summary, status and sentiment for pending rows (pipeline.js summarizeRows, now on Claude).

Without Gemini's response schema, malformed cells leave their rows unprocessed
(retried next run) instead of being coerced; a ClaudeError aborts the build.
"""
import pytest

from claude_api import ClaudeError
import cs_summarize
from cs_summarize import summarize

PRODUCT = {"slug": "marine-radar", "name": "MarineRadar", "sheet_id_env": "MARINE_RADAR_SHEET_ID",
           "support_contact": "connect@marineradar.com", "sentiment_col": "H"}


def row(translated="", summary="", chat="chat"):
    return [46315.5, "subject", chat, translated, summary, "", "", ""]


def item(cell, **overrides):
    value = {"cell": cell, "real_question": True, "summary": f"Summary {cell}", "tag": "answered",
             "sentiment": "neutral"}
    value.update(overrides)
    return value


def run(rows, response):
    return summarize(rows, PRODUCT, generate=lambda prompt, **kwargs: response)


def test_prompt_is_the_gemini_prompt_with_pending_chats_appended():
    rows = [row("Saved", "done"), row("  Where is my ship?  "), row("Translation Error"), row(""),
            row("Second chat")]
    calls = []

    def generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return {"items": []}

    summarize(rows, PRODUCT, generate=generate)
    prompt, kwargs = calls[0]
    assert kwargs == {"max_tokens": 16384}
    assert prompt == "\n".join([
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
        '- forwarded = user asked a real question and the AI asked them to email/contact support (e.g. "mail us", "contact connect@marineradar.com") instead of answering.',
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
    ]) + "C3: Where is my ship?\n\nC6: Second chat\n\n"


def test_support_contact_falls_back_to_support():
    calls = []
    summarize([row("x")], dict(PRODUCT, support_contact=""),
              generate=lambda prompt, **_: calls.append(prompt) or {"items": []})
    assert '"contact support") instead of answering.' in calls[0]


def test_no_pending_rows_means_no_call():
    result = summarize([row("x", "done"), row("Translation Error")], PRODUCT,
                       generate=lambda *a, **k: pytest.fail("no call"))
    assert result.items == []


def test_valid_items_are_normalised_in_model_order():
    rows = [row("a"), row("b")]
    result = run(rows, {"items": [
        item("C3", summary="  Second  ", tag="FORWARDED", sentiment="Negative"),
        item("C2", summary="", tag="answered", sentiment="positive"),
    ]})
    assert result.items == [
        {"cell_ref": "C3", "row": 3, "summary": "Second", "tag": "forwarded", "sentiment": "negative"},
        {"cell_ref": "C2", "row": 2, "summary": "(No summary)", "tag": "answered", "sentiment": "positive"},
    ]


def test_real_question_false_is_abandoned_whatever_the_ai_replied():
    result = run([row("hi")], {"items": [item("C2", real_question=False, tag="forwarded")]})
    assert result.items[0]["tag"] == "abandoned"
    result = run([row("hi")], {"items": [item("C2", real_question="false", tag="answered")]})
    assert result.items[0]["tag"] == "answered"


def test_summarize_missing_cell_counts_unprocessed():
    result = run([row("a"), row("b")], {"items": [item("C3")]})
    assert [i["cell_ref"] for i in result.items] == ["C3"]


def test_summarize_duplicate_cell_counts_unprocessed():
    result = run([row("a"), row("b")], {"items": [item("C2"), item("C3"), item("C2", summary="other")]})
    assert [i["cell_ref"] for i in result.items] == ["C3"]


@pytest.mark.parametrize("bad", [{"tag": "resolved"}, {"sentiment": "angry"}, {"tag": None}, {"sentiment": 3},
                                 {"summary": ["PRIVATE"]}])
def test_summarize_invalid_enum_counts_unprocessed(bad):
    result = run([row("a"), row("b")], {"items": [item("C2", **bad), item("C3")]})
    assert [i["cell_ref"] for i in result.items] == ["C3"]


@pytest.mark.parametrize("response", [
    {}, {"items": "PRIVATE"}, {"items": None}, {"items": [None, "C2", ["C2"]]},
    {"items": [item("C9"), item("D2"), item(2), item("C02x")]},
])
def test_malformed_responses_leave_every_row_unprocessed(response):
    assert run([row("a")], response).items == []


def test_summarize_claude_error_aborts_build():
    def generate(*_, **__):
        raise ClaudeError("incomplete-response:max_tokens")

    with pytest.raises(ClaudeError) as caught:
        summarize([row("PRIVATE chat")], PRODUCT, generate=generate)
    assert str(caught.value) == "Claude API: incomplete-response:max_tokens"


def test_default_generate_is_resolved_from_claude_api_at_call_time(monkeypatch):
    import claude_api
    calls = []
    monkeypatch.setattr(claude_api, "generate_json",
                        lambda prompt, **kwargs: calls.append(kwargs) or {"items": [item("C2")]})
    assert len(cs_summarize.summarize([row("x")], PRODUCT).items) == 1
    assert calls == [{"max_tokens": 16384}]
