import pytest

from conftest import raw_character


def info_from(hb, **over):
    return hb.ddb.hp_details(hb.ddb.parse_character(raw_character(**over)))


def test_max_hp_includes_con_and_per_level_bonuses(hb):
    raw = raw_character(modifiers={
        "feat":  [{"type": "bonus", "subType": "hit-points-per-level", "value": 2}],          # Tough
        "class": [{"type": "bonus", "subType": "hit-points-per-level", "value": 1,
                   "componentId": 111}],                                                     # class lvl 5
    })
    pct, cur, mx = hb.ddb.calculate_hp(hb.ddb.parse_character(raw))
    # 40 base + 8 levels * +2 CON + 8 * 2 (Tough) + 5 * 1 (class feature) = 77
    assert (cur, mx) == (67, 77)


def test_temporary_hp_is_separate_from_max(hb):
    info = info_from(hb, removedHitPoints=0, temporaryHitPoints=5)
    assert (info["cur"], info["mx"], info["temp"], info["pct"]) == (56, 56, 5, 1.0)
    assert hb.theme.hp_text(info) == "56 / 56  +5"


def test_override_and_unconfigured(hb):
    d = hb.ddb.parse_character(raw_character(overrideHitPoints=30, removedHitPoints=40))
    assert hb.ddb.calculate_hp(d) == (0.0, 0, 30)
    empty = hb.ddb.parse_character(raw_character(baseHitPoints=0, classes=[], stats=[]))
    assert hb.ddb.calculate_hp(empty)[0] is None
    assert hb.theme.hp_text(hb.ddb.hp_details(empty)) == "—"


def test_constitution_set_item(hb):
    raw = raw_character(modifiers={"item": [{"type": "set", "subType": "constitution-score", "value": 19}]})
    assert hb.ddb.parse_character(raw)["conMod"] == 4


def test_conditions_death_saves_and_avatar(hb):
    d = hb.ddb.parse_character(raw_character(
        conditions=[{"id": 11}, {"id": 4, "level": 2}, {"id": 999}],
        deathSaves={"failCount": 1, "successCount": 2, "isStabilized": False}))
    assert d["conditions"] == ["Poisoned", "Exhaustion 2"]
    assert d["deathSaves"] == {"fail": 1, "success": 2, "stable": False}
    assert d["avatar_url"].startswith("https://www.dndbeyond.com/")


@pytest.mark.parametrize("removed,saves,expected", [
    (0,  {}, "full"),
    (10, {}, "scratched"),
    (50, {}, "critical"),
    (56, {"failCount": 0}, "dying"),                       # 0 HP is not dead in 5e
    (56, {"failCount": 2, "successCount": 2}, "dying"),
    (56, {"isStabilized": True}, "stable"),
    (56, {"failCount": 3}, "dead"),                        # three failed saves
])
def test_dying_stable_dead(hb, removed, saves, expected):
    info = info_from(hb, removedHitPoints=removed, deathSaves=saves)
    assert hb.theme.display_state(info) == expected


def test_threshold_states_and_unknown(hb):
    assert [hb.theme.hp_state(p) for p in (None, 0.1, 0.3, 0.6, 0.9, 1.0)] == \
           ["unknown", "critical", "bloodied", "injured", "scratched", "full"]
    assert hb.theme.display_state(None) == "unknown"


def test_manual_characters(hb):
    ch = {"source": "manual", "max_hp": 30, "current_hp": 30, "temp_hp": 0}
    ddb = hb.ddb
    ddb.apply_hp_change(ch, "temp", 5)
    ddb.apply_hp_change(ch, "damage", 8)                   # 5 from temp HP, 3 from HP
    assert (ch["current_hp"], ch["temp_hp"]) == (27, 0)
    ddb.apply_hp_change(ch, "heal", 100)
    assert ch["current_hp"] == 30                          # capped at max
    ddb.apply_hp_change(ch, "max", 20)
    assert (ch["max_hp"], ch["current_hp"]) == (20, 20)
    ddb.apply_hp_change(ch, "damage", 50)
    info = ddb.manual_info(ch)
    assert info["cur"] == 0 and info["npc"]
    assert hb.theme.display_state(info) == "dead"          # NPCs don't make death saves
    with pytest.raises(ValueError):
        ddb.apply_hp_change(ch, "bogus", 1)


def test_palettes_and_badges(hb):
    t = hb.theme
    assert t.state_color("full") == "#00e676"
    t.set_palette("colorblind")
    assert t.state_color("full") == "#1e88e5" and t.palette_name() == "colorblind"
    fg, bg, bd = t.badge_colors("critical")
    assert fg == t.state_color("critical") and bg.startswith("#") and len(bg) == 7
    t.set_palette("nonsense")
    assert t.palette_name() == "default"


def test_backoff_and_versions(hb):
    assert [hb.ddb.backoff_delay(n) for n in range(1, 8)] == [5, 10, 20, 40, 80, 120, 120]
    assert hb.updater.parse_version("v2.10.0") > hb.updater.parse_version("2.9.9")
    assert hb.updater.parse_version("v.2.0.2") == (2, 0, 2)
