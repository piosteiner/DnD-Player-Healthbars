import json
import os

from conftest import make_image


def test_save_is_atomic_and_keeps_backup(hb):
    c = hb.config
    assert c.save_config({"games": [], "v": 1})
    assert c.save_config({"games": [], "v": 2})
    assert json.load(open(c.CONFIG_FILE, encoding="utf-8"))["v"] == 2
    assert json.load(open(c.CONFIG_FILE + ".bak", encoding="utf-8"))["v"] == 1
    assert not os.path.exists(c.CONFIG_FILE + ".tmp")


def test_damaged_config_is_restored_from_backup(hb):
    c = hb.config
    c.save_config({"games": [{"name": "Old"}]})
    c.save_config({"games": [{"name": "New"}]})
    with open(c.CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write('{"games": [ {"name": "trunc')                  # interrupted write
    cfg, notes = c.load_config()
    assert cfg["games"][0]["name"] == "Old"
    assert notes and "restored" in notes[0]
    assert len([f for f in os.listdir(c.BASE_DIR) if ".damaged-" in f]) == 1


def test_damaged_config_without_backup_starts_empty_but_keeps_file(hb):
    c = hb.config
    with open(c.CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("not json")
    cfg, notes = c.load_config()
    assert cfg == {"games": []}
    assert notes and "could not be read" in notes[0]
    assert any(".damaged-" in f for f in os.listdir(c.BASE_DIR))


def test_save_failure_is_reported(hb, monkeypatch):
    c = hb.config
    errors = []
    c.SAVE_ERROR_HANDLER = errors.append
    monkeypatch.setattr(c.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    assert c.save_config({"games": []}) is False
    assert errors and "locked" in errors[0]


def test_migration_makes_everything_portable(hb, tmp_path):
    c = hb.config
    make_image(os.path.join(c.BASE_DIR, "thorin.png"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = make_image(elsewhere / "hurt.jpg", color="blue")
    cfg = {"games": [{"name": "Camp", "characters": [{
        "name": "Thorin Oak!", "character_id": "123",
        "portrait_unscathed": os.path.join(c.BASE_DIR, "thorin.png"),
        "portrait_injured":   outside,
        "portrait_bloodied":  outside,                  # same image twice → stored once
        "portrait_dead":      "C:/gone/missing.png",    # missing → left alone
    }]}]}
    assert c.migrate_config(cfg)
    ch = cfg["games"][0]["characters"][0]
    assert ch["portrait_unscathed"] == "thorin.png"
    assert ch["portrait_injured"] == "portraits/Thorin Oak_123/injured.jpg"
    assert ch["portrait_bloodied"] == ch["portrait_injured"]
    assert ch["portrait_dead"] == "C:/gone/missing.png"
    assert cfg["games"][0]["id"] and cfg["config_version"] == c.CONFIG_VERSION
    assert c.migrate_config(cfg) is False             # idempotent


def test_portrait_resolution_by_state(hb):
    c = hb.config
    for name in ("inj.png", "crit.png", "dead.png", "av.png"):
        make_image(os.path.join(c.BASE_DIR, name))
    ch = {"portrait_injured": "inj.png", "portrait_critical": "crit.png",
          "portrait_dead": "dead.png", "avatar": "av.png"}
    assert c.resolve_portrait_key(ch, "bloodied") == "portrait_injured"   # nearest healthier
    assert c.resolve_portrait_key(ch, "dying") == "portrait_critical"     # dying ≠ dead
    assert c.resolve_portrait_key(ch, "dead") == "portrait_dead"
    assert c.resolve_portrait_key({"avatar": "av.png"}, "full") == "avatar"
    assert c.resolve_portrait_key({}, "full") == ""


def test_apply_settings(hb):
    hb.config.apply_settings({"poll_interval": 1, "palette": "colorblind"})
    assert hb.config.poll_interval() == hb.config.MIN_POLL
    assert hb.theme.palette_name() == "colorblind"
