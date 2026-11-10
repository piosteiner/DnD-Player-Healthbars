"""Smoke tests of the real Tk UI with D&D Beyond mocked out."""
import os
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


def pump(root, seconds):
    from healthbar.ui.common import drain_ui_queue
    end = time.time() + seconds
    while time.time() < end:
        drain_ui_queue()
        root.update()
        time.sleep(0.02)


def wait_for(root, cond, seconds=5):
    from healthbar.ui.common import drain_ui_queue
    end = time.time() + seconds
    while time.time() < end:
        drain_ui_queue()
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_manager_live_flow(hb, root, monkeypatch):
    from healthbar.ui.manager import ManagerWindow
    make_image(os.path.join(hb.config.BASE_DIR, "p.png"))
    raw = raw_character(temporaryHitPoints=4, conditions=[{"id": 11}])
    monkeypatch.setattr(hb.ddb, "make_session", lambda cid: object())
    monkeypatch.setattr(hb.ddb, "get_character", lambda s, cid: hb.ddb.parse_character(raw))
    hb.config.POLL_INTERVAL = 2

    ch = {"name": "Thorin", "character_id": "123", "portrait_unscathed": "p.png"}
    npc = {"name": "Goblin", "character_id": "npc00ff00ff", "source": "manual",
           "max_hp": 7, "current_hp": 7, "temp_hp": 0}
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": [ch, npc]},
                     {"id": "eeee0000", "name": "Other", "characters": []}],
           "last_game": "eeee0000"}
    hb.overlay.HUB.sync_config(cfg)
    mgr = ManagerWindow(root, cfg)
    assert mgr._game_var.get() == "Other"                     # remembers the last game
    mgr._select_game(cfg["games"][0])
    assert cfg["last_game"] == "abcd1234"
    assert {"123", "npc00ff00ff"} <= set(mgr._row_widgets)
    assert mgr._row_widgets["npc00ff00ff"]["badge"].cget("text") == "7 / 7"   # manual HP shown

    mgr._open_window(ch)
    mgr._windows["123"].win.geometry("+222+111")
    assert wait_for(root, lambda: (hb.overlay.HUB.state_for("123") or {}).get("loaded"))
    st = hb.overlay.HUB.state_for("123")
    assert st["live"] and (st["cur"], st["mx"], st["temp"]) == (46, 56, 4)
    assert st["conditions"] == ["Poisoned"]
    assert mgr._row_widgets["123"]["badge"].cget("text") == "46 / 56  +4"
    assert wait_for(root, lambda: mgr._status.get("123", ("", ""))[1] == "ok")

    # manual character: live + damage via the HP dialog
    mgr._open_window(npc)
    pump(root, 0.2)
    mgr._open_hp_dialog(npc)
    dlg = mgr._hp_dialogs["npc00ff00ff"]
    dlg._amount.set("3")
    dlg._apply("damage")
    pump(root, 0.2)
    assert npc["current_hp"] == 4
    assert hb.overlay.HUB.state_for("npc00ff00ff")["cur"] == 4
    assert mgr._row_widgets["npc00ff00ff"]["badge"].cget("text") == "4 / 7"
    dlg.destroy()

    mgr._close_window("123")
    assert ch["window_pos"] == [222, 111]
    assert hb.overlay.HUB.state_for("123")["live"] is False
    assert os.path.isfile(hb.config.CONFIG_FILE)


def test_dialogs_build(hb, root):
    from healthbar.ui.dialogs import (CharacterDialog, GameDialog, HPDialog, OBSDialog,
                                      SettingsDialog)
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": []}]}
    npc = {"name": "Goblin", "character_id": "npc1", "source": "manual", "max_hp": 7}
    for dlg in (CharacterDialog(root, {}), CharacterDialog(root, npc), GameDialog(root, {}),
                OBSDialog(root, hb.obs.settings(cfg), "Camp"), SettingsDialog(root, cfg, True),
                HPDialog(root, npc, lambda c: None)):
        root.update()
        dlg.destroy()


def test_character_dialog_ddb_and_manual(hb, root, tmp_path):
    from healthbar.ui.dialogs import CharacterDialog
    outside = make_image(tmp_path / "pic.png")
    dlg = CharacterDialog(root, {})
    dlg._vars["character_id"].set("https://www.dndbeyond.com/characters/987654")
    dlg._vars["name"].set("Luna")
    dlg._portrait_vars["portrait_unscathed"].set(outside)
    dlg._use_for_all(dlg._portrait_vars["portrait_unscathed"])
    dlg._submit()
    r = dlg.result
    assert r["character_id"] == "987654" and r["source"] == "dndbeyond"
    assert r["portrait_dead"] == r["portrait_unscathed"] == "portraits/Luna_987654/unscathed.png"

    dlg = CharacterDialog(root, {})
    dlg._set_mode(True)
    dlg._vars["name"].set("Owlbear")
    dlg._vars["max_hp"].set("59")
    dlg._vars["current_hp"].set("70")                      # clamped to max
    dlg._submit()
    r = dlg.result
    assert r["source"] == "manual" and r["character_id"].startswith("npc")
    assert (r["max_hp"], r["current_hp"], r["temp_hp"]) == (59, 59, 0)
