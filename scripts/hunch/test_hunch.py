"""Calendar boundaries and decisions for the short UTC executive brief."""
from datetime import date, timedelta
import json
import re

import pytest

from hr_model import build_model

REPORT_DATE = date(2026, 11, 23)


def build(*, report_date=REPORT_DATE, cohorts=(), days=(), streaks=(), **kwargs):
    return build_model(report_date, cohorts=list(cohorts), days=list(days), streaks=list(streaks), **kwargs)


def cohort(day, n=100, **counts):
    return {"d0": day, "n": n, "d1": 0, "d7": 0, "d15": 0, "d30": 0, "paid": 0, **counts}


def day(day, **counts):
    return {"day": day, "players": 0, "new_players": 0, "new_paid": 0, "daily_players": 0, **counts}


def streak(day, **counts):
    return {"day": day, "streak2": 0, "streak7": 0, "longest": 0, **counts}


def retention(model, metric="d1"):
    return next(row for row in model["retention"] if row["id"] == metric)


def fact_ids(model):
    return {s["id"] for s in model["statements"] if s["kind"] == "fact"}


def watch_ids(model):
    return [s["id"] for s in model["watch_out"]]


@pytest.mark.parametrize("metric,first,last,old_first,old_last", [
    ("d1", "2026-11-15", "2026-11-21", "2026-11-08", "2026-11-14"),
    ("d7", "2026-11-09", "2026-11-15", "2026-11-02", "2026-11-08"),
    ("d15", "2026-11-01", "2026-11-07", "2026-10-31", "2026-10-31"),
])
def test_retention_uses_seven_latest_finished_utc_cohort_days(metric, first, last, old_first, old_last):
    rows = [cohort(first, n=40, **{metric: 10}), cohort(last, n=60, **{metric: 30}),
            cohort("2026-10-30", n=1000, **{metric: 1000}),
            cohort((date.fromisoformat(last) + timedelta(days=1)).isoformat(), n=900, **{metric: 900})]
    row = retention(build(cohorts=rows), metric)
    assert row["current"]["start"] == date.fromisoformat(first)
    assert row["current"]["end"] == date.fromisoformat(last)
    assert (row["current"]["k"], row["current"]["n"], row["current"]["rate"]) == (40, 100, .4)
    assert row["previous"]["start"] == date.fromisoformat(old_first)
    assert row["previous"]["end"] == date.fromisoformat(old_last)


@pytest.mark.parametrize("report_date,state,n", [(date(2026, 11, 1), "open", 0), (date(2026, 11, 2), "ready", 40)])
def test_first_next_day_group_waits_for_a_complete_utc_day(report_date, state, n):
    row = retention(build(report_date=report_date, cohorts=[cohort("2026-10-31", n=40, d1=12)]))
    assert row["current"]["state"] == state
    assert row["current"]["n"] == n
    assert row["current"]["available_on"] == date(2026, 11, 2)
    assert row["previous"]["state"] == "open"
    assert row["change"] is None


@pytest.mark.parametrize("report_date,state,n", [(date(2026, 11, 30), "open", 0), (date(2026, 12, 1), "ready", 100)])
def test_thirty_day_result_first_appears_in_december_email(report_date, state, n):
    row = retention(build(report_date=report_date, cohorts=[cohort("2026-10-31", d30=5)]), "d30")
    assert row["current"]["state"] == state
    assert row["current"]["n"] == n
    assert row["current"]["available_on"] == date(2026, 12, 1)
    assert row["band"] == ("good" if n else "grey")


def test_no_players_in_finished_week_is_distinct_from_an_open_window():
    model = build(cohorts=[cohort("2026-11-14", d1=30)])
    row = retention(model)
    assert row["current"]["state"] == "empty"
    assert row["current"]["rate"] is None
    assert row["previous"]["n"] == 100
    assert row["change"] is None
    assert retention(model, "d30")["current"]["state"] == "open"


@pytest.mark.parametrize("metric,stop,good", [("d1", 150, 300), ("d7", 60, 120), ("d15", 40, 80), ("d30", 25, 50)])
@pytest.mark.parametrize("edge", ["below_stop", "at_stop", "below_good", "at_good"])
def test_colour_bands_include_the_line_edges(metric, stop, good, edge):
    k, expected = {"below_stop": (stop - 1, "stop"), "at_stop": (stop, "continue"),
                   "below_good": (good - 1, "continue"), "at_good": (good, "good")}[edge]
    dates = {"d1": "2026-12-09", "d7": "2026-12-03", "d15": "2026-11-25", "d30": "2026-11-10"}
    model = build(report_date=date(2026, 12, 11), cohorts=[cohort(dates[metric], n=1000, **{metric: k})])
    assert retention(model, metric)["band"] == expected


@pytest.mark.parametrize("n,band", [(29, "grey"), (30, "good")])
def test_small_samples_are_grey_without_hiding_the_result(n, band):
    row = retention(build(cohorts=[cohort("2026-11-21", n=n, d1=n)]))
    assert row["current"]["rate"] == 1
    assert row["current"]["n"] == n
    assert row["band"] == band


def test_comparison_is_same_window_shifted_one_week_and_needs_both_counts():
    model = build(cohorts=[cohort("2026-11-08", n=20, d1=4), cohort("2026-11-15", n=20, d1=6)])
    assert retention(model)["change"] == pytest.approx(.1)
    assert retention(model)["band"] == "grey"
    assert retention(build(cohorts=[cohort("2026-11-15", d1=30)]))["change"] is None


def test_yesterday_counts_compare_same_weekday_and_keep_untagged_other():
    model = build(days=[day("2026-11-22", players=13, new_players=5, new_paid=2, daily_players=8),
                        day("2026-11-15", players=20, new_players=8, new_paid=6, daily_players=7)],
                  streaks=[streak("2026-11-22", streak2=5, streak7=2, longest=13),
                           streak("2026-11-15", streak2=4, streak7=3, longest=10)])
    expected = {"players": (13, 20, -7), "new_players": (5, 8, -3), "new_paid": (2, 6, -4),
                "new_other": (3, 2, 1), "daily_players": (8, 7, 1), "streak2": (5, 4, 1),
                "streak7": (2, 3, -1), "longest": (13, 10, 3)}
    for key, (value, previous, change) in expected.items():
        assert model["yesterday"][key] == {"value": value, "previous": previous, "change": change}
    assert model["yesterday"]["day"] == date(2026, 11, 22)


@pytest.mark.parametrize("field,alert", [("new_players", "new_low"), ("players", "players_low")])
@pytest.mark.parametrize("yesterday,expected", [(4, True), (5, False), (6, False)])
def test_watch_half_average_is_strict_and_excludes_yesterday(field, alert, yesterday, expected):
    days = [day(f"2026-11-{d}", **{field: 10}) for d in range(15, 22)] + [day("2026-11-22", **{field: yesterday})]
    assert (alert in watch_ids(build(days=days))) is expected


def test_watch_average_includes_zero_days_and_has_exact_seven_day_bounds():
    model = build(days=[day("2026-11-14", new_players=700), day("2026-11-15", new_players=14),
                        day("2026-11-22", new_players=1), day("2026-11-23", new_players=700)])
    assert "new_low" not in watch_ids(model)  # Average is two; yesterday is exactly half.
    assert "new_low" in watch_ids(build(days=[day("2026-11-15", new_players=14)]))


@pytest.mark.parametrize("metric,old_day,new_day,stop", [("d1", "2026-11-14", "2026-11-21", 15), ("d7", "2026-11-08", "2026-11-15", 6)])
@pytest.mark.parametrize("old_k,new_k,alert", [(0, 0, False), (0, 1, False), (1, 0, True), (1, 1, False)])
def test_watch_stop_alert_requires_a_crossing(metric, old_day, new_day, stop, old_k, new_k, alert):
    model = build(cohorts=[cohort(old_day, **{metric: stop if old_k else stop - 1}),
                          cohort(new_day, **{metric: stop if new_k else stop - 1})])
    assert (f"{metric}_crossed" in watch_ids(model)) is alert


@pytest.mark.parametrize("old_n,new_n", [(29, 100), (100, 29)])
def test_watch_crossing_requires_both_windows_to_have_thirty_players(old_n, new_n):
    model = build(cohorts=[cohort("2026-11-14", n=old_n, d1=old_n), cohort("2026-11-21", n=new_n)])
    assert "d1_crossed" not in watch_ids(model)


def test_provisional_return_lines_never_trigger_stop_alerts():
    model = build(report_date=date(2026, 12, 15), cohorts=[cohort("2026-11-22", d15=10), cohort("2026-11-29", d15=0),
                                                        cohort("2026-11-07", d30=10), cohort("2026-11-14", d30=0)])
    assert retention(model, "d15")["band"] == "stop"
    assert retention(model, "d30")["band"] == "stop"
    assert not watch_ids(model)


def test_watch_streak_fall_is_against_the_same_day_last_week():
    model = build(streaks=[streak("2026-11-15", streak7=3), streak("2026-11-21", streak7=1), streak("2026-11-22", streak7=2)])
    assert watch_ids(model) == ["streak7_down"]


@pytest.mark.parametrize("today", [3, 4])
def test_watch_streak_does_not_fire_when_level_or_up(today):
    assert not watch_ids(build(streaks=[streak("2026-11-15", streak7=3), streak("2026-11-22", streak7=today)]))


def test_watch_keeps_only_two_with_stop_crossing_first_then_new_players():
    model = build(cohorts=[cohort("2026-11-14", d1=30), cohort("2026-11-21", d1=0)],
                  days=[day("2026-11-15", new_players=70, players=140)], streaks=[streak("2026-11-15", streak7=3)])
    assert watch_ids(model) == ["d1_crossed", "new_low"]
    assert watch_ids(build(days=[day("2026-11-15", new_players=70, players=140)], streaks=[streak("2026-11-15", streak7=3)])) == ["new_low", "players_low"]


@pytest.mark.parametrize("cohorts,expected", [([cohort("2026-11-21", n=100, d1=30)], "30%"),
    ([cohort("2026-11-21", n=20, d1=3)], "15% (of 20)"), ([cohort("2026-11-21", n=30, d1=2)], "6.7%"), ([], "–")])
def test_subject_shows_rate_sample_size_new_players_and_streak(cohorts, expected):
    model = build(cohorts=cohorts, days=[day("2026-11-22", new_players=5)], streaks=[streak("2026-11-22", streak2=7)])
    assert model["subject"] == f"TreasureHunch · back next day {expected} · 5 new · 7 on a streak"


def test_subject_keeps_manual_test_prefix_and_open_group_dash():
    model = build(report_date=date(2026, 11, 1), cohorts=[cohort("2026-10-31", d1=30)], test_number="42")
    assert model["subject"] == "[Test 42] TreasureHunch · back next day – · 0 new · 0 on a streak"


@pytest.mark.parametrize("metric,k,suffix,sentence,action", [
    ("d1", 14, "stop", "Back next day is below the stop line.", "act_game"),
    ("d1", 15, "continue", "Back next day is worth continuing.", "act_game"),
    ("d1", 30, "good", "Back next day is at or above the good line.", "act_none"),
    ("d7", 5, "stop", "Back after a week is below the stop line.", "act_game"),
    ("d7", 6, "continue", "Back after a week is worth continuing.", "act_game"),
    ("d7", 12, "good", "Back after a week is at or above the good line.", "act_none"),
])
def test_each_return_statement_matches_its_own_row(metric, k, suffix, sentence, action):
    model = build(cohorts=[cohort("2026-11-21" if metric == "d1" else "2026-11-15", **{metric: k})])
    found = {s["id"]: s for s in model["statements"]}
    chosen = found[f"{metric}_{suffix}"]
    assert chosen["text"] == sentence
    assert chosen["actions"] == [action]
    assert found[action]["kind"] == "action"
    assert {s for s in fact_ids(model) if s.startswith(metric + "_")} == {f"{metric}_{suffix}"}


@pytest.mark.parametrize("metric,old,current,identifier,sentence,action", [
    ("new_players", 8, 5, "new_down", "New players are down on last week.", "act_ads"),
    ("new_players", 5, 8, "new_up", "New players are up on last week.", "act_none"),
    ("players", 8, 5, "players_down", "Fewer players started a round than last week.", "act_game"),
    ("streak7", 3, 2, "streak7_down", "Fewer players kept a week-long streak.", "act_streak"),
    ("streak7", 2, 3, "streak7_up", "More players kept a week-long streak.", "act_none"),
])
def test_each_direction_statement_matches_its_measure(metric, old, current, identifier, sentence, action):
    key, make = ("streaks", streak) if metric == "streak7" else ("days", day)
    model = build(**{key: [make("2026-11-15", **{metric: old}), make("2026-11-22", **{metric: current})]})
    statement = next(s for s in model["statements"] if s["id"] == identifier)
    assert statement["text"] == sentence
    assert statement["actions"] == [action]
    equal = {key: [make("2026-11-15", **{metric: old}), make("2026-11-22", **{metric: old})]}
    opposite = {key: [make("2026-11-15", **{metric: current}), make("2026-11-22", **{metric: old})]}
    assert identifier not in fact_ids(build(**equal))
    assert identifier not in fact_ids(build(**opposite))


@pytest.mark.parametrize("n", [0, 1, 29])
def test_small_samples_and_unfinished_or_provisional_rows_offer_no_return_verdict(n):
    model = build(cohorts=[cohort("2026-11-15", n=n), cohort("2026-11-01", n=100)])
    assert not {s for s in fact_ids(model) if s.startswith(("d1_", "d7_", "d15_", "d30_"))}


def test_statements_have_plain_fixed_text_and_link_to_present_actions():
    model = build(cohorts=[cohort("2026-11-15", d1=0, d7=0)], days=[day("2026-11-15", new_players=8, players=10)],
                  streaks=[streak("2026-11-15", streak7=2)])
    statements = model["statements"]
    json.dumps(statements, allow_nan=False)
    ids = {s["id"] for s in statements}
    assert len(ids) == len(statements)
    for s in statements:
        assert not re.search(r"\d|\bD[0-9]+\b|cohort|retention", s["text"])
        if s["kind"] == "fact":
            assert set(s["actions"]) <= ids


def test_positive_read_does_not_dismiss_a_stop_warning(monkeypatch, capsys):
    import hr_commentary as commentary

    model = build(cohorts=[cohort("2026-11-14", d1=30), cohort("2026-11-21", d1=0)],
                  days=[day("2026-11-15", new_players=1), day("2026-11-22", new_players=2)])
    assert "d1_crossed" in watch_ids(model)
    monkeypatch.setattr(commentary, "generate_text", lambda *a, **k: '{"pick":["new_up","act_none"]}')
    assert commentary.summarize(model["statements"]) == (
        "New players are up on last week. Keep watching this result."
    )
    assert capsys.readouterr() == ("summary: ok\n", "")
