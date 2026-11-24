"""Synthetic executive-brief fixture; run this file to render without any API."""
from datetime import date, timedelta
from pathlib import Path
import sys

REPORT_DATE = date(2026, 11, 23)


def preview_inputs():
    cohorts = []
    for offset in range(16):
        day = date(2026, 10, 31) + timedelta(days=offset)
        cohorts.append({"d0": day.isoformat(), "n": 40, "d1": 12, "d7": 4,
                        "d15": 2, "d30": 0, "paid": 32})
    days, streaks = [], []
    for offset in range(15):
        day = date(2026, 11, 8) + timedelta(days=offset)
        earlier = day <= date(2026, 11, 15)
        days.append({"day": day.isoformat(), "players": 45 if earlier else 13,
                     "new_players": 40 if earlier else 0, "new_paid": 32 if earlier else 0,
                     "daily_players": 20 if earlier else 8})
        streaks.append({"day": day.isoformat(), "streak2": 4 if earlier else 5,
                        "streak7": 1 if earlier else 2, "longest": max(2, offset - 1)})
    return {"cohorts": cohorts, "days": days, "streaks": streaks}


def render_preview(output):
    from hr_model import build_model
    from hr_render_email import render

    model = build_model(REPORT_DATE, **preview_inputs())
    approved = {statement["id"]: statement["text"] for statement in model["statements"]}
    model["summary"] = approved["new_down"] + " " + approved["act_ads"]
    _, html, _ = render(model)
    Path(output).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    render_preview(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hunch-lane-preview.html")
