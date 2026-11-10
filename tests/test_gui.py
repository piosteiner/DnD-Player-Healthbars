"""Smoke test of the real Tk UI with D&D Beyond mocked out."""
import os
import queue
import time

import pytest

from conftest import make_image, raw_character

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def pump(app, root, seconds):
    """Run the Tk loop + the app's worker→UI queue for a while."""
    end = time.time() + seconds
    while time.time() < end:
        while True:
            try:
                fn = app._ui_queue.get_nowait()
            except queue.Empty:
                break
            fn()
        root.update()
        time.sleep(0.02)


def test_manager_live_flow(app, root, monkeypatch):
    make_image(os.path.join(app._BASE_DIR, "p.png"))
    raw = raw_character(temporaryHitPoints=4, conditions=[{"id": 11}])
    monkeypatch.setattr(app, "make_session", lambda cid: object())
    monkeypatch.setattr(app, "get_character", lambda s, cid: app.parse_character(raw))
    app.POLL_INTERVAL = 1

    ch = {"name": "Thorin", "character_id": "123", "portrait_unscathed": "p.png"}
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": [ch]}]}
    app.OVERLAY_HUB.sync_config(cfg)
    mgr = app.ManagerWindow(root, cfg)
    assert "123" in mgr._row_widgets

    mgr._open_window(ch)
    mgr._windows["123"].win.geometry("+222+111")
    pump(app, root, 1.5)
    st = app.OVERLAY_HUB.state_for("123")
    assert st["live"] and (st["cur"], st["mx"], st["temp"]) == (46, 56, 4)
    assert st["conditions"] == ["Poisoned"]
    assert mgr._row_widgets["123"]["badge"].cget("text") == "46 / 56  +4"
    assert mgr._status["123"][1] == "ok"

    mgr._close_window("123")
    assert ch["window_pos"] == [222, 111]
    assert app.OVERLAY_HUB.state_for("123")["live"] is False
    assert os.path.isfile(app.CONFIG_FILE)                 # position saved


def test_dialogs_build(app, root):
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": []}]}
    for dlg in (app.CharacterDialog(root, {}), app.GameDialog(root, {}),
                app.OBSDialog(root, app.obs_settings(cfg), "Camp"),
                app.SettingsDialog(root, cfg)):
        root.update()
        dlg.destroy()


def test_character_dialog_imports_portraits(app, root, tmp_path):
    outside = make_image(tmp_path / "pic.png")
    dlg = app.CharacterDialog(root, {})
    dlg._vars["character_id"].set("https://www.dndbeyond.com/characters/987654")
    dlg._vars["name"].set("Luna")
    dlg._portrait_vars["portrait_unscathed"].set(outside)
    dlg._use_for_all(dlg._portrait_vars["portrait_unscathed"])
    dlg._submit()
    r = dlg.result
    assert r["character_id"] == "987654"
    assert r["portrait_dead"] == r["portrait_unscathed"] == "portraits/Luna_987654/unscathed.png"
    assert len(os.listdir(os.path.join(app._BASE_DIR, "portraits", "Luna_987654"))) == 1
