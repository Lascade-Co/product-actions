#!/usr/bin/env python3
"""Hold a built report until its local delivery time (default 05:55).

Lateness never fails delivery: if a queued gate or slow build finishes after
the target, send immediately with the original report date. The locked dedupe
step must run after this hold and immediately before delivery.

NOW may contain an ISO timestamp to override the UTC clock for tests.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import gate


def now_utc() -> datetime:
    return gate.now_utc()


def target_for(report_date: date | str, tz: str | ZoneInfo, target: str = "05:55") -> datetime:
    """Local wall-clock release time; raises ValueError for an invalid target or zone."""
    day = date.fromisoformat(report_date) if isinstance(report_date, str) else report_date
    return gate.target_for(day, tz, gate.parse_target(target))


def hold_until(report_date: date, tz: str, target: str = "05:55") -> None:
    release = target_for(report_date, tz, target).astimezone(timezone.utc)
    wait = max(0.0, (release - now_utc()).total_seconds())
    print(f"hold_seconds={wait:.0f}")
    if wait:
        time.sleep(wait)


def _target(value: str) -> str:
    gate.parse_target(value)
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", required=True, type=date.fromisoformat)
    parser.add_argument("--tz", required=True, type=gate.parse_zone)
    parser.add_argument("--target", default="05:55", type=_target)
    args = parser.parse_args(argv)
    hold_until(args.report_date, args.tz, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
