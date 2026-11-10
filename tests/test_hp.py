from conftest import raw_character


def test_max_hp_includes_con_and_per_level_bonuses(app):
    raw = raw_character(modifiers={
        "feat":  [{"type": "bonus", "subType": "hit-points-per-level", "value": 2}],          # Tough
        "class": [{"type": "bonus", "subType": "hit-points-per-level", "value": 1,
                   "componentId": 111}],                                                     # scales w/ class lvl 5
    })
    pct, cur, mx = app.calculate_hp(app.parse_character(raw))
    # 40 base + 8 levels * +2 CON + 8 * 2 (Tough) + 5 * 1 (class feature) = 77
    assert (cur, mx) == (67, 77)


def test_temporary_hp_is_separate_from_max(app):
    d = app.parse_character(raw_character(removedHitPoints=0, temporaryHitPoints=5))
    info = app.hp_details(d)
    assert (info["cur"], info["mx"], info["temp"], info["pct"]) == (56, 56, 5, 1.0)
    assert app.hp_text(info) == "56 / 56  +5"


def test_override_and_unconfigured(app):
    d = app.parse_character(raw_character(overrideHitPoints=30, removedHitPoints=40))
    assert app.calculate_hp(d) == (0.0, 0, 30)          # never below 0
    empty = app.parse_character(raw_character(baseHitPoints=0, classes=[], stats=[]))
    assert app.calculate_hp(empty)[0] is None
    assert app.hp_text(app.hp_details(empty)) == "—"


def test_constitution_set_item(app):
    raw = raw_character(modifiers={"item": [{"type": "set", "subType": "constitution-score",
                                             "value": 19}]})          # Amulet of Health
    assert app.parse_character(raw)["conMod"] == 4


def test_conditions_death_saves_and_avatar(app):
    d = app.parse_character(raw_character(
        conditions=[{"id": 11}, {"id": 4, "level": 2}, {"id": 999}],
        deathSaves={"failCount": 1, "successCount": 2, "isStabilized": False}))
    assert d["conditions"] == ["Poisoned", "Exhaustion 2"]
    assert d["deathSaves"] == {"fail": 1, "success": 2, "stable": False}
    assert d["avatar_url"].startswith("https://www.dndbeyond.com/")


def test_hp_states(app):
    assert [app.hp_state(p) for p in (None, 0, 0.1, 0.3, 0.6, 0.9, 1.0)] == \
           ["unknown", "dead", "critical", "bloodied", "injured", "scratched", "full"]


def test_backoff_and_versions(app):
    assert [app.backoff_delay(n) for n in range(1, 8)] == [5, 10, 20, 40, 80, 120, 120]
    assert app.parse_version("v2.10.0") > app.parse_version("2.9.9")
    assert app.parse_version("v.2.0.2") == (2, 0, 2)
