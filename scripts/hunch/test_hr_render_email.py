"""Reader-facing guarantees for the short TreasureHunch email."""
from copy import deepcopy
from datetime import date
import re

import pytest

from hr_render_email import render


def _window(n, k, *, state="ready", available_on=date(2026, 11, 2)):
    return {
        "state": state,
        "n": n,
        "k": k,
        "rate": k / n if n else None,
        "start": date(2026, 11, 15),
        "end": date(2026, 11, 21),
        "available_on": available_on,
    }


@pytest.fixture
def brief():
    # Hand-checked counts differ by direction so swapped rows are visible.
    counts = {
        "players": (20, 16), "new_players": (5, 9),
        "new_paid": (3, 6), "new_other": (2, 3), "daily_players": (8, 8),
        "streak2": (5, 6), "streak7": (2, 1), "longest": (13, 6),
    }
    rows = [
        {"id": "d1", "label": "Back next day", "days": 1,
         "good": .30, "stop": .15, "provisional": False,
         "current": _window(40, 8), "previous": _window(40, 6),
         "band": "continue", "change": .05},
        {"id": "d7", "label": "Back after a week", "days": 7,
         "good": .12, "stop": .06, "provisional": False,
         "current": _window(40, 5), "previous": _window(40, 6),
         "band": "good", "change": -.025},
        {"id": "d15", "label": "Back after 15 days", "days": 15,
         "good": .08, "stop": .04, "provisional": True,
         "current": _window(20, 1), "previous": _window(0, 0, state="open"),
         "band": "grey", "change": None},
        {"id": "d30", "label": "Back after 30 days", "days": 30,
         "good": .05, "stop": .025, "provisional": True,
         "current": _window(0, 0, state="open", available_on=date(2026, 12, 1)),
         "previous": _window(0, 0, state="open", available_on=date(2026, 12, 1)),
         "band": "grey", "change": None},
    ]
    return {
        "report_date": date(2026, 11, 23), "last_day": date(2026, 11, 22),
        "subject": "TreasureHunch · back next day 20% · 5 new · 5 on a streak",
        "summary": "New players are down on last week. Check with Jishnu whether the ads are running.",
        "yesterday": {"day": date(2026, 11, 22), **{
            key: {"value": now, "previous": before, "change": now - before}
            for key, (now, before) in counts.items()
        }},
        "retention": rows,
        "watch_out": [],
    }


def test_daily_brief_preserves_each_count_and_its_week_earlier_direction(brief):
    subject, html, text = render(brief)
    assert subject == "TreasureHunch · back next day 20% · 5 new · 5 on a streak"
    assert "TreasureHunch · Mon 23 Nov" in text
    assert "Players: 20 · +4 vs last week" in text
    assert "New players: 5 (3 from ads, 2 other) · -4 vs last week" in text
    assert "Daily puzzle: 8 · same vs last week" in text
    assert "On a streak: 5 for 2+ days, 2 for 7+ days, longest 13 days" in text
    assert "2+ days -1, 7+ days +1, longest +7 days vs last week" in text
    assert brief["summary"] in html
    assert "Watch out" not in text
    assert "Watch out" not in html
    assert not re.search(r"\bD(?:1|7|15|30)\b|release|8 Nov|What changed", text)


def test_return_rates_have_sample_counts_and_percentage_point_changes(brief):
    _, html, text = render(brief)
    assert "Back next day: 20% · +5 points vs last week · of 40 players" in text
    assert "Back after a week: 12.5% · -2.5 points vs last week · of 40 players" in text
    assert "Back after 15 days: 5% · of 20 players" in text
    # Only the return rate carries a pass-line colour; count changes stay neutral.
    assert re.search(r'<span[^>]*color:#8a6520;[^>]*>20%</span>', html)
    assert re.search(r'<span[^>]*color:#2a8c4a;[^>]*>12\.5%</span>', html)
    assert re.search(r'<span[^>]*color:#888888;[^>]*>5%</span>', html)
    assert "20.0%" not in text


def test_open_and_finished_empty_windows_do_not_show_rates_or_comparisons(brief):
    brief["retention"][2]["current"] = _window(0, 0, state="empty")
    _, html, text = render(brief)
    assert "Back after 15 days: no new players that week" in text
    assert "Back after 30 days: from 1 Dec" in text
    for label in ("Back after 15 days", "Back after 30 days"):
        line = next(line for line in text.splitlines() if line.startswith(label + ":"))
        assert "%" not in line
        assert "vs last week" not in line
        assert "of 0" not in line
    assert "no new players that week" in html
    assert "from 1 Dec" in html


def test_missing_previous_players_omits_the_change(brief):
    brief["retention"][0]["previous"] = _window(0, 0, state="empty")
    brief["retention"][0]["change"] = None
    _, _, text = render(brief)
    assert "Back next day: 20% · of 40 players" in text


def test_unchanged_longest_streak_has_a_readable_comparison(brief):
    brief["yesterday"]["longest"] = {"value": 13, "previous": 13, "change": 0}
    _, _, text = render(brief)
    assert "longest same vs last week" in text


def test_watch_out_shows_the_models_two_alerts_in_priority_order(brief):
    brief["watch_out"] = [
        {"id": "return_stop", "text": "Back next day crossed below the stop line."},
        {"id": "new_low", "text": "New players fell below half the recent average."},
    ]
    _, html, text = render(brief)
    assert text.count("Watch out") == 1
    assert text.index(brief["watch_out"][0]["text"]) < text.index(brief["watch_out"][1]["text"])
    assert brief["watch_out"][0]["text"] in html
    assert brief["watch_out"][1]["text"] in html


def test_missing_summary_falls_back_and_dynamic_text_is_escaped(brief):
    empty = deepcopy(brief)
    empty.pop("summary")
    _, html, text = render(empty)
    assert "Summary unavailable today." in html
    assert "Summary unavailable today." in text
    brief["summary"] = "Read <this> & check again."
    brief["watch_out"] = [{"id": "check", "text": "Watch <these> & those."}]
    _, html, text = render(brief)
    assert "Read &lt;this&gt; &amp; check again." in html
    assert "Watch &lt;these&gt; &amp; those." in html
    assert "Read <this> & check again." in text


def test_email_keeps_outlook_skeleton_and_explains_pass_lines(brief):
    _, html, text = render(brief)
    assert html.startswith('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"')
    assert "<o:OfficeDocumentSettings>" in html
    assert '<!-- Ghost table for Outlook -->' in html
    assert re.search(r'<!--\[if mso\]>\s*<table[^>]*width="600"', html)
    assert '<!-- /Email container -->' in html
    assert '.ExternalClass' in html
    assert '@media (prefers-color-scheme: dark)' in html
    assert not re.search(r'<(?:img|script)\b', html)
    assert "Good / worth continuing: next day 30% / 15%; week 12% / 6%;" in text
    assert "15 days 8% / 4%; 30 days 5% / 2.5% (both provisional)." in text
    assert "Below the lower line = stop. Grey = fewer than 30 players." in text
    assert "Other means no ad tag." in text
    assert "Days are UTC days." in text
