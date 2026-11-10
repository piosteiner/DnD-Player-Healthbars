"""Dialogs: character, HP change (manual characters), game, OBS, settings."""
import os
import re
import secrets
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import requests

from .. import config, ddb, obs, system, theme
from ..theme import (BTN_EDIT_BD, BTN_EDIT_BG, BTN_EDIT_FG, BTN_HEAL_BD, BTN_HEAL_BG,
                     BTN_HEAL_FG, BTN_SAVE_BD, BTN_SAVE_BG, BTN_SAVE_FG, DANGER_BD, DANGER_BG,
                     DANGER_FG, DLG_BG, DLG_ENTRY_BG, ERR_FG, F_BOLD, F_SMALL, F_TINY, HP_TEMP,
                     MGR_BORDER, MGR_BORDER2, MGR_BORDER3, MGR_PILL, MGR_ROW, OK_FG, T_DIM,
                     T_MUTED, T_PRIMARY, T_SECONDARY, WARN_FG)
from .common import (Tooltip, ToggleSwitch, dialog_footer, dialog_frame, field_label, hint,
                     mk_sep, run_on_ui, styled_button, styled_entry, toggle_row)


def _int(var: tk.StringVar, default=None):
    try:
        return int(var.get().strip())
    except ValueError:
        return default


# ── Character ───────────────────────────────────────────────────────────────
class CharacterDialog(tk.Toplevel):
    _STATES = [("portrait_unscathed", "full",      "100%"),
               ("portrait_scratched", "scratched", "75–100%"),
               ("portrait_injured",   "injured",   "50–75%"),
               ("portrait_bloodied",  "bloodied",  "25–50%"),
               ("portrait_critical",  "critical",  "0–25% · dying"),
               ("portrait_dead",      "dead",      "dead")]
    PREVIEW = 52

    def __init__(self, parent, ch: dict):
        super().__init__(parent)
        self.title("Character")
        self.transient(parent)
        self.grab_set()
        self.result     = None
        self.avatar_url = ""
        self._ch        = ch
        self._build(ch)

    def _build(self, ch):
        body = dialog_frame(self, "Edit character" if ch else "Add character")
        self._vars = {}

        # Source switch: D&D Beyond or manual (NPC)
        self._manual = tk.BooleanVar(value=ddb.is_manual(ch))
        seg = tk.Frame(body, bg=DLG_BG)
        seg.pack(fill="x", pady=(0, 6))
        self._seg_btns = {}
        for val, text in [(False, "D&D Beyond character"), (True, "Manual — NPC, monster, companion")]:
            b = tk.Button(seg, text=text, font=F_TINY, relief="flat", bd=0, padx=10, pady=4,
                          cursor="hand2", highlightthickness=1,
                          command=lambda v=val: self._set_mode(v))
            b.pack(side="left", padx=(0, 4))
            self._seg_btns[val] = b

        self._ddb_frame = tk.Frame(body, bg=DLG_BG)
        field_label(self._ddb_frame, "CHARACTER ID OR URL")
        hint(self._ddb_frame, "Paste the D&D Beyond character URL or just the number. "
                              "The character sheet must be public.")
        self._vars["character_id"] = tk.StringVar(
            value="" if ddb.is_manual(ch) else ch.get("character_id", ""))
        self._id_entry = styled_entry(self._ddb_frame, self._vars["character_id"], width=50)
        self._id_entry.pack(fill="x", ipady=4, pady=(0, 2))
        self._vars["character_id"].trace_add("write", lambda *_: self._on_id_changed())
        self._test_label = tk.Label(self._ddb_frame, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY,
                                    wraplength=440, justify="left")
        self._test_label.pack(anchor="w", pady=(2, 0))
        self._test_after_id = None
        self._test_seq = 0

        self._manual_frame = tk.Frame(body, bg=DLG_BG)
        hint(self._manual_frame, "For characters that aren't on D&D Beyond. You change their HP "
                                 "yourself in the app (click the HP badge); they show on stream "
                                 "like everyone else. At 0 HP they count as dead.", pady=(0, 4))
        hp_row = tk.Frame(self._manual_frame, bg=DLG_BG)
        hp_row.pack(fill="x")
        info = ddb.manual_info(ch) if ddb.is_manual(ch) else {"mx": 20, "cur": 20, "temp": 0}
        for key, label, val in [("max_hp", "MAX HP", info["mx"]), ("current_hp", "CURRENT HP", info["cur"]),
                                ("temp_hp", "TEMP HP", info["temp"])]:
            col = tk.Frame(hp_row, bg=DLG_BG)
            col.pack(side="left", padx=(0, 10))
            field_label(col, label)
            self._vars[key] = tk.StringVar(value=str(val))
            styled_entry(col, self._vars[key], width=8).pack(anchor="w", ipady=4)

        self._name_anchor = tk.Frame(body, bg=DLG_BG)
        self._name_anchor.pack(fill="x")
        field_label(self._name_anchor, "NAME")
        self._vars["name"] = tk.StringVar(value=ch.get("name", ""))
        self._name_entry = styled_entry(self._name_anchor, self._vars["name"], width=50)
        self._name_entry.pack(fill="x", ipady=4, pady=(0, 2))

        mk_sep(body, MGR_BORDER, 0)
        field_label(body, "PORTRAITS BY HEALTH STATE", pady=(10, 2))
        hint(body, "Optional. Empty states use the nearest state that has an image; with none at "
                   "all, the D&D Beyond avatar is used. Square images look best. Images are copied "
                   "into the app's portraits folder.", pady=(0, 6))
        self._portrait_vars = {}
        grid = tk.Frame(body, bg=DLG_BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="c")
        grid.columnconfigure(1, weight=1, uniform="c")
        for idx, (key, state, pct_label) in enumerate(self._STATES):
            r, c = divmod(idx, 2)
            cell = tk.Frame(grid, bg=MGR_ROW, highlightthickness=1, highlightbackground=MGR_BORDER2)
            cell.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            inner = tk.Frame(cell, bg=MGR_ROW)
            inner.pack(fill="x", padx=6, pady=6)
            prev = tk.Canvas(inner, width=self.PREVIEW, height=self.PREVIEW, bg=MGR_ROW,
                             highlightthickness=0, cursor="hand2")
            prev.pack(side="left", padx=(0, 6))
            rcol = tk.Frame(inner, bg=MGR_ROW)
            rcol.pack(side="left", fill="x", expand=True)
            hrow = tk.Frame(rcol, bg=MGR_ROW)
            hrow.pack(fill="x")
            tk.Label(hrow, text=theme.STATE_LABELS[state], bg=MGR_ROW, fg=theme.state_color(state),
                     font=("Segoe UI", 9, "bold")).pack(side="left")
            tk.Label(hrow, text=pct_label, bg=MGR_ROW, fg=T_DIM, font=F_TINY).pack(side="right")
            var = tk.StringVar(value=ch.get(key, ""))
            self._portrait_vars[key] = var
            name_lbl = tk.Label(rcol, text="", bg=MGR_ROW, fg=T_DIM, font=F_TINY, anchor="w")
            name_lbl.pack(fill="x")
            brow = tk.Frame(rcol, bg=MGR_ROW)
            brow.pack(fill="x", pady=(2, 0))
            for text, cmd, tip in [("Browse…", lambda v=var: self._browse(v), "Choose an image"),
                                   ("All", lambda v=var: self._use_for_all(v), "Use this image for every state"),
                                   ("✕", lambda v=var: v.set(""), "Remove this image")]:
                b = styled_button(brow, text, BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD, cmd, font=F_TINY)
                b.pack(side="left", padx=(0, 3), ipadx=3)
                Tooltip(b, tip)
            prev.bind("<Button-1>", lambda _e, v=var: self._browse(v))
            Tooltip(prev, lambda v=var: config.portrait_abspath(v.get()) or "Click to choose an image")
            var.trace_add("write", lambda *_a, v=var, p=prev, l=name_lbl: self._draw_preview(v, p, l))
            self._draw_preview(var, prev, name_lbl)

        mk_sep(body, MGR_BORDER, 0)
        opt_row = tk.Frame(body, bg=DLG_BG)
        opt_row.pack(fill="x", pady=(10, 2))
        tk.Label(opt_row, text="Desktop window always on top", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._on_top_var = tk.BooleanVar(value=bool(ch.get("always_on_top", False)))
        ToggleSwitch(opt_row, self._on_top_var, bg=DLG_BG).pack(side="right")
        opa_row = tk.Frame(body, bg=DLG_BG)
        opa_row.pack(fill="x", pady=(8, 2))
        tk.Label(opa_row, text="Desktop window opacity", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._opacity_label = tk.Label(opa_row, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY)
        self._opacity_label.pack(side="right")
        self._opacity_var = tk.DoubleVar(value=float(ch.get("opacity", 1.0)))
        on_opacity = lambda val: self._opacity_label.config(text=f"{int(float(val) * 100)} %")
        on_opacity(self._opacity_var.get())
        tk.Scale(body, variable=self._opacity_var, from_=0.2, to=1.0, resolution=0.05,
                 orient="horizontal", command=on_opacity, showvalue=False,
                 bg="#5a8090", troughcolor=DLG_ENTRY_BG, width=12, sliderlength=22,
                 highlightthickness=0, bd=0, sliderrelief="flat", cursor="hand2",
                 activebackground=BTN_SAVE_FG).pack(fill="x", pady=(4, 0))

        dialog_footer(self, self._submit)
        self._set_mode(self._manual.get())
        if ch.get("character_id") and not ddb.is_manual(ch):
            self.after(100, self._run_test)

    def _set_mode(self, manual: bool):
        self._manual.set(manual)
        for val, b in self._seg_btns.items():
            on = val == manual
            b.config(bg=BTN_SAVE_BG if on else MGR_ROW, fg=BTN_SAVE_FG if on else T_DIM,
                     highlightbackground=BTN_SAVE_BD if on else MGR_BORDER2,
                     activebackground=BTN_SAVE_BG, activeforeground=BTN_SAVE_FG)
        self._ddb_frame.pack_forget()
        self._manual_frame.pack_forget()
        (self._manual_frame if manual else self._ddb_frame).pack(fill="x", before=self._name_anchor)
        (self._name_entry if manual else self._id_entry).focus_set()

    def _draw_preview(self, var, canvas, label):
        path = config.portrait_abspath(var.get().strip())
        ok = bool(path) and os.path.isfile(path)
        canvas.delete("all")
        photo = theme.thumb_photo(path if ok else "", self.PREVIEW, DLG_ENTRY_BG, 6)
        canvas._photo = photo
        canvas.create_image(self.PREVIEW // 2, self.PREVIEW // 2, image=photo)
        if not var.get().strip():
            canvas.create_text(self.PREVIEW // 2, self.PREVIEW // 2, text="+", fill=T_MUTED,
                               font=("Segoe UI", 16))
            label.config(text="no image", fg=T_MUTED)
        elif not ok:
            label.config(text="⚠ file not found", fg=WARN_FG)
        else:
            label.config(text=os.path.basename(path)[:22], fg=T_DIM)

    def _use_for_all(self, src_var):
        v = src_var.get().strip()
        for var in self._portrait_vars.values():
            var.set(v)

    def _extract_id(self) -> str:
        raw = self._vars["character_id"].get().strip()
        m = re.search(r"dndbeyond\.com/(?:profile/[^/]+/)?characters/(\d+)", raw)
        if m:
            self._vars["character_id"].set(m.group(1))
            return m.group(1)
        return raw if re.fullmatch(r"\d+", raw) else ""

    def _on_id_changed(self):
        if self._test_after_id:
            try: self.after_cancel(self._test_after_id)
            except tk.TclError: pass
        if not self._vars["character_id"].get().strip():
            self._test_label.config(text="", fg=T_DIM)
            return
        self._test_label.config(text="…", fg=T_DIM)
        self._test_after_id = self.after(800, self._run_test)

    def _run_test(self):
        cid = self._extract_id()
        if not cid:
            self._test_label.config(text="⚠ Enter a valid character ID or URL.", fg=WARN_FG)
            return
        self._test_label.config(text="Checking D&D Beyond…", fg=T_DIM)
        self._test_seq += 1
        seq = self._test_seq

        def work():
            try:
                data = ddb.get_character(ddb.make_session(cid), cid)
                return ("ok", ddb.hp_details(data), data.get("api_name", ""), data.get("avatar_url", ""))
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                if code == 404:        return ("not_found", None, None, None)
                if code in (401, 403): return ("private", None, None, None)
                return ("http_error", code, None, None)
            except Exception as e:
                return ("error", str(e), None, None)

        def done(result):
            if seq != self._test_seq or not self.winfo_exists():
                return
            kind = result[0]
            if kind == "ok":
                info, api_name, self.avatar_url = result[1], result[2], result[3] or ""
                self._test_label.config(text=f"✓ Found {api_name or 'character'} — HP {theme.hp_text(info)}",
                                        fg=OK_FG)
                if not self._vars["name"].get().strip() and api_name:
                    self._vars["name"].set(api_name)
            elif kind == "not_found":
                self._test_label.config(text="✗ Character not found — check the ID.", fg=ERR_FG)
            elif kind == "private":
                self._test_label.config(text="✗ Character is private — on D&D Beyond open the "
                                             "character's Home → Privacy and set it to Public.", fg=ERR_FG)
            elif kind == "http_error":
                self._test_label.config(text=f"✗ D&D Beyond error ({result[1]}) — try again later.", fg=ERR_FG)
            else:
                self._test_label.config(text="✗ Could not reach D&D Beyond — check your internet.", fg=ERR_FG)

        threading.Thread(target=lambda: (lambda r: run_on_ui(lambda: done(r)))(work()),
                         daemon=True).start()

    def _browse(self, var):
        start = config.portrait_abspath(var.get().strip())
        path = filedialog.askopenfilename(
            parent=self, initialdir=os.path.dirname(start) if start else config.BASE_DIR,
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"), ("All files", "*.*")])
        if path:
            var.set(path)

    def _submit(self):
        name = self._vars["name"].get().strip()
        vals = {"name": name}
        if self._manual.get():
            mx, cur, temp = (_int(self._vars["max_hp"]), _int(self._vars["current_hp"]),
                             _int(self._vars["temp_hp"], 0))
            if not mx or mx < 1 or cur is None or cur < 0 or temp is None or temp < 0:
                messagebox.showwarning("HP", "Enter whole numbers: max HP at least 1, current "
                                       "and temporary HP 0 or more.", parent=self)
                return
            vals.update(source="manual", max_hp=mx, current_hp=min(cur, mx), temp_hp=temp,
                        character_id=self._ch.get("character_id") if ddb.is_manual(self._ch)
                        else "npc" + secrets.token_hex(4))
        else:
            cid = self._extract_id()
            if not cid:
                messagebox.showwarning("Required", "Enter the character ID or URL.", parent=self)
                return
            vals.update(source="dndbeyond", character_id=cid)
        if not name:
            messagebox.showwarning("Required", "Enter a name for the character.", parent=self)
            return
        for key, var in self._portrait_vars.items():
            p = var.get().strip()
            if p:
                try:
                    p = config.make_portable(p, vals, key)
                except OSError as e:
                    messagebox.showwarning("Portrait", f"Could not copy the image into the portraits "
                                           f"folder:\n{e}\n\nThe original location is used instead.",
                                           parent=self)
            vals[key] = p
        vals["always_on_top"] = self._on_top_var.get()
        vals["opacity"]       = round(self._opacity_var.get(), 2)
        self.result = vals
        self.destroy()


# ── HP change for manual characters ─────────────────────────────────────────
class HPDialog(tk.Toplevel):
    """Small, non-modal window to damage / heal a manual character. Stays open
    during combat; Enter = damage, Shift+Enter = heal, Esc = close."""

    def __init__(self, parent, ch: dict, on_change):
        super().__init__(parent)
        self.ch, self.on_change = ch, on_change
        self.title(f"HP — {ch.get('name', '')}")
        self.transient(parent)
        body = dialog_frame(self, ch.get("name", "HP"))
        self._hp = tk.Label(body, text="", bg=DLG_BG, font=("Consolas", 20, "bold"))
        self._hp.pack(anchor="w")
        row = tk.Frame(body, bg=DLG_BG)
        row.pack(fill="x", pady=(8, 4))
        tk.Label(row, text="Amount", bg=DLG_BG, fg=T_SECONDARY, font=F_SMALL).pack(side="left")
        self._amount = tk.StringVar()
        self._entry = styled_entry(row, self._amount, width=8)
        self._entry.config(font=("Consolas", 14, "bold"), justify="center")
        self._entry.pack(side="left", padx=8, ipady=3)
        btns = tk.Frame(body, bg=DLG_BG)
        btns.pack(fill="x", pady=(4, 0))
        for text, kind, colors, tip in [
            ("−  Damage", "damage", (DANGER_BG, DANGER_FG, DANGER_BD), "Enter · uses temporary HP first"),
            ("+  Heal",   "heal",   (BTN_HEAL_BG, BTN_HEAL_FG, BTN_HEAL_BD), "Shift+Enter · up to max HP"),
            ("Temp HP",   "temp",   ("#173040", HP_TEMP, "#24506a"), "Set temporary HP to this amount"),
            ("Max HP",    "max",    (BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD), "Set maximum HP"),
        ]:
            b = styled_button(btns, text, *colors, lambda k=kind: self._apply(k), font=F_SMALL)
            b.pack(side="left", padx=(0, 4), ipady=4, ipadx=6)
            Tooltip(b, tip)
        hint(body, "Enter = damage · Shift+Enter = heal · Esc = close · "
                   "mouse wheel on the HP badge = ±1", pady=(8, 0))
        self.bind("<Return>", lambda _e: self._apply("damage"))
        self.bind("<Shift-Return>", lambda _e: self._apply("heal"))
        self.refresh()
        self._entry.focus_set()

    def refresh(self):
        if not self.winfo_exists():
            return
        info = ddb.manual_info(self.ch)
        self._hp.config(text=theme.hp_text(info), fg=theme.state_color(theme.display_state(info)))

    def _apply(self, kind):
        amount = _int(self._amount)
        if amount is None or amount < 0 or (kind == "max" and amount < 1):
            self._entry.config(highlightbackground=ERR_FG)
            return "break"
        self._entry.config(highlightbackground=MGR_BORDER3)
        ddb.apply_hp_change(self.ch, kind, amount)
        self._amount.set("")
        self.refresh()
        self.on_change(self.ch)
        return "break"


# ── Game ────────────────────────────────────────────────────────────────────
class GameDialog(tk.Toplevel):
    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.title("Game")
        self.transient(parent)
        self.grab_set()
        self.result = None
        body = dialog_frame(self, "Edit game" if game else "Add game")
        field_label(body, "GAME NAME")
        self._name_var = tk.StringVar(value=game.get("name", ""))   # NB: not self._name (Tk uses it)
        e = styled_entry(body, self._name_var, width=36)
        e.pack(fill="x", ipady=4, pady=(0, 2))
        dialog_footer(self, self._submit)
        e.focus_set()

    def _submit(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Required", "Game name is required.", parent=self)
            return
        self.result = {"name": name}
        self.destroy()


# ── OBS connection ──────────────────────────────────────────────────────────
class OBSDialog(tk.Toplevel):
    CURRENT = "(current scene)"

    def __init__(self, parent, settings: dict, game_name: str | None = None):
        super().__init__(parent)
        self.title("OBS connection")
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.action = None          # None | "each" | "party"
        body = dialog_frame(self, "OBS connection")
        hint(body, "In OBS open Tools → WebSocket Server Settings, tick \"Enable WebSocket "
                   "server\", then click \"Show Connect Info\" and copy the port and password here.",
             wrap=400, fg=T_DIM, pady=(0, 4))
        self._vars = {}
        for key, label, show in [("host", "HOST", ""), ("port", "PORT", ""), ("password", "PASSWORD", "*")]:
            field_label(body, label)
            var = tk.StringVar(value=str(settings.get(key, "")))
            self._vars[key] = var
            styled_entry(body, var, width=44, show=show).pack(fill="x", ipady=4, pady=(0, 2))
        field_label(body, "ADD OVERLAYS TO SCENE", pady=(8, 2))
        scene_row = tk.Frame(body, bg=DLG_BG)
        scene_row.pack(fill="x")
        self._scene_var = tk.StringVar(value=settings.get("scene") or self.CURRENT)
        self._scene_menu = tk.OptionMenu(scene_row, self._scene_var, self._scene_var.get())
        self._scene_menu.config(bg=DLG_ENTRY_BG, fg=T_PRIMARY, activebackground=MGR_BORDER2,
                                activeforeground=T_PRIMARY, relief="flat", bd=0,
                                highlightthickness=1, highlightbackground=MGR_BORDER3,
                                font=F_SMALL, anchor="w")
        self._scene_menu["menu"].config(bg=MGR_PILL, fg=T_PRIMARY, font=F_SMALL)
        self._scene_menu.pack(side="left", fill="x", expand=True, ipady=2, padx=(0, 6))
        styled_button(scene_row, "Test & load scenes", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                      self._test).pack(side="left", ipady=3, ipadx=6)
        self._status = tk.Label(body, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY,
                                wraplength=400, justify="left")
        self._status.pack(anchor="w", pady=(6, 0))
        extra = []
        if game_name:
            hint(body, f"For “{game_name}” add one source per character (arrange them freely) or a "
                       "single party source with everyone side by side.", wrap=400, pady=(8, 0))
            extra = [("Save & add each character", lambda: self._finish("each")),
                     ("Save & add party source", lambda: self._finish("party"))]
        dialog_footer(self, lambda: self._finish(None), extra)

    def _values(self) -> dict | None:
        port = _int(self._vars["port"])
        if port is None:
            messagebox.showwarning("OBS", "Port must be a number (usually 4455).", parent=self)
            return None
        scene = self._scene_var.get()
        return {"host": self._vars["host"].get().strip() or "127.0.0.1", "port": port,
                "password": self._vars["password"].get(),
                "scene": "" if scene == self.CURRENT else scene}

    def _test(self):
        settings = self._values()
        if settings is None:
            return
        self._status.config(text="Connecting…", fg=T_DIM)

        def work():
            try:
                scenes = obs.list_scenes(settings)
                run_on_ui(lambda: self._test_done(scenes, None))
            except Exception as e:
                msg = str(e)
                run_on_ui(lambda: self._test_done(None, msg))
        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, scenes, err):
        if not self.winfo_exists():
            return
        if err:
            self._status.config(text=f"✗ {err}", fg=ERR_FG)
            return
        menu = self._scene_menu["menu"]
        menu.delete(0, "end")
        for name in [self.CURRENT] + scenes:
            menu.add_command(label=name, command=lambda v=name: self._scene_var.set(v))
        if self._scene_var.get() not in [self.CURRENT] + scenes:
            self._scene_var.set(self.CURRENT)
        self._status.config(text=f"✓ Connected — {len(scenes)} scenes found.", fg=OK_FG)

    def _finish(self, action):
        settings = self._values()
        if settings is None:
            return
        self.result, self.action = settings, action
        self.destroy()


# ── Settings ────────────────────────────────────────────────────────────────
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg: dict, has_tray: bool):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.grab_set()
        self.result = None
        body = dialog_frame(self, "Settings")

        field_label(body, "CHECK D&D BEYOND EVERY … SECONDS")
        row = tk.Frame(body, bg=DLG_BG)
        row.pack(fill="x")
        self._poll = tk.StringVar(value=str(cfg.get("poll_interval", config.DEFAULT_POLL_INTERVAL)))
        tk.Spinbox(row, from_=config.MIN_POLL, to=config.MAX_POLL, textvariable=self._poll, width=5,
                   bg=DLG_ENTRY_BG, fg=T_PRIMARY, buttonbackground=MGR_BORDER2,
                   insertbackground=T_PRIMARY, relief="flat", bd=0, highlightthickness=1,
                   highlightbackground=MGR_BORDER3, font=F_SMALL).pack(side="left", ipady=3)
        tk.Label(row, text=f"  {config.MIN_POLL}–{config.MAX_POLL}. Lower = faster updates on stream, "
                           "but more requests to D&D Beyond.", bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                 wraplength=330, justify="left").pack(side="left")

        self._palette = toggle_row(body, "Colour-blind friendly colours",
                                   cfg.get("palette") == "colorblind",
                                   "Blue → yellow → orange → magenta instead of green → red, "
                                   "in the app and on stream.")
        self._autostart = toggle_row(body, "Start with Windows (minimised)",
                                     system.get_autostart() if system.autostart_supported() else False,
                                     "" if system.autostart_supported()
                                     else "Only available in the .exe on Windows.",
                                     system.autostart_supported())
        self._updates = toggle_row(body, "Check for new versions at startup",
                                   bool(cfg.get("check_updates", True)))
        self._tray = toggle_row(body, "✕ hides the app in the system tray",
                                bool(cfg.get("close_to_tray", False)),
                                "Off: ✕ quits the app. On: it keeps running in the tray "
                                "(right-click the tray icon to quit)." if has_tray
                                else "Not available in this build.", has_tray)

        srv = cfg.get("overlay_server") or {}
        field_label(body, "OVERLAY SERVER PORT", pady=(12, 2))
        prow = tk.Frame(body, bg=DLG_BG)
        prow.pack(fill="x")
        self._port = tk.StringVar(value=str(srv.get("port", 7777)))
        styled_entry(prow, self._port, width=8).pack(side="left", ipady=3)
        tk.Label(prow, text="  takes effect after restarting the app (update OBS sources "
                            "afterwards via OBS).", bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                 wraplength=330, justify="left").pack(side="left")

        mk_sep(body, MGR_BORDER, 0)
        frow = tk.Frame(body, bg=DLG_BG)
        frow.pack(fill="x", pady=(10, 0))
        for text, path in [("Open data folder", config.BASE_DIR), ("Open log file", config.LOG_FILE)]:
            styled_button(frow, text, BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                          lambda p=path: system.open_path(p), font=F_TINY).pack(
                side="left", padx=(0, 6), ipadx=6, ipady=2)
        hint(body, config.BASE_DIR, wrap=420, pady=(4, 0))
        dialog_footer(self, self._submit)

    def _submit(self):
        poll, port = _int(self._poll), _int(self._port)
        if poll is None or port is None or not 1024 <= port <= 65535:
            messagebox.showwarning("Settings", f"Check interval must be {config.MIN_POLL}–"
                                   f"{config.MAX_POLL} and the port 1024–65535.", parent=self)
            return
        self.result = {"poll_interval": max(config.MIN_POLL, min(config.MAX_POLL, poll)),
                       "palette": "colorblind" if self._palette.get() else "default",
                       "autostart": self._autostart.get(),
                       "check_updates": self._updates.get(),
                       "close_to_tray": self._tray.get(), "port": port}
        self.destroy()
