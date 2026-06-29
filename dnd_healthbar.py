"""
D&D Beyond Live Health Bar
--------------------------
Multi-game, multi-character health bar overlay.

Data model:
  games: [
    {
      "id":   "1234567",          # D&D Beyond game ID
      "name": "My Campaign",
      "characters": [
        {
          "name":          "Thorin",
          "user_id":       "1111111",
          "character_id":  "2222222",
          "cookie_header": "CobaltSession=...",
          "portrait_path": "/path/to/portrait.png"
        }
      ]
    }
  ]

Requirements:
    pip install requests websocket-client Pillow
"""

APP_VERSION = "1.0.1"

import os, sys, json, time, threading, traceback
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import requests, websocket

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
AUTH_URL      = "https://auth-service.dndbeyond.com/v1/cobalt-token"
WS_BASE       = "wss://game-log-api-live.dndbeyond.com/v1"
CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"
ORIGIN        = "https://www.dndbeyond.com"
REFERER       = "https://www.dndbeyond.com"

# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------
WINDOW_W      = 320
PORTRAIT_SIZE = 280
BAR_H         = 36
BAR_PAD       = 16
CORNER_R      = 18
BG            = "#1a1a2e"
BAR_BG        = "#3a0a0a"
C_GREEN       = "#00e676"
C_AMBER       = "#ffb300"
C_RED         = "#f44336"
C_DEAD        = "#555555"
C_TEXT        = "#e8e8e8"
C_DIM         = "#888899"
C_ENTRY       = "#2a2a4e"
C_BTN         = "#3a3a6e"
C_BTN2        = "#4a4a8e"
C_DANGER      = "#6a1a1a"
F_MAIN        = ("Segoe UI", 13, "bold")
F_MED         = ("Segoe UI", 11, "bold")
F_SMALL       = ("Segoe UI", 10)
F_TINY        = ("Segoe UI", 9)
WINDOW_H      = PORTRAIT_SIZE + BAR_H + BAR_PAD * 3 + 60

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
# D&D Beyond API
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
# Helpers
# ---------------------------------------------------------------------------
def round_image(img: Image.Image, radius: int) -> Image.Image:
    img  = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], radius=radius, fill=255)
    img.putalpha(mask)
    return img

def lerp_color(c1: str, c2: str, t: float) -> str:
    r1,g1,b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"

def hp_color(pct: float) -> str:
    if pct <= 0:   return C_DEAD
    if pct > 0.5:  return lerp_color(C_AMBER, C_GREEN, (pct - 0.5) / 0.5)
    return             lerp_color(C_RED,   C_AMBER, pct / 0.5)

def sep(parent):
    tk.Frame(parent, bg="#333355", height=1).pack(fill="x", padx=8, pady=6)

# ---------------------------------------------------------------------------
# HP window  (one per character)
# ---------------------------------------------------------------------------
class CharacterWindow:
    def __init__(self, master, game_id: str, char: dict, on_closed=None):
        """
        char dict keys: name, user_id, character_id, cookie_header, always_on_top
                        portrait_unscathed, portrait_scratched, portrait_injured,
                        portrait_bloodied, portrait_critical, portrait_dead
        """
        self.game_id    = game_id
        self.char       = char
        self.on_closed  = on_closed
        self._stop      = threading.Event()
        self._ws        = None
        self._session   = requests.Session()
        self._photo     = None
        self._last_state = None   # track which portrait is currently shown

        self.win = tk.Toplevel(master)
        self.win.title(char.get("name", "HP Bar"))
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.win.attributes("-topmost", bool(char.get("always_on_top", False)))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._load_portrait(self._resolve_portrait(1.0))   # show unscathed at startup

        threading.Thread(target=self._run_loop, daemon=True).start()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.portrait_canvas = tk.Canvas(self.win, width=PORTRAIT_SIZE,
            height=PORTRAIT_SIZE, bg=BG, highlightthickness=0)
        self.portrait_canvas.pack(padx=BAR_PAD, pady=(BAR_PAD, 0))
        self._img_id = self.portrait_canvas.create_image(
            PORTRAIT_SIZE//2, PORTRAIT_SIZE//2, anchor="center")

        self.bar_canvas = tk.Canvas(self.win,
            width=WINDOW_W - BAR_PAD*2, height=BAR_H, bg=BG, highlightthickness=0)
        self.bar_canvas.pack(padx=BAR_PAD, pady=(4, 0))

        self.hp_label = tk.Label(self.win, text="HP: — / —",
                                 bg=BG, fg=C_TEXT, font=F_MAIN)
        self.hp_label.pack()

        self.status_label = tk.Label(self.win, text="Connecting…",
                                     bg=BG, fg=C_DIM, font=F_SMALL)
        self.status_label.pack(pady=(2, BAR_PAD))

        self._draw_bar(1.0)

    # Map pct → config key (checked top-to-bottom, first match wins)
    _PORTRAIT_STATES = [
        (1.00, 1.00, "portrait_unscathed"),
        (0.75, 1.00, "portrait_scratched"),
        (0.50, 0.75, "portrait_injured"),
        (0.25, 0.50, "portrait_bloodied"),
        (0.00, 0.25, "portrait_critical"),
        (0.00, 0.00, "portrait_dead"),
    ]

    def _state_key_for(self, pct: float) -> str:
        """Return the config key for the portrait matching this HP percentage."""
        if pct <= 0.0:
            return "portrait_dead"
        if pct < 0.25:
            return "portrait_critical"
        if pct < 0.50:
            return "portrait_bloodied"
        if pct < 0.75:
            return "portrait_injured"
        if pct < 1.0:
            return "portrait_scratched"
        return "portrait_unscathed"

    def _resolve_portrait(self, pct: float) -> str:
        """Walk from the ideal state upward until we find a non-empty path, then fall back to any set."""
        order = [
            "portrait_unscathed", "portrait_scratched", "portrait_injured",
            "portrait_bloodied",  "portrait_critical",  "portrait_dead",
        ]
        ideal = self._state_key_for(pct)
        idx   = order.index(ideal)

        # Try ideal state, then walk toward scratched/unscathed (better health = earlier in list)
        for key in [order[idx]] + order[max(0, idx-1)::-1] + order[idx+1:]:
            p = self.char.get(key, "")
            if p and os.path.isfile(p):
                return p
        return ""   # no portrait configured at all

    def _update_portrait_for(self, pct: float):
        """Reload portrait only when the state bucket changes."""
        state = self._state_key_for(pct)
        if state == self._last_state:
            return
        self._last_state = state
        path = self._resolve_portrait(pct)
        self._load_portrait(path)

    def _load_portrait(self, path: str):
        if path and os.path.isfile(path):
            img = Image.open(path).convert("RGBA").resize(
                (PORTRAIT_SIZE, PORTRAIT_SIZE), Image.LANCZOS)
        else:
            img = Image.new("RGBA", (PORTRAIT_SIZE, PORTRAIT_SIZE), "#2a2a4a")
        img = round_image(img, CORNER_R)
        self._photo = ImageTk.PhotoImage(img)
        self.portrait_canvas.itemconfig(self._img_id, image=self._photo)

    def _draw_bar(self, pct: float):
        c = self.bar_canvas; c.delete("all")
        w = WINDOW_W - BAR_PAD*2; h = BAR_H; r = h//2
        col = hp_color(pct)
        # background pill
        c.create_arc(0,0,r*2,h,      start=90, extent=180,  fill=BAR_BG, outline="")
        c.create_rectangle(r,0,w-r,h,                        fill=BAR_BG, outline="")
        c.create_arc(w-r*2,0,w,h,   start=270, extent=180,  fill=BAR_BG, outline="")
        # filled pill
        fw = max(0, int(w * max(0.0, min(1.0, pct))))
        if fw > r*2:
            c.create_arc(0,0,r*2,h,       start=90, extent=180,  fill=col, outline="")
            c.create_rectangle(r,0,fw-r,h,                         fill=col, outline="")
            c.create_arc(fw-r*2,0,fw,h,  start=270, extent=180,  fill=col, outline="")
        elif fw > 0:
            c.create_arc(0,0,r*2,h,       start=90, extent=180,  fill=col, outline="")
            c.create_rectangle(r,0,fw,h,                            fill=col, outline="")

    def _update_ui(self, pct, cur, mx, status):
        def _do():
            self._draw_bar(pct)
            self.hp_label.config(text=f"HP: {cur} / {mx}")
            self.status_label.config(text=status)
            self._update_portrait_for(pct)
        self.win.after(0, _do)

    def _set_status(self, msg):
        self.win.after(0, lambda: self.status_label.config(text=msg))

    # ── Worker ───────────────────────────────────────────────────────────────
    def _run_loop(self):
        cookie  = self.char["cookie_header"]
        user_id = self.char["user_id"]
        char_id = self.char["character_id"]
        token, ttl, start, refresh_at = None, 300, None, 270

        while not self._stop.is_set():
            try:
                if start is None or (time.monotonic() - start) > refresh_at:
                    self._set_status("Authenticating…")
                    token, ttl = get_token(cookie)
                    refresh_at = max(30, ttl - 30)
                    start = time.monotonic()

                self._set_status("Fetching character…")
                cdata = get_character(cookie, token, char_id)
                pct, cur, mx = calculate_hp(cdata)
                self._update_ui(pct, cur, mx, "Listening for updates…")
                self._listen_ws(cookie, user_id, char_id, token, start, refresh_at)

            except Exception as e:
                print(f"[{char_id}] error: {e}")
                traceback.print_exc()
                self._set_status("Error — retrying in 5s…")
                time.sleep(5)
                start = None

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
                    self._set_status("HP changed — refreshing…")
                    ws.close(); self._ws = None
                    cdata = get_character(cookie, token, char_id)
                    pct, cur, mx = calculate_hp(cdata)
                    self._update_ui(pct, cur, mx, "Listening for updates…")
                    ws = websocket.create_connection(ws_url, timeout=30,
                         header={"Origin": ORIGIN, "Cookie": cookie})
                    self._ws = ws
        finally:
            try: ws.close()
            except: pass
            self._ws = None

    def close(self):
        if self._stop.is_set():
            return   # already closing, ignore double-call
        self._stop.set()
        if self._ws:
            try: self._ws.close()
            except: pass
        try: self.win.destroy()
        except: pass
        if self.on_closed: self.on_closed()

# ---------------------------------------------------------------------------
# Character add / edit dialog
# ---------------------------------------------------------------------------
class CharacterDialog(tk.Toplevel):
    def __init__(self, parent, ch: dict):
        super().__init__(parent)
        self.title("Character")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        fields = [
            ("name",          "Character name", ch.get("name",          "")),
            ("user_id",       "User ID",        ch.get("user_id",       "")),
            ("character_id",  "Character ID",   ch.get("character_id",  "")),
            ("cookie_header", "Cookie header",  ch.get("cookie_header", "")),
        ]
        self._vars   = {}
        self._entries = {}
        for i, (key, label, val) in enumerate(fields):
            tk.Label(self, text=label, bg=BG, fg=C_TEXT, font=F_SMALL).grid(
                row=i, column=0, sticky="w", padx=12, pady=4)
            var  = tk.StringVar(value=val)
            show = "*" if key == "cookie_header" else ""
            ent  = tk.Entry(self, textvariable=var, width=44, show=show,
                            bg=C_ENTRY, fg=C_TEXT, insertbackground=C_TEXT)
            ent.grid(row=i, column=1, padx=(0,4), pady=4)
            if key == "cookie_header":
                tk.Button(self, text="👁", bg=C_BTN, fg=C_TEXT,
                          command=lambda e=ent: self._toggle(e)).grid(row=i, column=2, padx=4)
            self._vars[key]    = var
            self._entries[key] = ent

        # ── Portrait section header ──
        r0 = len(fields)
        tk.Frame(self, bg="#333355", height=1).grid(
            row=r0, column=0, columnspan=3, sticky="ew", padx=8, pady=(8,4))
        tk.Label(self, text="Portraits by health state",
                 bg=BG, fg=C_DIM, font=F_TINY).grid(
            row=r0+1, column=0, columnspan=3, sticky="w", padx=12)
        tk.Label(self, text="(leave blank to reuse the previous state's image)",
                 bg=BG, fg=C_DIM, font=F_TINY).grid(
            row=r0+2, column=0, columnspan=3, sticky="w", padx=12, pady=(0,4))

        # State definitions: (config key, label, colour hint)
        self._portrait_states = [
            ("portrait_unscathed", "Unscathed   100 %",       "#00e676"),
            ("portrait_scratched", "Scratched   75–100 %",    "#80e676"),
            ("portrait_injured",   "Injured      50–75 %",    "#ffb300"),
            ("portrait_bloodied",  "Bloodied     25–50 %",    "#ff6600"),
            ("portrait_critical",  "Critical      0–25 %",    "#f44336"),
            ("portrait_dead",      "Dead              0 %",   "#555555"),
        ]
        self._portrait_vars = {}
        for idx, (key, label, colour) in enumerate(self._portrait_states):
            row = r0 + 3 + idx
            tk.Label(self, text=label, bg=BG, fg=colour, font=F_SMALL).grid(
                row=row, column=0, sticky="w", padx=12, pady=2)
            var = tk.StringVar(value=ch.get(key, ""))
            ent = tk.Entry(self, textvariable=var, width=34,
                           bg=C_ENTRY, fg=C_TEXT, insertbackground=C_TEXT)
            ent.grid(row=row, column=1, padx=(0,4), pady=2)
            tk.Button(self, text="Browse…", bg=C_BTN, fg=C_TEXT, font=F_TINY,
                      command=lambda v=var: self._browse_portrait(v)).grid(
                row=row, column=2, padx=4, pady=2)
            self._portrait_vars[key] = var

        # ── Always on top ──
        sep_row = r0 + 3 + len(self._portrait_states)
        tk.Frame(self, bg="#333355", height=1).grid(
            row=sep_row, column=0, columnspan=3, sticky="ew", padx=8, pady=(8,4))
        self._on_top_var = tk.BooleanVar(value=bool(ch.get("always_on_top", False)))
        tk.Checkbutton(self, text="Always on top", variable=self._on_top_var,
                       bg=BG, fg=C_TEXT, selectcolor=C_ENTRY,
                       activebackground=BG, activeforeground=C_TEXT,
                       font=F_SMALL).grid(
            row=sep_row+1, column=0, columnspan=3, padx=12, sticky="w")

        tk.Label(self,
                 text="⚠  Cookie may change over time — re-enter it here if the connection fails.",
                 bg=BG, fg=C_DIM, font=F_TINY, wraplength=420, justify="left").grid(
            row=sep_row+2, column=0, columnspan=3, padx=12, sticky="w")

        bf = tk.Frame(self, bg=BG)
        bf.grid(row=sep_row+3, column=0, columnspan=3, pady=10)
        tk.Button(bf, text="Save", bg=C_BTN2, fg=C_TEXT, font=F_MED,
                  padx=16, command=self._submit).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg=C_BTN, fg=C_TEXT,
                  command=self.destroy).pack(side="left", padx=6)

    def _toggle(self, entry):
        entry.config(show="" if entry.cget("show") == "*" else "*")

    def _browse_portrait(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif"), ("All", "*.*")])
        if path: var.set(path)

    def _submit(self):
        vals = {k: v.get().strip() for k, v in self._vars.items()}
        if not all([vals["name"], vals["user_id"], vals["character_id"], vals["cookie_header"]]):
            messagebox.showwarning("Required", "All fields except portraits are required.", parent=self)
            return
        for key, var in self._portrait_vars.items():
            vals[key] = var.get().strip()
        vals["always_on_top"] = self._on_top_var.get()
        self.result = vals
        self.destroy()

# ---------------------------------------------------------------------------
# Game add / rename dialog
# ---------------------------------------------------------------------------
class GameDialog(tk.Toplevel):
    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.title("Game")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        fields = [
            ("name", "Game name", game.get("name", "")),
            ("id",   "Game ID",   game.get("id",   "")),
        ]
        self._vars = {}
        for i, (key, label, val) in enumerate(fields):
            tk.Label(self, text=label, bg=BG, fg=C_TEXT, font=F_SMALL).grid(
                row=i, column=0, sticky="w", padx=12, pady=6)
            var = tk.StringVar(value=val)
            tk.Entry(self, textvariable=var, width=32,
                     bg=C_ENTRY, fg=C_TEXT, insertbackground=C_TEXT).grid(
                row=i, column=1, padx=12, pady=6)
            self._vars[key] = var

        bf = tk.Frame(self, bg=BG)
        bf.grid(row=len(fields), column=0, columnspan=2, pady=10)
        tk.Button(bf, text="Save", bg=C_BTN2, fg=C_TEXT, font=F_MED,
                  padx=16, command=self._submit).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg=C_BTN, fg=C_TEXT,
                  command=self.destroy).pack(side="left", padx=6)

    def _submit(self):
        name = self._vars["name"].get().strip()
        gid  = self._vars["id"].get().strip()
        if not name or not gid:
            messagebox.showwarning("Required", "Both name and Game ID are required.", parent=self)
            return
        self.result = {"name": name, "id": gid}
        self.destroy()

# ---------------------------------------------------------------------------
# Manager window
# ---------------------------------------------------------------------------
class ManagerWindow:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root = root
        self.cfg  = cfg
        self._windows: dict[str, CharacterWindow] = {}  # character_id → window

        root.title(f"D&D Health Bar  v{APP_VERSION}")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self._build_ui()
        self._refresh_games()

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Game selector bar ──
        game_bar = tk.Frame(self.root, bg=BG, pady=8)
        game_bar.pack(fill="x", padx=12)

        tk.Label(game_bar, text="Game:", bg=BG, fg=C_TEXT, font=F_MED).pack(side="left")

        self._game_var  = tk.StringVar()
        self._game_menu = tk.OptionMenu(game_bar, self._game_var, "")
        self._game_menu.config(bg=C_ENTRY, fg=C_TEXT, activebackground=C_BTN,
                               highlightthickness=0, font=F_SMALL, width=22)
        self._game_menu["menu"].config(bg=C_ENTRY, fg=C_TEXT, font=F_SMALL)
        self._game_menu.pack(side="left", padx=6)
        self._game_var.trace_add("write", lambda *_: self._refresh_chars())

        tk.Button(game_bar, text="+ Add",    bg=C_BTN,    fg=C_TEXT, font=F_SMALL,
                  command=self._add_game).pack(side="left", padx=2)
        tk.Button(game_bar, text="✎ Edit",   bg=C_BTN,    fg=C_TEXT, font=F_SMALL,
                  command=self._edit_game).pack(side="left", padx=2)
        tk.Button(game_bar, text="✕ Delete", bg=C_DANGER, fg=C_TEXT, font=F_SMALL,
                  command=self._delete_game).pack(side="left", padx=2)

        sep(self.root)

        # ── Character list (scrollable) ──
        self._char_frame = tk.Frame(self.root, bg=BG)
        self._char_frame.pack(fill="both", expand=True, padx=12)

        sep(self.root)

        # ── Add character button ──
        bottom = tk.Frame(self.root, bg=BG, pady=6)
        bottom.pack(fill="x", padx=12)
        tk.Button(bottom, text="+ Add character to this game",
                  bg=C_BTN2, fg=C_TEXT, font=F_SMALL,
                  command=self._add_character).pack(side="left")

    # ── Games ─────────────────────────────────────────────────────────────────
    def _games(self) -> list:
        return self.cfg.setdefault("games", [])

    def _current_game(self) -> dict | None:
        sel = self._game_var.get()
        return next((g for g in self._games() if g["name"] == sel), None)

    def _refresh_games(self):
        names = [g["name"] for g in self._games()]
        menu  = self._game_menu["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._game_var.set(v))
        cur = self._game_var.get()
        if names and cur not in names:
            self._game_var.set(names[0])
        elif not names:
            self._game_var.set("")
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

    def _delete_game(self):
        g = self._current_game()
        if not g: return
        if not messagebox.askyesno("Delete game",
            f"Delete '{g['name']}' and all its characters?\nOpen HP windows will be closed.",
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
        if g is None:
            tk.Label(self._char_frame,
                     text="No game selected. Add a game above.",
                     bg=BG, fg=C_DIM, font=F_SMALL).pack(pady=20)
        elif not g.get("characters"):
            tk.Label(self._char_frame,
                     text="No characters yet. Click '+ Add character' below.",
                     bg=BG, fg=C_DIM, font=F_SMALL).pack(pady=20)
        else:
            for ch in g["characters"]:
                self._make_char_row(ch, g)
        self.root.update_idletasks()
        self.root.geometry("")   # auto-resize

    def _make_char_row(self, ch: dict, game: dict):
        cid    = ch["character_id"]
        is_open = cid in self._windows

        row = tk.Frame(self._char_frame, bg="#22223a", pady=6, padx=8)
        row.pack(fill="x", pady=3)

        # thumbnail
        thumb = 44
        cvs   = tk.Canvas(row, width=thumb, height=thumb, bg="#22223a", highlightthickness=0)
        cvs.pack(side="left", padx=(0, 10))
        self._draw_thumb(cvs, ch, thumb)

        # info block
        info = tk.Frame(row, bg="#22223a")
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=ch.get("name", "Unknown"),
                 bg="#22223a", fg=C_TEXT, font=F_MED, anchor="w").pack(anchor="w")
        tk.Label(info, text=f"User: {ch.get('user_id','')}  |  Char: {cid}",
                 bg="#22223a", fg=C_DIM, font=F_TINY, anchor="w").pack(anchor="w")

        # buttons (right side)
        btn_col = tk.Frame(row, bg="#22223a")
        btn_col.pack(side="right")

        toggle_txt = "Close window" if is_open else "Open window"
        toggle_bg  = C_DANGER if is_open else C_BTN2
        tk.Button(btn_col, text=toggle_txt, bg=toggle_bg, fg=C_TEXT, font=F_SMALL,
                  command=lambda c=ch, g=game: self._toggle_window(c, g)
                  ).pack(fill="x", pady=1)

        edit_del = tk.Frame(btn_col, bg="#22223a")
        edit_del.pack(fill="x")
        tk.Button(edit_del, text="✎ Edit", bg=C_BTN, fg=C_TEXT, font=F_TINY,
                  command=lambda c=ch, g=game: self._edit_character(c, g)
                  ).pack(side="left", padx=(0,2))
        tk.Button(edit_del, text="✕", bg=C_DANGER, fg=C_TEXT, font=F_TINY,
                  command=lambda c=ch, g=game: self._delete_character(c, g)
                  ).pack(side="left")

    def _draw_thumb(self, canvas: tk.Canvas, ch: dict, size: int):
        # Use unscathed portrait for thumbnail, fall back through states
        state_keys = [
            "portrait_unscathed", "portrait_scratched", "portrait_injured",
            "portrait_bloodied",  "portrait_critical",  "portrait_dead",
        ]
        path = next((ch.get(k, "") for k in state_keys
                     if ch.get(k) and os.path.isfile(ch.get(k, ""))), "")
        try:
            if path:
                img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
            else:
                img = Image.new("RGBA", (size, size), "#2a2a4a")
            img = round_image(img, 6)
            photo = ImageTk.PhotoImage(img)
            canvas._photo = photo
            canvas.create_image(size//2, size//2, image=photo, anchor="center")
        except Exception:
            pass

    def _toggle_window(self, ch: dict, game: dict):
        cid = ch["character_id"]
        if cid in self._windows:
            self._close_window(cid)
        else:
            self._open_window(ch, game)
        self._refresh_chars()

    def _open_window(self, ch: dict, game: dict):
        cid = ch["character_id"]
        win = CharacterWindow(
            master     = self.root,
            game_id    = game["id"],
            char       = ch,
            on_closed  = lambda c=cid: self._on_window_closed(c),
        )
        self._windows[cid] = win

    def _close_window(self, cid: str):
        if cid in self._windows:
            try: self._windows[cid].close()
            except: pass
            self._windows.pop(cid, None)

    def _on_window_closed(self, cid: str):
        self._windows.pop(cid, None)
        save_config(self.cfg)
        self._refresh_chars()

    def _add_character(self):
        g = self._current_game()
        if not g:
            messagebox.showwarning("No game", "Add a game first.", parent=self.root)
            return
        dlg = CharacterDialog(self.root, {})
        self.root.wait_window(dlg)
        if dlg.result:
            g.setdefault("characters", []).append(dlg.result)
            save_config(self.cfg)
            self._refresh_chars()

    def _edit_character(self, ch: dict, game: dict):
        dlg = CharacterDialog(self.root, ch.copy())
        self.root.wait_window(dlg)
        if not dlg.result: return
        ch.update(dlg.result)
        save_config(self.cfg)
        # refresh portrait in open window if any
        cid = ch["character_id"]
        if cid in self._windows:
            win = self._windows[cid]
            win._last_state = None   # force portrait reload on next HP update
        self._refresh_chars()

    def _delete_character(self, ch: dict, game: dict):
        if not messagebox.askyesno("Delete character",
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
