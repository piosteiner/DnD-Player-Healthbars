"""The desktop HP window of one live character."""
import logging
import os
import re
import tkinter as tk

from PIL import Image, ImageTk

from .. import config, ddb, system, theme
from ..theme import BAR_H, BAR_PAD, CORNER_R, F_MONO, HP_TEMP, OVL_BAR_BG, OVL_BG, OVL_W, T_PRIMARY
from .common import run_on_ui

log = logging.getLogger("dnd_healthbar")


class CharacterWindow:
    """Shows portrait + HP bar. D&D Beyond characters are fed by the shared
    poller (worker thread); manual characters via show_info()."""

    def __init__(self, master, char: dict, on_closed=None, on_hp_update=None,
                 status_cb=None, on_char_changed=None):
        self.char            = char
        self.cid             = char["character_id"]
        self.manual          = ddb.is_manual(char)
        self.on_closed       = on_closed
        self.on_hp_update    = on_hp_update
        self.on_char_changed = on_char_changed
        self.status_cb       = status_cb
        self._closed         = False
        self._photo          = None
        self._last_state     = None
        self._avatar_checked = False
        self.info            = None

        self.win = tk.Toplevel(master)
        self.win.title(char.get("name", "HP"))
        self.win.configure(bg=OVL_BG)
        self.win.resizable(False, False)
        self.apply_window_options()
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        pos = char.get("window_pos")       # restore last position if still on screen
        if (isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, int) for v in pos)
                and system.position_on_screen(self.win, *pos)):
            self.win.geometry(f"+{pos[0]}+{pos[1]}")

        self._build_ui()
        self._load_portrait(config.resolve_portrait_path(self.char, "full"))
        self._apply_hp_visibility()

        if self.manual:
            self._set_status("Manual HP — click the HP badge to change it", "ok")
            self.show_info(ddb.manual_info(char))
        else:
            ddb.POLLER.add(self.cid, self._on_data, self._set_status)

    # ── setup ────────────────────────────────────────────────────────────────
    def apply_window_options(self):
        self.win.attributes("-topmost", bool(self.char.get("always_on_top", False)))
        self.win.attributes("-alpha", max(0.2, min(1.0, float(self.char.get("opacity", 1.0)))))

    def set_title(self, name: str):
        """Window title doubles as the OBS window-capture match key."""
        self.win.title(name or "HP")

    def _build_ui(self):
        self.portrait_canvas = tk.Canvas(self.win, width=OVL_W, height=OVL_W,
                                         bg=OVL_BG, highlightthickness=0)
        self.portrait_canvas.pack()
        self._img_id = self.portrait_canvas.create_image(OVL_W // 2, OVL_W // 2, anchor="center")
        self.hp_frame = tk.Frame(self.win, bg=OVL_BG)
        self.hp_frame.pack(fill="x", padx=BAR_PAD, pady=(BAR_PAD, BAR_PAD))
        self.bar_canvas = tk.Canvas(self.hp_frame, width=OVL_W - BAR_PAD * 2, height=BAR_H,
                                    bg=OVL_BG, highlightthickness=0)
        self.bar_canvas.pack()
        self.hp_label = tk.Label(self.hp_frame, text="", bg=OVL_BG, fg=T_PRIMARY,
                                 font=F_MONO, anchor="w")
        self._draw_bar({"pct": 1.0, "cur": 1, "mx": 1, "temp": 0}, "full")

    def _apply_hp_visibility(self):
        if self.char.get("show_hp_numbers", False):
            self.hp_label.pack(anchor="w", pady=(6, 0))
        else:
            self.hp_label.pack_forget()
        self.win.update_idletasks()
        self.win.geometry(f"{OVL_W}x{self.win.winfo_reqheight()}")

    def refresh_visibility(self):
        self.win.after(0, self._apply_hp_visibility)

    # ── portrait / bar ───────────────────────────────────────────────────────
    def reload_portrait(self):
        self._last_state = None
        self._update_portrait(theme.display_state(self.info) if self.info else "full")

    def _update_portrait(self, state: str):
        if state == self._last_state:
            return
        self._last_state = state
        self._load_portrait(config.resolve_portrait_path(self.char, state))

    def _load_portrait(self, path: str):
        size = OVL_W
        try:
            img = (theme.fit_image(Image.open(path), size, OVL_BG) if path
                   else Image.new("RGBA", (size, size), OVL_BG))
        except Exception as e:
            log.warning("Could not load portrait %s: %s", path, e)
            img = Image.new("RGBA", (size, size), OVL_BG)
        self._photo = ImageTk.PhotoImage(theme.round_image(img, CORNER_R))
        self.portrait_canvas.itemconfig(self._img_id, image=self._photo)

    def _draw_bar(self, info: dict, state: str):
        c = self.bar_canvas
        c.delete("all")
        w, h = OVL_W - BAR_PAD * 2, BAR_H
        theme.draw_pill(c, 0, w, h, OVL_BAR_BG)
        if info.get("pct") is None:
            for x in range(h // 2, w - h // 2, 12):
                c.create_rectangle(x, 4, x + 6, h - 4, fill="#2a3a44", outline="")
            return
        cur, mx, temp = info["cur"], info["mx"], info.get("temp", 0)
        total = max(mx, cur + temp) or 1
        if temp:
            theme.draw_pill(c, 0, w * (cur + temp) / total, h, HP_TEMP)
        theme.draw_pill(c, 0, int(w * cur / total), h, theme.state_color(state))

    @staticmethod
    def label_text(info: dict, state: str) -> str:
        if info.get("pct") is None:
            return "HP not configured"
        t = theme.hp_text(info, "  /  ")
        ds = info.get("death_saves") or {}
        if state == "dying":
            t += f"   Dying ✓{ds.get('success', 0)} ✗{ds.get('fail', 0)}"
        elif state == "stable":
            t += "   Stable"
        elif state == "dead":
            t += "   Dead"
        return t

    # ── data flow ────────────────────────────────────────────────────────────
    def _on_data(self, data: dict):
        """Poller thread: new character data from D&D Beyond."""
        self._maybe_fetch_avatar(data)
        self.show_info(ddb.hp_details(data))

    def show_info(self, info: dict):
        """Any thread: display new HP info (marshalled to the UI thread)."""
        def _do():
            if self._closed:
                return
            self.info = info
            state = theme.display_state(info)
            self._draw_bar(info, state)
            self._update_portrait(state)
            self.hp_label.config(text=self.label_text(info, state))
            if self.on_hp_update:
                self.on_hp_update(self.cid, info)
        run_on_ui(_do)

    def redraw(self):
        """Re-render with the current info (e.g. after a palette change)."""
        if self.info:
            self.show_info(self.info)

    def _set_status(self, msg: str, kind: str = "busy"):
        if self.status_cb and not self._closed:
            self.status_cb(self.cid, msg, kind)

    def _maybe_fetch_avatar(self, data: dict):
        """No portraits set? Use the character's D&D Beyond avatar (poller thread)."""
        if self._avatar_checked:
            return
        self._avatar_checked = True
        url = data.get("avatar_url")
        if not url or config.has_custom_portrait(self.char):
            return
        cur = self.char.get("avatar")
        if cur and os.path.isfile(config.portrait_abspath(cur)):
            return
        try:
            rel = config.download_avatar(url, self.char)
        except Exception as e:
            log.warning("Avatar download failed for %s: %s", self.char.get("name"), e)
            return
        if rel:
            def _do():
                self.char["avatar"] = rel
                if not self._closed:
                    self.reload_portrait()
                if self.on_char_changed:
                    self.on_char_changed(self.char)
            run_on_ui(_do)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if not self.manual:
            ddb.POLLER.remove(self.cid)
        try:                                 # remember the window position
            m = re.search(r"\+(-?\d+)\+(-?\d+)$", self.win.geometry())
            if m:
                self.char["window_pos"] = [int(m.group(1)), int(m.group(2))]
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_closed:
            self.on_closed()
