from datetime import date
from zoneinfo import ZoneInfo

import pytest

import editions
from editions import EDITIONS, Edition, get_edition


def test_registry_holds_exactly_pt_and_ist():
    assert EDITIONS == {"pt": Edition("pt", "America/Los_Angeles"), "ist": Edition("ist", "Asia/Kolkata")}


def test_zone_and_label():
    assert get_edition("pt").zone == ZoneInfo("America/Los_Angeles")
    assert get_edition("ist").zone == ZoneInfo("Asia/Kolkata")
    assert (get_edition("pt").label, get_edition("ist").label) == ("PT", "IST")


@pytest.mark.parametrize("name,day,expected", [
    ("pt", date(2026, 3, 8), "2026-03-08T12:55:00Z"),
    ("pt", date(2026, 11, 1), "2026-11-01T13:55:00Z"),
    ("ist", date(2026, 11, 1), "2026-11-01T00:25:00Z"),
])
def test_at_is_local_wall_time_as_utc_iso(name, day, expected):
    assert get_edition(name).at(day, 5, 55) == expected


def test_unknown_edition_is_rejected():
    with pytest.raises(ValueError):
        get_edition("both")


def test_editions_are_immutable():
    with pytest.raises(AttributeError):
        editions.EDITIONS["pt"].timezone = "UTC"
