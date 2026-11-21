"""Translation of column C into column D (pipeline.js translateRows, now on Claude)."""
import pytest

from claude_api import ClaudeError
import cs_translate
from cs_translate import TRANSLATION_ERROR, translate_rows


def row(chat="", translated="", summary=""):
    return [46315.5, "subject", chat, translated, summary, "", "", ""]


def test_prompt_is_the_gemini_prompt_with_cell_blocks():
    rows = [row("hola"), row("bonjour")]
    prompts = []

    def generate(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        return {"items": [{"cell": "C2", "english": "hello"}, {"cell": "C3", "english": "hello"}]}

    translate_rows(rows, generate=generate, log=lambda _: None)
    prompt, kwargs = prompts[0]
    assert kwargs == {"max_tokens": 32000}
    assert prompt == "\n".join([
        'You will receive customer support chat transcripts, each labelled with a spreadsheet cell like "C2".',
        "Translate each one into English, preserving speaker labels, line breaks and meaning.",
        'If a transcript is ALREADY entirely in English, return "english" as an empty string for it (do not repeat it).',
        'Return STRICT JSON: { "items": [ { "cell": "C2", "english": "..." } ] } with one item per cell.',
        "Return only that JSON object, with no markdown fences or other text.",
        "",
        "TRANSCRIPTS:",
        "",
        "C2:\nhola\n",
        "C3:\nbonjour\n",
    ])


def test_translations_fill_d_and_empty_english_keeps_the_original():
    rows = [row("hola"), row("  already English  ")]
    result = translate_rows(rows, generate=lambda prompt, **_: {"items": [
        {"cell": "C2", "english": " hello "}, {"cell": "C3", "english": ""}]}, log=lambda _: None)
    assert result.updates == [("D2", "hello"), ("D3", "already English")]
    assert rows[0][3] == "hello" and rows[1][3] == "already English"


def test_skip_rules_match_the_js_resume_logic():
    rows = [row("done", "x", "summary"), row("translated", "English text"), row(""),
            row("retry me", TRANSLATION_ERROR), row("new")]
    seen = []

    def generate(prompt, **_):
        seen.append(prompt)
        return {"items": [{"cell": "C5", "english": "a"}, {"cell": "C6", "english": "b"}]}

    result = translate_rows(rows, generate=generate, log=lambda _: None)
    assert result.updates == [("D5", "a"), ("D6", "b")]
    assert "C2:" not in seen[0] and "C3:" not in seen[0] and "C4:" not in seen[0]


def test_no_pending_rows_means_no_call():
    result = translate_rows([row("x", "done")], generate=lambda *a, **k: pytest.fail("no call"), log=print)
    assert result.updates == []


def test_chats_are_cut_to_5000_and_chunks_hold_at_most_20000_chars():
    rows = [row("a" * 6000), row("b" * 5000), row("c" * 5000), row("d" * 5000), row("e" * 10)]
    prompts = []

    def generate(prompt, **_):
        prompts.append(prompt)
        return {"items": []}

    translate_rows(rows, generate=generate, log=lambda _: None)
    assert len(prompts) == 2
    assert "C2:\n" + "a" * 5000 + "\n" in prompts[0] and "a" * 5001 not in prompts[0]
    assert all(f"C{n}:" in prompts[0] for n in (2, 3, 4, 5))
    assert "C6:\neeeeeeeeee\n" in prompts[1]


def test_missing_cells_are_marked_translation_error():
    rows = [row("uno"), row("dos")]
    result = translate_rows(rows, generate=lambda *_, **__: {"items": [{"cell": "C3", "english": "two"}]},
                            log=lambda _: None)
    assert result.updates == [("D2", TRANSLATION_ERROR), ("D3", "two")]


def test_translate_claude_error_marks_chunk():
    rows = [row("x" * 5000) for _ in range(4)] + [row("y" * 5000)]
    logs = []
    calls = []

    def generate(prompt, **_):
        calls.append(prompt)
        if len(calls) == 1:
            raise ClaudeError("rate-limit")
        return {"items": [{"cell": "C6", "english": "why"}]}

    result = translate_rows(rows, generate=generate, log=logs.append)
    assert len(calls) == 2
    assert result.updates == [(f"D{n}", TRANSLATION_ERROR) for n in range(2, 6)] + [("D6", "why")]
    assert [r[3] for r in rows] == [TRANSLATION_ERROR] * 4 + ["why"]
    assert logs == ["Translation failed; rows=4 reason=rate-limit"]


@pytest.mark.parametrize("response", [
    {"items": "PRIVATE"}, {"items": [None, "PRIVATE"]}, {"wrong": []}, {"items": [{"cell": 2, "english": None}]},
])
def test_malformed_responses_mark_rows_without_logging_content(response):
    rows = [row("PRIVATE chat")]
    logs = []
    result = translate_rows(rows, generate=lambda *_, **__: response, log=logs.append)
    assert result.updates == [("D2", TRANSLATION_ERROR)]
    assert "PRIVATE" not in "\n".join(logs)


def test_any_exception_marks_the_chunk_without_its_message():
    rows = [row("PRIVATE chat")]
    logs = []

    def generate(*_, **__):
        raise RuntimeError("PRIVATE upstream error")

    result = translate_rows(rows, generate=generate, log=logs.append)
    assert result.updates == [("D2", TRANSLATION_ERROR)]
    assert logs == ["Translation failed; rows=1"]


def test_default_generate_is_resolved_from_claude_api_at_call_time(monkeypatch):
    import claude_api
    calls = []
    monkeypatch.setattr(claude_api, "generate_json",
                        lambda prompt, **kwargs: calls.append(kwargs) or {"items": [{"cell": "C2", "english": "x"}]})
    cs_translate.translate_rows([row("y")], log=lambda _: None)
    assert calls == [{"max_tokens": 32000}]
