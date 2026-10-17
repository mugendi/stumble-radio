from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from stumble_radio import world_times


def test_daypart_edges_map_only_valid_hours():
    expect = {
        5: "late",
        6: "breakfast",
        9: "breakfast",
        10: "afternoon",
        16: "afternoon",
        17: "evening",
        21: "evening",
        22: "late",
        2: "late",
    }
    for hour, slug in expect.items():
        assert world_times.daypart_for(hour) == slug
    assert world_times.daypart_label(world_times.daypart_for(7)) == "Breakfast Shows"
    with pytest.raises(ValueError):
        world_times.daypart_for(24)


def test_local_hour_resolves_zone_and_unknowns():
    moment = datetime(2026, 10, 18, 9, 41, tzinfo=UTC)
    assert world_times.local_hour("KE", moment) == 12
    assert world_times.local_hour("XXX", moment) is None
    bad = dict(world_times.CC_TZS, QA="Nonexistent/Zone")
    orig = world_times.CC_TZS
    world_times.CC_TZS = bad
    try:
        assert world_times.local_hour("QA", moment) is None
    finally:
        world_times.CC_TZS = orig


def test_every_country_zone_resolves():
    for zone in world_times.CC_TZS.values():
        ZoneInfo(zone)
