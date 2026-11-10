"""Shared UI plumbing: the worker→UI queue and styled widgets."""
import logging
import queue
import tkinter as tk

from ..theme import (BTN_CANCEL_BD, BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_OPEN_BD, BTN_OPEN_BG,
                     BTN_OPEN_FG, BTN_SAVE_BD, BTN_SAVE_BG, BTN_SAVE_FG, DLG_BG, DLG_ENTRY_BG,
                     DLG_LABEL_FG, F_BOLD, F_LABEL, F_MED, F_SMALL, F_TINY, MGR_BORDER,
                     MGR_BORDER2, MGR_BORDER3, MGR_HEADER, MGR_PILL, OK_FG, T_PRIMARY)

log = logging.getLogger("dnd_healthbar")

# ── Thread-safe UI dispatch ─────────────────────────────────────────────────
# Tkinter must only be touched from the main thread. Worker threads put
# callables on this queue; the main loop drains it every 50 ms.
ui_queue: "queue.Queue" = queue.Queue()

def run_on_ui(fn):
    ui_queue.put(fn)

def drain_ui_queue():
    while True:
        try:
            fn = ui_queue.get_nowait()
        except queue.Empty:
            return
        try:
            fn()
        except tk.TclError:
            pass                  # widget destroyed meanwhile
        except Exception:
            log.exception("UI callback failed")

def pump_ui_queue(root: tk.Tk):
    drain_ui_queue()
    try:
        root.after(50, pump_ui_queue, root)
    except tk.TclError:
        pass

# ── Widgets ─────────────────────────────────────────────────────────────────
def mk_sep(parent, color=MGR_BORDER, pad=0):
    f = tk.Frame(parent, bg=color, height=1)
    f.pack(fill="x", padx=pad)
    return f

def styled_button(parent, text, bg, fg, bd, command, font=F_SMALL, width=None, pady=0):
    kw = dict(text=text, bg=bg, fg=fg, relief="flat", bd=0,
              highlightthickness=1, highlightbackground=bd,
              activebackground=bd, activeforeground=fg,
              font=font, cursor="hand2", command=command, pady=pady)
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def styled_entry(parent, textvariable, width=30, show=""):
    return tk.Entry(parent, textvariable=textvariable, width=width, show=show,
                    bg=DLG_ENTRY_BG, fg=T_PRIMARY, insertbackground=T_PRIMARY,
                    relief="flat", bd=0, highlightthickness=1,
                    highlightbackground=MGR_BORDER3, highlightcolor="#5a8090", font=F_SMALL)

def field_label(parent, text, pady=(6, 2)):
    tk.Label(parent, text=text, bg=DLG_BG, fg=DLG_LABEL_FG, font=F_LABEL).pack(anchor="w", pady=pady)

def hint(parent, text, wrap=440, fg="#6f8a9a", pady=(0, 2)):
    tk.Label(parent, text=text, bg=DLG_BG, fg=fg, font=F_TINY, wraplength=wrap,
             justify="left").pack(anchor="w", pady=pady)

def popup_menu(root) -> tk.Menu:
    return tk.Menu(root, tearoff=0, bg=MGR_PILL, fg=T_PRIMARY, activebackground=MGR_BORDER2,
                   activeforeground=T_PRIMARY, relief="flat", bd=0, font=F_SMALL)

def dialog_frame(dlg: tk.Toplevel, title: str) -> tk.Frame:
    """Common dialog chrome: header + body frame; Esc cancels."""
    dlg.configure(bg=DLG_BG)
    dlg.resizable(False, False)
    hdr = tk.Frame(dlg, bg=MGR_HEADER)
    hdr.pack(fill="x")
    tk.Label(hdr, text=title, bg=MGR_HEADER, fg=T_PRIMARY,
             font=F_BOLD, anchor="w").pack(side="left", padx=14, pady=10)
    mk_sep(dlg, MGR_BORDER)
    body = tk.Frame(dlg, bg=DLG_BG)
    body.pack(fill="x", padx=14, pady=10)
    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    return body

def dialog_footer(dlg, on_save, extra=None, save_text="Save"):
    """Footer with Save/Cancel (+ extra buttons on the left); Enter = Save."""
    mk_sep(dlg, MGR_BORDER)
    foot = tk.Frame(dlg, bg=MGR_HEADER)
    foot.pack(fill="x", padx=14, pady=8)
    for text, cmd in (extra or []):
        styled_button(foot, text, BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD, cmd).pack(
            side="left", ipady=4, ipadx=8, padx=(0, 4))
    styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                  dlg.destroy).pack(side="right", padx=(4, 0), ipady=4, ipadx=8)
    styled_button(foot, save_text, BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                  on_save, font=F_MED).pack(side="right", ipady=4, ipadx=12)
    dlg.bind("<Return>", lambda _e: on_save())
    return foot


class Tooltip:
    """Hover help. `text` may be a string or a callable returning one."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            try: self.widget.after_cancel(self._after)
            except tk.TclError: pass
            self._after = None

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        try:
            x = self.widget.winfo_pointerx() + 12
            y = self.widget.winfo_pointery() + 16
            self._tip = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            tk.Label(tw, text=text, bg="#0b1218", fg=T_PRIMARY, font=F_TINY, justify="left",
                     wraplength=300, padx=8, pady=4, highlightthickness=1,
                     highlightbackground=MGR_BORDER3).pack()
            tw.geometry(f"+{x}+{y}")
        except tk.TclError:
            self._tip = None

    def _hide(self, _e=None):
        self._cancel()
        if self._tip:
            try: self._tip.destroy()
            except tk.TclError: pass
            self._tip = None


class ToggleSwitch(tk.Canvas):
    W, H, R = 36, 20, 9

    def __init__(self, parent, variable, command=None, **kw):
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0,
                         cursor="hand2", **kw)
        self._var = variable
        self._cmd = command
        self.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = self._var.get()
        self._round_rect(1, 1, self.W - 1, self.H - 1, radius=self.R,
                         fill="#1a4030" if on else "#1a3040",
                         outline="#2a5040" if on else "#2a4050")
        kx = self.W - self.R - 3 if on else self.R + 3 - (self.R - self.H // 2 + 2)
        self.create_oval(kx - self.H // 2 + 3, 3, kx + self.H // 2 - 3, self.H - 3,
                         fill=OK_FG if on else "#3a5060", outline="")

    def _round_rect(self, x1, y1, x2, y2, radius=9, **kw):
        pts = [x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y2-radius, x2, y2,
               x2-radius, y2, x1+radius, y2, x1, y2, x1, y2-radius, x1, y1+radius, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _toggle(self, _=None):
        self._var.set(not self._var.get())
        if self._cmd: self._cmd()


def toggle_row(parent, text, value: bool, hint_text: str = "", enabled: bool = True,
               fg="#8ab0c0") -> tk.BooleanVar:
    """Label + toggle switch (+ optional hint) in a dialog."""
    r = tk.Frame(parent, bg=DLG_BG)
    r.pack(fill="x", pady=(10, 0))
    tk.Label(r, text=text, bg=DLG_BG, fg=fg if enabled else "#6f8a9a", font=F_SMALL).pack(side="left")
    var = tk.BooleanVar(value=value)
    if enabled:
        ToggleSwitch(r, var, bg=DLG_BG).pack(side="right")
    if hint_text:
        hint(parent, hint_text, wrap=420, pady=(0, 0))
    return var
