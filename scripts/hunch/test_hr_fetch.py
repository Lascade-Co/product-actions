"""PostHog boundary tests use synthetic data and never contact the service."""
from __future__ import annotations

import datetime as dt
import signal
import time

import pytest
import requests

import hr_fetch as fetch


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return self.body


def test_missing_key_fails_with_safe_reason_before_http(monkeypatch, capsys):
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("unexpected HTTP"))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.fetch_all(dt.date(2026, 11, 19))
    assert exc.value.reason == "posthog-key-missing"
    assert str(exc.value) == "posthog-key-missing"
    assert capsys.readouterr() == ("", "")


def test_fetch_emits_utc_queries_and_maps_three_result_sets(monkeypatch, capsys):
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "synthetic-key")
    submitted = []
    results = iter([
        {"columns": ["d0", "n", "d1", "d7", "d15", "d30", "paid"],
         "results": [["2026-11-01", 40, 6, 2, 1, 0, 15]]},
        {"columns": ["day", "players", "new_players", "new_paid", "daily_players"],
         "results": [["2026-11-18", 30, 8, 3, 20]]},
        {"columns": ["day", "streak2", "streak7", "longest"],
         "results": [["2026-11-18", 7, 3, 12]]},
    ])

    def post(url, *, json, headers, timeout):
        assert url == "https://us.posthog.com/api/projects/701052/query/"
        assert headers == {"Authorization": "Bearer synthetic-key"}
        assert json["refresh"] == "force_async"
        assert json["query"]["kind"] == "HogQLQuery"
        assert 0 < timeout <= 60
        assert len(submitted) < 3, "fetch submitted more than the three required queries"
        submitted.append(json["query"]["query"])
        return Response(200, next(results))

    monkeypatch.setattr(requests, "post", post)
    actual = fetch.fetch_all(dt.date(2026, 11, 19))
    assert actual == {
        "cohorts": [{"d0": "2026-11-01", "n": 40, "d1": 6, "d7": 2,
                     "d15": 1, "d30": 0, "paid": 15}],
        "days": [{"day": "2026-11-18", "players": 30, "new_players": 8,
                  "new_paid": 3, "daily_players": 20}],
        "streaks": [{"day": "2026-11-18", "streak2": 7, "streak7": 3, "longest": 12}],
    }
    assert len(submitted) == 3
    for sql in submitted:
        assert "toDate(toTimeZone(" in sql
        assert "toDate(timestamp, 'UTC')" not in sql
        assert "timestamp < toDateTime('2026-11-19 00:00:00', 'UTC')" in sql
        assert "LIMIT " in sql
    assert capsys.readouterr() == ("", "")


def test_successful_fetch_passes_new_schema_through_without_event_normalization(monkeypatch):
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "synthetic-key")
    monkeypatch.setattr(fetch, "query_sql", lambda report_date: {
        "cohorts": "cohort query", "days": "day query", "streaks": "streak query",
    })
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(200, {
        "columns": [], "results": [],
    }))
    assert fetch.fetch_all(dt.date(2026, 11, 19)) == {
        "cohorts": [], "days": [], "streaks": [],
    }


def test_cohort_query_counts_exact_return_days_and_first_play_ad_source():
    sql = fetch.query_sql(dt.date(2026, 11, 19))["cohorts"]
    assert "WHERE event = 'hunt_started'" in sql
    assert "timestamp >= toDateTime('2026-10-31 00:00:00', 'UTC')" in sql
    assert "min(toDate(toTimeZone(timestamp, 'UTC'))) AS d0" in sql
    assert "groupUniqArray(toDate(toTimeZone(timestamp, 'UTC'))) AS days" in sql
    assert "argMin(ifNull(toString(properties.utm_medium), ''), timestamp) AS med" in sql
    for day in (1, 7, 15, 30):
        assert f"countIf(has(days, d0 + {day})) AS d{day}" in sql
    assert "countIf(med = 'paid') AS paid" in sql


def test_day_query_counts_round_starters_and_new_players_from_their_first_start():
    sql = fetch.query_sql(dt.date(2026, 11, 19))["days"]
    assert "timestamp >= toDateTime('2026-11-04 00:00:00', 'UTC')" in sql
    assert "timestamp >= toDateTime('2026-10-31 00:00:00', 'UTC')" in sql
    assert "min(toDate(toTimeZone(timestamp, 'UTC'))) AS d0" in sql
    assert "argMin(ifNull(toString(properties.utm_medium), ''), timestamp) AS med" in sql
    assert "uniqExactIf(events.person_id, event = 'hunt_started') AS players" in sql
    assert "event = 'hunt_started' AND first_plays.d0 = day) AS new_players" in sql
    assert "event = 'hunt_started' AND first_plays.d0 = day AND first_plays.med = 'paid') AS new_paid" in sql
    assert "event = 'hunt_completed' AND properties.mode = 'daily') AS daily_players" in sql


def test_streak_query_deduplicates_daily_puzzle_players_before_counting_streaks():
    sql = fetch.query_sql(dt.date(2026, 11, 19))["streaks"]
    assert "timestamp >= toDateTime('2026-11-04 00:00:00', 'UTC')" in sql
    assert "WHERE event = 'hunt_completed' AND properties.mode = 'daily'" in sql
    assert "max(toInt64OrZero(toString(properties.streak))) AS streak" in sql
    assert "GROUP BY day, person_id" in sql
    assert "countIf(streak >= 2) AS streak2" in sql
    assert "countIf(streak >= 7) AS streak7" in sql
    assert "max(streak) AS longest" in sql


def test_async_pending_responses_are_polled_until_complete(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(202, {"query_status": {"id": "synthetic"}}))
    responses = iter([
        Response(202, {"query_status": {"id": "synthetic", "complete": False}}),
        Response(200, {"query_status": {"complete": True, "error": False,
                                      "results": {"columns": ["n"], "results": [[40]]}}}),
    ])

    def get(url, **kwargs):
        assert url == "https://us.posthog.com/api/projects/701052/query/synthetic/"
        return next(responses)

    monkeypatch.setattr(requests, "get", get)
    assert fetch.make_runner("synthetic", poll_s=0)("synthetic query") == [{"n": 40}]


def test_transient_submit_failure_is_retried_without_private_exception(monkeypatch, capsys):
    responses = iter([
        Response(504, {"private": "data"}),
        Response(200, {"columns": ["n"], "results": [[40]]}),
    ])
    monkeypatch.setattr(requests, "post", lambda *a, **k: next(responses))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    assert fetch.make_runner("synthetic", retries=2)("synthetic query") == [{"n": 40}]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("status,body,reason", [
    (401, {"detail": "private response"}, "posthog-key-invalid"),
    (403, {"detail": "API key missing required scope 'query:read'"}, "posthog-scope-missing"),
    (403, {"detail": "You don't have access to the project."}, "posthog-project-denied"),
    (403, {"detail": "private response", "code": "permission_denied"}, "posthog-rejected-403-permission_denied"),
    (403, ["private"], "posthog-rejected-403"),
    (200, {"query_status": {"complete": True, "error": "private query"}}, "posthog-query-error"),
    (200, {"columns": ["n"], "results": [[40]], "hasMore": True}, "posthog-truncated"),
    (200, {"columns": ["n", "paid"], "results": [[40]]}, "posthog-invalid-response"),
    (200, ["private", "invalid"], "posthog-invalid-response"),
])
def test_api_errors_never_expose_response_bodies(monkeypatch, capsys, status, body, reason):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(status, body))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.make_runner("synthetic", retries=1, poll_s=0)("synthetic query")
    assert exc.value.reason == reason
    assert str(exc.value) == reason
    assert capsys.readouterr() == ("", "")


def test_network_failure_has_only_sanitized_reason(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise requests.RequestException("private-body-key-person")

    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(fetch.FetchError) as exc:
        fetch.make_runner("synthetic", retries=1)("synthetic query")
    assert exc.value.reason == "posthog-unavailable"
    assert str(exc.value) == "posthog-unavailable"
    assert capsys.readouterr() == ("", "")


def test_poll_timeout_stops_waiting(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(202, {"query_status": {"id": "synthetic"}}))
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("poll exceeded its budget"))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.make_runner("synthetic", retries=1, poll_s=0, max_wait_s=0)("synthetic query")
    assert exc.value.reason == "posthog-unavailable"


def test_elapsed_deadline_prevents_any_http(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("unexpected HTTP"))
    deadline = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    with pytest.raises(fetch.FetchError) as exc:
        fetch.make_runner("synthetic", deadline=deadline)("synthetic query")
    assert exc.value.reason == "build-deadline"


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="Unix deadline enforcement")
def test_absolute_deadline_interrupts_blocking_http_and_restores_alarm(monkeypatch):
    def blocked(*args, **kwargs):
        time.sleep(2)
        return Response(200, {"columns": [], "results": []})

    monkeypatch.setattr(requests, "post", blocked)
    previous = signal.getsignal(signal.SIGALRM)
    start = time.monotonic()
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=0.15)
    with pytest.raises(fetch.FetchError) as exc:
        fetch.make_runner("synthetic", deadline=deadline)("synthetic query")
    assert exc.value.reason == "build-deadline"
    assert time.monotonic() - start < 0.75
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
