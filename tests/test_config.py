import json
import os

from conftest import make_image


def test_save_is_atomic_and_keeps_backup(app):
    assert app.save_config({"games": [], "v": 1})
    assert app.save_config({"games": [], "v": 2})
    assert json.load(open(app.CONFIG_FILE, encoding="utf-8"))["v"] == 2
    assert json.load(open(app.CONFIG_FILE + ".bak", encoding="utf-8"))["v"] == 1
    assert not os.path.exists(app.CONFIG_FILE + ".tmp")


def test_damaged_config_is_restored_from_backup(app):
    app.save_config({"games": [{"name": "Old"}]})
    app.save_config({"games": [{"name": "New"}]})
    with open(app.CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write('{"games": [ {"name": "trunc')                  # interrupted write
    cfg, notes = app.load_config()
    assert cfg["games"][0]["name"] == "Old"                    # previous good version
    assert notes and "restored" in notes[0]
    kept = [f for f in os.listdir(app._BASE_DIR) if ".damaged-" in f]
    assert len(kept) == 1                                      # broken file kept, not lost


def test_damaged_config_without_backup_starts_empty_but_keeps_file(app):
    with open(app.CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("not json")
    cfg, notes = app.load_config()
    assert cfg == {"games": []}
    assert notes and "could not be read" in notes[0]
    assert any(".damaged-" in f for f in os.listdir(app._BASE_DIR))


def test_save_failure_is_reported(app, monkeypatch):
    errors = []
    app.SAVE_ERROR_HANDLER = errors.append
    monkeypatch.setattr(app.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    assert app.save_config({"games": []}) is False
    assert errors and "locked" in errors[0]


def test_migration_makes_everything_portable(app, tmp_path):
    base = app._BASE_DIR
    inside  = make_image(os.path.join(base, "thorin.png"))
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    outside = make_image(outside_dir / "hurt.jpg", color="blue")
    cfg = {"games": [{"name": "Camp", "characters": [{
        "name": "Thorin Oak!", "character_id": "123",
        "portrait_unscathed": inside,
        "portrait_injured":   outside,
        "portrait_bloodied":  outside,                  # same image twice → stored once
        "portrait_dead":      "C:/gone/missing.png",    # missing → left alone
    }]}]}
    assert app.migrate_config(cfg)
    ch = cfg["games"][0]["characters"][0]
    assert ch["portrait_unscathed"] == "thorin.png"
    assert ch["portrait_injured"] == "portraits/Thorin Oak_123/injured.jpg"
    assert ch["portrait_bloodied"] == ch["portrait_injured"]
    assert ch["portrait_dead"] == "C:/gone/missing.png"
    assert os.path.isfile(os.path.join(base, "portraits", "Thorin Oak_123", "injured.jpg"))
    assert cfg["games"][0]["id"] and cfg["config_version"] == app.CONFIG_VERSION
    assert app.migrate_config(cfg) is False             # idempotent


def test_portrait_resolution_with_avatar_fallback(app):
    base = app._BASE_DIR
    make_image(os.path.join(base, "inj.png"))
    make_image(os.path.join(base, "av.png"))
    ch = {"portrait_injured": "inj.png", "avatar": "av.png"}
    assert app.resolve_portrait_key(ch, 0.1) == "portrait_injured"   # nearest state
    assert app.resolve_portrait_key(ch, None) == "portrait_injured"
    assert app.resolve_portrait_key({"avatar": "av.png"}, 0.5) == "avatar"
    assert app.resolve_portrait_key({}, 0.5) == ""
    assert app.resolve_portrait_path(ch, 0.1) == os.path.join(base, "inj.png")
