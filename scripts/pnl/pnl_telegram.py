"""Rendering and delivery.

Rendering only; Telegram transport (retries, token redaction) is notify.py.
Three ways this silently failed to send, each hit in practice: an unescaped
exception string ("400 can't parse entities" — nothing delivered, on exactly the
day a source broke); a message over 4096 characters; and a truncation landing
mid-entity.
"""

from __future__ import annotations

from notify import escape
from pnl_money import (
    Amount,
    SourceValue,
    Unavailable,
    combine,
    format_delta_usd,
    format_usd,
    round_usd,
)

_LIMIT = 4096


def truncate(text: str, limit: int = _LIMIT) -> str:
    """Cut on a line boundary — never mid-entity, which would emit a half
    written ``&am`` and reproduce the failure being defended against.

    Warnings are appended after the table, so they are the first thing lost.
    The marker keeps that visible: a silently shortened warning list reads as a
    complete one.
    """
    if len(text) <= limit:
        return text
    marker = "\n… truncated"
    kept = []
    for line in text.split("\n"):
        candidate = "\n".join(kept + [line])
        if len(candidate) + len(marker) > limit:
            break
        kept.append(line)
    if not kept:
        return marker.lstrip("\n")
    return "\n".join(kept) + marker


def _shown(value: SourceValue) -> str:
    return format_usd(value.usd) if isinstance(value, Amount) else "unavailable"


def _line(label: str, value: SourceValue) -> str:
    return f"{escape(label)} · {escape(_shown(value))}"


def render(report: dict) -> str:
    revenue, spend = report["revenue"], report["spend"]

    # Round each line once, then derive the totals from the rounded parts, or
    # the printed column visibly fails to subtract.
    rounded_revenue = {
        k: Amount(round_usd(v.usd)) if isinstance(v, Amount) else v for k, v in revenue.items()
    }
    rounded_spend = {
        k: Amount(round_usd(v.usd)) if isinstance(v, Amount) else v for k, v in spend.items()
    }

    revenue_total = combine(rounded_revenue.values(), "no revenue source could be read")
    spend_total = combine(rounded_spend.values(), "no spend source could be read")

    if not isinstance(revenue_total, Amount):
        # A net built from spend alone reads as a catastrophic loss to anyone
        # who sees the figure before the warning.
        net: SourceValue = Unavailable("no revenue source could be read")
    elif not isinstance(spend_total, Amount):
        # Treating an unreadable spend total as zero would print the net as
        # equal to gross revenue — a record month, on precisely the day every
        # spend source broke.
        net = Unavailable("no spend source could be read")
    else:
        net = Amount(revenue_total.usd - spend_total.usd)

    # Tags are structure and must not be escaped; everything interpolated into
    # them must be. Each part is its own line, and no tag spans a line, so
    # line-boundary truncation can never split one.
    parts = [
        f"<b>Marketing net</b> · {escape(report['month_label'])}",
        "",
        f"<b>Revenue · {escape(_shown(revenue_total))}</b>",
    ]
    parts += [_line(label, value) for label, value in rounded_revenue.items()]
    parts += ["", f"<b>Spend · {escape(_shown(spend_total))}</b>"]
    parts += [_line(label, value) for label, value in rounded_spend.items()]
    parts += ["", f"<b>Net · {escape(_shown(net))}</b>"]

    comparison = report.get("comparison")
    if comparison:
        value = comparison["value"]
        shown = format_delta_usd(value.usd) if isinstance(value, Amount) else "unavailable"
        parts.append(f"<b>{escape(comparison['label'])} · {escape(shown)}</b>")

    window = report.get("appstore_window_label")
    if window:
        parts.append(
            f"<i>{escape(f'App Store {window}; every other source through today.')}</i>"
        )

    warnings = report.get("warnings") or []
    if warnings:
        parts.append("")
        parts += [f"⚠️ {escape(w)}" for w in warnings]

    return truncate("\n".join(parts))
