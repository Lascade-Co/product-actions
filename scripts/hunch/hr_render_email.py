"""Render the brief on the canonical email style guide's complete skeleton."""
from __future__ import annotations

from html import escape
from pathlib import Path
from string import Template


FONT = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif"
HEADING_FONT = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
INK, MUTED = "#222222", "#666666"
RATE_COLOURS = {
    "good": "#2a8c4a", "continue": "#8a6520", "stop": "#c0392b", "grey": "#888888",
}
TABLE = '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"'
TEMPLATE = Template(Path(__file__).with_name("hr_email_template.html").read_text())

PASS_LINES = (
    "Good / worth continuing: next day 30% / 15%; week 12% / 6%; "
    "15 days 8% / 4%; 30 days 5% / 2.5% (both provisional). "
    "Below the lower line = stop. Grey = fewer than 30 players."
)
DEFINITIONS = (
    "Returns mean playing again exactly that many days later, for the latest week of players "
    "whose day has passed. Other means no ad tag. Days are UTC days."
)


def _number(value):
    """At most one decimal, without a trailing zero or a rounded negative zero."""
    rounded = round(value, 1)
    return f"{rounded if rounded else 0:.1f}".rstrip("0").rstrip(".")


def _change(value, *, points=False):
    if not value:
        return "same"
    amount = _number(value * 100 if points else value)
    return ("+" if value > 0 else "") + amount + (" points" if points else "")


def _span(text, *, color=INK, weight=400, size=None, muted=False):
    size_style = f" font-size:{size}px;" if size else ""
    cls = ' class="text-muted"' if muted else ' class="text-main"' if color == INK else ""
    return (
        f'<span style="color:{color}; font-weight:{weight};{size_style}"{cls}>'
        f'{escape(str(text))}</span>'
    )


def _paragraph(content, *, size=14, muted=False):
    return (
        f'<p style="margin:0; Margin:0; font-family:{FONT}; font-size:{size}px; '
        f'line-height:1.5; color:{MUTED if muted else INK};" '
        f'class="{"text-muted" if muted else "text-main"}">{content}</p>'
    )


def _row(content, *, top=0, bottom=0):
    return (
        f'<tr><td style="padding:{top}px 40px {bottom}px 40px;" class="body-cell">'
        f'{content}</td></tr>'
    )


def _heading(text):
    return _row(
        f'<h2 class="heading-dm" style="margin:0; Margin:0; font-family:{HEADING_FONT}; '
        f'font-size:18px; font-weight:600; line-height:1.3; color:{INK};">'
        f'{escape(text)}</h2>', top=16, bottom=5,
    )


def _yesterday_lines(yesterday):
    """The same four lines drive both representations of the email."""
    value = lambda key: yesterday[key]["value"]
    change = lambda key: _change(yesterday[key]["change"])
    longest_change = change("longest") + (" days" if yesterday["longest"]["change"] else "")
    return [
        ("Players", str(value("players")), f'{change("players")} vs last week'),
        ("New players", f'{value("new_players")} ({value("new_paid")} from ads, '
         f'{value("new_other")} other)', f'{change("new_players")} vs last week'),
        ("Daily puzzle", str(value("daily_players")), f'{change("daily_players")} vs last week'),
        ("On a streak", f'{value("streak2")} for 2+ days, {value("streak7")} for 7+ days, '
         f'longest {value("longest")} days',
         f'2+ days {change("streak2")}, 7+ days {change("streak7")}, '
         f'longest {longest_change} vs last week'),
    ]


def _retention_row(row):
    current = row["current"]
    label = row["label"]
    if current["state"] == "open":
        available = current["available_on"]
        detail = f"from {available.day} {available:%b}"
        contents = _span(detail, color=MUTED, size=13, muted=True)
    elif current["state"] == "empty":
        detail = "no new players that week"
        contents = _span(detail, color=MUTED, size=13, muted=True)
    else:
        rate = _number(current["rate"] * 100) + "%"
        colour = RATE_COLOURS[row["band"]]
        details = []
        if row["change"] is not None and current["n"] and row["previous"]["n"]:
            details.append(_change(row["change"], points=True) + " vs last week")
        details.append(f'of {current["n"]} players')
        detail = rate + " · " + " · ".join(details)
        contents = _span(rate, color=colour, weight=700) + " &nbsp;" + _span(
            " · ".join(details), color=MUTED, size=12, muted=True,
        )
    cell_style = f"padding:4px 0; font-family:{FONT}; font-size:14px; line-height:1.5;"
    html = (
        f'<tr><td valign="top" width="42%" style="{cell_style} color:{INK};" '
        f'class="text-main">{escape(label)}</td>'
        f'<td valign="top" style="{cell_style}">{contents}</td></tr>'
    )
    return html, f"{label}: {detail}"


def render(model):
    """Return subject, email-safe HTML, and equivalent plain text; never log facts."""
    subject = model["subject"]
    report_date = model["report_date"]
    masthead = f"TreasureHunch · {report_date:%a} {report_date.day} {report_date:%b}"
    summary = model.get("summary") or "Summary unavailable today."
    parts = [_row(
        f'<h1 class="heading-dm" style="margin:0; Margin:0; font-family:{HEADING_FONT}; '
        f'font-size:22px; font-weight:700; line-height:1.3; letter-spacing:-0.015em; '
        f'color:{INK};">{escape(masthead)}</h1>', top=20, bottom=10,
    )]
    parts.append(_row(_paragraph(escape(summary), size=15), bottom=2))
    lines = [subject, "", masthead, "", summary, "", "Yesterday"]

    parts.append(_heading("Yesterday"))
    for label, value, note in _yesterday_lines(model["yesterday"]):
        main = _span(label + ": ", weight=600) + _span(value)
        note_html = _span(note, color=MUTED, size=12, muted=True)
        if label == "On a streak":
            main += "<br />" + note_html
        else:
            main += " &nbsp;" + note_html
        parts.append(_row(_paragraph(main), bottom=3))
        lines.append(f"{label}: {value} · {note}")

    parts.append(_heading("Coming back"))
    lines.extend(["", "Coming back"])
    retention = [_retention_row(row) for row in model["retention"]]
    parts.append(_row(TABLE + ">" + "".join(row[0] for row in retention) + "</table>"))
    lines.extend(row[1] for row in retention)

    if model["watch_out"]:
        parts.append(_heading("Watch out"))
        lines.extend(["", "Watch out"])
        for alert in model["watch_out"]:
            parts.append(_row(_paragraph(escape(alert["text"])), bottom=3))
            lines.append(alert["text"])

    parts.append(_row(
        TABLE + '><tr><td style="border-top:1px solid #dddddd; font-size:1px; '
        'line-height:1px; mso-line-height-rule:exactly;" class="divider-line">'
        '&nbsp;</td></tr></table>', top=16, bottom=9,
    ))
    parts.append(_row(_paragraph(escape(PASS_LINES), size=11, muted=True), bottom=5))
    parts.append(_row(_paragraph(escape(DEFINITIONS), size=11, muted=True), bottom=20))
    content = (
        TABLE + ' style="background-color:#f5f3f1;" class="email-body-bg">'
        + "".join(parts) + "</table>"
    )
    html = TEMPLATE.substitute(
        subject=escape(subject), preheader=escape(summary), content=content,
    )
    lines.extend(["", PASS_LINES, DEFINITIONS])
    return subject, html, "\n".join(lines)
