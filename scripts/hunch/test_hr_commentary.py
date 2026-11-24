"""The model chooses approved statements; its prose never reaches the email."""
import datetime as dt
import json

import pytest


STATEMENTS = [
    {
        "id": "new_down",
        "kind": "fact",
        "text": "New players are down on last week.",
        "actions": ["act_ads"],
    },
    {
        "id": "streak7_up",
        "kind": "fact",
        "text": "More players kept a week-long streak.",
        "actions": ["act_none"],
    },
    {
        "id": "act_ads",
        "kind": "action",
        "text": "Check with Jishnu whether the ads are running.",
    },
    {
        "id": "act_none",
        "kind": "action",
        "text": "Nothing to act on today.",
    },
]
GOOD_PICK = '{"pick":["new_down","act_ads"]}'
GOOD_SUMMARY = (
    "New players are down on last week. "
    "Check with Jishnu whether the ads are running."
)


def test_valid_pick_renders_only_the_two_fixed_sentences(monkeypatch, capsys):
    import hr_commentary as C

    calls = []

    def generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return GOOD_PICK

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == GOOD_SUMMARY
    assert len(calls) == 1
    assert json.loads(calls[0][0].split("STATEMENTS:\n", 1)[1]) == STATEMENTS
    assert calls[0][1] == {"max_tokens": 512, "timeout": 90}
    captured = capsys.readouterr()
    assert captured.out == "summary: ok\n"
    assert captured.err == ""


@pytest.mark.parametrize("response,reason", [
    ('{"pick":["unknown","act_ads"]}', "unknown"),
    ('{"pick":["new_down","unknown"]}', "unknown"),
    ('{"pick":["new_down","new_down"]}', "repeat"),
    ('{"pick":["new_down","streak7_up"]}', "kind"),
    ('{"pick":["act_ads","act_none"]}', "kind"),
    ('{"pick":["act_ads","new_down"]}', "kind"),
    ('{"pick":["new_down","act_none"]}', "action"),
    ("private model prose", "json"),
    ('```json\n{"pick":["new_down","act_ads"]}\n```', "json"),
    ('{"pick":["new_down","act_ads"]} private prose', "json"),
    ('["new_down","act_ads"]', "shape"),
    ('{"pick":["new_down","act_ads"],"text":"private prose"}', "shape"),
    ('{"pick":"new_down"}', "shape"),
    ('{"pick":["new_down"]}', "shape"),
    ('{"pick":["new_down","act_ads","act_none"]}', "shape"),
    ('{"pick":["new_down",null]}', "shape"),
    ('{"pick":["new_down",["act_ads"]]}', "shape"),
    ('{}', "shape"),
])
def test_rejected_pick_retries_once_then_falls_back(monkeypatch, capsys, response, reason):
    import hr_commentary as C

    prompts = []

    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return response

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == "Summary unavailable today."
    assert len(prompts) == 2
    assert prompts[1].startswith(prompts[0])
    assert "Rejected for: " + reason in prompts[1][len(prompts[0]):]
    assert response not in prompts[1][len(prompts[0]):]
    captured = capsys.readouterr()
    assert captured.out == f"summary: fallback:{reason}\n"
    assert captured.err == ""


def test_valid_retry_renders_fixed_sentences_and_does_not_echo_reply(monkeypatch, capsys):
    import hr_commentary as C

    prompts = []

    def generate(prompt, **kwargs):
        prompts.append(prompt)
        return "private response body" if len(prompts) == 1 else GOOD_PICK

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == GOOD_SUMMARY
    assert len(prompts) == 2
    assert "Rejected for: json" in prompts[1]
    assert "private response body" not in prompts[1]
    captured = capsys.readouterr()
    assert captured.out == "summary: ok\n"
    assert captured.err == ""


@pytest.mark.parametrize("error,reason", [
    (RuntimeError("private API body and figures"), "api"),
    (TimeoutError("private prompt"), "timeout"),
])
def test_api_errors_retry_once_and_are_sanitized(monkeypatch, capsys, error, reason):
    import hr_commentary as C

    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        raise error

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == "Summary unavailable today."
    assert len(calls) == 2
    assert str(error) not in calls[1]
    captured = capsys.readouterr()
    assert captured.out == f"summary: fallback:{reason}\n"
    assert captured.err == ""


@pytest.mark.parametrize("error_reason,safe_reason", [
    ("auth", "auth"),
    ("timeout", "timeout"),
    ("rate-limit", "rate"),
    ("sdk-unavailable", "sdk"),
    ("private error body", "api"),
])
def test_claude_errors_keep_only_safe_reasons(monkeypatch, capsys, error_reason, safe_reason):
    import hr_commentary as C

    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        raise C.ClaudeError(error_reason)

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == "Summary unavailable today."
    assert len(calls) == 2
    captured = capsys.readouterr()
    assert captured.out == f"summary: fallback:{safe_reason}\n"
    assert captured.err == ""


def test_api_failure_can_recover_on_the_one_retry(monkeypatch, capsys):
    import hr_commentary as C

    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise TimeoutError("private request body")
        return GOOD_PICK

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS) == GOOD_SUMMARY
    assert len(calls) == 2
    assert capsys.readouterr().out == "summary: ok\n"


@pytest.mark.parametrize("statements", [[], [STATEMENTS[2]]])
def test_no_approved_facts_falls_back_without_an_api_request(monkeypatch, capsys, statements):
    import hr_commentary as C

    def generate(*args, **kwargs):
        pytest.fail("no fact exists for the model to choose")

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(statements) == C.FALLBACK
    assert capsys.readouterr().out == "summary: fallback:no-facts\n"


def test_unserializable_input_is_optional_and_does_not_leak(monkeypatch, capsys):
    import hr_commentary as C

    statements = [{**STATEMENTS[0], "text": {"private input"}}]

    def generate(*args, **kwargs):
        pytest.fail("invalid input should not reach the API")

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(statements) == C.FALLBACK
    captured = capsys.readouterr()
    assert captured.out == "summary: fallback:invalid\n"
    assert captured.err == ""


def test_summary_skips_when_build_deadline_is_close(monkeypatch, capsys):
    import hr_commentary as C

    def generate(*args, **kwargs):
        pytest.fail("summary should not consume the rendering reserve")

    monkeypatch.setattr(C, "generate_text", generate)
    now = dt.datetime(2026, 11, 23, 13, 47, 50, tzinfo=dt.timezone.utc)
    assert C.summarize(STATEMENTS, deadline=now + dt.timedelta(seconds=10), clock=lambda: now) == C.FALLBACK
    assert capsys.readouterr().out == "summary: fallback:deadline\n"


def test_request_timeouts_leave_the_sdk_retry_and_rendering_reserve(monkeypatch):
    import hr_commentary as C

    now = dt.datetime(2026, 11, 23, 13, 47, 50, tzinfo=dt.timezone.utc)
    times = iter([now, now + dt.timedelta(seconds=15)])
    calls = []

    def generate(prompt, **kwargs):
        calls.append(kwargs)
        return "invalid" if len(calls) == 1 else GOOD_PICK

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS, deadline=now + dt.timedelta(seconds=105), clock=lambda: next(times)) == GOOD_SUMMARY
    assert calls == [
        {"max_tokens": 512, "timeout": 30},
        {"max_tokens": 512, "timeout": 25},
    ]


def test_summary_skips_retry_when_first_request_uses_the_deadline(monkeypatch, capsys):
    import hr_commentary as C

    now = dt.datetime(2026, 11, 23, 13, 47, 50, tzinfo=dt.timezone.utc)
    times = iter([now, now + dt.timedelta(seconds=80)])
    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        return "private invalid response"

    monkeypatch.setattr(C, "generate_text", generate)
    assert C.summarize(STATEMENTS, deadline=now + dt.timedelta(seconds=105), clock=lambda: next(times)) == C.FALLBACK
    assert len(calls) == 1
    assert capsys.readouterr().out == "summary: fallback:deadline\n"
