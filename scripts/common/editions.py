"""Report editions: the PT and IST audiences and their local clocks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Edition:
    name: str
    timezone: str

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def label(self) -> str:
        """Step-name label: "PT" or "IST"."""
        return self.name.upper()

    def at(self, day: date, hour: int, minute: int) -> str:
        """Local wall-clock time on day, as a UTC ISO string ending in "Z"."""
        local = datetime.combine(day, time(hour, minute), self.zone)
        return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


EDITIONS = {
    "pt": Edition("pt", "America/Los_Angeles"),
    "ist": Edition("ist", "Asia/Kolkata"),
}


def get_edition(name: str) -> Edition:
    try:
        return EDITIONS[name]
    except (KeyError, TypeError):
        raise ValueError("unknown edition") from None
