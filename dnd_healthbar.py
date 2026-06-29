"""
D&D Beyond Live Health Bar
--------------------------
Multi-game, multi-character health bar overlay.

Data model:
  games: [
    {
      "id":   "1234567",
      "name": "My Campaign",
      "characters": [
        {
          "name":               "Thorin",
          "user_id":            "1111111",
          "character_id":       "2222222",
          "cookie_header":      "CobaltSession=...",
          "always_on_top":      false,
          "show_hp_numbers":    false,
          "portrait_unscathed": "/path/to/full.png",
          "portrait_scratched": "/path/to/scratched.png",
          "portrait_injured":   "/path/to/injured.png",
          "portrait_bloodied":  "/path/to/bloodied.png",
          "portrait_critical":  "/path/to/critical.png",
          "portrait_dead":      "/path/to/dead.png"
        }
      ]
    }
  ]

Requirements:
    pip install requests websocket-client Pillow
"""

APP_VERSION = "1.1.0"

import os, sys, json, time, threading, traceback
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import requests, websocket

# ---------------------------------------------------------------------------
# D&D Beyond API
# ---------------------------------------------------------------------------
AUTH_URL      = "https://auth-service.dndbeyond.com/v1/cobalt-token"
WS_BASE       = "wss://game-log-api-live.dndbeyond.com/v1"
CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"
ORIGIN        = "https://www.dndbeyond.com"
REFERER       = "https://www.dndbeyond.com"

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
# Manager chrome
MGR_BG        = "#16202a"   # window body
MGR_HEADER    = "#0f1720"   # header / footer / status bar
MGR_ROW       = "#1e2c38"   # character row bg
MGR_ROW_LIVE  = "#1e2c38"   # live row (border changes instead)
MGR_BORDER    = "#243040"   # separator / outer border
MGR_BORDER2   = "#2a3c4a"   # row inner border
MGR_BORDER3   = "#344858"   # button / input border
MGR_PILL      = "#1e2c38"   # game pill bg

# Manager text
T_PRIMARY     = "#dce8f0"   # names, titles
T_SECONDARY   = "#8ab0c0"   # icon buttons, secondary labels
T_DIM         = "#5a7888"   # subtext / char IDs
T_MUTED       = "#3a5060"   # very muted hints

# HP state colours (bright)
HP_FULL       = "#00e676"
HP_SCRATCH    = "#40e880"
HP_INJURED    = "#ffb300"
HP_BLOODIED   = "#ff6b00"
HP_CRIT       = "#f44336"
HP_DEAD       = "#555555"

# HP state bg colours (dark tinted)
HPB_FULL      = "#0a2a14"
HPB_SCRATCH   = "#0a2a14"
HPB_INJURED   = "#2a2200"
HPB_BLOODIED  = "#2a1400"
HPB_CRIT      = "#2a0808"
HPB_DEAD      = "#181818"

# HP state border colours
HBB_FULL      = "#0f4020"
HBB_SCRATCH   = "#0f4020"
HBB_INJURED   = "#3a3000"
HBB_BLOODIED  = "#3a2000"
HBB_CRIT      = "#3a1010"
HBB_DEAD      = "#282828"

# Overlay window
OVL_BG        = "#293136"
OVL_BAR_BG    = "#1e272e"
OVL_BORDER    = "#344048"

# Buttons
BTN_OPEN_BG   = "#1a3848";  BTN_OPEN_FG  = "#60b0d0";  BTN_OPEN_BD  = "#2a5060"
BTN_CLOSE_BG  = "#3a1818";  BTN_CLOSE_FG = "#e07070";  BTN_CLOSE_BD = "#5a2222"
BTN_EDIT_BG   = "#1e2c38";  BTN_EDIT_FG  = "#7aaabb";  BTN_EDIT_BD  = "#344858"
BTN_SAVE_BG   = "#1a3848";  BTN_SAVE_FG  = "#60c0d8";  BTN_SAVE_BD  = "#2a5060"
BTN_CANCEL_BG = "#1e2c38";  BTN_CANCEL_FG= "#7aaabb";  BTN_CANCEL_BD= "#344858"
DANGER_BG     = "#3a1010";  DANGER_FG    = "#e05050";  DANGER_BD    = "#5a2020"

# Entry fields / dialogs
DLG_BG        = "#16202a"
DLG_ENTRY_BG  = "#1e2c38"
DLG_LABEL_FG  = "#6a8898"
DLG_SEP       = "#243040"

# Fonts
F_TITLE  = ("Segoe UI", 14, "bold")
F_BOLD   = ("Segoe UI", 11, "bold")
F_MED    = ("Segoe UI", 10, "bold")
F_SMALL  = ("Segoe UI", 10)
F_TINY   = ("Segoe UI", 9)
F_MONO   = ("Consolas", 11, "bold")

PORTRAIT_SIZE = 280
BAR_H         = 32
BAR_PAD       = 12
CORNER_R      = 14
OVL_W         = 280
HP_H          = BAR_H + BAR_PAD * 2 + 4   # height of hp section (bar + padding)
HP_H_NUMS     = HP_H + 26                  # extra height when numbers are shown

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# When bundled by PyInstaller sys.executable points to the actual .exe;
# __file__ would point into the temp extraction folder instead.
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_BASE_DIR, "dnd_healthbar.json")

def load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: could not read config: {e}")
    return {"games": []}

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save config: {e}")

# ---------------------------------------------------------------------------
# D&D Beyond API helpers
# ---------------------------------------------------------------------------
def get_token(cookie: str) -> tuple[str, int]:
    headers = {"Accept": "*/*", "Origin": ORIGIN, "Referer": REFERER, "Cookie": cookie}
    resp = requests.get(AUTH_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data["token"], int(data.get("ttl", 300))


def get_character(cookie: str, token: str, character_id: str) -> dict:
    headers = {
        "Accept": "application/json",
        "Origin": ORIGIN, "Referer": REFERER,
        "Cookie": cookie,
        "Authorization": "Bearer " + token,
        "Connection": "close",
    }
    resp = requests.get(CHARACTER_URL + character_id + "?includeCustomItems=true",
                        headers=headers, timeout=30)
    resp.raise_for_status()
    char = resp.json().get("data", {})

    total_level = sum(c.get("level", 0) for c in char.get("classes", []))
    override_stats = {s["id"]: s["value"] for s in char.get("overrideStats", []) if s.get("value") is not None}
    base_stats     = {s["id"]: s["value"] for s in char.get("stats", [])          if s.get("value") is not None}
    bonus_stats    = {s["id"]: s["value"] for s in char.get("bonusStats", [])     if s.get("value") is not None}

    if 3 in override_stats:
        con_score = override_stats[3]
    else:
        con_score = base_stats.get(3, 10) + bonus_stats.get(3, 0)
        for src in ("race", "feat", "class", "background"):
            for mod in char.get("modifiers", {}).get(src, []):
                if mod.get("subType") == "constitution-score" and mod.get("type") == "bonus":
                    con_score += int(mod.get("value") or mod.get("fixedValue") or 0)

    return {
        "baseHitPoints":      int(char.get("baseHitPoints")      or 0),
        "bonusHitPoints":     int(char.get("bonusHitPoints")     or 0),
        "overrideHitPoints":  char.get("overrideHitPoints"),
        "removedHitPoints":   int(char.get("removedHitPoints")   or 0),
        "temporaryHitPoints": int(char.get("temporaryHitPoints") or 0),
        "totalLevel":         total_level,
        "conMod":             (con_score - 10) // 2,
    }


def calculate_hp(d: dict) -> tuple[float, int, int]:
    override = d.get("overrideHitPoints")
    if override is not None:
        max_hp = int(override)
    else:
        max_hp = d["baseHitPoints"] + d["totalLevel"] * d["conMod"] + d["bonusHitPoints"]
    display_max = max_hp + d["temporaryHitPoints"]
    current     = max(0, display_max - d["removedHitPoints"])
    pct         = (current / display_max) if display_max > 0 else 0.0
    return pct, current, display_max


def should_refresh(evt: dict, character_id: str) -> bool:
    if evt.get("eventType") != "character-sheet/character-update/fulfilled":
        return False
    if evt.get("entityType") != "character":
        return False
    eid  = str(evt.get("entityId", ""))
    dcid = str((evt.get("data") or {}).get("characterId", ""))
    return eid == character_id or dcid == character_id

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def hp_state(pct: float) -> str:
    if pct <= 0:    return "dead"
    if pct < 0.25:  return "critical"
    if pct < 0.50:  return "bloodied"
    if pct < 0.75:  return "injured"
    if pct < 1.0:   return "scratched"
    return "full"

def hp_bar_color(pct: float) -> str:
    states = {
        "full":      HP_FULL,
        "scratched": HP_SCRATCH,
        "injured":   HP_INJURED,
        "bloodied":  HP_BLOODIED,
        "critical":  HP_CRIT,
        "dead":      HP_DEAD,
    }
    return states[hp_state(pct)]

def hp_badge_colors(pct: float) -> tuple[str, str, str]:
    """Returns (fg, bg, border) for the HP badge in the manager row."""
    m = {
        "full":      (HP_FULL,     HPB_FULL,     HBB_FULL),
        "scratched": (HP_SCRATCH,  HPB_SCRATCH,  HBB_SCRATCH),
        "injured":   (HP_INJURED,  HPB_INJURED,  HBB_INJURED),
        "bloodied":  (HP_BLOODIED, HPB_BLOODIED, HBB_BLOODIED),
        "critical":  (HP_CRIT,     HPB_CRIT,     HBB_CRIT),
        "dead":      (HP_DEAD,     HPB_DEAD,      HBB_DEAD),
    }
    return m[hp_state(pct)]

def round_image(img: Image.Image, radius: int) -> Image.Image:
    img  = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], radius=radius, fill=255)
    img.putalpha(mask)
    return img

def mk_sep(parent, color=MGR_BORDER, pad=0):
    tk.Frame(parent, bg=color, height=1).pack(fill="x", padx=pad)

# ---------------------------------------------------------------------------
# Styled widgets
# ---------------------------------------------------------------------------
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
                    relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=MGR_BORDER3,
                    highlightcolor="#5a8090", font=F_SMALL)

# ---------------------------------------------------------------------------
# Toggle switch widget (canvas-based pill)
# ---------------------------------------------------------------------------
class ToggleSwitch(tk.Canvas):
    W, H, R = 36, 20, 9

    def __init__(self, parent, variable: tk.BooleanVar, command=None, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         highlightthickness=0, **kw)
        self._var = variable
        self._cmd = command
        self.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = self._var.get()
        track_col = "#1a4030" if on else "#1a3040"
        bd_col    = "#2a5040" if on else "#2a4050"
        knob_col  = HP_FULL   if on else "#3a5060"
        self.create_round_rect(1, 1, self.W-1, self.H-1, radius=self.R,
                               fill=track_col, outline=bd_col)
        kx = self.W - self.R - 3 if on else self.R + 3 - (self.R - self.H//2 + 2)
        self.create_oval(kx-self.H//2+3, 3, kx+self.H//2-3, self.H-3,
                         fill=knob_col, outline="")

    def create_round_rect(self, x1, y1, x2, y2, radius=9, **kw):
        pts = [x1+radius,y1, x2-radius,y1, x2,y1, x2,y1+radius,
               x2,y2-radius, x2,y2, x2-radius,y2, x1+radius,y2,
               x1,y2, x1,y2-radius, x1,y1+radius, x1,y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _toggle(self, _=None):
        self._var.set(not self._var.get())
        if self._cmd: self._cmd()

# ---------------------------------------------------------------------------
# Character HP overlay window
# ---------------------------------------------------------------------------
class CharacterWindow:
    def __init__(self, master, game_id: str, char: dict,
                 on_closed=None, on_hp_update=None):
        self.game_id      = game_id
        self.char         = char
        self.on_closed    = on_closed
        self.on_hp_update = on_hp_update   # callback(cid, pct, cur, mx)
        self._stop        = threading.Event()
        self._ws          = None
        self._photo       = None
        self._last_state  = None
        self._cur_pct     = 1.0
        self._cur_hp      = (0, 0)

        # show_hp_numbers is driven by the manager toggle — we just read the char dict
        self.win = tk.Toplevel(master)
        self.win.title(char.get("name", "HP"))
        self.win.configure(bg=OVL_BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", bool(char.get("always_on_top", False)))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._load_portrait(self._resolve_portrait(1.0))
        self._apply_hp_visibility()

        threading.Thread(target=self._run_loop, daemon=True).start()

    # ── UI build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.portrait_canvas = tk.Canvas(self.win, width=OVL_W, height=OVL_W,
                                         bg=OVL_BG, highlightthickness=0)
        self.portrait_canvas.pack()
        self._img_id = self.portrait_canvas.create_image(
            OVL_W // 2, OVL_W // 2, anchor="center")

        # HP bar section
        self.hp_frame = tk.Frame(self.win, bg=OVL_BG)
        self.hp_frame.pack(fill="x", padx=BAR_PAD, pady=(BAR_PAD, BAR_PAD))

        self.bar_canvas = tk.Canvas(self.hp_frame, width=OVL_W - BAR_PAD*2,
                                    height=BAR_H, bg=OVL_BG, highlightthickness=0)
        self.bar_canvas.pack()

        # HP number label — conditionally shown
        self.hp_label = tk.Label(self.hp_frame, text="", bg=OVL_BG,
                                 fg=T_PRIMARY, font=F_MONO, anchor="w")

        self._draw_bar(1.0)

    def _apply_hp_visibility(self):
        """Show or hide the HP number label and resize the window accordingly."""
        show = bool(self.char.get("show_hp_numbers", False))
        if show:
            self.hp_label.pack(anchor="w", pady=(6, 0))
        else:
            self.hp_label.pack_forget()
        # Let tkinter recalculate, then lock the size
        self.win.update_idletasks()
        self.win.geometry(f"{OVL_W}x{self.win.winfo_reqheight()}")

    # ── Portrait ─────────────────────────────────────────────────────────────
    _STATE_ORDER = ["portrait_unscathed","portrait_scratched","portrait_injured",
                    "portrait_bloodied","portrait_critical","portrait_dead"]
    _STATE_MAP   = {"full":"portrait_unscathed","scratched":"portrait_scratched",
                    "injured":"portrait_injured","bloodied":"portrait_bloodied",
                    "critical":"portrait_critical","dead":"portrait_dead"}

    def _resolve_portrait(self, pct: float) -> str:
        ideal = self._STATE_MAP[hp_state(pct)]
        idx   = self._STATE_ORDER.index(ideal)
        for key in [self._STATE_ORDER[idx]] + self._STATE_ORDER[max(0,idx-1)::-1] + self._STATE_ORDER[idx+1:]:
            p = self.char.get(key, "")
            if p and os.path.isfile(p):
                return p
        return ""

    def _update_portrait_for(self, pct: float):
        state = hp_state(pct)
        if state == self._last_state:
            return
        self._last_state = state
        self._load_portrait(self._resolve_portrait(pct))

    def _load_portrait(self, path: str):
        size = OVL_W
        if path and os.path.isfile(path):
            img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        else:
            img = Image.new("RGBA", (size, size), OVL_BG)
        img = round_image(img, CORNER_R)
        self._photo = ImageTk.PhotoImage(img)
        self.portrait_canvas.itemconfig(self._img_id, image=self._photo)

    # ── Bar ──────────────────────────────────────────────────────────────────
    def _draw_bar(self, pct: float):
        c = self.bar_canvas
        c.delete("all")
        w = OVL_W - BAR_PAD * 2
        h = BAR_H
        r = h // 2
        col = hp_bar_color(pct)
        # track
        c.create_arc(0,0,r*2,h,      start=90,  extent=180,  fill=OVL_BAR_BG, outline="")
        c.create_rectangle(r,0,w-r,h,                         fill=OVL_BAR_BG, outline="")
        c.create_arc(w-r*2,0,w,h,    start=270, extent=180,  fill=OVL_BAR_BG, outline="")
        # fill
        fw = max(0, int(w * max(0.0, min(1.0, pct))))
        if fw > r*2:
            c.create_arc(0,0,r*2,h,      start=90,  extent=180,  fill=col, outline="")
            c.create_rectangle(r,0,fw-r,h,                         fill=col, outline="")
            c.create_arc(fw-r*2,0,fw,h,  start=270, extent=180,  fill=col, outline="")
        elif fw > 0:
            c.create_arc(0,0,r*2,h,      start=90,  extent=180,  fill=col, outline="")
            c.create_rectangle(r,0,fw,h,                            fill=col, outline="")

    # ── UI update (thread-safe) ───────────────────────────────────────────────
    def _update_ui(self, pct: float, cur: int, mx: int):
        self._cur_pct = pct
        self._cur_hp  = (cur, mx)
        def _do():
            self._draw_bar(pct)
            self._update_portrait_for(pct)
            self.hp_label.config(text=f"{cur}  /  {mx}")
            if self.on_hp_update:
                self.on_hp_update(self.char["character_id"], pct, cur, mx)
        self.win.after(0, _do)

    def refresh_visibility(self):
        """Called by manager when the HP-number toggle changes."""
        self.win.after(0, self._apply_hp_visibility)

    # ── Worker ───────────────────────────────────────────────────────────────
    def _run_loop(self):
        cookie  = self.char["cookie_header"]
        user_id = self.char["user_id"]
        char_id = self.char["character_id"]
        token, ttl, start, refresh_at = None, 300, None, 270

        while not self._stop.is_set():
            try:
                if start is None or (time.monotonic() - start) > refresh_at:
                    self._set_status("auth")
                    token, ttl = get_token(cookie)
                    refresh_at = max(30, ttl - 30)
                    start = time.monotonic()

                self._set_status("fetch")
                cdata = get_character(cookie, token, char_id)
                pct, cur, mx = calculate_hp(cdata)
                self._update_ui(pct, cur, mx)
                self._set_status("listen")
                self._listen_ws(cookie, user_id, char_id, token, start, refresh_at)

            except Exception as e:
                print(f"[{char_id}] error: {e}")
                traceback.print_exc()
                self._set_status("error")
                time.sleep(5)
                start = None

    def _set_status(self, key: str):
        msgs = {"auth":"Authenticating…","fetch":"Fetching character…",
                "listen":"Listening…","error":"Error — retrying…"}
        if self.on_hp_update:
            # pass status as special call with pct=-1 to signal status-only update
            cid = self.char["character_id"]
            # We use a dedicated callback instead
            pass
        if self._status_cb:
            self._status_cb(self.char["character_id"], msgs.get(key, key))

    def _listen_ws(self, cookie, user_id, char_id, token, start, refresh_at):
        ws_url = (WS_BASE + "?gameId=" + self.game_id
                  + "&userId=" + user_id + "&stt=" + token)
        ws = websocket.create_connection(ws_url, timeout=30,
             header={"Origin": ORIGIN, "Cookie": cookie})
        self._ws = ws
        try:
            while not self._stop.is_set():
                if (time.monotonic() - start) > refresh_at:
                    break
                ws.settimeout(5)
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    print(f"[{char_id}] ws: {e}"); break
                if not msg: continue
                try: evt = json.loads(msg)
                except: continue
                if should_refresh(evt, char_id):
                    ws.close(); self._ws = None
                    cdata = get_character(cookie, token, char_id)
                    pct, cur, mx = calculate_hp(cdata)
                    self._update_ui(pct, cur, mx)
                    ws = websocket.create_connection(ws_url, timeout=30,
                         header={"Origin": ORIGIN, "Cookie": cookie})
                    self._ws = ws
        finally:
            try: ws.close()
            except: pass
            self._ws = None

    def close(self):
        if self._stop.is_set(): return
        self._stop.set()
        if self._ws:
            try: self._ws.close()
            except: pass
        try: self.win.destroy()
        except: pass
        if self.on_closed: self.on_closed()

    # status callback set by manager after creation
    _status_cb = None

# ---------------------------------------------------------------------------
# Character dialog
# ---------------------------------------------------------------------------
class CharacterDialog(tk.Toplevel):
    _STATES = [
        ("portrait_unscathed", "Unscathed",  "100%",    HP_FULL),
        ("portrait_scratched", "Scratched",  "75–100%", HP_SCRATCH),
        ("portrait_injured",   "Injured",    "50–75%",  HP_INJURED),
        ("portrait_bloodied",  "Bloodied",   "25–50%",  HP_BLOODIED),
        ("portrait_critical",  "Critical",   "0–25%",   HP_CRIT),
        ("portrait_dead",      "Dead",       "0%",      HP_DEAD),
    ]

    def __init__(self, parent, ch: dict):
        super().__init__(parent)
        self.title("Character")
        self.configure(bg=DLG_BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._cookie_shown = False
        self._build(ch)

    def _build(self, ch):
        # ── Header ──
        hdr = tk.Frame(self, bg=MGR_HEADER)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Edit character", bg=MGR_HEADER, fg=T_PRIMARY,
                 font=F_BOLD, anchor="w").pack(side="left", padx=14, pady=10)
        mk_sep(self, MGR_BORDER)

        body = tk.Frame(self, bg=DLG_BG)
        body.pack(fill="x", padx=14, pady=10)

        # ── Credentials ──
        cred_fields = [
            ("name",         "CHARACTER NAME", ch.get("name",         ""), False),
            ("user_id",      "USER ID",        ch.get("user_id",      ""), False),
            ("character_id", "CHARACTER ID",   ch.get("character_id", ""), False),
        ]
        self._vars = {}
        for key, label, val, _ in cred_fields:
            self._add_field(body, key, label, val, show="")

        # cookie with eye toggle
        tk.Label(body, text="COOKIE HEADER", bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6,2))
        cf = tk.Frame(body, bg=DLG_BG)
        cf.pack(fill="x", pady=(0,4))
        self._vars["cookie_header"] = tk.StringVar(value=ch.get("cookie_header",""))
        self._cookie_entry = styled_entry(cf, self._vars["cookie_header"], width=36, show="*")
        self._cookie_entry.pack(side="left", ipady=4, padx=(0,4))
        styled_button(cf, "👁", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                      self._toggle_cookie, font=F_SMALL).pack(side="left")

        # ── Portrait section ──
        mk_sep(body, MGR_BORDER, 0)
        tk.Label(body, text="PORTRAITS BY HEALTH STATE", bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(10,6))

        self._portrait_vars = {}
        grid = tk.Frame(body, bg=DLG_BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        for idx, (key, state_name, pct_label, col) in enumerate(self._STATES):
            r, c = divmod(idx, 2)
            cell = tk.Frame(grid, bg=MGR_ROW, highlightthickness=1,
                            highlightbackground=MGR_BORDER2)
            cell.grid(row=r, column=c, padx=3, pady=3, sticky="ew")

            hrow = tk.Frame(cell, bg=MGR_ROW)
            hrow.pack(fill="x", padx=8, pady=(6,2))
            tk.Label(hrow, text=state_name, bg=MGR_ROW, fg=col,
                     font=("Segoe UI", 9, "bold")).pack(side="left")
            tk.Label(hrow, text=pct_label, bg=MGR_ROW, fg=T_DIM,
                     font=F_TINY).pack(side="right")

            var = tk.StringVar(value=ch.get(key, ""))
            self._portrait_vars[key] = var

            frow = tk.Frame(cell, bg=MGR_ROW)
            frow.pack(fill="x", padx=8, pady=(0,6))
            ent = tk.Entry(frow, textvariable=var, width=16,
                           bg=DLG_ENTRY_BG, fg=T_DIM, insertbackground=T_DIM,
                           relief="flat", bd=0, highlightthickness=1,
                           highlightbackground=MGR_BORDER2, font=F_TINY)
            ent.pack(side="left", fill="x", expand=True, ipady=3, padx=(0,4))
            styled_button(frow, "…", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                          lambda v=var: self._browse(v), font=F_TINY).pack(side="left")

        # ── Always on top ──
        mk_sep(body, MGR_BORDER, 0)
        opt_row = tk.Frame(body, bg=DLG_BG)
        opt_row.pack(fill="x", pady=(10,2))
        tk.Label(opt_row, text="Always on top", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._on_top_var = tk.BooleanVar(value=bool(ch.get("always_on_top", False)))
        ToggleSwitch(opt_row, self._on_top_var, bg=DLG_BG).pack(side="right")

        # ── Warning ──
        tk.Label(body,
                 text="⚠  Cookie may change over time — re-enter if connection fails.",
                 bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                 wraplength=380, justify="left").pack(anchor="w", pady=(8,2))

        # ── Footer ──
        mk_sep(self, MGR_BORDER)
        foot = tk.Frame(self, bg=MGR_HEADER)
        foot.pack(fill="x", padx=14, pady=8)
        styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                      self.destroy).pack(side="right", padx=(4,0), ipady=4, ipadx=8)
        styled_button(foot, "Save",  BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                      self._submit, font=F_MED).pack(side="right", ipady=4, ipadx=12)

    def _add_field(self, parent, key, label, val, show=""):
        tk.Label(parent, text=label, bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6,2))
        var = tk.StringVar(value=val)
        self._vars[key] = var
        styled_entry(parent, var, width=42, show=show).pack(
            fill="x", ipady=4, pady=(0,2))

    def _toggle_cookie(self):
        self._cookie_shown = not self._cookie_shown
        self._cookie_entry.config(show="" if self._cookie_shown else "*")

    def _browse(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.gif"),("All","*.*")])
        if path: var.set(path)

    def _submit(self):
        vals = {k: v.get().strip() for k, v in self._vars.items()}
        if not all([vals["name"], vals["user_id"],
                    vals["character_id"], vals["cookie_header"]]):
            messagebox.showwarning("Required",
                "Name, User ID, Character ID and Cookie are required.", parent=self)
            return
        for key, var in self._portrait_vars.items():
            vals[key] = var.get().strip()
        vals["always_on_top"]  = self._on_top_var.get()
        self.result = vals
        self.destroy()

# ---------------------------------------------------------------------------
# Game dialog
# ---------------------------------------------------------------------------
class GameDialog(tk.Toplevel):
    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.title("Game")
        self.configure(bg=DLG_BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        hdr = tk.Frame(self, bg=MGR_HEADER)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Game", bg=MGR_HEADER, fg=T_PRIMARY,
                 font=F_BOLD, anchor="w").pack(side="left", padx=14, pady=10)
        mk_sep(self, MGR_BORDER)

        body = tk.Frame(self, bg=DLG_BG)
        body.pack(fill="x", padx=14, pady=10)

        self._vars = {}
        for key, label, val in [("name","GAME NAME",game.get("name","")),
                                  ("id",  "GAME ID",  game.get("id",  ""))]:
            tk.Label(body, text=label, bg=DLG_BG, fg=DLG_LABEL_FG,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6,2))
            var = tk.StringVar(value=val)
            self._vars[key] = var
            styled_entry(body, var, width=32).pack(fill="x", ipady=4, pady=(0,2))

        mk_sep(self, MGR_BORDER)
        foot = tk.Frame(self, bg=MGR_HEADER)
        foot.pack(fill="x", padx=14, pady=8)
        styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                      self.destroy).pack(side="right", padx=(4,0), ipady=4, ipadx=8)
        styled_button(foot, "Save",  BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                      self._submit, font=F_MED).pack(side="right", ipady=4, ipadx=12)

    def _submit(self):
        name = self._vars["name"].get().strip()
        gid  = self._vars["id"].get().strip()
        if not name or not gid:
            messagebox.showwarning("Required","Both fields are required.", parent=self)
            return
        self.result = {"name": name, "id": gid}
        self.destroy()

# ---------------------------------------------------------------------------
# Manager window
# ---------------------------------------------------------------------------
class ManagerWindow:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root     = root
        self.cfg      = cfg
        self._windows: dict[str, CharacterWindow] = {}
        self._hp_data: dict[str, tuple] = {}       # cid → (pct, cur, mx)
        self._status:  dict[str, str]   = {}       # cid → status string
        self._hp_toggles: dict[str, tk.BooleanVar] = {}  # cid → BooleanVar

        root.title(f"D&D Health Bar  v{APP_VERSION}")
        root.configure(bg=MGR_BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self._build_ui()
        self._refresh_games()

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=MGR_HEADER)
        hdr.pack(fill="x")
        logo = tk.Label(hdr, text="⚔", bg="#1e2c38", fg="#8ab0c0",
                        font=("Segoe UI", 16), width=2, relief="flat",
                        highlightthickness=1, highlightbackground=MGR_BORDER3)
        logo.pack(side="left", padx=(12,8), pady=10)
        title_col = tk.Frame(hdr, bg=MGR_HEADER)
        title_col.pack(side="left")
        tk.Label(title_col, text="D&D Health Bar", bg=MGR_HEADER, fg=T_PRIMARY,
                 font=F_TITLE).pack(anchor="w")
        tk.Label(title_col, text=f"v{APP_VERSION}", bg=MGR_HEADER, fg=T_DIM,
                 font=F_TINY).pack(anchor="w")
        mk_sep(self.root, MGR_BORDER)

        # Game bar
        gbar = tk.Frame(self.root, bg=MGR_HEADER, pady=7)
        gbar.pack(fill="x", padx=10)

        self._game_var = tk.StringVar()
        self._game_btn = tk.Button(
            gbar, textvariable=self._game_var,
            bg=MGR_PILL, fg=T_PRIMARY, font=F_BOLD,
            relief="flat", bd=0,
            highlightthickness=1, highlightbackground=MGR_BORDER3,
            activebackground=MGR_BORDER2, activeforeground=T_PRIMARY,
            anchor="w", padx=10, cursor="hand2",
            command=self._game_menu_popup)
        self._game_btn.pack(side="left", fill="x", expand=True, ipady=5)

        for txt, col, bdc, cmd in [
            ("✎", BTN_EDIT_BG,  BTN_EDIT_BD,  self._edit_game),
            ("＋", BTN_EDIT_BG,  BTN_EDIT_BD,  self._add_game),
            ("✕", DANGER_BG,   DANGER_BD,    self._delete_game),
        ]:
            styled_button(gbar, txt, col, BTN_EDIT_FG if col!=DANGER_BG else DANGER_FG,
                          bdc, cmd, font=F_MED, width=3).pack(
                side="left", padx=(4,0), ipady=5)

        mk_sep(self.root, MGR_BORDER)

        # Character list
        self._char_frame = tk.Frame(self.root, bg=MGR_BG)
        self._char_frame.pack(fill="both", expand=True, padx=8, pady=6)

        mk_sep(self.root, MGR_BORDER)

        # Add character button
        add_frame = tk.Frame(self.root, bg=MGR_BG, pady=6)
        add_frame.pack(fill="x", padx=10)
        add_btn = tk.Button(add_frame, text="＋  Add character to this game",
                            bg=MGR_BG, fg=T_MUTED,
                            relief="flat", bd=0,
                            highlightthickness=1, highlightbackground=MGR_BORDER2,
                            highlightcolor="#3a5060",
                            activebackground=MGR_BORDER2, activeforeground=T_DIM,
                            font=F_SMALL, cursor="hand2",
                            command=self._add_character)
        add_btn.pack(fill="x", ipady=5)

        mk_sep(self.root, MGR_BORDER)

        # Status bar
        self._status_bar = tk.Frame(self.root, bg=MGR_HEADER, pady=4)
        self._status_bar.pack(fill="x", padx=10)
        self._status_label = tk.Label(self._status_bar, text="No windows open",
                                      bg=MGR_HEADER, fg=T_MUTED, font=F_TINY,
                                      anchor="w")
        self._status_label.pack(fill="x")

    # ── Game popup menu (replaces OptionMenu) ────────────────────────────────
    def _game_menu_popup(self):
        names = [g["name"] for g in self._games()]
        if not names: return
        menu = tk.Menu(self.root, tearoff=0, bg=MGR_PILL, fg=T_PRIMARY,
                       activebackground=MGR_BORDER2, activeforeground=T_PRIMARY,
                       relief="flat", bd=0, font=F_SMALL)
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._select_game(v))
        x = self._game_btn.winfo_rootx()
        y = self._game_btn.winfo_rooty() + self._game_btn.winfo_height()
        menu.tk_popup(x, y)

    def _select_game(self, name: str):
        self._game_var.set(name)
        self._refresh_chars()

    # ── Games ─────────────────────────────────────────────────────────────────
    def _games(self):
        return self.cfg.setdefault("games", [])

    def _current_game(self):
        sel = self._game_var.get()
        return next((g for g in self._games() if g["name"] == sel), None)

    def _refresh_games(self):
        names = [g["name"] for g in self._games()]
        cur   = self._game_var.get()
        if names and cur not in names:
            self._game_var.set(names[0])
            self._refresh_chars()
        elif not names:
            self._game_var.set("  No games yet  ")
            self._refresh_chars()

    def _add_game(self):
        dlg = GameDialog(self.root, {})
        self.root.wait_window(dlg)
        if not dlg.result: return
        g = {"id": dlg.result["id"], "name": dlg.result["name"], "characters": []}
        self._games().append(g)
        save_config(self.cfg)
        self._refresh_games()
        self._game_var.set(g["name"])
        self._refresh_chars()

    def _edit_game(self):
        g = self._current_game()
        if not g: return
        dlg = GameDialog(self.root, g.copy())
        self.root.wait_window(dlg)
        if not dlg.result: return
        g["name"] = dlg.result["name"]
        g["id"]   = dlg.result["id"]
        save_config(self.cfg)
        self._refresh_games()
        self._game_var.set(g["name"])
        self._refresh_chars()

    def _delete_game(self):
        g = self._current_game()
        if not g: return
        if not messagebox.askyesno("Delete game",
            f"Delete '{g['name']}' and all its characters?\nOpen windows will be closed.",
            parent=self.root): return
        for ch in g.get("characters", []):
            self._close_window(ch["character_id"])
        self.cfg["games"] = [x for x in self._games() if x is not g]
        save_config(self.cfg)
        self._refresh_games()

    # ── Characters ────────────────────────────────────────────────────────────
    def _refresh_chars(self):
        for w in self._char_frame.winfo_children():
            w.destroy()
        g = self._current_game()
        if g is None or not g.get("characters"):
            msg = ("No game selected — add one above."
                   if g is None else
                   "No characters yet — add one below.")
            tk.Label(self._char_frame, text=msg,
                     bg=MGR_BG, fg=T_MUTED, font=F_SMALL).pack(pady=16)
        else:
            for ch in g["characters"]:
                self._make_char_row(ch, g)
        self.root.update_idletasks()
        self.root.geometry("")

    def _make_char_row(self, ch: dict, game: dict):
        cid     = ch["character_id"]
        is_open = cid in self._windows

        row = tk.Frame(self._char_frame, bg=MGR_ROW,
                       highlightthickness=1,
                       highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
        row.pack(fill="x", pady=3)
        inner = tk.Frame(row, bg=MGR_ROW)
        inner.pack(fill="x", padx=8, pady=6)

        # Thumbnail
        thumb = 38
        cvs = tk.Canvas(inner, width=thumb, height=thumb, bg=MGR_ROW,
                        highlightthickness=0)
        cvs.pack(side="left", padx=(0,8))
        self._draw_thumb(cvs, ch, thumb)

        # Info
        info = tk.Frame(inner, bg=MGR_ROW)
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=ch.get("name","Unknown"), bg=MGR_ROW, fg=T_PRIMARY,
                 font=F_BOLD, anchor="w").pack(anchor="w")
        tk.Label(info, text=cid, bg=MGR_ROW, fg=T_DIM,
                 font=F_TINY, anchor="w").pack(anchor="w")

        # HP badge
        hp_data = self._hp_data.get(cid)
        badge_frame = tk.Frame(inner, bg=MGR_ROW)
        badge_frame.pack(side="left", padx=6)
        if hp_data and is_open:
            pct, cur, mx = hp_data
            fg, bg, bd = hp_badge_colors(pct)
            badge = tk.Label(badge_frame, text=f"{cur} / {mx}",
                             bg=bg, fg=fg, font=("Consolas",10,"bold"),
                             padx=7, pady=2,
                             highlightthickness=1, highlightbackground=bd)
            badge.pack()
        else:
            tk.Label(badge_frame, text="—",
                     bg=HPB_DEAD, fg=T_MUTED, font=F_TINY,
                     padx=7, pady=2,
                     highlightthickness=1, highlightbackground=HBB_DEAD).pack()

        # HP number toggle (per character)
        if cid not in self._hp_toggles:
            self._hp_toggles[cid] = tk.BooleanVar(
                value=bool(ch.get("show_hp_numbers", False)))
        hp_var = self._hp_toggles[cid]

        def _on_hp_toggle(c=ch, cid=cid, var=hp_var):
            c["show_hp_numbers"] = var.get()
            save_config(self.cfg)
            if cid in self._windows:
                self._windows[cid].refresh_visibility()

        tog_col = tk.Frame(inner, bg=MGR_ROW)
        tog_col.pack(side="left", padx=(0,4))
        tk.Label(tog_col, text="HP", bg=MGR_ROW, fg=T_DIM, font=F_TINY).pack()
        ToggleSwitch(tog_col, hp_var, command=_on_hp_toggle, bg=MGR_ROW).pack()

        # Status dot
        status_msg = self._status.get(cid, "")
        dot_col = "#00e676" if (is_open and status_msg == "Listening…") else \
                  "#f44336" if (is_open and "Error" in status_msg) else "#2a3c4a"
        dot = tk.Canvas(inner, width=8, height=8, bg=MGR_ROW, highlightthickness=0)
        dot.pack(side="left", padx=(0,6))
        dot.create_oval(1,1,7,7, fill=dot_col, outline="")

        # Open/close + edit buttons
        btns = tk.Frame(inner, bg=MGR_ROW)
        btns.pack(side="right")

        if is_open:
            styled_button(btns, "■", BTN_CLOSE_BG, BTN_CLOSE_FG, BTN_CLOSE_BD,
                          lambda c=ch, g=game: self._toggle_window(c, g),
                          width=3).pack(side="left", padx=(0,3), ipady=4)
        else:
            styled_button(btns, "▶", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
                          lambda c=ch, g=game: self._toggle_window(c, g),
                          width=3).pack(side="left", padx=(0,3), ipady=4)

        styled_button(btns, "✎", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                      lambda c=ch, g=game: self._edit_character(c, g),
                      width=3).pack(side="left", padx=(0,3), ipady=4)
        styled_button(btns, "✕", DANGER_BG, DANGER_FG, DANGER_BD,
                      lambda c=ch, g=game: self._delete_character(c, g),
                      width=3).pack(side="left", ipady=4)

    def _draw_thumb(self, canvas, ch, size):
        keys = ["portrait_unscathed","portrait_scratched","portrait_injured",
                "portrait_bloodied","portrait_critical","portrait_dead"]
        path = next((ch.get(k,"") for k in keys
                     if ch.get(k) and os.path.isfile(ch.get(k,""))), "")
        try:
            img = Image.open(path).convert("RGBA").resize((size,size),Image.LANCZOS) \
                  if path else Image.new("RGBA",(size,size),MGR_ROW)
            img = round_image(img, 5)
            photo = ImageTk.PhotoImage(img)
            canvas._photo = photo
            canvas.create_image(size//2, size//2, image=photo, anchor="center")
        except: pass

    # ── Window management ─────────────────────────────────────────────────────
    def _toggle_window(self, ch, game):
        cid = ch["character_id"]
        if cid in self._windows:
            self._close_window(cid)
        else:
            self._open_window(ch, game)
        self._refresh_chars()

    def _open_window(self, ch, game):
        cid = ch["character_id"]
        win = CharacterWindow(
            master       = self.root,
            game_id      = game["id"],
            char         = ch,
            on_closed    = lambda c=cid: self._on_window_closed(c),
            on_hp_update = self._on_hp_update,
        )
        win._status_cb = self._on_status_update
        self._windows[cid] = win

    def _close_window(self, cid):
        if cid in self._windows:
            try: self._windows[cid].close()
            except: pass
            self._windows.pop(cid, None)
        self._hp_data.pop(cid, None)
        self._status.pop(cid, None)
        self._update_status_bar()

    def _on_window_closed(self, cid):
        self._windows.pop(cid, None)
        self._hp_data.pop(cid, None)
        self._status.pop(cid, None)
        save_config(self.cfg)
        self.root.after(0, self._refresh_chars)
        self.root.after(0, self._update_status_bar)

    def _on_hp_update(self, cid, pct, cur, mx):
        self._hp_data[cid] = (pct, cur, mx)
        self.root.after(0, self._refresh_chars)

    def _on_status_update(self, cid, msg):
        self._status[cid] = msg
        self.root.after(0, self._update_status_bar)

    def _update_status_bar(self):
        if not self._windows:
            self._status_label.config(text="No windows open", fg=T_MUTED)
            return
        parts = []
        for cid, win in self._windows.items():
            name = win.char.get("name","?")
            msg  = self._status.get(cid, "…")
            parts.append(f"{name}: {msg}")
        self._status_label.config(text="   ·   ".join(parts), fg=T_DIM)

    # ── Character CRUD ────────────────────────────────────────────────────────
    def _add_character(self):
        g = self._current_game()
        if not g:
            messagebox.showwarning("No game","Add a game first.", parent=self.root)
            return
        dlg = CharacterDialog(self.root, {})
        self.root.wait_window(dlg)
        if dlg.result:
            g.setdefault("characters",[]).append(dlg.result)
            save_config(self.cfg)
            self._refresh_chars()

    def _edit_character(self, ch, game):
        dlg = CharacterDialog(self.root, ch.copy())
        self.root.wait_window(dlg)
        if not dlg.result: return
        ch.update(dlg.result)
        save_config(self.cfg)
        cid = ch["character_id"]
        if cid in self._windows:
            self._windows[cid]._last_state = None
        self._refresh_chars()

    def _delete_character(self, ch, game):
        if not messagebox.askyesno("Delete",
            f"Remove '{ch.get('name','?')}' from this game?", parent=self.root): return
        self._close_window(ch["character_id"])
        game["characters"] = [c for c in game["characters"] if c is not ch]
        save_config(self.cfg)
        self._refresh_chars()

    def _on_quit(self):
        save_config(self.cfg)
        for cid in list(self._windows):
            self._close_window(cid)
        self.root.destroy()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    cfg  = load_config()
    root = tk.Tk()
    ManagerWindow(root, cfg)
    root.mainloop()

if __name__ == "__main__":
    main()
