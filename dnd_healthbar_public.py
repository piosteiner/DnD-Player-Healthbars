"""
D&D Beyond Live Health Bar — Public Edition
--------------------------------------------
Works with public D&D Beyond character sheets only.
No login, no cookies, no sensitive credentials required.

Data model:
  games: [
    {
      "name": "My Campaign",
      "characters": [
        {
          "name":               "Thorin",
          "character_id":       "2222222",
          "always_on_top":      false,
          "show_hp_numbers":    false,
          "window_pos":         [100, 100],
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
  overlay_server: {"enabled": true, "port": 7777}

OBS browser source:
  While the app runs it serves each character's overlay at
  http://127.0.0.1:7777/overlay/<character_id>  (localhost only).

Requirements:
    pip install requests Pillow
"""

APP_VERSION = "2.1.0"

import os, sys, io, json, time, re, threading, traceback, queue
import html, mimetypes, webbrowser, urllib.parse, http.server
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageChops
import requests

# System tray support (optional — falls back to normal minimize if not installed)
try:
    import pystray
    from pystray import MenuItem as TrayItem
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"
ORIGIN        = "https://www.dndbeyond.com"
UA            = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
POLL_INTERVAL = 5   # seconds between HP checks

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
MGR_BG        = "#16202a"
MGR_HEADER    = "#0f1720"
MGR_ROW       = "#1e2c38"
MGR_BORDER    = "#243040"
MGR_BORDER2   = "#2a3c4a"
MGR_BORDER3   = "#344858"
MGR_PILL      = "#1e2c38"
T_PRIMARY     = "#dce8f0"
T_SECONDARY   = "#8ab0c0"
T_DIM         = "#82a0b0"   # brightened for readability
T_MUTED       = "#6f8a9a"   # brightened for readability
HP_FULL       = "#00e676"
HP_SCRATCH    = "#40e880"
HP_INJURED    = "#ffb300"
HP_BLOODIED   = "#ff6b00"
HP_CRIT       = "#f44336"
HP_DEAD       = "#555555"
HPB_FULL      = "#0a2a14";  HBB_FULL     = "#0f4020"
HPB_SCRATCH   = "#0a2a14";  HBB_SCRATCH  = "#0f4020"
HPB_INJURED   = "#2a2200";  HBB_INJURED  = "#3a3000"
HPB_BLOODIED  = "#2a1400";  HBB_BLOODIED = "#3a2000"
HPB_CRIT      = "#2a0808";  HBB_CRIT     = "#3a1010"
HPB_DEAD      = "#181818";  HBB_DEAD     = "#282828"
OVL_BG        = "#293136"
OVL_BAR_BG    = "#1e272e"
BTN_OPEN_BG   = "#1a3848";  BTN_OPEN_FG  = "#60b0d0";  BTN_OPEN_BD  = "#2a5060"
BTN_CLOSE_BG  = "#3a1818";  BTN_CLOSE_FG = "#e07070";  BTN_CLOSE_BD = "#5a2222"
BTN_EDIT_BG   = "#1e2c38";  BTN_EDIT_FG  = "#7aaabb";  BTN_EDIT_BD  = "#344858"
BTN_SAVE_BG   = "#1a3848";  BTN_SAVE_FG  = "#60c0d8";  BTN_SAVE_BD  = "#2a5060"
BTN_CANCEL_BG = "#1e2c38";  BTN_CANCEL_FG= "#7aaabb";  BTN_CANCEL_BD= "#344858"
DANGER_BG     = "#3a1010";  DANGER_FG    = "#e05050";  DANGER_BD    = "#5a2020"
DLG_BG        = "#16202a"
DLG_ENTRY_BG  = "#1e2c38"
DLG_LABEL_FG  = "#7ea6b6"
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_BASE_DIR, "dnd_healthbar_public.json")

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
    # Keep the browser overlays in sync with names / portraits / toggles
    OVERLAY_HUB.sync_config(cfg)

# ---------------------------------------------------------------------------
# API helpers — no auth required
# ---------------------------------------------------------------------------
def make_session(character_id: str) -> requests.Session:
    """Visit the public character page to collect the Geo cookie."""
    session = requests.Session()
    session.get(f"{ORIGIN}/characters/{character_id}",
                headers={"User-Agent": UA}, timeout=10)
    return session


def get_character(session: requests.Session, character_id: str) -> dict:
    """Fetch public character data — no Authorization header needed."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-GB,en;q=0.6",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "User-Agent": UA,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Priority": "u=1, i",
    }
    resp = session.get(CHARACTER_URL + character_id + "?includeCustomItems=true",
                       headers=headers, timeout=30)
    resp.raise_for_status()
    char = resp.json().get("data", {})

    total_level    = sum(c.get("level", 0) for c in char.get("classes", []))
    override_stats = {s["id"]: s["value"] for s in char.get("overrideStats", []) if s.get("value") is not None}
    base_stats     = {s["id"]: s["value"] for s in char.get("stats", [])          if s.get("value") is not None}
    bonus_stats    = {s["id"]: s["value"] for s in char.get("bonusStats", [])     if s.get("value") is not None}

    if 3 in override_stats:
        con_score = override_stats[3]
    else:
        con_score = base_stats.get(3, 10) + bonus_stats.get(3, 0)
        con_set = None
        for src in ("race", "feat", "class", "background", "item", "condition"):
            for mod in char.get("modifiers", {}).get(src, []):
                if mod.get("subType") != "constitution-score":
                    continue
                mod_value = mod.get("value") or mod.get("fixedValue")
                if mod.get("type") == "bonus":
                    con_score += int(mod_value or 0)
                elif mod.get("type") == "set" and mod_value is not None:
                    # e.g. Amulet of Health: sets CON to a fixed value if higher
                    con_set = max(con_set or 0, int(mod_value))
        if con_set is not None:
            con_score = max(con_score, con_set)

    # Flat "+N HP per level" bonuses (Tough feat, Hill Dwarf, Draconic
    # Resilience, ...). Class features scale with the level of the class
    # that grants them; everything else scales with total character level.
    feature_class_level = {}
    for c in char.get("classes", []):
        for f in c.get("classFeatures", []) or []:
            fid = (f.get("definition") or {}).get("id")
            if fid is not None:
                feature_class_level[fid] = c.get("level", 0)
    hp_per_level_bonus = 0
    for src in ("race", "feat", "class", "background"):
        for mod in char.get("modifiers", {}).get(src, []):
            if mod.get("type") != "bonus" or mod.get("subType") != "hit-points-per-level":
                continue
            per_level = int(mod.get("value") or mod.get("fixedValue") or 0)
            levels    = total_level
            if src == "class":
                levels = feature_class_level.get(mod.get("componentId"), total_level)
            hp_per_level_bonus += per_level * levels

    return {
        "api_name":           char.get("name", ""),
        "baseHitPoints":      int(char.get("baseHitPoints")      or 0),
        "bonusHitPoints":     int(char.get("bonusHitPoints")     or 0),
        "overrideHitPoints":  char.get("overrideHitPoints"),
        "removedHitPoints":   int(char.get("removedHitPoints")   or 0),
        "temporaryHitPoints": int(char.get("temporaryHitPoints") or 0),
        "totalLevel":         total_level,
        "conMod":             (con_score - 10) // 2,
        "hpPerLevelBonus":    hp_per_level_bonus,
    }


def calculate_hp(d: dict) -> tuple[float | None, int, int]:
    """Returns (pct, current, max). pct is None if character has no HP data yet."""
    override = d.get("overrideHitPoints")
    if override is not None:
        max_hp = int(override)
    else:
        max_hp = (d["baseHitPoints"] + d["totalLevel"] * d["conMod"]
                  + d.get("hpPerLevelBonus", 0) + d["bonusHitPoints"])

    if max_hp <= 0:
        return None, 0, 0   # character not configured yet

    display_max = max_hp + d["temporaryHitPoints"]
    current     = max(0, display_max - d["removedHitPoints"])
    pct         = current / display_max
    return pct, current, display_max

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def hp_state(pct) -> str:
    if pct is None: return "unknown"
    if pct <= 0:    return "dead"
    if pct < 0.25:  return "critical"
    if pct < 0.50:  return "bloodied"
    if pct < 0.75:  return "injured"
    if pct < 1.0:   return "scratched"
    return "full"

def hp_bar_color(pct) -> str:
    return {"full":HP_FULL,"scratched":HP_SCRATCH,"injured":HP_INJURED,
            "bloodied":HP_BLOODIED,"critical":HP_CRIT,"dead":HP_DEAD,
            "unknown":"#3a4a54"}[hp_state(pct)]

def hp_badge_colors(pct) -> tuple[str,str,str]:
    m = {"full":(HP_FULL,HPB_FULL,HBB_FULL),"scratched":(HP_SCRATCH,HPB_SCRATCH,HBB_SCRATCH),
         "injured":(HP_INJURED,HPB_INJURED,HBB_INJURED),"bloodied":(HP_BLOODIED,HPB_BLOODIED,HBB_BLOODIED),
         "critical":(HP_CRIT,HPB_CRIT,HBB_CRIT),"dead":(HP_DEAD,HPB_DEAD,HBB_DEAD),
         "unknown":(T_DIM,"#1e2c38",MGR_BORDER2)}
    return m[hp_state(pct)]

def round_image(img: Image.Image, radius: int) -> Image.Image:
    img  = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,img.width,img.height], radius=radius, fill=255)
    # Combine with existing alpha so transparent areas (letterbox, PNG
    # transparency) stay transparent instead of turning opaque black.
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img

def fit_image(img: Image.Image, size: int, bg_color: str) -> Image.Image:
    """Scale image to fit within a square of `size` px, preserving aspect ratio.
    Remaining space is filled with bg_color (letterbox/pillarbox). No cropping."""
    img = img.convert("RGBA")
    iw, ih = img.size
    scale  = min(size / iw, size / ih)
    new_w  = int(iw * scale)
    new_h  = int(ih * scale)
    img    = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), bg_color)
    x_off  = (size - new_w) // 2
    y_off  = (size - new_h) // 2
    canvas.paste(img, (x_off, y_off), img)
    return canvas

# ---------------------------------------------------------------------------
# Thread-safe UI dispatch
# ---------------------------------------------------------------------------
# Tkinter must only be touched from the main thread. Worker threads (HP
# polling, connection tests, tray menu) put callables on this queue and the
# main loop drains it periodically.
_ui_queue: "queue.Queue" = queue.Queue()

def run_on_ui(fn):
    _ui_queue.put(fn)

def _pump_ui_queue(root: tk.Tk):
    try:
        while True:
            fn = _ui_queue.get_nowait()
            try:
                fn()
            except tk.TclError:
                pass   # widget was destroyed meanwhile
            except Exception:
                traceback.print_exc()
    except queue.Empty:
        pass
    try:
        root.after(50, _pump_ui_queue, root)
    except tk.TclError:
        pass   # root destroyed — app is quitting

# ---------------------------------------------------------------------------
# Portrait resolution (shared by desktop window and browser overlay)
# ---------------------------------------------------------------------------
PORTRAIT_KEYS = ["portrait_unscathed","portrait_scratched","portrait_injured",
                 "portrait_bloodied","portrait_critical","portrait_dead"]
_STATE_TO_KEY = {"full":"portrait_unscathed","scratched":"portrait_scratched",
                 "injured":"portrait_injured","bloodied":"portrait_bloodied",
                 "critical":"portrait_critical","dead":"portrait_dead",
                 "unknown":"portrait_unscathed"}

def resolve_portrait_key(char: dict, pct) -> str:
    """Find the best available portrait slot for the current HP state.

    Starts at the ideal state and walks outward in both directions,
    alternating closer-healthier then closer-worse, so the nearest
    portrait is always preferred over a distant one.

    Example for bloodied (idx=3), walk order:
        bloodied(3) → injured(2) → critical(4) → scratched(1) → dead(5) → unscathed(0)
    """
    idx   = PORTRAIT_KEYS.index(_STATE_TO_KEY[hp_state(pct)])
    n     = len(PORTRAIT_KEYS)
    order = [idx]
    for offset in range(1, n):
        if idx - offset >= 0: order.append(idx - offset)
        if idx + offset < n:  order.append(idx + offset)
    for i in order:
        key = PORTRAIT_KEYS[i]
        p   = char.get(key, "")
        if p and os.path.isfile(p):
            return key
    return ""

# ---------------------------------------------------------------------------
# Browser-source overlay server (for OBS)
# ---------------------------------------------------------------------------
DEFAULT_OVERLAY_PORT = 7777

class OverlayHub:
    """Thread-safe snapshot of everything the browser overlays need.
    Written from the Tk main thread, read from HTTP server threads."""

    def __init__(self):
        self._lock   = threading.Lock()
        self._chars: dict[str, dict] = {}   # cid → config snapshot
        self._live:  dict[str, dict] = {}   # cid → latest HP (only while window open)
        self._img_cache: dict[tuple, bytes] = {}
        self.port: int | None = None

    def url_for(self, cid: str) -> str | None:
        return f"http://127.0.0.1:{self.port}/overlay/{cid}" if self.port else None

    def sync_config(self, cfg: dict):
        snap = {}
        for g in cfg.get("games", []):
            for ch in g.get("characters", []):
                cid = str(ch.get("character_id", ""))
                if not cid or cid in snap:
                    continue
                s = {"name": ch.get("name", ""), "game": g.get("name", ""),
                     "show_hp_numbers": bool(ch.get("show_hp_numbers", False))}
                for k in PORTRAIT_KEYS:
                    s[k] = ch.get(k, "")
                snap[cid] = s
        with self._lock:
            self._chars = snap

    def characters(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self._chars.items())

    def set_live(self, cid: str, live: bool):
        with self._lock:
            if live:
                self._live.setdefault(cid, {})
            else:
                self._live.pop(cid, None)

    def update_hp(self, cid: str, pct, cur: int, mx: int):
        with self._lock:
            if cid in self._live:
                self._live[cid] = {"pct": pct, "cur": cur, "mx": mx}

    def state_for(self, cid: str) -> dict | None:
        with self._lock:
            ch = self._chars.get(cid)
            if ch is None:
                return None
            ch   = dict(ch)
            live = cid in self._live
            hp   = dict(self._live.get(cid, {}))
        loaded = "pct" in hp
        pct    = hp.get("pct") if loaded else None
        key    = resolve_portrait_key(ch, pct if loaded else 1.0)
        try:
            ver = int(os.path.getmtime(ch[key])) if key else 0
        except OSError:
            ver = 0
        return {"name": ch["name"], "live": live, "loaded": loaded,
                "pct": pct, "cur": hp.get("cur", 0), "mx": hp.get("mx", 0),
                "state": hp_state(pct), "color": hp_bar_color(pct),
                "show_hp_numbers": ch["show_hp_numbers"],
                "portrait": key, "portrait_v": ver}

    def portrait_png(self, cid: str, key: str) -> bytes | None:
        """Portrait fitted + rounded exactly like the desktop window, at 2x
        resolution, with a transparent background. Cached per file mtime."""
        if key not in PORTRAIT_KEYS:
            return None
        with self._lock:
            path = (self._chars.get(cid) or {}).get(key, "")
        if not path or not os.path.isfile(path):
            return None
        cache_key = (path, os.path.getmtime(path))
        with self._lock:
            if cache_key in self._img_cache:
                return self._img_cache[cache_key]
        size = OVL_W * 2
        img  = round_image(fit_image(Image.open(path), size, (0, 0, 0, 0)), CORNER_R * 2)
        buf  = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
        with self._lock:
            self._img_cache[cache_key] = data
        return data

OVERLAY_HUB = OverlayHub()

OVERLAY_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>HP overlay</title>
<style>
  html,body{margin:0;padding:0;background:transparent;overflow:hidden;
            font-family:"Segoe UI",system-ui,sans-serif}
  #wrap{width:100vw;box-sizing:border-box;opacity:0;transition:opacity .4s ease}
  #wrap.show{opacity:1}
  body.card #wrap{background:#293136;border-radius:5vw}
  #portrait{display:block;width:100vw;height:100vw;object-fit:contain}
  #portrait.empty{visibility:hidden}
  #hp{padding:4.3vw}
  #track{position:relative;height:11.43vw;border-radius:5.71vw;
         background:#1e272e;overflow:hidden}
  #track.unknown{background:repeating-linear-gradient(90deg,#1e272e 0 2vw,#2a3a44 2vw 4.3vw)}
  #fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:5.71vw;
        transition:width .6s ease,background-color .6s ease}
  #nums{display:none;margin-top:2.1vw;color:#dce8f0;white-space:pre;
        font:bold 5.2vw Consolas,"Courier New",monospace;
        text-shadow:0 0 .6vw #000,0 0 .6vw #000}
</style></head>
<body>
<div id="wrap">
  <img id="portrait" class="empty" alt="">
  <div id="hp"><div id="track"><div id="fill"></div></div><div id="nums"></div></div>
</div>
<script>
  const cid    = location.pathname.split("/").filter(Boolean)[1];
  const params = new URLSearchParams(location.search);
  if (params.get("card") === "1") document.body.classList.add("card");
  const always = params.get("always") === "1";
  const $ = id => document.getElementById(id);
  let lastSrc = null;
  async function tick() {
    try {
      const r = await fetch(`/api/${cid}`, {cache: "no-store"});
      if (!r.ok) throw new Error(r.status);
      const s = await r.json();
      $("wrap").classList.toggle("show", always || (s.live && s.loaded));
      const src = s.portrait ? `/portrait/${cid}/${s.portrait}?v=${s.portrait_v}` : "";
      if (src !== lastSrc) {
        lastSrc = src;
        if (src) { $("portrait").src = src; $("portrait").classList.remove("empty"); }
        else     { $("portrait").removeAttribute("src"); $("portrait").classList.add("empty"); }
      }
      if (s.pct === null) {
        $("track").classList.add("unknown");
        $("fill").style.width = "0";
        $("nums").textContent = s.loaded ? "HP not configured" : "";
      } else {
        $("track").classList.remove("unknown");
        $("fill").style.width = (Math.max(0, Math.min(1, s.pct)) * 100) + "%";
        $("fill").style.backgroundColor = s.color;
        $("nums").textContent = `${s.cur}  /  ${s.mx}`;
      }
      $("nums").style.display = s.show_hp_numbers ? "block" : "none";
    } catch (e) {
      if (!always) $("wrap").classList.remove("show");   // app closed
    }
    setTimeout(tick, 1000);
  }
  tick();
</script>
</body></html>
"""

def _overlay_index_html() -> str:
    rows = []
    for cid, ch in sorted(OVERLAY_HUB.characters(),
                          key=lambda kv: (kv[1]["game"].lower(), kv[1]["name"].lower())):
        url = OVERLAY_HUB.url_for(cid) or ""
        rows.append(
            f'<tr><td>{html.escape(ch["game"])}</td><td>{html.escape(ch["name"])}</td>'
            f'<td><code>{html.escape(url)}</code></td>'
            f'<td><button data-url="{html.escape(url)}">Copy</button> '
            f'<a href="{html.escape(url)}?always=1&card=1" target="_blank">Preview</a></td></tr>')
    body = "\n".join(rows) or '<tr><td colspan="4">No characters configured yet.</td></tr>'
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>D&amp;D Health Bar overlays</title>
<style>
  body{{background:#16202a;color:#dce8f0;font:14px "Segoe UI",system-ui,sans-serif;margin:24px}}
  h1{{font-size:20px}} p{{color:#82a0b0;max-width:720px}}
  table{{border-collapse:collapse;margin-top:12px}}
  td,th{{padding:8px 12px;border-bottom:1px solid #243040;text-align:left}}
  th{{color:#7ea6b6;font-size:12px;text-transform:uppercase}}
  code{{color:#60c0d8}} a{{color:#60b0d0}}
  button{{background:#1a3848;color:#60c0d8;border:1px solid #2a5060;padding:4px 10px;cursor:pointer}}
</style></head><body>
<h1>D&amp;D Health Bar — OBS overlays</h1>
<p>In OBS add a <b>Browser</b> source, paste a URL below, and set the size to
<b>280 × 340</b> (or any width — the overlay scales). The overlay appears when you
open the character in the app and fades out when you close it.
Add <code>?card=1</code> for the dark card background, or <code>?always=1</code> to keep it visible.</p>
<table><tr><th>Game</th><th>Character</th><th>Overlay URL</th><th></th></tr>
{body}
</table>
<script>
document.querySelectorAll("button[data-url]").forEach(b => b.onclick = async () => {{
  await navigator.clipboard.writeText(b.dataset.url);
  b.textContent = "Copied!"; setTimeout(() => b.textContent = "Copy", 1500);
}});
</script></body></html>"""

class _OverlayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "DnDHealthBar"

    def log_message(self, *args):
        pass   # keep the console quiet

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8",
                                  _overlay_index_html().encode("utf-8"))
            if re.fullmatch(r"/overlay/\d+/?", path):
                return self._send(200, "text/html; charset=utf-8",
                                  OVERLAY_HTML.encode("utf-8"))
            m = re.fullmatch(r"/api/(\d+)", path)
            if m:
                st = OVERLAY_HUB.state_for(m.group(1))
                if st is None:
                    return self._send(404, "application/json", b'{"error":"unknown character"}')
                return self._send(200, "application/json", json.dumps(st).encode("utf-8"))
            m = re.fullmatch(r"/portrait/(\d+)/(portrait_[a-z]+)", path)
            if m:
                data = OVERLAY_HUB.portrait_png(m.group(1), m.group(2))
                if data is None:
                    return self._send(404, "text/plain", b"Not found")
                return self._send(200, "image/png", data, cache=True)
            self._send(404, "text/plain", b"Not found")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            traceback.print_exc()
            try: self._send(500, "text/plain", b"Internal error")
            except Exception: pass

    def _send(self, code: int, ctype: str, body: bytes, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

def start_overlay_server(port: int) -> int | None:
    """Start the overlay HTTP server on 127.0.0.1. Tries `port` and the next
    9 ports if it is taken. Returns the port in use, or None."""
    for p in range(port, port + 10):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", p), _OverlayHandler)
        except OSError:
            continue
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        OVERLAY_HUB.port = p
        return p
    print(f"Warning: could not start overlay server on ports {port}-{port+9}")
    return None

# ---------------------------------------------------------------------------
# Window position helpers
# ---------------------------------------------------------------------------
def _virtual_screen(widget) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the whole desktop across all monitors."""
    if sys.platform == "win32":
        try:
            import ctypes
            gsm = ctypes.windll.user32.GetSystemMetrics
            return gsm(76), gsm(77), gsm(78), gsm(79)
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()

def position_on_screen(widget, x: int, y: int) -> bool:
    vx, vy, vw, vh = _virtual_screen(widget)
    return vx - OVL_W + 60 <= x <= vx + vw - 60 and vy <= y <= vy + vh - 60

def mk_sep(parent, color=MGR_BORDER, pad=0):
    tk.Frame(parent, bg=color, height=1).pack(fill="x", padx=pad)

def styled_button(parent, text, bg, fg, bd, command, font=F_SMALL, width=None, pady=0):
    kw = dict(text=text, bg=bg, fg=fg, relief="flat", bd=0,
              highlightthickness=1, highlightbackground=bd,
              activebackground=bd, activeforeground=fg,
              font=font, cursor="hand2", command=command, pady=pady)
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def styled_entry(parent, textvariable, width=30):
    return tk.Entry(parent, textvariable=textvariable, width=width,
                    bg=DLG_ENTRY_BG, fg=T_PRIMARY, insertbackground=T_PRIMARY,
                    relief="flat", bd=0, highlightthickness=1,
                    highlightbackground=MGR_BORDER3, highlightcolor="#5a8090",
                    font=F_SMALL)

# ---------------------------------------------------------------------------
# Toggle switch
# ---------------------------------------------------------------------------
class ToggleSwitch(tk.Canvas):
    W, H, R = 36, 20, 9
    def __init__(self, parent, variable, command=None, **kw):
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0, **kw)
        self._var = variable; self._cmd = command
        self.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()
    def _draw(self):
        self.delete("all")
        on = self._var.get()
        self.create_round_rect(1,1,self.W-1,self.H-1, radius=self.R,
                               fill="#1a4030" if on else "#1a3040",
                               outline="#2a5040" if on else "#2a4050")
        kx = self.W-self.R-3 if on else self.R+3-(self.R-self.H//2+2)
        self.create_oval(kx-self.H//2+3,3,kx+self.H//2-3,self.H-3,
                         fill=HP_FULL if on else "#3a5060", outline="")
    def create_round_rect(self, x1,y1,x2,y2,radius=9,**kw):
        pts=[x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,x2,y2-radius,x2,y2,
             x2-radius,y2,x1+radius,y2,x1,y2,x1,y2-radius,x1,y1+radius,x1,y1]
        return self.create_polygon(pts, smooth=True, **kw)
    def _toggle(self,_=None):
        self._var.set(not self._var.get())
        if self._cmd: self._cmd()

# ---------------------------------------------------------------------------
# HP overlay window
# ---------------------------------------------------------------------------
class CharacterWindow:
    def __init__(self, master, char: dict, on_closed=None, on_hp_update=None,
                 status_cb=None):
        self.char         = char
        self.on_closed    = on_closed
        self.on_hp_update = on_hp_update
        self._stop        = threading.Event()
        self._photo       = None
        self._last_state  = None
        self._status_cb   = status_cb   # set before the worker thread starts

        self.win = tk.Toplevel(master)
        self.win.title(char.get("name","HP"))
        self.win.configure(bg=OVL_BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", bool(char.get("always_on_top", False)))
        opacity = max(0.2, min(1.0, float(char.get("opacity", 1.0))))
        self.win.attributes("-alpha", opacity)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        # Restore last position (ignored if that monitor is gone)
        pos = char.get("window_pos")
        if (isinstance(pos, list) and len(pos) == 2
                and all(isinstance(v, int) for v in pos)
                and position_on_screen(self.win, *pos)):
            self.win.geometry(f"+{pos[0]}+{pos[1]}")

        self._build_ui()
        self._load_portrait(self._resolve_portrait(1.0))
        self._apply_hp_visibility()
        threading.Thread(target=self._run_loop, daemon=True).start()

    def set_title(self, name: str):
        """Window title doubles as the OBS window-capture match key."""
        self.win.title(name or "HP")

    def _build_ui(self):
        self.portrait_canvas = tk.Canvas(self.win, width=OVL_W, height=OVL_W,
                                         bg=OVL_BG, highlightthickness=0)
        self.portrait_canvas.pack()
        self._img_id = self.portrait_canvas.create_image(OVL_W//2, OVL_W//2, anchor="center")
        self.hp_frame = tk.Frame(self.win, bg=OVL_BG)
        self.hp_frame.pack(fill="x", padx=BAR_PAD, pady=(BAR_PAD, BAR_PAD))
        self.bar_canvas = tk.Canvas(self.hp_frame, width=OVL_W-BAR_PAD*2,
                                    height=BAR_H, bg=OVL_BG, highlightthickness=0)
        self.bar_canvas.pack()
        self.hp_label = tk.Label(self.hp_frame, text="", bg=OVL_BG,
                                 fg=T_PRIMARY, font=F_MONO, anchor="w")
        self._draw_bar(1.0)

    def _apply_hp_visibility(self):
        if bool(self.char.get("show_hp_numbers", False)):
            self.hp_label.pack(anchor="w", pady=(6,0))
        else:
            self.hp_label.pack_forget()
        self.win.update_idletasks()
        self.win.geometry(f"{OVL_W}x{self.win.winfo_reqheight()}")

    def refresh_visibility(self):
        self.win.after(0, self._apply_hp_visibility)

    def _resolve_portrait(self, pct) -> str:
        key = resolve_portrait_key(self.char, pct)
        return self.char.get(key, "") if key else ""

    def _update_portrait_for(self, pct: float):
        state = hp_state(pct)
        if state == self._last_state: return
        self._last_state = state
        self._load_portrait(self._resolve_portrait(pct))

    def _load_portrait(self, path: str):
        size = OVL_W
        if path and os.path.isfile(path):
            img = fit_image(Image.open(path), size, OVL_BG)
        else:
            img = Image.new("RGBA", (size, size), OVL_BG)
        img = round_image(img, CORNER_R)
        self._photo = ImageTk.PhotoImage(img)
        self.portrait_canvas.itemconfig(self._img_id, image=self._photo)

    def _draw_bar(self, pct):
        c=self.bar_canvas; c.delete("all")
        w=OVL_W-BAR_PAD*2; h=BAR_H; r=h//2
        col=hp_bar_color(pct)
        # Track (always drawn)
        c.create_arc(0,0,r*2,h,    start=90, extent=180,  fill=OVL_BAR_BG,outline="")
        c.create_rectangle(r,0,w-r,h,                      fill=OVL_BAR_BG,outline="")
        c.create_arc(w-r*2,0,w,h,  start=270,extent=180,  fill=OVL_BAR_BG,outline="")
        if pct is None:
            # Show a subtle striped/dotted pattern to indicate "no data"
            for x in range(r, w-r, 12):
                c.create_rectangle(x, 4, x+6, h-4, fill="#2a3a44", outline="")
            return
        fw=max(0,int(w*max(0.0,min(1.0,pct))))
        if fw>r*2:
            c.create_arc(0,0,r*2,h,    start=90, extent=180,  fill=col,outline="")
            c.create_rectangle(r,0,fw-r,h,                     fill=col,outline="")
            c.create_arc(fw-r*2,0,fw,h,start=270,extent=180,  fill=col,outline="")
        elif fw>0:
            c.create_arc(0,0,r*2,h,    start=90, extent=180,  fill=col,outline="")
            c.create_rectangle(r,0,fw,h,                        fill=col,outline="")

    def _update_ui(self, pct, cur, mx):
        """Called from the worker thread — marshals onto the Tk main thread."""
        def _do():
            if self._stop.is_set(): return
            self._draw_bar(pct)
            self._update_portrait_for(pct)
            if pct is None:
                self.hp_label.config(text="HP not configured")
            else:
                self.hp_label.config(text=f"{cur}  /  {mx}")
            if self.on_hp_update:
                self.on_hp_update(self.char["character_id"], pct, cur, mx)
        run_on_ui(_do)

    def _set_status(self, key: str):
        msgs = {"init":"Connecting…","fetch":"Fetching HP…",
                "poll":f"Polling every {POLL_INTERVAL}s…","error":"Error — retrying…",
                "session":"Refreshing session…"}
        if self._status_cb:
            self._status_cb(self.char["character_id"], msgs.get(key, key))

    def _set_error(self, msg: str):
        """Surface a persistent error both in status bar and on the HP window."""
        if self._status_cb:
            self._status_cb(self.char["character_id"], f"⚠ {msg}")
        def _do():
            if self._stop.is_set(): return
            self._draw_bar(None)
            self.hp_label.config(text=f"⚠ {msg}")
        run_on_ui(_do)

    def _run_loop(self):
        char_id          = self.char["character_id"]
        session          = None
        consecutive_errs = 0
        MAX_ERRS         = 5   # surface a visible error after this many consecutive failures

        while not self._stop.is_set():
            try:
                if session is None:
                    self._set_status("init")
                    session = make_session(char_id)

                self._set_status("fetch")
                cdata = get_character(session, char_id)
                pct, cur, mx = calculate_hp(cdata)
                self._update_ui(pct, cur, mx)
                consecutive_errs = 0
                self._set_status("poll")

                while not self._stop.is_set():
                    time.sleep(POLL_INTERVAL)
                    if self._stop.is_set(): break
                    cdata = get_character(session, char_id)
                    pct, cur, mx = calculate_hp(cdata)
                    self._update_ui(pct, cur, mx)

            except requests.exceptions.HTTPError as e:
                # NB: a Response is falsy for 4xx/5xx, so test against None
                code = e.response.status_code if e.response is not None else 0
                if code in (401, 403):
                    # Session cookie expired — recreate silently
                    print(f"[{char_id}] session expired ({code}), refreshing…")
                    self._set_status("session")
                    session = None
                    time.sleep(2)
                elif code == 404:
                    self._set_error("Character not found")
                    time.sleep(30)
                else:
                    consecutive_errs += 1
                    print(f"[{char_id}] HTTP {code}")
                    session = None
                    if consecutive_errs >= MAX_ERRS:
                        self._set_error(f"Connection lost (HTTP {code})")
                    else:
                        self._set_status("error")
                    time.sleep(5)

            except Exception as e:
                consecutive_errs += 1
                print(f"[{char_id}] error: {e}")
                traceback.print_exc()
                session = None
                if consecutive_errs >= MAX_ERRS:
                    self._set_error("Connection lost — check your network")
                else:
                    self._set_status("error")
                time.sleep(5)

    def close(self):
        if self._stop.is_set(): return
        self._stop.set()
        # Remember where the window was so it reopens in the same spot
        try:
            m = re.search(r"\+(-?\d+)\+(-?\d+)$", self.win.geometry())
            if m:
                self.char["window_pos"] = [int(m.group(1)), int(m.group(2))]
        except tk.TclError:
            pass
        try: self.win.destroy()
        except: pass
        if self.on_closed: self.on_closed()

# ---------------------------------------------------------------------------
# Character dialog
# ---------------------------------------------------------------------------
class CharacterDialog(tk.Toplevel):
    _STATES = [
        ("portrait_unscathed","Unscathed","100%",    HP_FULL),
        ("portrait_scratched","Scratched","75–100%", HP_SCRATCH),
        ("portrait_injured",  "Injured",  "50–75%",  HP_INJURED),
        ("portrait_bloodied", "Bloodied", "25–50%",  HP_BLOODIED),
        ("portrait_critical", "Critical", "0–25%",   HP_CRIT),
        ("portrait_dead",     "Dead",     "0%",      HP_DEAD),
    ]

    def __init__(self, parent, ch: dict):
        super().__init__(parent)
        self.title("Character")
        self.configure(bg=DLG_BG)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._build(ch)

    def _build(self, ch):
        hdr = tk.Frame(self, bg=MGR_HEADER)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Edit character", bg=MGR_HEADER, fg=T_PRIMARY,
                 font=F_BOLD, anchor="w").pack(side="left", padx=14, pady=10)
        mk_sep(self, MGR_BORDER)

        body = tk.Frame(self, bg=DLG_BG)
        body.pack(fill="x", padx=14, pady=10)

        self._vars = {}

        # Character name
        tk.Label(body, text="CHARACTER NAME", bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(6,2))
        self._vars["name"] = tk.StringVar(value=ch.get("name",""))
        styled_entry(body, self._vars["name"], width=42).pack(fill="x", ipady=4, pady=(0,2))

        # Character ID — accepts full URL or bare ID
        tk.Label(body, text="CHARACTER ID OR URL", bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(6,2))
        tk.Label(body, text="Paste the full URL or just the numeric ID",
                 bg=DLG_BG, fg=T_MUTED, font=F_TINY).pack(anchor="w", pady=(0,2))
        id_row = tk.Frame(body, bg=DLG_BG)
        id_row.pack(fill="x", pady=(0,2))
        self._vars["character_id"] = tk.StringVar(value=ch.get("character_id",""))
        id_entry = styled_entry(id_row, self._vars["character_id"], width=32)
        id_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0,6))
        # Auto-extract ID and test whenever the field changes
        self._vars["character_id"].trace_add("write", lambda *_: self._on_id_changed())

        # Feedback label (no manual test button)
        self._test_label = tk.Label(body, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY)
        self._test_label.pack(anchor="w", pady=(4,0))
        self._test_after_id = None   # debounce handle
        self._test_seq      = 0      # ignore results from superseded tests

        mk_sep(body, MGR_BORDER, 0)
        tk.Label(body, text="PORTRAITS BY HEALTH STATE", bg=DLG_BG, fg=DLG_LABEL_FG,
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(10,2))
        tk.Label(body,
                 text="Ideal: square (1:1). Other ratios are fitted without cropping — "
                      "bars will appear on the shorter sides.",
                 bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                 wraplength=380, justify="left").pack(anchor="w", pady=(0,6))

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
                     font=("Segoe UI",9,"bold")).pack(side="left")
            tk.Label(hrow, text=pct_label, bg=MGR_ROW, fg=T_DIM,
                     font=F_TINY).pack(side="right")
            var = tk.StringVar(value=ch.get(key,""))
            self._portrait_vars[key] = var
            frow = tk.Frame(cell, bg=MGR_ROW)
            frow.pack(fill="x", padx=8, pady=(0,6))
            tk.Entry(frow, textvariable=var, width=16, bg=DLG_ENTRY_BG, fg=T_DIM,
                     insertbackground=T_DIM, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=MGR_BORDER2,
                     font=F_TINY).pack(side="left", fill="x", expand=True, ipady=3, padx=(0,4))
            styled_button(frow, "…", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                          lambda v=var: self._browse(v), font=F_TINY).pack(side="left")

        mk_sep(body, MGR_BORDER, 0)
        opt_row = tk.Frame(body, bg=DLG_BG)
        opt_row.pack(fill="x", pady=(10,2))
        tk.Label(opt_row, text="Always on top", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._on_top_var = tk.BooleanVar(value=bool(ch.get("always_on_top",False)))
        ToggleSwitch(opt_row, self._on_top_var, bg=DLG_BG).pack(side="right")

        # Opacity slider
        opa_row = tk.Frame(body, bg=DLG_BG)
        opa_row.pack(fill="x", pady=(8,2))
        tk.Label(opa_row, text="Overlay opacity", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._opacity_label = tk.Label(opa_row, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY)
        self._opacity_label.pack(side="right")
        self._opacity_var = tk.DoubleVar(value=float(ch.get("opacity", 1.0)))
        def _on_opacity(val):
            self._opacity_label.config(text=f"{int(float(val)*100)} %")
        _on_opacity(self._opacity_var.get())
        tk.Scale(body, variable=self._opacity_var, from_=0.2, to=1.0, resolution=0.05,
                 orient="horizontal", command=_on_opacity,
                 bg=DLG_BG, fg=T_DIM, troughcolor=DLG_ENTRY_BG,
                 highlightthickness=0, bd=0, sliderrelief="flat",
                 activebackground=BTN_SAVE_BG).pack(fill="x", pady=(2,0))

        mk_sep(self, MGR_BORDER)
        foot = tk.Frame(self, bg=MGR_HEADER)
        foot.pack(fill="x", padx=14, pady=8)
        styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                      self.destroy).pack(side="right", padx=(4,0), ipady=4, ipadx=8)
        styled_button(foot, "Save", BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                      self._submit, font=F_MED).pack(side="right", ipady=4, ipadx=12)

    def _extract_id(self) -> str:
        """Extract bare numeric ID from whatever is in the field. Returns the ID."""
        raw = self._vars["character_id"].get().strip()
        m   = re.search(r"dndbeyond\.com/characters/(\d+)", raw)
        if m:
            self._vars["character_id"].set(m.group(1))
            return m.group(1)
        return raw if re.fullmatch(r"\d+", raw) else ""

    def _on_id_changed(self):
        """Called on every keystroke — debounce then auto-test."""
        # Cancel any pending test
        if self._test_after_id:
            try: self.after_cancel(self._test_after_id)
            except: pass
        raw = self._vars["character_id"].get().strip()
        if not raw:
            self._test_label.config(text="", fg=T_DIM)
            return
        # Show pending indicator immediately
        self._test_label.config(text="…", fg=T_DIM)
        # Wait 800ms after last keystroke before firing
        self._test_after_id = self.after(800, self._run_test)

    def _run_test(self):
        """Extract ID then test in background thread."""
        cid = self._extract_id()
        if not cid:
            self._test_label.config(text="⚠ Enter a valid character ID or URL.", fg=HP_INJURED)
            return
        self._test_label.config(text="Testing…", fg=T_DIM)
        self._test_seq += 1
        seq = self._test_seq

        def _work():
            try:
                session  = make_session(cid)
                data     = get_character(session, cid)
                pct, cur, mx = calculate_hp(data)
                api_name = data.get("api_name", "")
                return ("ok", cur, mx, api_name)
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                if code == 404:        return ("not_found",  None, None, None)
                if code in (401, 403): return ("private",    None, None, None)
                return ("http_error", code, None, None)
            except Exception as e:
                return ("error", str(e), None, None)

        def _done(result):
            if seq != self._test_seq or not self.winfo_exists():
                return   # a newer test superseded this one, or dialog closed
            if result[0] == "ok":
                cur, mx, api_name = result[1], result[2], result[3]
                hp_text = f"{cur} / {mx}" if cur is not None else "not configured"
                self._test_label.config(text=f"✓ Reachable — HP: {hp_text}", fg=HP_FULL)
                # Auto-fill name only if the field is still empty
                if not self._vars["name"].get().strip() and api_name:
                    self._vars["name"].set(api_name)
            elif result[0] == "not_found":
                self._test_label.config(
                    text="✗ Character not found — check the ID.", fg=HP_CRIT)
            elif result[0] == "private":
                self._test_label.config(
                    text="✗ Character is private — make it public on D&D Beyond.", fg=HP_CRIT)
            elif result[0] == "http_error":
                self._test_label.config(
                    text=f"✗ Server error ({result[1]}) — try again later.", fg=HP_CRIT)
            else:
                self._test_label.config(text="✗ Connection failed.", fg=HP_CRIT)

        def _thread():
            result = _work()                       # network I/O off the UI thread
            run_on_ui(lambda: _done(result))
        threading.Thread(target=_thread, daemon=True).start()

    def _browse(self, var):
        path = filedialog.askopenfilename(
            filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.gif"),("All","*.*")])
        if path: var.set(path)

    def _submit(self):
        self._extract_id()
        vals = {k: v.get().strip() for k, v in self._vars.items()}
        if not all([vals["name"], vals["character_id"]]):
            messagebox.showwarning("Required","Name and Character ID are required.",parent=self)
            return
        for key, var in self._portrait_vars.items():
            vals[key] = var.get().strip()
        vals["always_on_top"] = self._on_top_var.get()
        vals["opacity"]       = round(self._opacity_var.get(), 2)
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
        for key, label, val in [("name","GAME NAME",game.get("name",""))]:
            tk.Label(body, text=label, bg=DLG_BG, fg=DLG_LABEL_FG,
                     font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(6,2))
            var = tk.StringVar(value=val)
            self._vars[key] = var
            styled_entry(body, var, width=32).pack(fill="x", ipady=4, pady=(0,2))
        mk_sep(self, MGR_BORDER)
        foot = tk.Frame(self, bg=MGR_HEADER)
        foot.pack(fill="x", padx=14, pady=8)
        styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                      self.destroy).pack(side="right", padx=(4,0), ipady=4, ipadx=8)
        styled_button(foot, "Save", BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                      self._submit, font=F_MED).pack(side="right", ipady=4, ipadx=12)

    def _submit(self):
        name = self._vars["name"].get().strip()
        if not name:
            messagebox.showwarning("Required","Game name is required.",parent=self)
            return
        self.result = {"name": name}
        self.destroy()

# ---------------------------------------------------------------------------
# Manager window
# ---------------------------------------------------------------------------
class ManagerWindow:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root     = root
        self.cfg      = cfg
        self._windows:    dict[str, CharacterWindow] = {}
        self._hp_data:    dict[str, tuple]           = {}
        self._status:     dict[str, str]             = {}
        self._hp_toggles: dict[str, tk.BooleanVar]  = {}
        self._row_widgets: dict[str, dict]           = {}
        # Sort state — persisted in cfg["sort"]
        prefs = cfg.setdefault("sort", {})
        self._sort_mode     = prefs.get("mode", "alpha_asc")
        self._live_on_top   = prefs.get("live_on_top", True)

        root.title(f"D&D Health Bar  v{APP_VERSION}  —  Public Edition")
        root.configure(bg=MGR_BG)
        root.resizable(True, True)
        root.minsize(440, 300)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self._build_ui()
        self._update_sort_btn_styles()
        self._refresh_games()

    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=MGR_HEADER)
        hdr.pack(fill="x")
        logo = tk.Label(hdr, text="⚔", bg="#1e2c38", fg="#8ab0c0",
                        font=("Segoe UI",16), width=2, relief="flat",
                        highlightthickness=1, highlightbackground=MGR_BORDER3)
        logo.pack(side="left", padx=(12,8), pady=10)
        tcol = tk.Frame(hdr, bg=MGR_HEADER)
        tcol.pack(side="left")
        tk.Label(tcol, text="D&D Health Bar  —  Public Edition",
                 bg=MGR_HEADER, fg=T_PRIMARY, font=F_TITLE).pack(anchor="w")
        tk.Label(tcol, text=f"v{APP_VERSION}  ·  public characters only  ·  no credentials required",
                 bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(anchor="w")
        if OVERLAY_HUB.port:
            obs_lbl = tk.Label(hdr, text="OBS overlays ↗", bg=MGR_HEADER, fg=BTN_OPEN_FG,
                               font=F_TINY, cursor="hand2")
            obs_lbl.pack(side="right", padx=12)
            obs_lbl.bind("<Button-1>", lambda _e: webbrowser.open(
                f"http://127.0.0.1:{OVERLAY_HUB.port}/"))
        mk_sep(self.root, MGR_BORDER)

        gbar = tk.Frame(self.root, bg=MGR_HEADER, pady=7)
        gbar.pack(fill="x", padx=10)
        self._game_var = tk.StringVar()
        self._game_btn = tk.Button(gbar, textvariable=self._game_var,
                                   bg=MGR_PILL, fg=T_PRIMARY, font=F_BOLD,
                                   relief="flat", bd=0,
                                   highlightthickness=1, highlightbackground=MGR_BORDER3,
                                   activebackground=MGR_BORDER2, activeforeground=T_PRIMARY,
                                   anchor="w", padx=10, cursor="hand2",
                                   command=self._game_menu_popup)
        self._game_btn.pack(side="left", fill="x", expand=True, ipady=5)
        for txt,col,bdc,cmd in [
            ("✎",BTN_EDIT_BG,BTN_EDIT_BD,self._edit_game),
            ("＋",BTN_EDIT_BG,BTN_EDIT_BD,self._add_game),
            ("✕",DANGER_BG,  DANGER_BD,  self._delete_game),
        ]:
            styled_button(gbar,txt,col,BTN_EDIT_FG if col!=DANGER_BG else DANGER_FG,
                          bdc,cmd,font=F_MED,width=3).pack(side="left",padx=(4,0),ipady=5)
        mk_sep(self.root, MGR_BORDER)

        # Sort bar
        sbar = tk.Frame(self.root, bg=MGR_HEADER, pady=5)
        sbar.pack(fill="x", padx=10)

        tk.Label(sbar, text="Sort:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(side="left", padx=(0,4))
        self._sort_btns = {}
        for group, label in [("alpha","A–Z"), ("hp","HP"), ("manual","Manual")]:
            btn = tk.Button(sbar, text=label, font=F_TINY, cursor="hand2",
                            relief="flat", bd=0, padx=8, pady=2,
                            highlightthickness=1,
                            command=lambda g=group: self._cycle_sort(g))
            btn.pack(side="left", padx=2)
            self._sort_btns[group] = btn

        tk.Frame(sbar, bg=MGR_HEADER, width=12).pack(side="left")
        tk.Label(sbar, text="Live on top:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(side="left", padx=(0,4))
        self._live_top_var = tk.BooleanVar(value=self._live_on_top)
        ToggleSwitch(sbar, self._live_top_var,
                     command=self._on_live_top_toggle, bg=MGR_HEADER).pack(side="left")

        mk_sep(self.root, MGR_BORDER)

        self._char_frame = tk.Frame(self.root, bg=MGR_BG)
        self._char_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self._char_frame.columnconfigure(0, weight=1)
        mk_sep(self.root, MGR_BORDER)

        add_frame = tk.Frame(self.root, bg=MGR_BG, pady=6)
        add_frame.pack(fill="x", padx=10)

        bulk_row = tk.Frame(add_frame, bg=MGR_BG)
        bulk_row.pack(fill="x", pady=(0,4))

        self._open_all_btn = styled_button(
            bulk_row, "▶▶  Open all", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
            self._open_all_windows, font=F_SMALL)
        self._open_all_btn.pack(side="left", fill="x", expand=True, ipady=5, padx=(0,4))

        self._close_all_btn = styled_button(
            bulk_row, "■■  Close all", BTN_CLOSE_BG, BTN_CLOSE_FG, BTN_CLOSE_BD,
            self._close_all_windows, font=F_SMALL)
        self._close_all_btn.pack(side="left", fill="x", expand=True, ipady=5)

        tk.Button(add_frame, text="＋  Add character",
                  bg=MGR_BG, fg=T_MUTED, relief="flat", bd=0,
                  highlightthickness=1, highlightbackground=MGR_BORDER2,
                  activebackground=MGR_BORDER2, activeforeground=T_DIM,
                  font=F_SMALL, cursor="hand2",
                  command=self._add_character).pack(fill="x", ipady=5)
        mk_sep(self.root, MGR_BORDER)

        self._status_bar = tk.Frame(self.root, bg=MGR_HEADER, pady=4)
        self._status_bar.pack(fill="x", padx=10)
        self._status_label = tk.Label(self._status_bar, text="No windows open",
                                      bg=MGR_HEADER, fg=T_MUTED, font=F_TINY, anchor="w")
        self._status_label.pack(fill="x")

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

    def _select_game(self, name):
        self._game_var.set(name)
        self._refresh_chars()

    def _games(self):
        return self.cfg.setdefault("games", [])

    def _current_game(self):
        sel = self._game_var.get()
        return next((g for g in self._games() if g["name"]==sel), None)

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
        g = {"name": dlg.result["name"], "characters": []}
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
        save_config(self.cfg)
        self._refresh_games()
        self._game_var.set(g["name"])
        self._refresh_chars()

    def _delete_game(self):
        g = self._current_game()
        if not g: return
        if not messagebox.askyesno("Delete game",
            f"Delete '{g['name']}' and all its characters?",parent=self.root): return
        for ch in g.get("characters",[]):
            self._close_window(ch["character_id"])
        self.cfg["games"] = [x for x in self._games() if x is not g]
        save_config(self.cfg)
        self._refresh_games()

    # ── Sort ─────────────────────────────────────────────────────────────────
    # Each group cycles: off → asc → desc → off
    _SORT_CYCLES = {
        "alpha":  [None, "alpha_asc",  "alpha_desc"],
        "hp":     [None, "hp_asc",     "hp_desc"],
        "manual": [None, "manual"],
    }
    _SORT_LABELS = {
        None:          {"alpha":"A–Z",    "hp":"HP",    "manual":"Manual"},
        "alpha_asc":   {"alpha":"A–Z ↑",  "hp":"HP",    "manual":"Manual"},
        "alpha_desc":  {"alpha":"A–Z ↓",  "hp":"HP",    "manual":"Manual"},
        "hp_asc":      {"alpha":"A–Z",    "hp":"HP ↑",  "manual":"Manual"},
        "hp_desc":     {"alpha":"A–Z",    "hp":"HP ↓",  "manual":"Manual"},
        "manual":      {"alpha":"A–Z",    "hp":"HP",    "manual":"Manual ✓"},
    }

    def _sort_group(self) -> str | None:
        """Return which group the current mode belongs to."""
        if self._sort_mode in ("alpha_asc","alpha_desc"): return "alpha"
        if self._sort_mode in ("hp_asc","hp_desc"):       return "hp"
        if self._sort_mode == "manual":                    return "manual"
        return None

    def _cycle_sort(self, group: str):
        """Clicking a sort button cycles through that group's states."""
        cycle = self._SORT_CYCLES[group]
        # If currently in a different group, start from index 1 (first active state)
        if self._sort_group() != group:
            new_mode = cycle[1]
        else:
            cur_idx  = cycle.index(self._sort_mode) if self._sort_mode in cycle else 0
            new_mode = cycle[(cur_idx + 1) % len(cycle)]
        self._sort_mode = new_mode
        self.cfg["sort"]["mode"] = new_mode
        save_config(self.cfg)
        self._update_sort_btn_styles()
        self._refresh_chars()

    def _on_live_top_toggle(self):
        self._live_on_top = self._live_top_var.get()
        self.cfg["sort"]["live_on_top"] = self._live_on_top
        save_config(self.cfg)
        self._refresh_chars()

    def _update_sort_btn_styles(self):
        labels = self._SORT_LABELS.get(self._sort_mode, self._SORT_LABELS[None])
        active_group = self._sort_group()
        for group, btn in self._sort_btns.items():
            active = group == active_group
            btn.config(
                text = labels[group],
                bg   = BTN_SAVE_BG if active else MGR_ROW,
                fg   = BTN_SAVE_FG if active else T_DIM,
                highlightbackground = BTN_SAVE_BD if active else MGR_BORDER2,
            )

    def _sorted_characters(self, characters: list) -> list:
        """Return characters in display order based on current sort mode."""
        chars     = list(characters)
        live_cids = set(self._windows.keys())

        if self._sort_mode == "alpha_asc":
            chars.sort(key=lambda c: c.get("name","").lower())
        elif self._sort_mode == "alpha_desc":
            chars.sort(key=lambda c: c.get("name","").lower(), reverse=True)
        elif self._sort_mode == "hp_asc":
            # Lowest HP first, offline (no data) at the end
            chars.sort(key=lambda c: self._hp_data[c["character_id"]][0]
                       if c["character_id"] in self._hp_data else 2.0)
        elif self._sort_mode == "hp_desc":
            # Highest HP first, offline at the end
            chars.sort(key=lambda c: -self._hp_data[c["character_id"]][0]
                       if c["character_id"] in self._hp_data else 2.0)
        # None or "manual" → keep config order

        if self._live_on_top:
            live    = [c for c in chars if c["character_id"] in live_cids]
            offline = [c for c in chars if c["character_id"] not in live_cids]
            chars   = live + offline

        return chars

    # ── Manual sort — arrow buttons ───────────────────────────────────────────
    def _move_character(self, cid: str, direction: int):
        """Move character up (-1) or down (+1) in the config list."""
        g = self._current_game()
        if not g: return
        chars        = g["characters"]
        sorted_chars = self._sorted_characters(chars)
        disp_idx     = next((i for i,c in enumerate(sorted_chars) if c["character_id"]==cid), None)
        if disp_idx is None: return
        new_disp_idx = disp_idx + direction
        if new_disp_idx < 0 or new_disp_idx >= len(sorted_chars): return

        # Swap in the underlying config list
        other_cid = sorted_chars[new_disp_idx]["character_id"]
        ci = next(i for i,c in enumerate(chars) if c["character_id"]==cid)
        oi = next(i for i,c in enumerate(chars) if c["character_id"]==other_cid)
        chars[ci], chars[oi] = chars[oi], chars[ci]
        save_config(self.cfg)
        self._refresh_chars()

    # ── Characters ────────────────────────────────────────────────────────────
    def _refresh_chars(self):
        """Full rebuild — only called when character list structure changes."""
        self._row_widgets.clear()
        for w in self._char_frame.winfo_children():
            w.destroy()
        g = self._current_game()
        if g is None or not g.get("characters"):
            msg = "No game selected." if g is None else "No characters yet — add one below."
            tk.Label(self._char_frame, text=msg,
                     bg=MGR_BG, fg=T_MUTED, font=F_SMALL).pack(pady=16)
        else:
            for ch in self._sorted_characters(g["characters"]):
                self._make_char_row(ch, g)
        self._update_sort_btn_styles()
        self.root.update_idletasks()
        self._update_status_bar()

    def _update_row_state(self, cid: str):
        """Surgically update open/close button and border for one row — no flicker."""
        w = self._row_widgets.get(cid)
        if not w: return
        is_open = cid in self._windows
        try:
            w["row"].config(highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
            if is_open:
                w["open_btn"].config(text="■", bg=BTN_CLOSE_BG, fg=BTN_CLOSE_FG,
                                     highlightbackground=BTN_CLOSE_BD)
            else:
                w["open_btn"].config(text="▶", bg=BTN_OPEN_BG, fg=BTN_OPEN_FG,
                                     highlightbackground=BTN_OPEN_BD)
                # Clear badge and mini bar when window closes
                w["badge"].config(text="—", bg=HPB_DEAD, fg=T_MUTED,
                                  font=F_TINY, highlightbackground=HBB_DEAD)
                self._draw_mini_bar(w["mini_bar"], None)
                w["dot"].itemconfig(w["dot_oval"], fill="#2a3c4a")
        except tk.TclError:
            pass

    def _make_char_row(self, ch, game):
        cid     = ch["character_id"]
        is_open = cid in self._windows
        row = tk.Frame(self._char_frame, bg=MGR_ROW, highlightthickness=1,
                       highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
        row.pack(fill="x", pady=5)
        inner = tk.Frame(row, bg=MGR_ROW)
        inner.pack(fill="x", padx=10, pady=8)

        # Arrow buttons for manual sort (only active in manual mode)
        if self._sort_mode == "manual":
            g_chars      = game.get("characters", [])
            sorted_chars = self._sorted_characters(g_chars)
            disp_idx     = next((i for i,c in enumerate(sorted_chars) if c["character_id"]==cid), 0)
            is_first     = disp_idx == 0
            is_last      = disp_idx == len(sorted_chars) - 1

            arrow_col = tk.Frame(inner, bg=MGR_ROW)
            arrow_col.pack(side="left", padx=(0,4))

            up_btn = tk.Button(arrow_col, text="↑", font=F_TINY, width=2,
                               bg=MGR_ROW if is_first else BTN_EDIT_BG,
                               fg=MGR_BORDER2 if is_first else BTN_EDIT_FG,
                               relief="flat", bd=0, highlightthickness=1,
                               highlightbackground=MGR_BORDER2,
                               cursor="arrow" if is_first else "hand2",
                               state="disabled" if is_first else "normal",
                               command=lambda c=cid: self._move_character(c, -1))
            up_btn.pack(side="top", pady=(0,1))

            dn_btn = tk.Button(arrow_col, text="↓", font=F_TINY, width=2,
                               bg=MGR_ROW if is_last else BTN_EDIT_BG,
                               fg=MGR_BORDER2 if is_last else BTN_EDIT_FG,
                               relief="flat", bd=0, highlightthickness=1,
                               highlightbackground=MGR_BORDER2,
                               cursor="arrow" if is_last else "hand2",
                               state="disabled" if is_last else "normal",
                               command=lambda c=cid: self._move_character(c, 1))
            dn_btn.pack(side="top")

        thumb = 38
        cvs = tk.Canvas(inner, width=thumb, height=thumb, bg=MGR_ROW, highlightthickness=0)
        cvs.pack(side="left", padx=(0,8))
        self._draw_thumb(cvs, ch, thumb)

        info = tk.Frame(inner, bg=MGR_ROW)
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=ch.get("name","Unknown"), bg=MGR_ROW,
                 fg=T_PRIMARY, font=F_BOLD, anchor="w").pack(anchor="w")
        tk.Label(info, text=cid, bg=MGR_ROW, fg=T_DIM,
                 font=F_TINY, anchor="w").pack(anchor="w")

        badge_frame = tk.Frame(inner, bg=MGR_ROW)
        badge_frame.pack(side="left", padx=6)
        hp_data = self._hp_data.get(cid)
        if hp_data and is_open:
            pct,cur,mx = hp_data
            fg,bg,bd = hp_badge_colors(pct)
            badge = tk.Label(badge_frame, text=f"{cur} / {mx}",
                     bg=bg, fg=fg, font=("Consolas",10,"bold"),
                     padx=7, pady=2,
                     highlightthickness=1, highlightbackground=bd)
        else:
            pct = None
            badge = tk.Label(badge_frame, text="—",
                     bg=HPB_DEAD, fg=T_MUTED, font=F_TINY,
                     padx=7, pady=2,
                     highlightthickness=1, highlightbackground=HBB_DEAD)
        badge.pack()

        # Mini HP bar
        mini_w, mini_h = 56, 5
        mini_bar = tk.Canvas(inner, width=mini_w, height=mini_h,
                             bg=MGR_ROW, highlightthickness=0)
        mini_bar.pack(side="left", padx=(0,4))
        self._draw_mini_bar(mini_bar, pct)

        if cid not in self._hp_toggles:
            self._hp_toggles[cid] = tk.BooleanVar(value=bool(ch.get("show_hp_numbers",False)))
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

        status_msg = self._status.get(cid,"")
        dot_col = HP_FULL if (is_open and "Polling" in status_msg) else \
                  HP_CRIT if (is_open and "Error" in status_msg) else "#2a3c4a"
        dot = tk.Canvas(inner, width=8, height=8, bg=MGR_ROW, highlightthickness=0)
        dot.pack(side="left", padx=(0,6))
        dot_oval = dot.create_oval(1,1,7,7, fill=dot_col, outline="")

        # Store references for in-place updates (avoids full row rebuild on poll)
        self._row_widgets[cid] = {"row": row, "badge": badge, "dot": dot,
                                   "dot_oval": dot_oval, "mini_bar": mini_bar}

        btns = tk.Frame(inner, bg=MGR_ROW)
        btns.pack(side="right")
        if is_open:
            open_btn = styled_button(btns,"■",BTN_CLOSE_BG,BTN_CLOSE_FG,BTN_CLOSE_BD,
                                     lambda c=ch,g=game: self._toggle_window(c,g),width=3)
        else:
            open_btn = styled_button(btns,"▶",BTN_OPEN_BG,BTN_OPEN_FG,BTN_OPEN_BD,
                                     lambda c=ch,g=game: self._toggle_window(c,g),width=3)
        open_btn.pack(side="left", padx=(0,3), ipady=4)
        self._row_widgets[cid]["open_btn"] = open_btn

        styled_button(btns,"OBS",BTN_EDIT_BG,BTN_EDIT_FG,BTN_EDIT_BD,
                      lambda c=ch: self._copy_overlay_url(c),
                      font=F_TINY).pack(side="left",padx=(0,3),ipady=4,ipadx=2)

        styled_button(btns,"✎",BTN_EDIT_BG,BTN_EDIT_FG,BTN_EDIT_BD,
                      lambda c=ch,g=game: self._edit_character(c,g),width=3).pack(side="left",padx=(0,3),ipady=4)
        styled_button(btns,"✕",DANGER_BG,DANGER_FG,DANGER_BD,
                      lambda c=ch,g=game: self._delete_character(c,g),width=3).pack(side="left",ipady=4)

    def _draw_mini_bar(self, canvas: tk.Canvas, pct):
        """Draw a small coloured HP bar inside a manager row."""
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        # Track
        canvas.create_rectangle(0, 0, w, h, fill=MGR_BORDER2, outline="")
        if pct is None:
            # Striped "no data" pattern
            for x in range(0, w, 8):
                canvas.create_rectangle(x, 0, x+4, h, fill="#2a3a44", outline="")
            return
        fw = max(0, int(w * max(0.0, min(1.0, pct))))
        if fw > 0:
            canvas.create_rectangle(0, 0, fw, h, fill=hp_bar_color(pct), outline="")

    def _draw_thumb(self, canvas, ch, size):
        keys=["portrait_unscathed","portrait_scratched","portrait_injured",
              "portrait_bloodied","portrait_critical","portrait_dead"]
        path=next((ch.get(k,"") for k in keys if ch.get(k) and os.path.isfile(ch.get(k,""))),"")
        try:
            img = fit_image(Image.open(path), size, MGR_ROW) \
                  if path else Image.new("RGBA",(size,size),MGR_ROW)
            img=round_image(img,8)
            photo=ImageTk.PhotoImage(img)
            canvas._photo=photo
            canvas.create_image(size//2,size//2,image=photo,anchor="center")
        except: pass

    def _toggle_window(self, ch, game):
        cid=ch["character_id"]
        if cid in self._windows:
            self._close_window(cid)
        else:
            self._open_window(ch)
        self.root.after(0, lambda c=cid: self._update_row_state(c))
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)

    def _open_window(self, ch):
        cid=ch["character_id"]
        win=CharacterWindow(master=self.root, char=ch,
                            on_closed=lambda c=cid: self._on_window_closed(c),
                            on_hp_update=self._on_hp_update,
                            status_cb=self._on_status_update)
        self._windows[cid]=win
        OVERLAY_HUB.set_live(cid, True)

    def _close_window(self, cid):
        if cid in self._windows:
            try: self._windows[cid].close()
            except: pass
            self._windows.pop(cid,None)
        self._hp_data.pop(cid,None)
        self._status.pop(cid,None)
        # keep the row widget refs — the row still exists, only its state needs updating
        self._update_status_bar()

    def _on_window_closed(self, cid):
        OVERLAY_HUB.set_live(cid, False)
        self._windows.pop(cid,None)
        self._hp_data.pop(cid,None)
        self._status.pop(cid,None)
        save_config(self.cfg)
        self.root.after(0, lambda c=cid: self._update_row_state(c))
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)
        self.root.after(0, self._update_status_bar)

    def _on_hp_update(self, cid, pct, cur, mx):
        self._hp_data[cid] = (pct, cur, mx)
        def _do():
            # Always update badge in place
            w = self._row_widgets.get(cid)
            if w:
                try:
                    fg, bg, bd = hp_badge_colors(pct)
                    w["badge"].config(text=f"{cur} / {mx}" if pct is not None else "—",
                                      bg=bg, fg=fg, highlightbackground=bd,
                                      font=("Consolas",10,"bold") if pct is not None else F_TINY)
                    self._draw_mini_bar(w["mini_bar"], pct)
                except tk.TclError:
                    pass
            # Reorder existing row widgets in place — no destroy/rebuild
            if self._sort_mode in ("hp_asc", "hp_desc") or self._live_on_top:
                self._reorder_rows()
        OVERLAY_HUB.update_hp(cid, pct, cur, mx)
        self.root.after(0, _do)

    def _reorder_rows(self):
        """Re-pack existing row frames in sorted order without destroying them."""
        g = self._current_game()
        if not g or not g.get("characters"): return
        sorted_chars = self._sorted_characters(g["characters"])
        new_order    = [c["character_id"] for c in sorted_chars]
        # Check current pack order matches desired — skip if already correct
        current_rows = [w for w in self._char_frame.pack_slaves()
                        if isinstance(w, tk.Frame)]
        current_order = []
        for row in current_rows:
            for cid, widgets in self._row_widgets.items():
                if widgets.get("row") is row:
                    current_order.append(cid)
                    break
        if current_order == new_order:
            return   # already in correct order, nothing to do
        for cid in new_order:
            w = self._row_widgets.get(cid)
            if w:
                try:
                    w["row"].pack_forget()
                    w["row"].pack(fill="x", pady=5)   # must match _make_char_row
                except tk.TclError:
                    pass

    def _on_status_update(self, cid, msg):
        """Called from worker threads."""
        def _do():
            if cid not in self._windows: return   # window closed meanwhile
            self._status[cid] = msg
            w = self._row_widgets.get(cid)
            if w:
                try:
                    dot_col = HP_FULL if "Polling" in msg else \
                              HP_CRIT if ("Error" in msg or "⚠" in msg) else "#2a3c4a"
                    w["dot"].itemconfig(w["dot_oval"], fill=dot_col)
                except tk.TclError:
                    pass
            self._update_status_bar()
        run_on_ui(_do)

    def _copy_overlay_url(self, ch):
        url = OVERLAY_HUB.url_for(ch["character_id"])
        if not url:
            messagebox.showwarning("OBS overlay",
                "The overlay server is not running (port in use or disabled in the config).",
                parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._status_label.config(
            text=f"Copied OBS browser-source URL for {ch.get('name','?')}: {url}", fg=BTN_OPEN_FG)
        self.root.after(4000, self._update_status_bar)

    def _update_status_bar(self):
        if not self._windows:
            self._status_label.config(text="No windows open", fg=T_MUTED)
        else:
            parts=[f"{self._windows[cid].char.get('name','?')}: {self._status.get(cid,'…')}"
                   for cid in self._windows]
            self._status_label.config(text="   ·   ".join(parts), fg=T_DIM)

        # Update open all / close all button states
        g = self._current_game()
        chars = g.get("characters", []) if g else []
        all_open   = all(c["character_id"] in self._windows for c in chars) if chars else False
        none_open  = not self._windows
        try:
            self._open_all_btn.config(
                state="disabled" if all_open or not chars else "normal",
                bg=MGR_ROW if (all_open or not chars) else BTN_OPEN_BG,
                fg=T_MUTED if (all_open or not chars) else BTN_OPEN_FG)
            self._close_all_btn.config(
                state="disabled" if none_open else "normal",
                bg=MGR_ROW if none_open else BTN_CLOSE_BG,
                fg=T_MUTED if none_open else BTN_CLOSE_FG)
        except tk.TclError:
            pass

    def _open_all_windows(self):
        g = self._current_game()
        if not g: return
        for ch in g.get("characters", []):
            if ch["character_id"] not in self._windows:
                self._open_window(ch)
        self._refresh_chars()

    def _close_all_windows(self):
        for cid in list(self._windows):
            self._close_window(cid)
        self._refresh_chars()

    def _add_character(self):
        g=self._current_game()
        if not g:
            messagebox.showwarning("No game","Add a game first.",parent=self.root); return
        dlg=CharacterDialog(self.root,{})
        self.root.wait_window(dlg)
        if dlg.result:
            g.setdefault("characters",[]).append(dlg.result)
            save_config(self.cfg)
            self._refresh_chars()

    def _edit_character(self, ch, game):
        old_cid=ch["character_id"]
        dlg=CharacterDialog(self.root,ch.copy())
        self.root.wait_window(dlg)
        if not dlg.result: return
        ch.update(dlg.result)
        save_config(self.cfg)
        cid=ch["character_id"]
        if old_cid in self._windows:
            if cid != old_cid:
                # Different character — restart the poller under the new ID
                self._close_window(old_cid)
                self._open_window(ch)
            else:
                w=self._windows[cid]
                w.set_title(ch.get("name",""))
                w.win.attributes("-topmost", bool(ch.get("always_on_top", False)))
                w.win.attributes("-alpha", max(0.2, min(1.0, float(ch.get("opacity", 1.0)))))
                w._last_state=None
                w._load_portrait(w._resolve_portrait(self._hp_data.get(cid,(1.0,))[0]))
        self._refresh_chars()

    def _delete_character(self, ch, game):
        if not messagebox.askyesno("Delete",
            f"Remove '{ch.get('name','?')}' from this game?",parent=self.root): return
        self._close_window(ch["character_id"])
        game["characters"]=[c for c in game["characters"] if c is not ch]
        save_config(self.cfg)
        self._refresh_chars()

    def _on_quit(self):
        save_config(self.cfg)
        for cid in list(self._windows): self._close_window(cid)
        self._stop_tray()
        self.root.destroy()

    # ── System tray ──────────────────────────────────────────────────────────
    _tray = None

    def _setup_tray(self):
        # Without pystray, closing the manager simply quits (set in __init__).
        if HAS_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)

    def _make_tray_icon(self):
        icon_img = Image.new("RGBA", (64, 64), "#293136")
        draw     = ImageDraw.Draw(icon_img)
        draw.ellipse([8,8,56,56], fill=HP_FULL)
        draw.ellipse([18,18,46,46], fill="#293136")
        menu = pystray.Menu(
            TrayItem("Show", self._restore_from_tray, default=True),
            TrayItem("Quit", self._quit_from_tray),
        )
        return pystray.Icon("DnD Health Bar", icon_img, "D&D Health Bar", menu)

    def _minimize_to_tray(self):
        self.root.withdraw()
        # A stopped pystray Icon can't be run again, so build a fresh one each time
        self._stop_tray()
        self._tray = self._make_tray_icon()
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _stop_tray(self):
        tray, self._tray = self._tray, None
        if tray:
            try: tray.stop()
            except Exception: pass

    # Tray menu callbacks run on pystray's thread
    def _restore_from_tray(self, icon=None, item=None):
        self._stop_tray()
        run_on_ui(self.root.deiconify)

    def _quit_from_tray(self, icon=None, item=None):
        self._stop_tray()
        run_on_ui(self._on_quit)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    cfg  = load_config()
    OVERLAY_HUB.sync_config(cfg)
    srv  = cfg.setdefault("overlay_server", {"enabled": True, "port": DEFAULT_OVERLAY_PORT})
    if srv.get("enabled", True):
        try:
            port = int(srv.get("port", DEFAULT_OVERLAY_PORT))
        except (TypeError, ValueError):
            port = DEFAULT_OVERLAY_PORT
        start_overlay_server(port)
    root = tk.Tk()
    app  = ManagerWindow(root, cfg)
    app._setup_tray()
    root.after(50, _pump_ui_queue, root)
    root.mainloop()

if __name__ == "__main__":
    main()