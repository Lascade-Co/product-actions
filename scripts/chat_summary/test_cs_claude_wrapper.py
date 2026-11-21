"""Port of gemini.test.js: model failures never expose response or customer content.

The Claude client itself is shared (scripts/ai/claude_api.py); these tests pin how
chat-summary surfaces its failures, with the network call monkeypatched away.
"""
import pytest

import claude_api
from claude_api import ClaudeError
import cs_main
import cs_summarize
import cs_translate

PRIVATE = "PRIVATE_CUSTOMER_SUMMARY_AND_RECIPIENT"
PRODUCT = {"slug": "marine-radar", "name": "MarineRadar", "sheet_id_env": "MARINE_RADAR_SHEET_ID",
           "support_contact": "", "sentiment_col": "H"}
GENERIC = "Chat digest build failed; no delivery marker was recorded."


def rows():
    return [[46315.5, "s", f"{PRIVATE} chat", f"{PRIVATE} translated", "", "", "", ""]]


@pytest.mark.parametrize("raw", [PRIVATE, f'["{PRIVATE}"]', f"```json\n{PRIVATE}\n```", f'"{PRIVATE}"'])
def test_unparseable_model_text_fails_with_a_fixed_reason(monkeypatch, raw):
    monkeypatch.setattr(claude_api, "generate_text", lambda prompt, **kwargs: raw)
    with pytest.raises(ClaudeError) as caught:
        cs_summarize.summarize(rows(), PRODUCT)
    assert PRIVATE not in str(caught.value)
    assert cs_main.failure_message(caught.value, "build") == "Claude API: invalid-json"


@pytest.mark.parametrize("reason", ["auth", "rate-limit", "timeout", "request-failed:http-400:invalid_request_error",
                                    "incomplete-response:max_tokens", "empty-response"])
def test_claude_errors_surface_only_their_reason(monkeypatch, reason):
    def fail(prompt, **kwargs):
        assert PRIVATE in prompt
        raise ClaudeError(reason)

    monkeypatch.setattr(claude_api, "generate_text", fail)
    with pytest.raises(ClaudeError) as caught:
        cs_summarize.summarize(rows(), PRODUCT)
    assert cs_main.failure_message(caught.value, "build") == f"Claude API: {reason}"


def test_other_failures_are_reduced_to_the_generic_line(monkeypatch):
    def fail(prompt, **kwargs):
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(claude_api, "generate_json", fail)
    with pytest.raises(RuntimeError) as caught:
        cs_summarize.summarize(rows(), PRODUCT)
    assert cs_main.failure_message(caught.value, "build") == GENERIC


def test_translation_failures_never_log_model_or_customer_text(monkeypatch):
    logs = []
    for failure in (ClaudeError("invalid-json"), RuntimeError(PRIVATE)):
        def fail(prompt, failure=failure, **kwargs):
            raise failure

        monkeypatch.setattr(claude_api, "generate_json", fail)
        data = [[46315.5, "s", f"{PRIVATE} chat", "", "", "", "", ""]]
        cs_translate.translate_rows(data, log=logs.append)
        assert data[0][3] == cs_translate.TRANSLATION_ERROR
    assert logs == ["Translation failed; rows=1 reason=invalid-json", "Translation failed; rows=1"]


def test_missing_api_key_is_a_safe_auth_failure(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    with pytest.raises(ClaudeError) as caught:
        cs_summarize.summarize(rows(), PRODUCT)
    assert cs_main.failure_message(caught.value, "build") == "Claude API: auth"
