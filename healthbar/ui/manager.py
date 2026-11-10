"""The main (manager) window."""
import logging
import secrets
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

from .. import APP_VERSION, config, ddb, obs, overlay, system, theme, updater
from ..theme import (BTN_CLOSE_BD, BTN_CLOSE_BG, BTN_CLOSE_FG, BTN_EDIT_BD, BTN_EDIT_BG,
                     BTN_EDIT_FG, BTN_OPEN_BD, BTN_OPEN_BG, BTN_OPEN_FG, BTN_SAVE_BD, BTN_SAVE_BG,
                     BTN_SAVE_FG, DANGER_BD, DANGER_BG, DANGER_FG, ERR_FG, F_BADGE, F_BOLD, F_MED,
                     F_SMALL, F_TINY, F_TITLE, HP_TEMP, MGR_BG, MGR_BORDER, MGR_BORDER2, MGR_BORDER3,
                     MGR_HEADER, MGR_PILL, MGR_ROW, OK_FG, T_DIM, T_MUTED, T_PRIMARY, WARN_FG)
from .character_window import CharacterWindow
from .common import Tooltip, ToggleSwitch, mk_sep, popup_menu, run_on_ui, styled_button
from .dialogs import CharacterDialog, GameDialog, HPDialog, OBSDialog, SettingsDialog

log = logging.getLogger("dnd_healthbar")

try:
    import pystray
    from pystray import MenuItem as TrayItem
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

BANNER_BG = "#173a2a"


class ManagerWindow:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root = root
        self.cfg  = cfg
        self._windows:     dict[str, CharacterWindow] = {}
        self._hp_data:     dict[str, dict]  = {}
        self._status:      dict[str, tuple] = {}     # cid → (msg, kind)
        self._hp_toggles:  dict[str, tk.BooleanVar] = {}
        self._row_widgets: dict[str, dict]  = {}
        self._hp_dialogs:  dict[str, HPDialog] = {}
        self._save_warned = False
        self._update_info = None
        prefs = cfg.setdefault("sort", {})
        self._sort_mode   = prefs.get("mode", "alpha_asc")
        self._live_on_top = prefs.get("live_on_top", True)

        root.title(f"D&D Health Bar  v{APP_VERSION}")
        root.configure(bg=MGR_BG)
        root.resizable(True, True)
        root.minsize(470, 320)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)
        root.report_callback_exception = lambda *a: log.error("UI error", exc_info=a)
        config.SAVE_ERROR_HANDLER = lambda msg: run_on_ui(lambda: self._on_save_error(msg))

        self._build_ui()
        self._update_sort_btn_styles()
        self._refresh_games(prefer_id=cfg.get("last_game"))

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=MGR_HEADER)
        hdr.pack(fill="x")
        self._logo_img = theme.make_icon(36)
        from PIL import ImageTk
        self._logo_photo = ImageTk.PhotoImage(self._logo_img)
        tk.Label(hdr, image=self._logo_photo, bg=MGR_HEADER).pack(side="left", padx=(12, 8), pady=8)
        tcol = tk.Frame(hdr, bg=MGR_HEADER)
        tcol.pack(side="left")
        tk.Label(tcol, text="D&D Health Bar", bg=MGR_HEADER, fg=T_PRIMARY, font=F_TITLE).pack(anchor="w")
        tk.Label(tcol, text=f"v{APP_VERSION}  ·  live HP for D&D Beyond", bg=MGR_HEADER, fg=T_DIM,
                 font=F_TINY).pack(anchor="w")
        links = tk.Frame(hdr, bg=MGR_HEADER)
        links.pack(side="right", padx=10)
        for text, cmd, tip in [
            ("⚙", self._open_settings, "Settings: check interval, colours, autostart, updates, data folder"),
            ("OBS", lambda: self._open_obs_dialog(), "Connect to OBS and add overlays automatically"),
            ("URLs ↗", self._open_overlay_index, "Show all overlay URLs and options in the browser"),
        ]:
            b = styled_button(links, text, MGR_HEADER, BTN_OPEN_FG, MGR_BORDER3, cmd, font=F_SMALL)
            b.pack(side="left", padx=(4, 0), ipadx=6, ipady=2)
            Tooltip(b, tip)
        self._hdr_sep = mk_sep(self.root, MGR_BORDER)
        self._banner = tk.Frame(self.root, bg=BANNER_BG)       # packed when an update exists

        gbar = tk.Frame(self.root, bg=MGR_HEADER, pady=7)
        gbar.pack(fill="x", padx=10)
        self._game_var = tk.StringVar()
        self._game_btn = tk.Button(gbar, textvariable=self._game_var, bg=MGR_PILL, fg=T_PRIMARY,
                                   font=F_BOLD, relief="flat", bd=0, highlightthickness=1,
                                   highlightbackground=MGR_BORDER3, activebackground=MGR_BORDER2,
                                   activeforeground=T_PRIMARY, anchor="w", padx=10, cursor="hand2",
                                   command=self._game_menu_popup)
        self._game_btn.pack(side="left", fill="x", expand=True, ipady=5)
        Tooltip(self._game_btn, "Switch game")
        for txt, col, bdc, cmd, tip in [("✎", BTN_EDIT_BG, BTN_EDIT_BD, self._edit_game, "Rename this game"),
                                        ("＋", BTN_EDIT_BG, BTN_EDIT_BD, self._add_game, "Add a game"),
                                        ("✕", DANGER_BG, DANGER_BD, self._delete_game, "Delete this game")]:
            b = styled_button(gbar, txt, col, BTN_EDIT_FG if col != DANGER_BG else DANGER_FG,
                              bdc, cmd, font=F_MED, width=3)
            b.pack(side="left", padx=(4, 0), ipady=5)
            Tooltip(b, tip)
        mk_sep(self.root, MGR_BORDER)

        sbar = tk.Frame(self.root, bg=MGR_HEADER, pady=5)
        sbar.pack(fill="x", padx=10)
        tk.Label(sbar, text="Sort:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(side="left", padx=(0, 4))
        self._sort_btns = {}
        for group, label, tip in [("alpha", "A–Z", "Sort by name (click again to reverse)"),
                                  ("hp", "HP", "Sort by current HP (click again to reverse)"),
                                  ("manual", "Manual", "Your own order — use the arrows")]:
            btn = tk.Button(sbar, text=label, font=F_TINY, cursor="hand2", relief="flat", bd=0,
                            padx=8, pady=2, highlightthickness=1,
                            command=lambda g=group: self._cycle_sort(g))
            btn.pack(side="left", padx=2)
            Tooltip(btn, tip)
            self._sort_btns[group] = btn
        tk.Frame(sbar, bg=MGR_HEADER, width=12).pack(side="left")
        lt = tk.Label(sbar, text="Live on top:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY)
        lt.pack(side="left", padx=(0, 4))
        self._live_top_var = tk.BooleanVar(value=self._live_on_top)
        ts = ToggleSwitch(sbar, self._live_top_var, command=self._on_live_top_toggle, bg=MGR_HEADER)
        ts.pack(side="left")
        for w in (lt, ts):
            Tooltip(w, "Show characters that are live (▶) at the top")
        mk_sep(self.root, MGR_BORDER)

        self._char_frame = tk.Frame(self.root, bg=MGR_BG)
        self._char_frame.pack(fill="both", expand=True, padx=8, pady=6)
        mk_sep(self.root, MGR_BORDER)

        add_frame = tk.Frame(self.root, bg=MGR_BG, pady=6)
        add_frame.pack(fill="x", padx=10)
        bulk = tk.Frame(add_frame, bg=MGR_BG)
        bulk.pack(fill="x", pady=(0, 4))
        self._open_all_btn = styled_button(bulk, "▶▶  Open all", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
                                           self._open_all_windows)
        self._open_all_btn.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        Tooltip(self._open_all_btn, "Go live with every character of this game")
        self._close_all_btn = styled_button(bulk, "■■  Close all", BTN_CLOSE_BG, BTN_CLOSE_FG,
                                            BTN_CLOSE_BD, self._close_all_windows)
        self._close_all_btn.pack(side="left", fill="x", expand=True, ipady=5)
        Tooltip(self._close_all_btn, "Stop all characters (overlays fade out)")
        tk.Button(add_frame, text="＋  Add character", bg=MGR_BG, fg=T_MUTED, relief="flat", bd=0,
                  highlightthickness=1, highlightbackground=MGR_BORDER2, activebackground=MGR_BORDER2,
                  activeforeground=T_DIM, font=F_SMALL, cursor="hand2",
                  command=self._add_character).pack(fill="x", ipady=5)
        mk_sep(self.root, MGR_BORDER)

        self._status_bar = tk.Frame(self.root, bg=MGR_HEADER, pady=4)
        self._status_bar.pack(fill="x", padx=10)
        self._status_label = tk.Label(self._status_bar, text="", bg=MGR_HEADER, fg=T_MUTED,
                                      font=F_TINY, anchor="w", justify="left")
        self._status_label.pack(fill="x")
        self._status_bar.bind("<Configure>",
                              lambda e: self._status_label.config(wraplength=max(200, e.width - 10)))

    def flash_status(self, text: str, color=BTN_OPEN_FG, ms: int = 5000):
        self._status_label.config(text=text, fg=color)
        self.root.after(ms, self._update_status_bar)

    # ── Updates ──────────────────────────────────────────────────────────────
    def check_updates_async(self):
        if not self.cfg.get("check_updates", True):
            return
        def work():
            try:
                info = updater.check_for_update()
            except Exception as e:
                log.info("Update check failed: %s", e)
                return
            if info:
                run_on_ui(lambda: self._show_update(info))
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _show_update(self, info: dict):
        tag = info["tag"]
        if self.cfg.get("dismissed_update") == tag:
            return
        self._update_info = info
        for w in self._banner.winfo_children():
            w.destroy()
        self._banner_label = tk.Label(self._banner, text=f"⬆  Version {tag.lstrip('v.')} is available",
                                      bg=BANNER_BG, fg=OK_FG, font=F_MED)
        self._banner_label.pack(side="left", padx=(12, 8), pady=6)
        if updater.can_self_update(info):
            self._banner_btn = styled_button(self._banner, "Update now", "#1f4d36", OK_FG, "#2e6b4c",
                                             self._self_update, font=F_TINY)
            Tooltip(self._banner_btn, "Download, replace this program and restart. "
                                      "Your settings and portraits stay as they are.")
        else:
            self._banner_btn = styled_button(self._banner, "Download", "#1f4d36", OK_FG, "#2e6b4c",
                                             lambda: webbrowser.open(info["url"]), font=F_TINY)
        self._banner_btn.pack(side="left", ipadx=8, ipady=2)
        notes = tk.Label(self._banner, text="What's new", bg=BANNER_BG, fg=T_DIM, font=F_TINY,
                         cursor="hand2")
        notes.pack(side="left", padx=8)
        notes.bind("<Button-1>", lambda _e: webbrowser.open(info["url"]))

        def dismiss():
            self.cfg["dismissed_update"] = tag
            config.save_config(self.cfg)
            self._banner.pack_forget()
        x = styled_button(self._banner, "✕", BANNER_BG, T_DIM, BANNER_BG, dismiss, font=F_TINY)
        x.pack(side="right", padx=8)
        Tooltip(x, "Hide until the next version")
        self._banner.pack(fill="x", after=self._hdr_sep)

    def _self_update(self):
        info = self._update_info
        exe  = sys.executable
        new  = exe + ".new"
        self._banner_btn.config(state="disabled", text="Downloading…")

        def progress(frac):
            run_on_ui(lambda: self._banner_label.config(text=f"⬇  Downloading {int(frac * 100)} %"))

        def work():
            try:
                updater.download(info, new, progress)
            except Exception as e:
                log.error("Update download failed: %s", e)
                msg = str(e)
                run_on_ui(lambda: self._update_failed(msg))
                return
            run_on_ui(lambda: self._install_update(new, exe))
        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _update_failed(self, msg):
        self._banner_label.config(text="⚠  Update failed", fg=WARN_FG)
        self._banner_btn.config(state="normal", text="Download manually",
                                command=lambda: webbrowser.open(self._update_info["url"]))
        messagebox.showwarning("Update", f"The update could not be downloaded:\n{msg}\n\n"
                               "You can download it manually from the release page.", parent=self.root)

    def _install_update(self, new, exe):
        self._banner_label.config(text="Restarting with the new version…")
        self.root.update_idletasks()
        try:
            updater.launch_replacer(new, exe)
        except Exception as e:
            self._update_failed(str(e))
            return
        self._on_quit()

    # ── Save errors ──────────────────────────────────────────────────────────
    def _on_save_error(self, msg: str):
        self._status_label.config(text=f"⚠ Settings could not be saved: {msg}", fg=ERR_FG)
        if not self._save_warned:
            self._save_warned = True
            messagebox.showwarning("D&D Health Bar",
                                   f"Your settings could not be saved.\n\n{msg}\n\nIf the folder is "
                                   "synced (e.g. Proton Drive, OneDrive), the sync client may be holding "
                                   "the file. The app keeps retrying on every change.", parent=self.root)

    # ── Games ────────────────────────────────────────────────────────────────
    def _games(self):
        return self.cfg.setdefault("games", [])

    def _current_game(self):
        sel = self._game_var.get()
        return next((g for g in self._games() if g["name"] == sel), None)

    def _game_menu_popup(self):
        if not self._games():
            return
        menu = popup_menu(self.root)
        for g in self._games():
            menu.add_command(label=g["name"], command=lambda gg=g: self._select_game(gg))
        menu.tk_popup(self._game_btn.winfo_rootx(),
                      self._game_btn.winfo_rooty() + self._game_btn.winfo_height())

    def _select_game(self, g):
        self._game_var.set(g["name"])
        self._remember_game(g)
        self._refresh_chars()

    def _remember_game(self, g):
        if g and self.cfg.get("last_game") != g.get("id"):
            self.cfg["last_game"] = g.get("id")
            config.save_config(self.cfg)

    def _refresh_games(self, prefer_id=None):
        games = self._games()
        names = [g["name"] for g in games]
        preferred = next((g for g in games if prefer_id and g.get("id") == prefer_id), None)
        if preferred:
            self._game_var.set(preferred["name"])
        elif names and self._game_var.get() not in names:
            self._game_var.set(names[0])
        elif not names:
            self._game_var.set("  No games yet  ")
        self._refresh_chars()

    def _add_game(self):
        dlg = GameDialog(self.root, {})
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        g = {"id": secrets.token_hex(4), "name": dlg.result["name"], "characters": []}
        self._games().append(g)
        self._select_game(g)
        config.save_config(self.cfg)

    def _edit_game(self):
        g = self._current_game()
        if not g:
            return
        dlg = GameDialog(self.root, g.copy())
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        g["name"] = dlg.result["name"]
        config.save_config(self.cfg)
        self._game_var.set(g["name"])
        self._refresh_chars()

    def _delete_game(self):
        g = self._current_game()
        if not g:
            return
        if not messagebox.askyesno("Delete game", f"Delete '{g['name']}' and all its characters?",
                                   parent=self.root):
            return
        for ch in g.get("characters", []):
            self._close_window(ch["character_id"])
        self.cfg["games"] = [x for x in self._games() if x is not g]
        config.save_config(self.cfg)
        self._refresh_games()

    # ── Sort ─────────────────────────────────────────────────────────────────
    _SORT_CYCLES = {"alpha": [None, "alpha_asc", "alpha_desc"],
                    "hp": [None, "hp_asc", "hp_desc"],
                    "manual": [None, "manual"]}
    _SORT_LABELS = {None:         {"alpha": "A–Z",   "hp": "HP",   "manual": "Manual"},
                    "alpha_asc":  {"alpha": "A–Z ↑", "hp": "HP",   "manual": "Manual"},
                    "alpha_desc": {"alpha": "A–Z ↓", "hp": "HP",   "manual": "Manual"},
                    "hp_asc":     {"alpha": "A–Z",   "hp": "HP ↑", "manual": "Manual"},
                    "hp_desc":    {"alpha": "A–Z",   "hp": "HP ↓", "manual": "Manual"},
                    "manual":     {"alpha": "A–Z",   "hp": "HP",   "manual": "Manual ✓"}}

    def _sort_group(self):
        if self._sort_mode in ("alpha_asc", "alpha_desc"): return "alpha"
        if self._sort_mode in ("hp_asc", "hp_desc"):       return "hp"
        if self._sort_mode == "manual":                    return "manual"
        return None

    def _cycle_sort(self, group: str):
        cycle = self._SORT_CYCLES[group]
        if self._sort_group() != group:
            self._sort_mode = cycle[1]
        else:
            i = cycle.index(self._sort_mode) if self._sort_mode in cycle else 0
            self._sort_mode = cycle[(i + 1) % len(cycle)]
        self.cfg["sort"]["mode"] = self._sort_mode
        config.save_config(self.cfg)
        self._refresh_chars()

    def _on_live_top_toggle(self):
        self._live_on_top = self._live_top_var.get()
        self.cfg["sort"]["live_on_top"] = self._live_on_top
        config.save_config(self.cfg)
        self._refresh_chars()

    def _update_sort_btn_styles(self):
        labels = self._SORT_LABELS.get(self._sort_mode, self._SORT_LABELS[None])
        active = self._sort_group()
        for group, btn in self._sort_btns.items():
            on = group == active
            btn.config(text=labels[group], bg=BTN_SAVE_BG if on else MGR_ROW,
                       fg=BTN_SAVE_FG if on else T_DIM,
                       highlightbackground=BTN_SAVE_BD if on else MGR_BORDER2)

    def _info_for(self, ch) -> dict | None:
        """HP info to display for a row: live data, or the stored HP of a
        manual character even while it isn't live."""
        cid = ch["character_id"]
        if cid in self._hp_data:
            return self._hp_data[cid]
        return ddb.manual_info(ch) if ddb.is_manual(ch) else None

    def _sorted_characters(self, characters: list) -> list:
        chars = list(characters)
        live  = set(self._windows)
        if self._sort_mode == "alpha_asc":
            chars.sort(key=lambda c: c.get("name", "").lower())
        elif self._sort_mode == "alpha_desc":
            chars.sort(key=lambda c: c.get("name", "").lower(), reverse=True)
        elif self._sort_mode in ("hp_asc", "hp_desc"):
            pct = lambda c: (self._info_for(c) or {}).get("pct")
            known   = [c for c in chars if pct(c) is not None]
            unknown = [c for c in chars if pct(c) is None]
            known.sort(key=pct, reverse=self._sort_mode == "hp_desc")
            chars = known + unknown
        if self._live_on_top:
            chars = [c for c in chars if c["character_id"] in live] + \
                    [c for c in chars if c["character_id"] not in live]
        return chars

    def _move_character(self, cid: str, direction: int):
        g = self._current_game()
        if not g:
            return
        chars = g["characters"]
        order = self._sorted_characters(chars)
        i = next((k for k, c in enumerate(order) if c["character_id"] == cid), None)
        if i is None or not 0 <= i + direction < len(order):
            return
        other = order[i + direction]["character_id"]
        a = next(k for k, c in enumerate(chars) if c["character_id"] == cid)
        b = next(k for k, c in enumerate(chars) if c["character_id"] == other)
        chars[a], chars[b] = chars[b], chars[a]
        config.save_config(self.cfg)
        self._refresh_chars()

    # ── Character rows ───────────────────────────────────────────────────────
    def _refresh_chars(self):
        self._row_widgets.clear()
        for w in self._char_frame.winfo_children():
            w.destroy()
        g = self._current_game()
        if g is None or not g.get("characters"):
            msg = ("Add a game with ＋ above to get started." if g is None
                   else "No characters yet — add one below.")
            tk.Label(self._char_frame, text=msg, bg=MGR_BG, fg=T_MUTED, font=F_SMALL).pack(pady=16)
        else:
            for ch in self._sorted_characters(g["characters"]):
                self._make_char_row(ch, g)
        self._update_sort_btn_styles()
        self._update_status_bar()

    def _status_color(self, cid) -> str:
        if cid not in self._windows:
            return "#2a3c4a"
        return {"ok": OK_FG, "error": ERR_FG}.get(self._status.get(cid, ("", "busy"))[1], WARN_FG)

    def _make_char_row(self, ch, game):
        cid     = ch["character_id"]
        manual  = ddb.is_manual(ch)
        is_open = cid in self._windows
        row = tk.Frame(self._char_frame, bg=MGR_ROW, highlightthickness=1,
                       highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
        row.pack(fill="x", pady=5)
        inner = tk.Frame(row, bg=MGR_ROW)
        inner.pack(fill="x", padx=10, pady=8)

        if self._sort_mode == "manual":
            order = self._sorted_characters(game.get("characters", []))
            i = next((k for k, c in enumerate(order) if c["character_id"] == cid), 0)
            col = tk.Frame(inner, bg=MGR_ROW)
            col.pack(side="left", padx=(0, 4))
            for text, d, disabled in [("↑", -1, i == 0), ("↓", 1, i == len(order) - 1)]:
                tk.Button(col, text=text, font=F_TINY, width=2,
                          bg=MGR_ROW if disabled else BTN_EDIT_BG,
                          fg=MGR_BORDER2 if disabled else BTN_EDIT_FG, relief="flat", bd=0,
                          highlightthickness=1, highlightbackground=MGR_BORDER2,
                          cursor="arrow" if disabled else "hand2",
                          state="disabled" if disabled else "normal",
                          command=lambda c=cid, dd=d: self._move_character(c, dd)).pack(pady=(0, 1))

        cvs = tk.Canvas(inner, width=38, height=38, bg=MGR_ROW, highlightthickness=0)
        cvs.pack(side="left", padx=(0, 8))
        self._draw_thumb(cvs, ch)

        info_f = tk.Frame(inner, bg=MGR_ROW)
        info_f.pack(side="left", fill="x", expand=True)
        name_lbl = tk.Label(info_f, text=ch.get("name", "Unknown"), bg=MGR_ROW, fg=T_PRIMARY,
                            font=F_BOLD, anchor="w")
        name_lbl.pack(anchor="w")
        id_lbl = tk.Label(info_f, text="Manual · NPC" if manual else cid, bg=MGR_ROW,
                          fg=HP_TEMP if manual else T_DIM, font=F_TINY, anchor="w")
        id_lbl.pack(anchor="w")

        badge_f = tk.Frame(inner, bg=MGR_ROW)
        badge_f.pack(side="left", padx=6)
        badge = tk.Label(badge_f, padx=7, pady=2, highlightthickness=1)
        badge.pack()
        hp = self._info_for(ch) if (is_open or manual) else None
        self._style_badge(badge, hp)
        mini = tk.Canvas(inner, width=56, height=5, bg=MGR_ROW, highlightthickness=0)
        mini.pack(side="left", padx=(0, 4))
        self._draw_mini_bar(mini, hp)
        if manual:
            badge.config(cursor="hand2")
            badge.bind("<Button-1>", lambda _e, c=ch: self._open_hp_dialog(c))
            badge.bind("<MouseWheel>", lambda e, c=ch: self._wheel_hp(c, e))
            Tooltip(badge, "Click to damage / heal · mouse wheel = ±1 HP")
        else:
            Tooltip(badge, "Current / maximum HP  (+ temporary HP)")

        if cid not in self._hp_toggles:
            self._hp_toggles[cid] = tk.BooleanVar(value=bool(ch.get("show_hp_numbers", False)))
        hp_var = self._hp_toggles[cid]

        def on_hp_toggle(c=ch, cid=cid, var=hp_var):
            c["show_hp_numbers"] = var.get()
            config.save_config(self.cfg)
            if cid in self._windows:
                self._windows[cid].refresh_visibility()
        tog_col = tk.Frame(inner, bg=MGR_ROW)
        tog_col.pack(side="left", padx=(0, 4))
        tk.Label(tog_col, text="HP", bg=MGR_ROW, fg=T_DIM, font=F_TINY).pack()
        tog = ToggleSwitch(tog_col, hp_var, command=on_hp_toggle, bg=MGR_ROW)
        tog.pack()
        Tooltip(tog, "Show HP numbers on the overlay")

        dot = tk.Canvas(inner, width=10, height=10, bg=MGR_ROW, highlightthickness=0)
        dot.pack(side="left", padx=(0, 6))
        dot_oval = dot.create_oval(1, 1, 9, 9, fill=self._status_color(cid), outline="")
        Tooltip(dot, lambda c=cid: self._status.get(c, ("", ""))[0] if c in self._windows
                else "Not live — press ▶")

        btns = tk.Frame(inner, bg=MGR_ROW)
        btns.pack(side="right")
        open_btn = styled_button(btns, "▶", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
                                 lambda c=ch: self._toggle_window(c), width=3)
        open_btn.pack(side="left", padx=(0, 3), ipady=4)
        Tooltip(open_btn, lambda c=cid: "Stop: close the overlay (fades out on stream)"
                if c in self._windows else "Go live: open the overlay and show it on stream")
        more = styled_button(btns, "⋯", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD, None, width=3)
        more.config(command=lambda c=ch, g=game, b=more: self._row_menu(
            c, g, b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
        more.pack(side="left", ipady=4)
        Tooltip(more, "More: OBS, URL, edit, delete …")

        self._row_widgets[cid] = {"row": row, "badge": badge, "dot": dot, "dot_oval": dot_oval,
                                  "mini_bar": mini, "open_btn": open_btn, "thumb": cvs}
        self._style_open_btn(open_btn, is_open)

        popup = lambda e, c=ch, g=game: self._row_menu(c, g, e.x_root, e.y_root)
        for w in (row, inner, info_f, name_lbl, id_lbl, cvs, badge_f):
            w.bind("<Button-3>", popup)
        for w in (cvs, name_lbl, id_lbl):
            w.bind("<Double-Button-1>", lambda _e, c=ch, g=game: self._edit_character(c, g))
            Tooltip(w, "Double-click to edit · right-click for more")

    def _row_menu(self, ch, game, x, y):
        m = popup_menu(self.root)
        if ddb.is_manual(ch):
            m.add_command(label="Change HP…", command=lambda: self._open_hp_dialog(ch))
            m.add_separator()
        m.add_command(label="Add to OBS", command=lambda: self._send_to_obs([ch]))
        m.add_command(label="Copy overlay URL", command=lambda: self._copy_overlay_url(ch))
        m.add_command(label="Preview overlay in browser", command=lambda: self._preview_overlay(ch))
        m.add_separator()
        m.add_command(label="Edit…", command=lambda: self._edit_character(ch, game))
        if not ddb.is_manual(ch):
            m.add_command(label="Copy diagnostics (for troubleshooting)",
                          command=lambda: self._copy_diagnostics(ch))
        m.add_command(label="Delete…", foreground=DANGER_FG,
                      command=lambda: self._delete_character(ch, game))
        m.tk_popup(x, y)

    def _style_open_btn(self, btn, is_open):
        if is_open:
            btn.config(text="■", bg=BTN_CLOSE_BG, fg=BTN_CLOSE_FG, activebackground=BTN_CLOSE_BD,
                       highlightbackground=BTN_CLOSE_BD)
        else:
            btn.config(text="▶", bg=BTN_OPEN_BG, fg=BTN_OPEN_FG, activebackground=BTN_OPEN_BD,
                       highlightbackground=BTN_OPEN_BD)

    def _style_badge(self, badge, hp):
        state = theme.display_state(hp)
        fg, bg, bd = theme.badge_colors(state)
        if hp and hp.get("pct") is not None:
            badge.config(text=theme.hp_text(hp), bg=bg, fg=fg, highlightbackground=bd, font=F_BADGE)
        else:
            badge.config(text="—", bg=bg, fg=fg, highlightbackground=bd, font=F_TINY)

    def _draw_mini_bar(self, canvas, hp):
        canvas.delete("all")
        w, h = int(canvas["width"]), int(canvas["height"])
        canvas.create_rectangle(0, 0, w, h, fill=MGR_BORDER2, outline="")
        if not hp or hp.get("pct") is None:
            for x in range(0, w, 8):
                canvas.create_rectangle(x, 0, x + 4, h, fill="#2a3a44", outline="")
            return
        total = max(hp["mx"], hp["cur"] + hp.get("temp", 0)) or 1
        if hp.get("temp"):
            canvas.create_rectangle(0, 0, int(w * (hp["cur"] + hp["temp"]) / total), h,
                                    fill=HP_TEMP, outline="")
        fw = int(w * hp["cur"] / total)
        if fw > 0:
            canvas.create_rectangle(0, 0, fw, h, fill=theme.state_color(theme.display_state(hp)),
                                    outline="")

    def _draw_thumb(self, canvas, ch):
        canvas.delete("all")
        photo = theme.thumb_photo(config.resolve_portrait_path(ch, "full"), 38, MGR_ROW, 8)
        canvas._photo = photo
        canvas.create_image(19, 19, image=photo)

    def _update_row(self, cid: str):
        w = self._row_widgets.get(cid)
        if not w:
            return
        ch = self._find_char(cid)
        is_open = cid in self._windows
        try:
            w["row"].config(highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
            self._style_open_btn(w["open_btn"], is_open)
            hp = self._info_for(ch) if ch and (is_open or ddb.is_manual(ch)) else None
            self._style_badge(w["badge"], hp)
            self._draw_mini_bar(w["mini_bar"], hp)
            w["dot"].itemconfig(w["dot_oval"], fill=self._status_color(cid))
        except tk.TclError:
            pass

    def _find_char(self, cid):
        for g in self._games():
            for c in g.get("characters", []):
                if c["character_id"] == cid:
                    return c
        return None

    # ── Manual characters ────────────────────────────────────────────────────
    def _open_hp_dialog(self, ch):
        cid = ch["character_id"]
        dlg = self._hp_dialogs.get(cid)
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.focus_force()
            return
        self._hp_dialogs[cid] = HPDialog(self.root, ch, self._on_manual_hp_changed)

    def _wheel_hp(self, ch, event):
        ddb.apply_hp_change(ch, "heal" if event.delta > 0 else "damage", 1)
        self._on_manual_hp_changed(ch)

    def _on_manual_hp_changed(self, ch):
        cid = ch["character_id"]
        config.save_config(self.cfg)
        win = self._windows.get(cid)
        if win:
            win.show_info(ddb.manual_info(ch))      # → _on_hp_update → overlay
        else:
            self._update_row(cid)
        dlg = self._hp_dialogs.get(cid)
        if dlg is not None and dlg.winfo_exists():
            dlg.refresh()

    # ── Live windows ─────────────────────────────────────────────────────────
    def _toggle_window(self, ch):
        cid = ch["character_id"]
        if cid in self._windows:
            self._close_window(cid)
        else:
            self._open_window(ch)
        self._update_row(cid)
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)

    def _open_window(self, ch):
        cid = ch["character_id"]
        self._status[cid] = ("Connecting…", "busy")
        self._windows[cid] = CharacterWindow(
            master=self.root, char=ch,
            on_closed=lambda c=cid: self._on_window_closed(c),
            on_hp_update=self._on_hp_update, status_cb=self._on_status_update,
            on_char_changed=self._on_char_changed)
        overlay.HUB.set_live(cid, True)

    def _close_window(self, cid):
        if cid in self._windows:
            self._windows[cid].close()            # → _on_window_closed
        self._update_status_bar()

    def _on_window_closed(self, cid):
        overlay.HUB.set_live(cid, False)
        self._windows.pop(cid, None)
        self._hp_data.pop(cid, None)
        self._status.pop(cid, None)
        config.save_config(self.cfg)              # saves the window position
        self.root.after(0, lambda c=cid: self._update_row(c))
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)
        self.root.after(0, self._update_status_bar)

    def _on_hp_update(self, cid, info: dict):
        """Main thread (from CharacterWindow.show_info)."""
        self._hp_data[cid] = info
        overlay.HUB.update_hp(cid, info)
        self._update_row(cid)
        if self._sort_mode in ("hp_asc", "hp_desc") or self._live_on_top:
            self._reorder_rows()

    def _on_char_changed(self, ch):
        """A worker changed the character (e.g. downloaded its avatar)."""
        config.save_config(self.cfg)
        w = self._row_widgets.get(ch["character_id"])
        if w:
            self._draw_thumb(w["thumb"], ch)

    def _reorder_rows(self):
        g = self._current_game()
        if not g or not g.get("characters"):
            return
        new_order = [c["character_id"] for c in self._sorted_characters(g["characters"])]
        by_row = {id(w["row"]): cid for cid, w in self._row_widgets.items()}
        if [by_row.get(id(w)) for w in self._char_frame.pack_slaves()] == new_order:
            return
        for cid in new_order:
            w = self._row_widgets.get(cid)
            if w:
                try:
                    w["row"].pack_forget()
                    w["row"].pack(fill="x", pady=5)      # must match _make_char_row
                except tk.TclError:
                    pass

    def _on_status_update(self, cid, msg, kind):
        """Worker threads."""
        def do():
            if cid not in self._windows:
                return
            self._status[cid] = (msg, kind)
            w = self._row_widgets.get(cid)
            if w:
                try: w["dot"].itemconfig(w["dot_oval"], fill=self._status_color(cid))
                except tk.TclError: pass
            self._update_status_bar()
        run_on_ui(do)

    def _update_status_bar(self):
        if not self._windows:
            self._status_label.config(text="No characters live — press ▶ to go live", fg=T_MUTED)
        else:
            errors = [(c, m) for c, (m, k) in self._status.items() if k == "error" and c in self._windows]
            if errors:
                self._status_label.config(fg=WARN_FG, text="   ·   ".join(
                    f"{self._windows[c].char.get('name', '?')}: {m}" for c, m in errors))
            else:
                names = ", ".join(w.char.get("name", "?") for w in self._windows.values())
                self._status_label.config(fg=T_DIM, text=f"Live: {names}  ·  D&D Beyond checked "
                                                         f"every {config.poll_interval()}s")
        g = self._current_game()
        chars = g.get("characters", []) if g else []
        all_open  = bool(chars) and all(c["character_id"] in self._windows for c in chars)
        none_open = not self._windows
        try:
            self._open_all_btn.config(state="disabled" if all_open or not chars else "normal",
                                      bg=MGR_ROW if (all_open or not chars) else BTN_OPEN_BG,
                                      fg=T_MUTED if (all_open or not chars) else BTN_OPEN_FG)
            self._close_all_btn.config(state="disabled" if none_open else "normal",
                                       bg=MGR_ROW if none_open else BTN_CLOSE_BG,
                                       fg=T_MUTED if none_open else BTN_CLOSE_FG)
        except tk.TclError:
            pass

    def _open_all_windows(self):
        g = self._current_game()
        if not g:
            return
        for ch in g.get("characters", []):
            if ch["character_id"] not in self._windows:
                self._open_window(ch)
        self._refresh_chars()

    def _close_all_windows(self):
        for cid in list(self._windows):
            self._close_window(cid)
        self._refresh_chars()

    # ── OBS / URLs / diagnostics ─────────────────────────────────────────────
    def _server_ok(self) -> bool:
        if overlay.HUB.port:
            return True
        messagebox.showwarning("Overlay", "The overlay server is not running (port in use or "
                               "disabled in the settings).", parent=self.root)
        return False

    def _open_overlay_index(self):
        if self._server_ok():
            webbrowser.open(f"http://127.0.0.1:{overlay.HUB.port}/")

    def _preview_overlay(self, ch):
        if self._server_ok():
            webbrowser.open(overlay.HUB.url_for(ch["character_id"]) + "?always=1&card=1")

    def _copy_overlay_url(self, ch):
        if not self._server_ok():
            return
        url = overlay.HUB.url_for(ch["character_id"])
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.flash_status(f"Copied overlay URL for {ch.get('name', '?')}: {url}")

    def _copy_diagnostics(self, ch):
        self._status_label.config(text=f"Collecting diagnostics for {ch.get('name', '?')}…", fg=T_DIM)
        cid = ch["character_id"]

        def work():
            try:
                text = ddb.diagnostics(cid)
            except Exception as e:
                text = None
                err = str(e)
            def done():
                if text is None:
                    self.flash_status(f"⚠ Could not collect diagnostics: {err}", ERR_FG, 7000)
                    return
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                log.info("Diagnostics for %s:\n%s", cid, text)
                self.flash_status("Diagnostics copied to the clipboard (also written to the log). "
                                  "Paste them wherever you ask for help.", OK_FG, 7000)
            run_on_ui(done)
        threading.Thread(target=work, daemon=True, name="diagnostics").start()

    def _open_obs_dialog(self, then=None):
        g   = self._current_game()
        dlg = OBSDialog(self.root, obs.settings(self.cfg), g["name"] if g and g.get("characters") else None)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        self.cfg["obs"] = dlg.result
        config.save_config(self.cfg)
        if dlg.action == "each" and g:
            self._send_to_obs(g.get("characters", []))
        elif dlg.action == "party" and g:
            self._obs_send([obs.party_item(g)], f"party “{g['name']}”")
        elif then:
            then()

    def _send_to_obs(self, chars: list):
        if not chars or not self._server_ok():
            return
        if not self.cfg.get("obs"):
            self._open_obs_dialog(then=lambda: self._send_to_obs(chars))
            return
        g     = self._current_game()
        order = [c["character_id"] for c in (g.get("characters", []) if g else [])]
        items = [obs.character_item(c, order.index(c["character_id"]) if c["character_id"] in order else 0)
                 for c in chars]
        self._obs_send(items, chars[0].get("name", "?") if len(chars) == 1 else f"{len(chars)} characters")

    def _obs_send(self, items: list, label: str):
        if not self._server_ok():
            return
        settings = obs.settings(self.cfg)
        self._status_label.config(text=f"Sending {label} to OBS…", fg=T_DIM)

        def work():
            try:
                scene, created, updated = obs.add_overlays(settings, items)
                run_on_ui(lambda: self._obs_done(label, scene, created, updated, None))
            except Exception as e:
                msg = str(e)
                log.warning("OBS: %s", msg)
                run_on_ui(lambda: self._obs_done(label, None, 0, 0, msg))
        threading.Thread(target=work, daemon=True, name="obs").start()

    def _obs_done(self, label, scene, created, updated, err):
        if err:
            self._status_label.config(text="OBS: failed", fg=ERR_FG)
            if messagebox.askyesno("OBS", f"{err}\n\nOpen the OBS connection settings?", parent=self.root):
                self._open_obs_dialog()
            return
        parts = [p for p in (f"{created} added" if created else "",
                             f"{updated} updated" if updated else "") if p]
        self.flash_status(f"OBS: {label} → scene '{scene}' ({', '.join(parts)}). "
                          "Press ▶ to show a character on stream.", OK_FG, 7000)

    # ── Settings ─────────────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self.root, self.cfg, HAS_TRAY)
        self.root.wait_window(dlg)
        r = dlg.result
        if not r:
            return
        old_port = (self.cfg.get("overlay_server") or {}).get("port", overlay.DEFAULT_PORT)
        for k in ("poll_interval", "palette", "check_updates", "close_to_tray"):
            self.cfg[k] = r[k]
        self.cfg.setdefault("overlay_server", {"enabled": True})["port"] = r["port"]
        config.apply_settings(self.cfg)
        config.save_config(self.cfg)               # also re-syncs overlays (palette)
        if system.autostart_supported():
            try:
                system.set_autostart(r["autostart"])
            except OSError as e:
                messagebox.showwarning("Settings", f"Could not change autostart: {e}", parent=self.root)
        self._setup_tray()
        ddb.POLLER.poll_now()
        for w in self._windows.values():
            w.redraw()
        self._refresh_chars()
        if r["port"] != old_port:
            messagebox.showinfo("Settings", "The new overlay port is used after you restart the app.",
                                parent=self.root)

    # ── Character CRUD ───────────────────────────────────────────────────────
    def _ensure_avatar(self, ch, url):
        if not url or ddb.is_manual(ch) or config.has_custom_portrait(ch):
            return
        def work():
            try:
                rel = config.download_avatar(url, ch)
            except Exception as e:
                log.warning("Avatar download failed: %s", e)
                return
            if rel:
                def done():
                    ch["avatar"] = rel
                    self._on_char_changed(ch)
                    if ch["character_id"] in self._windows:
                        self._windows[ch["character_id"]].reload_portrait()
                run_on_ui(done)
        threading.Thread(target=work, daemon=True, name="avatar").start()

    def _add_character(self):
        g = self._current_game()
        if not g:
            messagebox.showwarning("No game", "Add a game first (＋ next to the game name).",
                                   parent=self.root)
            return
        dlg = CharacterDialog(self.root, {})
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        if any(c["character_id"] == dlg.result["character_id"] for c in g.get("characters", [])):
            messagebox.showwarning("Already added", "This character is already in this game.",
                                   parent=self.root)
            return
        g.setdefault("characters", []).append(dlg.result)
        config.save_config(self.cfg)
        self._refresh_chars()
        self._ensure_avatar(dlg.result, dlg.avatar_url)

    def _edit_character(self, ch, game):
        old_cid = ch["character_id"]
        dlg = CharacterDialog(self.root, ch.copy())
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        if not ddb.is_manual(dlg.result):
            for k in ("max_hp", "current_hp", "temp_hp"):
                ch.pop(k, None)
        ch.update(dlg.result)
        config.save_config(self.cfg)
        cid = ch["character_id"]
        if old_cid in self._windows:
            w = self._windows[old_cid]
            if cid != old_cid or w.manual != ddb.is_manual(ch):
                self._close_window(old_cid)
                self._open_window(ch)
            else:
                w.set_title(ch.get("name", ""))
                w.apply_window_options()
                w.reload_portrait()
                if w.manual:
                    w.show_info(ddb.manual_info(ch))
        self._refresh_chars()
        self._ensure_avatar(ch, dlg.avatar_url)

    def _delete_character(self, ch, game):
        if not messagebox.askyesno("Delete", f"Remove '{ch.get('name', '?')}' from this game?",
                                   parent=self.root):
            return
        self._close_window(ch["character_id"])
        dlg = self._hp_dialogs.pop(ch["character_id"], None)
        if dlg is not None and dlg.winfo_exists():
            dlg.destroy()
        game["characters"] = [c for c in game["characters"] if c is not ch]
        config.save_config(self.cfg)
        self._refresh_chars()

    def _on_quit(self):
        for cid in list(self._windows):
            self._close_window(cid)
        config.save_config(self.cfg)
        self._stop_tray()
        self.root.destroy()

    # ── Window state / system tray ───────────────────────────────────────────
    _tray = None

    def start_minimized(self):
        if HAS_TRAY and self.cfg.get("close_to_tray", False):
            self._minimize_to_tray()
        else:
            self.root.iconify()

    def _setup_tray(self):
        """✕ quits by default; hiding to the tray is opt-in (Settings)."""
        if HAS_TRAY and self.cfg.get("close_to_tray", False):
            self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

    def _minimize_to_tray(self):
        self.root.withdraw()
        self._stop_tray()                         # a stopped Icon can't be re-run
        menu = pystray.Menu(TrayItem("Show", self._restore_from_tray, default=True),
                            TrayItem("Quit", self._quit_from_tray))
        self._tray = pystray.Icon("DnD Health Bar", theme.make_icon(64), "D&D Health Bar", menu)
        threading.Thread(target=self._tray.run, daemon=True, name="tray").start()

    def _stop_tray(self):
        tray, self._tray = self._tray, None
        if tray:
            try: tray.stop()
            except Exception: pass

    def _restore_from_tray(self, icon=None, item=None):      # pystray thread
        self._stop_tray()
        run_on_ui(self.root.deiconify)

    def _quit_from_tray(self, icon=None, item=None):          # pystray thread
        self._stop_tray()
        run_on_ui(self._on_quit)
