"""Pure UTC-day facts and approved sentences for the executive brief."""
from __future__ import annotations

from datetime import date, timedelta

START = date(2026, 10, 31)
MIN_PLAYERS = 30
RETURNS = (
    ("d1", "Back next day", 1, .30, .15, False),
    ("d7", "Back after a week", 7, .12, .06, False),
    ("d15", "Back after 15 days", 15, .08, .04, True),
    ("d30", "Back after 30 days", 30, .05, .025, True),
)
DAY_FIELDS = ("players", "new_players", "new_paid", "daily_players")
STREAK_FIELDS = ("streak2", "streak7", "longest")
ACTIONS = {
    "act_ads": "Check with Jishnu whether the ads are running.",
    "act_game": "Check with Rohit what could bring players back.",
    "act_streak": "Check with Rohit whether the daily puzzle is working.",
    "act_none": "Keep watching this result.",
}


def _date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def retention_window(cohorts, last_day, metric, days):
    """Pool the latest seven eligible first-play days, stopping at game launch."""
    end = last_day - timedelta(days=days)
    start = max(START, end - timedelta(days=6))
    eligible = [row for row in cohorts if start <= row["d0"] <= end]
    n = sum(row["n"] for row in eligible)
    k = sum(row[metric] for row in eligible)
    return {"state": "open" if end < START else "ready" if n else "empty",
            "start": start, "end": end, "available_on": START + timedelta(days=days + 1),
            "k": k, "n": n, "rate": k / n if n else None}


def colour_band(window, good, stop):
    if window["n"] < MIN_PLAYERS:
        return "grey"
    return "good" if window["rate"] >= good else "continue" if window["rate"] >= stop else "stop"


def retention_rows(cohorts, last_day):
    rows = []
    for metric, label, days, good, stop, provisional in RETURNS:
        current = retention_window(cohorts, last_day, metric, days)
        previous = retention_window(cohorts, last_day - timedelta(days=7), metric, days)
        rows.append({"id": metric, "label": label, "days": days,
                     "good": good, "stop": stop, "provisional": provisional,
                     "current": current, "previous": previous,
                     "band": colour_band(current, good, stop),
                     "change": current["rate"] - previous["rate"]
                     if current["n"] and previous["n"] else None})
    return rows


def daily_rows(last_day, days, streaks):
    """Missing UTC days count as zero, including in the alert average."""
    day_lookup = {_date(row["day"]): row for row in days}
    streak_lookup = {_date(row["day"]): row for row in streaks}
    rows = []
    for offset in range(14, -1, -1):
        day = last_day - timedelta(days=offset)
        row = {"day": day}
        row.update({key: int(day_lookup.get(day, {}).get(key, 0)) for key in DAY_FIELDS})
        row.update({key: int(streak_lookup.get(day, {}).get(key, 0)) for key in STREAK_FIELDS})
        row["new_other"] = row["new_players"] - row["new_paid"]
        rows.append(row)
    return rows


def yesterday_lines(days):
    current, previous = days[-1], days[-8]
    return {"day": current["day"], **{
        key: {"value": current[key], "previous": previous[key], "change": current[key] - previous[key]}
        for key in (*DAY_FIELDS, "new_other", *STREAK_FIELDS)}}


def watch_out_rules(retention, yesterday, days):
    """Stop crossings take priority, then new players, players and week streaks."""
    alerts = []
    for row in retention:
        now, before = row["current"], row["previous"]
        if (not row["provisional"] and now["n"] >= MIN_PLAYERS and before["n"] >= MIN_PLAYERS
                and now["rate"] < row["stop"] <= before["rate"]):
            alerts.append({"id": f'{row["id"]}_crossed',
                           "text": f'{row["label"]} crossed below the stop line.'})
    for field, identifier, label in (("new_players", "new_low", "New players"),
                                      ("players", "players_low", "Daily players")):
        average = sum(day[field] for day in days[-8:-1]) / 7
        if yesterday[field]["value"] < average / 2:
            alerts.append({"id": identifier, "text": f"{label} are under half the average for the prior week."})
    if yesterday["streak7"]["change"] < 0:
        alerts.append({"id": "streak7_down", "text": "Fewer players kept a week-long streak than last week."})
    return alerts[:2]


def approved_statements(retention, yesterday):
    """Eleven possible facts and four actions; only true facts reach Claude."""
    statements = []

    def fact(identifier, text, action):
        statements.append({"id": identifier, "kind": "fact", "text": text, "actions": [action]})

    verdicts = {"stop": ("below the stop line", "act_game"),
                "continue": ("worth continuing", "act_game"),
                "good": ("at or above the good line", "act_none")}
    for row in retention:
        if row["provisional"] or row["band"] == "grey":
            continue
        words, action = verdicts[row["band"]]
        fact(f'{row["id"]}_{row["band"]}', f'{row["label"]} is {words}.', action)
    if yesterday["new_players"]["change"] < 0:
        fact("new_down", "New players are down on last week.", "act_ads")
    elif yesterday["new_players"]["change"] > 0:
        fact("new_up", "New players are up on last week.", "act_none")
    if yesterday["players"]["change"] < 0:
        fact("players_down", "Fewer players started a round than last week.", "act_game")
    if yesterday["streak7"]["change"] < 0:
        fact("streak7_down", "Fewer players kept a week-long streak.", "act_streak")
    elif yesterday["streak7"]["change"] > 0:
        fact("streak7_up", "More players kept a week-long streak.", "act_none")
    allowed_actions = {action for statement in statements for action in statement["actions"]}
    statements.extend({"id": identifier, "kind": "action", "text": text}
                      for identifier, text in ACTIONS.items() if identifier in allowed_actions)
    return statements


def subject(retention, yesterday, test_number=None):
    current = retention[0]["current"]
    rate = "–"
    if current["n"]:
        rate = f'{100 * current["rate"]:.1f}'.rstrip("0").rstrip(".") + "%"
        if current["n"] < MIN_PLAYERS:
            rate += f' (of {current["n"]})'
    prefix = f"[Test {test_number}] " if test_number is not None else ""
    return (f"{prefix}TreasureHunch · back next day {rate} · "
            f'{yesterday["new_players"]["value"]} new · {yesterday["streak2"]["value"]} on a streak')


def build_model(report_date, *, cohorts, days, streaks, test_number=None):
    """Build the report without I/O, logging, release markers or AI-authored text."""
    report_date = _date(report_date)
    last_day = report_date - timedelta(days=1)
    cohort_rows = [{"d0": _date(row["d0"]), **{field: int(row[field])
                   for field in ("n", "d1", "d7", "d15", "d30", "paid")}} for row in cohorts]
    retention = retention_rows(cohort_rows, last_day)
    daily = daily_rows(last_day, days, streaks)
    yesterday = yesterday_lines(daily)
    return {"report_date": report_date, "last_day": last_day,
            "retention": retention, "yesterday": yesterday,
            "watch_out": watch_out_rules(retention, yesterday, daily),
            "statements": approved_statements(retention, yesterday),
            "subject": subject(retention, yesterday, test_number)}
