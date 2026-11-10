"""
D&D Beyond Live Health Bar — Public Edition
--------------------------------------------
Works with public D&D Beyond character sheets only.
No login, no cookies, no sensitive credentials required.

Portable: the program, its settings and all portrait images live in one
folder. Move, copy or sync that folder and everything keeps working.

  Health Bar/
    DnD_HealthBar_Public.exe
    dnd_healthbar_public.json      settings + characters (+ .bak backup)
    dnd_healthbar.log              log file (for troubleshooting)
    portraits/<name>_<id>/...      portrait images (paths stored relative)

Config data model:
  games: [
    {
      "id":   "a1b2c3d4",                # stable id (party overlay URL)
      "name": "My Campaign",
      "characters": [
        {
          "name":               "Thorin",
          "character_id":       "2222222",
          "always_on_top":      false,
          "show_hp_numbers":    false,
          "opacity":            1.0,
          "window_pos":         [100, 100],
          "portrait_unscathed": "portraits/Thorin_2222222/unscathed.png",
          "portrait_scratched": "", "portrait_injured": "", "portrait_bloodied": "",
          "portrait_critical":  "", "portrait_dead": "",
          "avatar":             "portraits/Thorin_2222222/avatar.png"   # from D&D Beyond
        }
      ]
    }
  ]
  overlay_server: {"enabled": true, "port": 7777}
  obs:            {"host": "127.0.0.1", "port": 4455, "password": "", "scene": ""}
  poll_interval:  5          close_to_tray: false          check_updates: true

OBS browser sources (localhost only):
  http://127.0.0.1:7777/overlay/<character_id>     one character
  http://127.0.0.1:7777/party/<game_id>            whole party in one source

Requirements:
    pip install -r requirements.txt
"""

APP_VERSION = "2.2.0"
GITHUB_REPO = "piosteiner/DnD-Player-Healthbars"

import os, sys, io, json, time, re, threading, traceback, queue, hashlib, base64
import shutil, secrets, logging, logging.handlers
import html, webbrowser, urllib.parse, urllib.request, http.server
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageChops
import requests

# System tray support (optional)
try:
    import pystray
    from pystray import MenuItem as TrayItem
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# OBS WebSocket support (optional — pip install websocket-client)
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

log = logging.getLogger("dnd_healthbar")

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"
ORIGIN        = "https://www.dndbeyond.com"
UA            = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
DEFAULT_POLL_INTERVAL = 5     # seconds between HP checks
POLL_INTERVAL         = DEFAULT_POLL_INTERVAL   # current value (from settings)
MIN_POLL, MAX_POLL    = 2, 60

# D&D Beyond condition ids (standard 5e conditions, alphabetical)
CONDITION_NAMES = {1: "Blinded", 2: "Charmed", 3: "Deafened", 4: "Exhaustion",
                   5: "Frightened", 6: "Grappled", 7: "Incapacitated", 8: "Invisible",
                   9: "Paralyzed", 10: "Petrified", 11: "Poisoned", 12: "Prone",
                   13: "Restrained", 14: "Stunned", 15: "Unconscious"}

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
T_DIM         = "#82a0b0"
T_MUTED       = "#6f8a9a"
HP_FULL       = "#00e676"
HP_SCRATCH    = "#40e880"
HP_INJURED    = "#ffb300"
HP_BLOODIED   = "#ff6b00"
HP_CRIT       = "#f44336"
HP_DEAD       = "#555555"
HP_TEMP       = "#4fc3f7"
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
F_LABEL  = ("Segoe UI", 8, "bold")
F_MONO   = ("Consolas", 11, "bold")
BAR_H         = 32
BAR_PAD       = 12
CORNER_R      = 14
OVL_W         = 280
CARD_H        = 340        # overlay design height without HP numbers
CARD_H_NUM    = 370        # ... with HP numbers
PARTY_GAP     = 16

# ---------------------------------------------------------------------------
# Paths (everything lives next to the program — portable)
# ---------------------------------------------------------------------------
CONFIG_NAME       = "dnd_healthbar_public.json"
LOG_NAME          = "dnd_healthbar.log"
PORTRAITS_DIRNAME = "portraits"

def _default_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

_BASE_DIR = CONFIG_FILE = LOG_FILE = ""

def set_base_dir(path: str):
    """Point the app at a data folder (used at startup and by the tests)."""
    global _BASE_DIR, CONFIG_FILE, LOG_FILE
    _BASE_DIR   = os.path.abspath(path)
    CONFIG_FILE = os.path.join(_BASE_DIR, CONFIG_NAME)
    LOG_FILE    = os.path.join(_BASE_DIR, LOG_NAME)

set_base_dir(_default_base_dir())

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging():
    """Log to a small rotating file next to the program. The .exe has no
    console, so without this every warning would vanish."""
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=512_000,
                                                  backupCount=1, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:            # running from source
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    sys.excepthook = lambda t, v, tb: log.error("Uncaught error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.error(
        "Uncaught error in thread %s", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    log.info("D&D Health Bar %s starting (data folder: %s)", APP_VERSION, _BASE_DIR)

# ---------------------------------------------------------------------------
# Portraits — stored inside the data folder, paths relative to it
# ---------------------------------------------------------------------------
PORTRAIT_KEYS = ["portrait_unscathed","portrait_scratched","portrait_injured",
                 "portrait_bloodied","portrait_critical","portrait_dead"]
IMAGE_KEYS    = PORTRAIT_KEYS + ["avatar"]
_STATE_TO_KEY = {"full":"portrait_unscathed","scratched":"portrait_scratched",
                 "injured":"portrait_injured","bloodied":"portrait_bloodied",
                 "critical":"portrait_critical","dead":"portrait_dead",
                 "unknown":"portrait_unscathed"}

def portrait_abspath(p: str) -> str:
    """Stored portrait path (relative to the data folder, or legacy absolute)
    → absolute path on this machine."""
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(_BASE_DIR, p))

def _is_inside_base(p: str) -> bool:
    try:
        a = os.path.normcase(os.path.abspath(p))
        b = os.path.normcase(_BASE_DIR)
        return os.path.commonpath([a, b]) == b
    except ValueError:          # different drives
        return False

def _to_relative(p: str) -> str:
    return os.path.relpath(os.path.abspath(p), _BASE_DIR).replace(os.sep, "/")

def character_folder(ch: dict) -> str:
    safe = re.sub(r"[^\w\- ]+", "", ch.get("name", "")).strip() or "character"
    return f"{PORTRAITS_DIRNAME}/{safe}_{ch.get('character_id', 'x')}"

def _file_digest(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def import_portrait(src: str, ch: dict, slot: str) -> str:
    """Copy an image into the character's portrait folder and return its
    relative path. Identical images are stored only once."""
    folder_rel = character_folder(ch)
    folder_abs = portrait_abspath(folder_rel)
    os.makedirs(folder_abs, exist_ok=True)
    size, digest = os.path.getsize(src), _file_digest(src)
    for fn in sorted(os.listdir(folder_abs)):
        fp = os.path.join(folder_abs, fn)
        if os.path.isfile(fp) and os.path.getsize(fp) == size and _file_digest(fp) == digest:
            return f"{folder_rel}/{fn}"
    ext = os.path.splitext(src)[1].lower() or ".png"
    dst, i = os.path.join(folder_abs, slot + ext), 2
    while os.path.exists(dst):
        dst, i = os.path.join(folder_abs, f"{slot}-{i}{ext}"), i + 1
    shutil.copy2(src, dst)
    return f"{folder_rel}/{os.path.basename(dst)}"

def make_portable(p: str, ch: dict, key: str) -> str:
    """Absolute path → relative path inside the data folder (copying the
    image in if it lives elsewhere). Missing files are left untouched."""
    if not p or not os.path.isabs(p):
        return p
    if _is_inside_base(p):
        return _to_relative(p)
    if os.path.isfile(p):
        return import_portrait(p, ch, key.replace("portrait_", ""))
    return p

def download_avatar(url: str, ch: dict) -> str | None:
    """Save the character's D&D Beyond avatar into its portrait folder."""
    u = urllib.parse.urlsplit(url or "")
    if u.scheme != "https" or not (u.hostname or "").endswith("dndbeyond.com"):
        return None
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    img.load()                                    # validate it is an image
    folder_rel = character_folder(ch)
    os.makedirs(portrait_abspath(folder_rel), exist_ok=True)
    rel = f"{folder_rel}/avatar.png"
    img.convert("RGBA").save(portrait_abspath(rel), "PNG")
    return rel

def has_custom_portrait(ch: dict) -> bool:
    return any(ch.get(k) and os.path.isfile(portrait_abspath(ch[k])) for k in PORTRAIT_KEYS)

def resolve_portrait_key(char: dict, pct) -> str:
    """Best available portrait slot for the HP state: the ideal state first,
    then alternately the nearest healthier / worse state, then the D&D
    Beyond avatar.  bloodied → injured → critical → scratched → dead → unscathed"""
    idx   = PORTRAIT_KEYS.index(_STATE_TO_KEY[hp_state(pct)])
    n     = len(PORTRAIT_KEYS)
    order = [idx]
    for offset in range(1, n):
        if idx - offset >= 0: order.append(idx - offset)
        if idx + offset < n:  order.append(idx + offset)
    for i in order:
        key = PORTRAIT_KEYS[i]
        p   = char.get(key, "")
        if p and os.path.isfile(portrait_abspath(p)):
            return key
    p = char.get("avatar", "")
    if p and os.path.isfile(portrait_abspath(p)):
        return "avatar"
    return ""

def resolve_portrait_path(char: dict, pct) -> str:
    key = resolve_portrait_key(char, pct)
    return portrait_abspath(char.get(key, "")) if key else ""

# ---------------------------------------------------------------------------
# Config — atomic saves, automatic backup, recovery, migration
# ---------------------------------------------------------------------------
CONFIG_VERSION     = 2
_save_lock         = threading.Lock()
SAVE_ERROR_HANDLER = None    # set by the manager: callable(message)
_save_blocked: str | None = None

def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config root is not an object")
    if not isinstance(data.get("games", []), list):
        raise ValueError("'games' is not a list")
    data.setdefault("games", [])
    return data

def load_config() -> tuple[dict, list[str]]:
    """Returns (config, notices). A damaged file is never overwritten: it is
    renamed aside and the automatic backup is used instead."""
    global _save_blocked
    notices: list[str] = []
    if not os.path.isfile(CONFIG_FILE):
        return {"games": []}, notices
    try:
        return _read_json(CONFIG_FILE), notices
    except Exception as e:
        log.error("Could not read %s: %s", CONFIG_FILE, e)
    damaged = CONFIG_FILE[:-5] + time.strftime(".damaged-%Y%m%d-%H%M%S.json")
    try:
        os.replace(CONFIG_FILE, damaged)
    except OSError as e:
        log.error("Could not move damaged config aside: %s", e)
        _save_blocked = ("The settings file is damaged and locked, so it is not "
                         "overwritten. Close other programs using it and restart.")
        damaged = CONFIG_FILE
    try:
        cfg = _read_json(CONFIG_FILE + ".bak")
        notices.append("Your settings file was damaged and has been restored from the "
                       f"automatic backup.\n\nThe damaged file was kept as:\n{damaged}")
        log.warning("Config restored from backup")
        return cfg, notices
    except Exception as e:
        log.error("Backup not usable either: %s", e)
        notices.append("Your settings file could not be read and no usable backup was "
                       f"found, so the app starts empty.\n\nThe unreadable file was kept as:\n{damaged}")
        return {"games": []}, notices

def save_config(cfg: dict) -> bool:
    """Write the config atomically (temp file + rename) and keep the previous
    version as .bak. Retries briefly if a sync client has the file locked."""
    ok, err = False, ""
    if _save_blocked:
        err = _save_blocked
    else:
        data = json.dumps(cfg, indent=2, ensure_ascii=False)
        tmp  = CONFIG_FILE + ".tmp"
        with _save_lock:
            for attempt in range(5):
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    if os.path.isfile(CONFIG_FILE):
                        try:
                            shutil.copyfile(CONFIG_FILE, CONFIG_FILE + ".bak")
                        except OSError as e:
                            log.warning("Could not update backup: %s", e)
                    os.replace(tmp, CONFIG_FILE)
                    ok = True
                    break
                except OSError as e:
                    err = str(e)
                    time.sleep(0.15 * (attempt + 1))
    OVERLAY_HUB.sync_config(cfg)
    if not ok:
        log.error("Could not save settings: %s", err)
        if SAVE_ERROR_HANDLER:
            SAVE_ERROR_HANDLER(err)
    return ok

def migrate_config(cfg: dict) -> bool:
    """Bring older configs up to date. Returns True if anything changed."""
    changed = False
    for g in cfg.setdefault("games", []):
        if not g.get("id"):
            g["id"] = secrets.token_hex(4)
            changed = True
        for ch in g.setdefault("characters", []):
            for key in IMAGE_KEYS:
                p = ch.get(key)
                if not p:
                    continue
                try:
                    newp = make_portable(p, ch, key)
                except OSError as e:
                    log.warning("Could not import portrait %s: %s", p, e)
                    continue
                if newp != p:
                    ch[key] = newp
                    changed = True
    if cfg.get("config_version") != CONFIG_VERSION:
        cfg["config_version"] = CONFIG_VERSION
        changed = True
    return changed

def poll_interval() -> int:
    return POLL_INTERVAL

def apply_poll_interval(cfg: dict):
    global POLL_INTERVAL
    try:
        v = int(cfg.get("poll_interval", DEFAULT_POLL_INTERVAL))
    except (TypeError, ValueError):
        v = DEFAULT_POLL_INTERVAL
    POLL_INTERVAL = max(MIN_POLL, min(MAX_POLL, v))

# ---------------------------------------------------------------------------
# D&D Beyond API — no auth required
# ---------------------------------------------------------------------------
def make_session(character_id: str) -> requests.Session:
    """Visit the public character page to collect the Geo cookie."""
    session = requests.Session()
    session.get(f"{ORIGIN}/characters/{character_id}",
                headers={"User-Agent": UA}, timeout=10)
    return session

def get_character(session: requests.Session, character_id: str) -> dict:
    """Fetch public character data and extract what the overlay needs."""
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
    return parse_character(resp.json().get("data", {}))

def parse_character(char: dict) -> dict:
    total_level    = sum(c.get("level", 0) for c in char.get("classes", []))
    override_stats = {s["id"]: s["value"] for s in char.get("overrideStats", []) if s.get("value") is not None}
    base_stats     = {s["id"]: s["value"] for s in char.get("stats", [])          if s.get("value") is not None}
    bonus_stats    = {s["id"]: s["value"] for s in char.get("bonusStats", [])     if s.get("value") is not None}
    modifiers      = char.get("modifiers") or {}

    if 3 in override_stats:
        con_score = override_stats[3]
    else:
        con_score = base_stats.get(3, 10) + bonus_stats.get(3, 0)
        con_set = None
        for src in ("race", "feat", "class", "background", "item", "condition"):
            for mod in modifiers.get(src, []) or []:
                if mod.get("subType") != "constitution-score":
                    continue
                mod_value = mod.get("value") or mod.get("fixedValue")
                if mod.get("type") == "bonus":
                    con_score += int(mod_value or 0)
                elif mod.get("type") == "set" and mod_value is not None:
                    con_set = max(con_set or 0, int(mod_value))   # e.g. Amulet of Health
        if con_set is not None:
            con_score = max(con_score, con_set)

    # "+N HP per level" (Tough, Hill Dwarf, Draconic Resilience, ...). Class
    # features scale with the granting class's level, others with total level.
    feature_class_level = {}
    for c in char.get("classes", []):
        for f in c.get("classFeatures", []) or []:
            fid = (f.get("definition") or {}).get("id")
            if fid is not None:
                feature_class_level[fid] = c.get("level", 0)
    hp_per_level_bonus = 0
    for src in ("race", "feat", "class", "background"):
        for mod in modifiers.get(src, []) or []:
            if mod.get("type") != "bonus" or mod.get("subType") != "hit-points-per-level":
                continue
            per_level = int(mod.get("value") or mod.get("fixedValue") or 0)
            levels    = total_level
            if src == "class":
                levels = feature_class_level.get(mod.get("componentId"), total_level)
            hp_per_level_bonus += per_level * levels

    ds = char.get("deathSaves") or {}
    conditions = []
    for c in char.get("conditions") or []:
        name = CONDITION_NAMES.get(c.get("id"))
        if not name:
            continue
        if name == "Exhaustion" and c.get("level"):
            name = f"Exhaustion {c['level']}"
        conditions.append(name)

    return {
        "api_name":           char.get("name", ""),
        "avatar_url":         (char.get("decorations") or {}).get("avatarUrl")
                              or char.get("avatarUrl") or "",
        "baseHitPoints":      int(char.get("baseHitPoints")      or 0),
        "bonusHitPoints":     int(char.get("bonusHitPoints")     or 0),
        "overrideHitPoints":  char.get("overrideHitPoints"),
        "removedHitPoints":   int(char.get("removedHitPoints")   or 0),
        "temporaryHitPoints": int(char.get("temporaryHitPoints") or 0),
        "totalLevel":         total_level,
        "conMod":             (con_score - 10) // 2,
        "hpPerLevelBonus":    hp_per_level_bonus,
        "deathSaves":         {"fail": int(ds.get("failCount") or 0),
                               "success": int(ds.get("successCount") or 0),
                               "stable": bool(ds.get("isStabilized"))},
        "conditions":         conditions,
    }

def calculate_hp(d: dict) -> tuple[float | None, int, int]:
    """(pct, current, max) of real hit points — temporary HP is separate.
    pct is None if the character has no HP configured yet."""
    override = d.get("overrideHitPoints")
    if override is not None:
        max_hp = int(override)
    else:
        max_hp = (d["baseHitPoints"] + d["totalLevel"] * d["conMod"]
                  + d.get("hpPerLevelBonus", 0) + d["bonusHitPoints"])
    if max_hp <= 0:
        return None, 0, 0
    current = max(0, min(max_hp, max_hp - d["removedHitPoints"]))
    return current / max_hp, current, max_hp

def hp_details(d: dict) -> dict:
    pct, cur, mx = calculate_hp(d)
    return {"pct": pct, "cur": cur, "mx": mx,
            "temp": max(0, d.get("temporaryHitPoints", 0)) if pct is not None else 0,
            "death_saves": d.get("deathSaves") or {"fail": 0, "success": 0, "stable": False},
            "conditions": list(d.get("conditions") or [])}

def hp_text(info: dict, sep: str = " / ") -> str:
    if info.get("pct") is None:
        return "—"
    t = f"{info['cur']}{sep}{info['mx']}"
    if info.get("temp"):
        t += f"  +{info['temp']}"
    return t

# ---------------------------------------------------------------------------
# Colour + image helpers
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
    # Combine with existing alpha so transparent areas stay transparent
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img

def fit_image(img: Image.Image, size: int, bg_color) -> Image.Image:
    """Scale to fit a `size` square, preserving aspect ratio (no cropping)."""
    img = img.convert("RGBA")
    iw, ih = img.size
    scale  = min(size / iw, size / ih)
    new_w, new_h = max(1, int(iw * scale)), max(1, int(ih * scale))
    img    = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), bg_color)
    canvas.paste(img, ((size - new_w) // 2, (size - new_h) // 2), img)
    return canvas

_thumb_cache: dict[tuple, "ImageTk.PhotoImage"] = {}

def thumb_photo(path: str, size: int, bg: str, radius: int = 8):
    """Small rounded thumbnail, cached per file + modification time so lists
    don't re-decode every image on each refresh. Main thread only."""
    try:
        key = (path, os.path.getmtime(path), size, bg, radius) if path else ("", 0, size, bg, radius)
    except OSError:
        key = ("", 0, size, bg, radius)
        path = ""
    photo = _thumb_cache.get(key)
    if photo is None:
        try:
            img = fit_image(Image.open(path), size, bg) if path else Image.new("RGBA", (size, size), bg)
        except Exception:
            img = Image.new("RGBA", (size, size), bg)
        photo = ImageTk.PhotoImage(round_image(img, radius))
        if len(_thumb_cache) > 300:
            _thumb_cache.clear()
        _thumb_cache[key] = photo
    return photo

# ---------------------------------------------------------------------------
# Thread-safe UI dispatch
# ---------------------------------------------------------------------------
# Tkinter must only be touched from the main thread. Worker threads put
# callables on this queue and the main loop drains it periodically.
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
                log.exception("UI callback failed")
    except queue.Empty:
        pass
    try:
        root.after(50, _pump_ui_queue, root)
    except tk.TclError:
        pass

# ---------------------------------------------------------------------------
# Browser-source overlay server (for OBS)
# ---------------------------------------------------------------------------
DEFAULT_OVERLAY_PORT = 7777

class OverlayHub:
    """Thread-safe snapshot of everything the browser overlays need.
    Written from the Tk main thread, read by HTTP server threads, which are
    woken up (server-sent events) whenever something changes."""

    def __init__(self):
        self._cond  = threading.Condition()
        self._chars: dict[str, dict] = {}   # cid → config snapshot
        self._games: list[dict]      = []   # [{"id","name","cids"}]
        self._live:  dict[str, dict] = {}   # cid → latest HP info (while open)
        self._img_cache: dict[tuple, bytes] = {}
        self.version = 0
        self.port: int | None = None

    # URLs
    def url_for(self, cid: str) -> str | None:
        return f"http://127.0.0.1:{self.port}/overlay/{cid}" if self.port else None

    def party_url(self, gid: str) -> str | None:
        return f"http://127.0.0.1:{self.port}/party/{gid}" if self.port else None

    def _bump(self):           # caller holds self._cond
        self.version += 1
        self._cond.notify_all()

    def wait_change(self, since: int, timeout: float) -> int:
        with self._cond:
            self._cond.wait_for(lambda: self.version != since, timeout)
            return self.version

    # Writers (main thread)
    def sync_config(self, cfg: dict):
        snap, games = {}, []
        for g in cfg.get("games", []):
            cids = []
            for ch in g.get("characters", []):
                cid = str(ch.get("character_id", ""))
                if not cid:
                    continue
                cids.append(cid)
                if cid in snap:
                    continue
                s = {"name": ch.get("name", ""), "game": g.get("name", ""),
                     "show_hp_numbers": bool(ch.get("show_hp_numbers", False))}
                for k in IMAGE_KEYS:
                    s[k] = portrait_abspath(ch.get(k, ""))
                snap[cid] = s
            games.append({"id": g.get("id", ""), "name": g.get("name", ""), "cids": cids})
        with self._cond:
            if snap != self._chars or games != self._games:
                self._chars, self._games = snap, games
                self._bump()

    def set_live(self, cid: str, live: bool):
        with self._cond:
            if live and cid not in self._live:
                self._live[cid] = {}
                self._bump()
            elif not live and cid in self._live:
                del self._live[cid]
                self._bump()

    def update_hp(self, cid: str, info: dict):
        with self._cond:
            if cid in self._live and self._live[cid] != info:
                self._live[cid] = dict(info)
                self._bump()

    # Readers (server threads)
    def characters(self) -> list[tuple[str, dict]]:
        with self._cond:
            return list(self._chars.items())

    def games(self) -> list[dict]:
        with self._cond:
            return [dict(g) for g in self._games]

    def state_for(self, cid: str) -> dict | None:
        with self._cond:
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
        return {"cid": cid, "name": ch["name"], "live": live, "loaded": loaded,
                "pct": pct, "cur": hp.get("cur", 0), "mx": hp.get("mx", 0),
                "temp": hp.get("temp", 0),
                "death_saves": hp.get("death_saves") or {"fail": 0, "success": 0, "stable": False},
                "conditions": hp.get("conditions") or [],
                "state": hp_state(pct), "color": hp_bar_color(pct),
                "show_hp_numbers": ch["show_hp_numbers"],
                "portrait": key, "portrait_v": ver}

    def party_state(self, gid: str) -> dict | None:
        with self._cond:
            g = next((x for x in self._games if x["id"] == gid), None)
        if g is None:
            return None
        chars = [s for s in (self.state_for(c) for c in g["cids"]) if s]
        return {"name": g["name"], "characters": chars}

    def portrait_png(self, cid: str, key: str) -> bytes | None:
        """Portrait fitted + rounded like the desktop window, at 2x resolution,
        transparent background. Cached per file modification time."""
        if key not in IMAGE_KEYS:
            return None
        with self._cond:
            path = (self._chars.get(cid) or {}).get(key, "")
        if not path or not os.path.isfile(path):
            return None
        cache_key = (path, os.path.getmtime(path))
        with self._cond:
            if cache_key in self._img_cache:
                return self._img_cache[cache_key]
        size = OVL_W * 2
        img  = round_image(fit_image(Image.open(path), size, (0, 0, 0, 0)), CORNER_R * 2)
        buf  = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
        with self._cond:
            if len(self._img_cache) > 64:
                self._img_cache.clear()
            self._img_cache[cache_key] = data
        return data

OVERLAY_HUB = OverlayHub()

# One page for both a single character (/overlay/<cid>) and a whole party
# (/party/<gid>). Updates arrive instantly via server-sent events.
OVERLAY_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>HP overlay</title>
<style>
  /* Sizes are design pixels times --u; JS sets --u so everything fits the
     browser source, whatever its width/height. */
  :root{--u:1px}
  html,body{margin:0;padding:0;background:transparent;overflow:hidden;
            font-family:"Segoe UI",system-ui,sans-serif}
  #stage{display:flex;gap:calc(var(--u)*16);justify-content:center;align-items:flex-start}
  body.column #stage{flex-direction:column;align-items:center}
  .card{position:relative;width:calc(var(--u)*280);flex:0 0 auto;box-sizing:border-box;
        opacity:0;transition:opacity .4s ease}
  .card.show{opacity:1}
  .card.gone{display:none}
  body.cardbg .card{background:#293136;border-radius:calc(var(--u)*14)}
  .pwrap{position:relative;width:calc(var(--u)*280);height:calc(var(--u)*280)}
  .portrait{display:block;width:100%;height:100%;object-fit:contain;transition:filter .8s ease}
  .portrait.empty{visibility:hidden}
  .card.dead .portrait{filter:grayscale(1) brightness(.6)}
  .card.hit .portrait{animation:shake .4s ease}
  .chips{position:absolute;left:calc(var(--u)*8);right:calc(var(--u)*8);top:calc(var(--u)*8);
         display:flex;flex-wrap:wrap;gap:calc(var(--u)*4)}
  .chip{font-size:calc(var(--u)*11);font-weight:600;padding:calc(var(--u)*2) calc(var(--u)*7);
        border-radius:calc(var(--u)*9);background:rgba(40,20,60,.85);color:#ecdcff;
        border:calc(var(--u)*1) solid rgba(190,150,255,.5)}
  .saves{position:absolute;left:0;right:0;bottom:calc(var(--u)*8);display:none;
         justify-content:center;gap:calc(var(--u)*5);align-items:center}
  .saves.on{display:flex}
  .pip{width:calc(var(--u)*14);height:calc(var(--u)*14);border-radius:50%;
       border:calc(var(--u)*2) solid rgba(255,255,255,.7);background:rgba(0,0,0,.45)}
  .pip.s.on{background:#00e676;border-color:#00e676}
  .pip.f.on{background:#f44336;border-color:#f44336}
  .sep{width:calc(var(--u)*10)}
  .stable{font:bold calc(var(--u)*13) "Segoe UI",sans-serif;color:#fff;letter-spacing:.08em;
          padding:calc(var(--u)*2) calc(var(--u)*10);border-radius:calc(var(--u)*9);
          background:rgba(0,120,60,.85)}
  .hp{padding:calc(var(--u)*12)}
  .track{position:relative;height:calc(var(--u)*32);border-radius:calc(var(--u)*16);
         background:#1e272e;overflow:hidden}
  .track.unknown{background:repeating-linear-gradient(90deg,#1e272e 0 calc(var(--u)*6),
                 #2a3a44 calc(var(--u)*6) calc(var(--u)*12))}
  .trail,.temp,.fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:calc(var(--u)*16)}
  .trail{background:#fff;opacity:.7}
  .temp{background:#4fc3f7;transition:width .6s ease}
  .fill{transition:width .6s ease,background-color .6s ease}
  .card.hit .track{animation:hit .9s ease}
  .card.heal .track{animation:heal .9s ease}
  .nums{display:none;margin-top:calc(var(--u)*6);color:#dce8f0;white-space:pre;
        font:bold calc(var(--u)*15) Consolas,"Courier New",monospace;
        text-shadow:0 0 calc(var(--u)*2) #000,0 0 calc(var(--u)*2) #000}
  .nums .t{color:#4fc3f7}
  @keyframes hit{0%{box-shadow:0 0 0 0 rgba(244,67,54,0)}
                 25%{box-shadow:0 0 calc(var(--u)*18) calc(var(--u)*4) rgba(244,67,54,.9)}
                 100%{box-shadow:0 0 0 0 rgba(244,67,54,0)}}
  @keyframes heal{0%{box-shadow:0 0 0 0 rgba(0,230,118,0)}
                  25%{box-shadow:0 0 calc(var(--u)*18) calc(var(--u)*4) rgba(0,230,118,.9)}
                  100%{box-shadow:0 0 0 0 rgba(0,230,118,0)}}
  @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(calc(var(--u)*-6))}
                   40%{transform:translateX(calc(var(--u)*5))}60%{transform:translateX(calc(var(--u)*-3))}
                   80%{transform:translateX(calc(var(--u)*2))}}
</style></head>
<body><div id="stage"></div>
<script>
  const parts  = location.pathname.split("/").filter(Boolean);   // overlay|party, id
  const party  = parts[0] === "party";
  const params = new URLSearchParams(location.search);
  if (params.get("card") === "1") document.body.classList.add("cardbg");
  if (params.get("layout") === "column") document.body.classList.add("column");
  const always   = params.get("always") === "1";
  const showCond = params.get("conditions") !== "0";
  const column   = params.get("layout") === "column";
  const stage    = document.getElementById("stage");
  const cards    = {};
  let n = 1, showNums = false;

  function fit() {
    const ch = showNums ? 370 : 340;
    const W  = column ? 280 : n * 280 + (n - 1) * 16;
    const H  = column ? n * ch + (n - 1) * 16 : ch;
    document.documentElement.style.setProperty("--u", Math.min(innerWidth / W, innerHeight / H) + "px");
  }
  addEventListener("resize", fit);

  function el(tag, cls, parent) {
    const e = document.createElement(tag); if (cls) e.className = cls;
    if (parent) parent.appendChild(e); return e;
  }
  function makeCard(cid) {
    const c = {cid, root: el("div", "card gone")};
    const pw = el("div", "pwrap", c.root);
    c.img   = el("img", "portrait empty", pw); c.img.alt = "";
    c.chips = el("div", "chips", pw);
    c.saves = el("div", "saves", pw);
    const hp = el("div", "hp", c.root);
    c.track = el("div", "track", hp);
    c.trail = el("div", "trail", c.track);
    c.temp  = el("div", "temp", c.track);
    c.fill  = el("div", "fill", c.track);
    c.nums  = el("div", "nums", hp);
    c.prevCur = null; c.src = null; c.visible = false;
    return cards[cid] = c;
  }
  function flash(c, cls) {
    c.root.classList.remove("hit", "heal"); void c.root.offsetWidth; c.root.classList.add(cls);
  }
  function setVisible(c, v) {
    if (v === c.visible) return;
    c.visible = v; clearTimeout(c.hideT);
    if (v) { c.root.classList.remove("gone"); requestAnimationFrame(() => c.root.classList.add("show")); }
    else   { c.root.classList.remove("show"); c.hideT = setTimeout(() => c.root.classList.add("gone"), 450); }
  }
  function update(c, s) {
    setVisible(c, always || (s.live && s.loaded));
    const src = s.portrait ? `/portrait/${s.cid}/${s.portrait}?v=${s.portrait_v}` : "";
    if (src !== c.src) {
      c.src = src;
      if (src) { c.img.src = src; c.img.classList.remove("empty"); }
      else     { c.img.removeAttribute("src"); c.img.classList.add("empty"); }
    }
    c.root.classList.toggle("dead", s.loaded && s.state === "dead");
    if (s.pct === null) {
      c.track.classList.add("unknown");
      for (const b of [c.fill, c.temp, c.trail]) b.style.width = "0";
      c.nums.textContent = s.loaded ? "HP not configured" : "";
      c.prevCur = null;
    } else {
      c.track.classList.remove("unknown");
      const total = Math.max(s.mx, s.cur + s.temp) || 1;
      const fw = (s.cur / total) * 100, tw = ((s.cur + s.temp) / total) * 100;
      if (c.prevCur !== null && s.cur < c.prevCur) {          // damage
        c.fill.style.transition  = "width .25s ease, background-color .6s ease";
        c.trail.style.transition = "width .8s ease .45s";
        flash(c, "hit");
      } else if (c.prevCur !== null && s.cur > c.prevCur) {   // healing
        c.trail.style.transition = "none";
        c.fill.style.transition  = "width .6s ease, background-color .6s ease";
        flash(c, "heal");
      }
      c.prevCur = s.cur;
      c.fill.style.width  = fw + "%";
      c.trail.style.width = fw + "%";
      c.temp.style.width  = tw + "%";
      c.fill.style.backgroundColor = s.color;
      c.nums.textContent = `${s.cur}  /  ${s.mx}`;
      if (s.temp) { const t = el("span", "t", c.nums); t.textContent = `  +${s.temp}`; }
    }
    c.nums.style.display = s.show_hp_numbers ? "block" : "none";
    // conditions
    c.chips.replaceChildren();
    if (showCond && s.loaded) for (const name of s.conditions) el("span", "chip", c.chips).textContent = name;
    // death saves (only while at 0 HP)
    const ds = s.death_saves || {};
    const dying = s.loaded && s.pct !== null && s.cur === 0;
    c.saves.classList.toggle("on", dying);
    c.saves.replaceChildren();
    if (dying) {
      if (ds.stable) el("span", "stable", c.saves).textContent = "STABLE";
      else {
        for (let i = 0; i < 3; i++) el("span", "pip s" + (i < ds.success ? " on" : ""), c.saves);
        el("span", "sep", c.saves);
        for (let i = 0; i < 3; i++) el("span", "pip f" + (i < ds.fail ? " on" : ""), c.saves);
      }
    }
  }
  function render(list) {
    n = Math.max(1, list.length);
    const nums = list.some(s => s.show_hp_numbers);
    if (nums !== showNums) showNums = nums;
    fit();
    const seen = new Set();
    for (const s of list) {
      const c = cards[s.cid] || makeCard(s.cid);
      stage.appendChild(c.root);          // keeps order
      update(c, s); seen.add(s.cid);
    }
    for (const cid in cards) if (!seen.has(cid)) { cards[cid].root.remove(); delete cards[cid]; }
  }
  fit();
  const es = new EventSource(party ? `/events/party/${parts[1]}` : `/events/${parts[1]}`);
  es.onmessage = e => { const d = JSON.parse(e.data); render(d.characters || []); };
  es.onerror   = () => { if (!always) for (const cid in cards) setVisible(cards[cid], false); };
</script>
</body></html>
"""

def _overlay_index_html() -> str:
    chars = dict(OVERLAY_HUB.characters())
    blocks = []
    for g in OVERLAY_HUB.games():
        rows = []
        purl = OVERLAY_HUB.party_url(g["id"]) or ""
        n    = max(1, len(g["cids"]))
        ph   = CARD_H_NUM if any(chars.get(c, {}).get("show_hp_numbers") for c in g["cids"]) else CARD_H
        rows.append(
            f'<tr class="party"><td><b>Whole party</b><br><small>{n * 280 + (n - 1) * PARTY_GAP} × '
            f'{ph}</small></td><td><code>{html.escape(purl)}</code></td>'
            f'<td><button data-url="{html.escape(purl)}">Copy</button> '
            f'<a href="{html.escape(purl)}?always=1&card=1" target="_blank">Preview</a></td></tr>')
        for cid in g["cids"]:
            ch  = chars.get(cid, {})
            url = OVERLAY_HUB.url_for(cid) or ""
            rows.append(
                f'<tr><td>{html.escape(ch.get("name", cid))}<br><small>280 × '
                f'{CARD_H_NUM if ch.get("show_hp_numbers") else CARD_H}</small></td>'
                f'<td><code>{html.escape(url)}</code></td>'
                f'<td><button data-url="{html.escape(url)}">Copy</button> '
                f'<a href="{html.escape(url)}?always=1&card=1" target="_blank">Preview</a></td></tr>')
        blocks.append(f'<h2>{html.escape(g["name"])}</h2><table>'
                      f'<tr><th>Source</th><th>URL</th><th></th></tr>{"".join(rows)}</table>')
    body = "\n".join(blocks) or "<p>No characters configured yet.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>D&amp;D Health Bar overlays</title>
<style>
  body{{background:#16202a;color:#dce8f0;font:14px "Segoe UI",system-ui,sans-serif;margin:24px}}
  h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px;color:#8ab0c0}}
  p,small{{color:#82a0b0}} p{{max-width:760px}}
  table{{border-collapse:collapse;margin-top:8px}}
  td,th{{padding:8px 12px;border-bottom:1px solid #243040;text-align:left;vertical-align:top}}
  th{{color:#7ea6b6;font-size:12px;text-transform:uppercase}}
  tr.party td{{background:#1a2632}}
  code{{color:#60c0d8}} a{{color:#60b0d0}}
  button{{background:#1a3848;color:#60c0d8;border:1px solid #2a5060;padding:4px 10px;cursor:pointer}}
</style></head><body>
<h1>D&amp;D Health Bar — OBS overlays</h1>
<p>Easiest: use <b>OBS ⚙</b> in the app to add these automatically. Manually: in OBS add a
<b>Browser</b> source, paste a URL and use the size shown (any size works — the overlay
scales to fit). A character appears when you press ▶ in the app and fades out on ■.</p>
<p>Options: <code>?card=1</code> dark card background · <code>?always=1</code> always visible ·
<code>?layout=column</code> stack the party vertically · <code>?conditions=0</code> hide conditions.</p>
{body}
<script>
document.querySelectorAll("button[data-url]").forEach(b => b.onclick = async () => {{
  await navigator.clipboard.writeText(b.dataset.url);
  b.textContent = "Copied!"; setTimeout(() => b.textContent = "Copy", 1500);
}});
</script></body></html>"""

PING_REPLY = b"dnd-healthbar"

class _OverlayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "DnDHealthBar"

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/ping":
                return self._send(200, "text/plain", PING_REPLY)
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8",
                                  _overlay_index_html().encode("utf-8"))
            if re.fullmatch(r"/(overlay/\d+|party/[0-9a-f]+)/?", path):
                return self._send(200, "text/html; charset=utf-8", OVERLAY_HTML.encode("utf-8"))
            m = re.fullmatch(r"/api/(\d+)", path)
            if m:
                return self._json(OVERLAY_HUB.state_for(m.group(1)))
            m = re.fullmatch(r"/api/party/([0-9a-f]+)", path)
            if m:
                return self._json(OVERLAY_HUB.party_state(m.group(1)))
            m = re.fullmatch(r"/events/(\d+)", path)
            if m:
                cid = m.group(1)
                return self._sse(lambda: {"characters": [s for s in [OVERLAY_HUB.state_for(cid)] if s]})
            m = re.fullmatch(r"/events/party/([0-9a-f]+)", path)
            if m:
                gid = m.group(1)
                return self._sse(lambda: OVERLAY_HUB.party_state(gid) or {"characters": []})
            m = re.fullmatch(r"/portrait/(\d+)/(portrait_[a-z]+|avatar)", path)
            if m:
                data = OVERLAY_HUB.portrait_png(m.group(1), m.group(2))
                if data is None:
                    return self._send(404, "text/plain", b"Not found")
                return self._send(200, "image/png", data, cache=True)
            self._send(404, "text/plain", b"Not found")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            log.exception("Overlay server error for %s", path)
            try: self._send(500, "text/plain", b"Internal error")
            except Exception: pass

    def _json(self, obj):
        if obj is None:
            return self._send(404, "application/json", b'{"error":"not found"}')
        return self._send(200, "application/json", json.dumps(obj).encode("utf-8"))

    def _sse(self, produce):
        """Server-sent events: push the state immediately and on every change."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b"retry: 2000\n\n")
        self.wfile.flush()
        seen = None
        while True:
            ver = OVERLAY_HUB.wait_change(seen if seen is not None else -1, 15)
            if ver != seen:
                seen = ver
                self.wfile.write(b"data: " + json.dumps(produce()).encode("utf-8") + b"\n\n")
            else:
                self.wfile.write(b": keep-alive\n\n")
            self.wfile.flush()

    def _send(self, code: int, ctype: str, body: bytes, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

class _ExclusiveHTTPServer(http.server.ThreadingHTTPServer):
    # http.server enables SO_REUSEADDR, which on Windows lets a second process
    # bind the *same* port. Demand exclusive use instead.
    allow_reuse_address = False
    daemon_threads      = True

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

def app_already_running(port: int) -> bool:
    """True if another instance of this app is serving overlays on `port`."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as r:
            return r.read() == PING_REPLY
    except Exception:
        return False

def start_overlay_server(port: int) -> int | None:
    """Start the overlay server on 127.0.0.1 (tries `port` .. `port`+9)."""
    for p in range(port, port + 10):
        try:
            srv = _ExclusiveHTTPServer(("127.0.0.1", p), _OverlayHandler)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True, name="overlay-server").start()
        OVERLAY_HUB.port = p
        log.info("Overlay server on http://127.0.0.1:%d/", p)
        return p
    log.error("Could not start overlay server on ports %d-%d", port, port + 9)
    return None

# ---------------------------------------------------------------------------
# Update check
# ---------------------------------------------------------------------------
def parse_version(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3])

def check_for_update(timeout: float = 6) -> tuple[str, str] | None:
    """(tag, url) of a newer GitHub release, or None."""
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                     headers={"Accept": "application/vnd.github+json",
                              "User-Agent": f"DnD-Health-Bar/{APP_VERSION}"},
                     timeout=timeout)
    r.raise_for_status()
    d   = r.json()
    tag = d.get("tag_name", "")
    if parse_version(tag) > parse_version(APP_VERSION):
        return tag, d.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"
    return None

# ---------------------------------------------------------------------------
# OBS WebSocket (v5 protocol, built into OBS 28+)
# ---------------------------------------------------------------------------
OBS_DEFAULTS = {"host": "127.0.0.1", "port": 4455, "password": "", "scene": ""}

class OBSError(Exception):
    def __init__(self, msg: str, code=None):
        super().__init__(msg)
        self.code = code

class OBSClient:
    """Minimal synchronous obs-websocket v5 client. Use as a context manager."""

    def __init__(self, host="127.0.0.1", port=4455, password="", timeout=5.0):
        self.host, self.port, self.password, self.timeout = host, int(port), password, timeout
        self._ws  = None
        self._req = 0

    def __enter__(self):
        if not HAS_WEBSOCKET:
            raise OBSError("OBS support needs the 'websocket-client' package.")
        try:
            self._ws = websocket.create_connection(
                f"ws://{self.host}:{self.port}", timeout=self.timeout,
                subprotocols=["obswebsocket.json"])
        except Exception:
            raise OBSError(f"Can't reach OBS at {self.host}:{self.port}.\n\n"
                           "Is OBS running, and is the WebSocket server enabled?\n"
                           "(OBS → Tools → WebSocket Server Settings)")
        try:
            hello = self._recv_op(0)
            ident = {"rpcVersion": 1, "eventSubscriptions": 0}
            auth  = hello.get("authentication")
            if auth:
                if not self.password:
                    raise OBSError("OBS asks for a WebSocket password — enter it in the "
                                   "OBS settings of this app.")
                secret = base64.b64encode(hashlib.sha256(
                    (self.password + auth["salt"]).encode()).digest()).decode()
                ident["authentication"] = base64.b64encode(hashlib.sha256(
                    (secret + auth["challenge"]).encode()).digest()).decode()
            self._send(1, ident)
            try:
                self._recv_op(2)
            except OBSError:
                raise
            except Exception:
                raise OBSError("OBS refused the connection — the WebSocket password is wrong.")
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._ws:
            try: self._ws.close()
            except Exception: pass
            self._ws = None

    def _send(self, op: int, d: dict):
        self._ws.send(json.dumps({"op": op, "d": d}))

    def _recv_op(self, op: int) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("op") == op:
                return msg.get("d", {})
        raise OBSError("OBS did not answer in time.")

    def call(self, request_type: str, data: dict | None = None) -> dict:
        self._req += 1
        rid = str(self._req)
        self._send(6, {"requestType": request_type, "requestId": rid,
                       "requestData": data or {}})
        while True:
            d = self._recv_op(7)
            if d.get("requestId") == rid:
                break
        status = d.get("requestStatus", {})
        if not status.get("result"):
            raise OBSError(f"OBS: {request_type} failed — "
                           f"{status.get('comment') or 'error ' + str(status.get('code'))}",
                           status.get("code"))
        return d.get("responseData") or {}

def obs_settings(cfg: dict) -> dict:
    s = dict(OBS_DEFAULTS)
    s.update(cfg.get("obs") or {})
    return s

def obs_list_scenes(obs: dict) -> list[str]:
    with OBSClient(obs["host"], obs["port"], obs["password"]) as c:
        return [s["sceneName"] for s in reversed(c.call("GetSceneList").get("scenes", []))]

def obs_source_name(char_name: str) -> str:
    return f"HP Overlay - {char_name}"

def obs_party_source_name(game_name: str) -> str:
    return f"HP Party - {game_name}"

def obs_add_overlays(obs: dict, items: list[dict]) -> tuple[str, int, int]:
    """Create or update one browser source per item in the target scene.
    items: [{"source", "url", "width", "height", "slot"}]. Newly created
    sources are placed side by side (by slot). Returns (scene, created, updated)."""
    with OBSClient(obs["host"], obs["port"], obs["password"]) as c:
        scene = obs.get("scene") or ""
        if not scene:
            cur   = c.call("GetCurrentProgramScene")
            scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        existing = {i["inputName"]: i.get("inputKind")
                    for i in c.call("GetInputList").get("inputs", [])}
        created = updated = 0
        for it in items:
            name     = it["source"]
            settings = {"url": it["url"], "width": it["width"], "height": it["height"],
                        "shutdown": False, "restart_when_active": False}
            new_item = None
            if name in existing:
                if existing[name] != "browser_source":
                    raise OBSError(f"OBS already has a non-browser source named '{name}'. "
                                   "Rename or delete it and try again.")
                c.call("SetInputSettings", {"inputName": name, "inputSettings": settings,
                                            "overlay": True})
                try:
                    c.call("GetSceneItemId", {"sceneName": scene, "sourceName": name})
                except OBSError as e:
                    if e.code != 600:   # 600 = ResourceNotFound → not in this scene yet
                        raise
                    new_item = c.call("CreateSceneItem", {"sceneName": scene,
                                                          "sourceName": name})["sceneItemId"]
                updated += 1
            else:
                new_item = c.call("CreateInput", {
                    "sceneName": scene, "inputName": name, "inputKind": "browser_source",
                    "inputSettings": settings, "sceneItemEnabled": True})["sceneItemId"]
                created += 1
            if new_item is not None:
                try:
                    c.call("SetSceneItemTransform", {
                        "sceneName": scene, "sceneItemId": new_item,
                        "sceneItemTransform": {"positionX": 20 + it.get("slot", 0) * 300,
                                               "positionY": 20}})
                except OBSError:
                    pass
        return scene, created, updated

def character_obs_item(ch: dict, slot: int = 0) -> dict:
    return {"source": obs_source_name(ch.get("name") or ch["character_id"]),
            "url": OVERLAY_HUB.url_for(ch["character_id"]), "width": OVL_W,
            "height": CARD_H_NUM if ch.get("show_hp_numbers") else CARD_H, "slot": slot}

def party_obs_item(game: dict) -> dict:
    chars = game.get("characters", [])
    n     = max(1, len(chars))
    return {"source": obs_party_source_name(game.get("name", "Party")),
            "url": OVERLAY_HUB.party_url(game["id"]),
            "width": n * OVL_W + (n - 1) * PARTY_GAP,
            "height": CARD_H_NUM if any(c.get("show_hp_numbers") for c in chars) else CARD_H,
            "slot": 0}

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

def open_path(path: str):
    """Open a folder or file with the system's default program."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                      # noqa: S606
        else:
            webbrowser.open("file://" + urllib.parse.quote(os.path.abspath(path)))
    except Exception as e:
        log.warning("Could not open %s: %s", path, e)

# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
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
                    highlightbackground=MGR_BORDER3, highlightcolor="#5a8090",
                    font=F_SMALL)

def field_label(parent, text, pady=(6, 2)):
    tk.Label(parent, text=text, bg=DLG_BG, fg=DLG_LABEL_FG, font=F_LABEL).pack(anchor="w", pady=pady)

def dialog_frame(dlg: tk.Toplevel, title: str) -> tk.Frame:
    """Common dialog chrome: header + body frame. Enter = OK, Esc = cancel."""
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

def dialog_footer(dlg, on_save, extra=None):
    mk_sep(dlg, MGR_BORDER)
    foot = tk.Frame(dlg, bg=MGR_HEADER)
    foot.pack(fill="x", padx=14, pady=8)
    for text, cmd in (extra or []):
        styled_button(foot, text, BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD, cmd).pack(
            side="left", ipady=4, ipadx=8, padx=(0, 4))
    styled_button(foot, "Cancel", BTN_CANCEL_BG, BTN_CANCEL_FG, BTN_CANCEL_BD,
                  dlg.destroy).pack(side="right", padx=(4,0), ipady=4, ipadx=8)
    styled_button(foot, "Save", BTN_SAVE_BG, BTN_SAVE_FG, BTN_SAVE_BD,
                  on_save, font=F_MED).pack(side="right", ipady=4, ipadx=12)
    dlg.bind("<Return>", lambda _e: on_save())

class Tooltip:
    """Hover help. `text` may be a string or a callable returning one."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = None
        self._tip   = None
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
            tk.Label(tw, text=text, bg="#0b1218", fg=T_PRIMARY, font=F_TINY,
                     justify="left", wraplength=300, padx=8, pady=4,
                     highlightthickness=1, highlightbackground=MGR_BORDER3).pack()
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

def draw_pill(c: tk.Canvas, x0: float, x1: float, h: int, color: str):
    """Horizontal bar segment with rounded ends from x0 to x1."""
    r = h // 2
    if x1 - x0 <= 0:
        return
    if x1 - x0 > r * 2:
        c.create_arc(x0, 0, x0 + r*2, h, start=90, extent=180, fill=color, outline="")
        c.create_rectangle(x0 + r, 0, x1 - r, h, fill=color, outline="")
        c.create_arc(x1 - r*2, 0, x1, h, start=270, extent=180, fill=color, outline="")
    else:
        c.create_arc(x0, 0, x0 + r*2, h, start=90, extent=180, fill=color, outline="")
        c.create_rectangle(x0 + r, 0, x1, h, fill=color, outline="")

# ---------------------------------------------------------------------------
# HP overlay window (desktop)
# ---------------------------------------------------------------------------
def backoff_delay(errors: int, base: int = 5, cap: int = 120) -> int:
    """5, 10, 20, 40, 80, 120, 120 … seconds."""
    return min(cap, base * 2 ** (max(1, min(errors, 7)) - 1))

class CharacterWindow:
    def __init__(self, master, char: dict, on_closed=None, on_hp_update=None,
                 status_cb=None, on_char_changed=None):
        self.char            = char
        self.on_closed       = on_closed
        self.on_hp_update    = on_hp_update
        self.on_char_changed = on_char_changed
        self._stop           = threading.Event()
        self._photo          = None
        self._last_state     = None
        self._avatar_checked = False
        self._status_cb      = status_cb   # set before the worker thread starts

        self.win = tk.Toplevel(master)
        self.win.title(char.get("name","HP"))
        self.win.configure(bg=OVL_BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", bool(char.get("always_on_top", False)))
        self.win.attributes("-alpha", max(0.2, min(1.0, float(char.get("opacity", 1.0)))))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        pos = char.get("window_pos")       # restore last position if still on screen
        if (isinstance(pos, list) and len(pos) == 2
                and all(isinstance(v, int) for v in pos)
                and position_on_screen(self.win, *pos)):
            self.win.geometry(f"+{pos[0]}+{pos[1]}")

        self._build_ui()
        self._load_portrait(resolve_portrait_path(self.char, 1.0))
        self._apply_hp_visibility()
        threading.Thread(target=self._run_loop, daemon=True,
                         name=f"poll-{char.get('character_id')}").start()

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
        self._draw_bar({"pct": 1.0, "cur": 1, "mx": 1, "temp": 0})

    def _apply_hp_visibility(self):
        if bool(self.char.get("show_hp_numbers", False)):
            self.hp_label.pack(anchor="w", pady=(6,0))
        else:
            self.hp_label.pack_forget()
        self.win.update_idletasks()
        self.win.geometry(f"{OVL_W}x{self.win.winfo_reqheight()}")

    def refresh_visibility(self):
        self.win.after(0, self._apply_hp_visibility)

    def reload_portrait(self, pct=None):
        self._last_state = None
        self._update_portrait_for(pct if pct is not None else 1.0)

    def _update_portrait_for(self, pct):
        state = hp_state(pct)
        if state == self._last_state: return
        self._last_state = state
        self._load_portrait(resolve_portrait_path(self.char, pct))

    def _load_portrait(self, path: str):
        size = OVL_W
        try:
            img = fit_image(Image.open(path), size, OVL_BG) if path else Image.new("RGBA", (size, size), OVL_BG)
        except Exception as e:
            log.warning("Could not load portrait %s: %s", path, e)
            img = Image.new("RGBA", (size, size), OVL_BG)
        self._photo = ImageTk.PhotoImage(round_image(img, CORNER_R))
        self.portrait_canvas.itemconfig(self._img_id, image=self._photo)

    def _draw_bar(self, info: dict):
        c = self.bar_canvas; c.delete("all")
        w, h = OVL_W - BAR_PAD*2, BAR_H
        pct = info.get("pct")
        draw_pill(c, 0, w, h, OVL_BAR_BG)
        if pct is None:
            for x in range(h//2, w - h//2, 12):
                c.create_rectangle(x, 4, x+6, h-4, fill="#2a3a44", outline="")
            return
        cur, mx, temp = info["cur"], info["mx"], info.get("temp", 0)
        total = max(mx, cur + temp) or 1
        if temp:
            draw_pill(c, 0, w * (cur + temp) / total, h, HP_TEMP)
        draw_pill(c, 0, int(w * cur / total), h, hp_bar_color(pct))

    def _label_text(self, info: dict) -> str:
        if info.get("pct") is None:
            return "HP not configured"
        t = hp_text(info, "  /  ")
        if info["cur"] == 0:
            ds = info.get("death_saves") or {}
            t += "   Stable" if ds.get("stable") else \
                 f"   ✓{ds.get('success', 0)} ✗{ds.get('fail', 0)}"
        return t

    def _update_ui(self, info: dict):
        """Called from the worker thread — marshals onto the Tk main thread."""
        def _do():
            if self._stop.is_set(): return
            self._draw_bar(info)
            self._update_portrait_for(info["pct"])
            self.hp_label.config(text=self._label_text(info))
            if self.on_hp_update:
                self.on_hp_update(self.char["character_id"], info)
        run_on_ui(_do)

    def _set_status(self, msg: str, kind: str = "busy"):
        if self._status_cb:
            self._status_cb(self.char["character_id"], msg, kind)

    def _set_error(self, msg: str):
        """Persistent error: status bar + on the HP window."""
        self._set_status(f"⚠ {msg}", "error")
        def _do():
            if self._stop.is_set(): return
            self._draw_bar({"pct": None})
            self.hp_label.config(text=f"⚠ {msg}")
        run_on_ui(_do)

    def _maybe_fetch_avatar(self, data: dict):
        """No portraits set? Use the character's D&D Beyond avatar."""
        if self._avatar_checked:
            return
        self._avatar_checked = True
        url = data.get("avatar_url")
        if not url or has_custom_portrait(self.char):
            return
        cur = self.char.get("avatar")
        if cur and os.path.isfile(portrait_abspath(cur)):
            return
        try:
            rel = download_avatar(url, self.char)
        except Exception as e:
            log.warning("Avatar download failed for %s: %s", self.char.get("name"), e)
            return
        if rel:
            def _do():
                self.char["avatar"] = rel
                if not self._stop.is_set():
                    self.reload_portrait()
                if self.on_char_changed:
                    self.on_char_changed(self.char)
            run_on_ui(_do)

    def _run_loop(self):
        cid        = self.char["character_id"]
        session    = None
        errors     = 0
        auth_fails = 0
        while not self._stop.is_set():
            delay = 0
            try:
                if session is None:
                    self._set_status("Connecting…")
                    session = make_session(cid)
                self._set_status("Fetching HP…")
                data = get_character(session, cid)
                self._update_ui(hp_details(data))
                self._maybe_fetch_avatar(data)
                errors = auth_fails = 0
                while not self._stop.is_set():
                    self._set_status(f"Live · checking every {poll_interval()}s", "ok")
                    if self._stop.wait(poll_interval()):
                        break
                    self._update_ui(hp_details(get_character(session, cid)))
            except requests.exceptions.HTTPError as e:
                # NB: a Response is falsy for 4xx/5xx, so test against None
                resp = e.response
                code = resp.status_code if resp is not None else 0
                session = None
                if code in (401, 403):
                    auth_fails += 1
                    if auth_fails == 1:          # session cookie expired — renew once
                        log.info("[%s] session expired (%s), refreshing", cid, code)
                        self._set_status("Refreshing session…")
                        delay = 2
                    else:
                        self._set_error("Character is private — make it public on D&D Beyond")
                        delay = backoff_delay(auth_fails, base=30, cap=300)
                elif code == 404:
                    self._set_error("Character not found — check the ID")
                    delay = 60
                elif code == 429:
                    errors += 1
                    try:
                        retry_after = int(resp.headers.get("Retry-After", "0"))
                    except (ValueError, AttributeError):
                        retry_after = 0
                    delay = max(retry_after, backoff_delay(errors, base=30, cap=300))
                    log.warning("[%s] rate limited, waiting %ss", cid, delay)
                    self._set_status(f"D&D Beyond asks us to slow down — retrying in {delay}s", "error")
                else:
                    errors += 1
                    delay = backoff_delay(errors)
                    log.warning("[%s] HTTP %s, retry in %ss", cid, code, delay)
                    if errors >= 3:
                        self._set_error(f"Connection problem (HTTP {code}) — retrying in {delay}s")
                    else:
                        self._set_status(f"Error — retrying in {delay}s", "error")
            except Exception as e:
                errors += 1
                session = None
                delay = backoff_delay(errors)
                log.warning("[%s] %s: %s — retry in %ss", cid, type(e).__name__, e, delay)
                if errors >= 3:
                    self._set_error(f"No connection — retrying in {delay}s")
                else:
                    self._set_status(f"Error — retrying in {delay}s", "error")
            if delay:
                self._stop.wait(delay)

    def close(self):
        if self._stop.is_set(): return
        self._stop.set()
        try:                               # remember the window position
            m = re.search(r"\+(-?\d+)\+(-?\d+)$", self.win.geometry())
            if m:
                self.char["window_pos"] = [int(m.group(1)), int(m.group(2))]
        except tk.TclError:
            pass
        try: self.win.destroy()
        except tk.TclError: pass
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

        field_label(body, "CHARACTER ID OR URL")
        tk.Label(body, text="Paste the D&D Beyond character URL or just the number. "
                            "The character sheet must be public.",
                 bg=DLG_BG, fg=T_MUTED, font=F_TINY, wraplength=440, justify="left"
                 ).pack(anchor="w", pady=(0,2))
        self._vars["character_id"] = tk.StringVar(value=ch.get("character_id",""))
        id_entry = styled_entry(body, self._vars["character_id"], width=50)
        id_entry.pack(fill="x", ipady=4, pady=(0,2))
        self._vars["character_id"].trace_add("write", lambda *_: self._on_id_changed())
        self._test_label = tk.Label(body, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY,
                                    wraplength=440, justify="left")
        self._test_label.pack(anchor="w", pady=(2,0))
        self._test_after_id = None
        self._test_seq      = 0

        field_label(body, "NAME")
        self._vars["name"] = tk.StringVar(value=ch.get("name",""))
        styled_entry(body, self._vars["name"], width=50).pack(fill="x", ipady=4, pady=(0,2))

        mk_sep(body, MGR_BORDER, 0)
        field_label(body, "PORTRAITS BY HEALTH STATE", pady=(10, 2))
        tk.Label(body, text="Optional. Empty states use the nearest state that has an image; "
                            "with none at all, the D&D Beyond avatar is used. Square images "
                            "look best. Images are copied into the app's portraits folder.",
                 bg=DLG_BG, fg=T_MUTED, font=F_TINY, wraplength=440, justify="left"
                 ).pack(anchor="w", pady=(0,6))

        self._portrait_vars = {}
        grid = tk.Frame(body, bg=DLG_BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="c")
        grid.columnconfigure(1, weight=1, uniform="c")
        for idx, (key, state_name, pct_label, col) in enumerate(self._STATES):
            r, c = divmod(idx, 2)
            cell = tk.Frame(grid, bg=MGR_ROW, highlightthickness=1, highlightbackground=MGR_BORDER2)
            cell.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            inner = tk.Frame(cell, bg=MGR_ROW)
            inner.pack(fill="x", padx=6, pady=6)
            prev = tk.Canvas(inner, width=self.PREVIEW, height=self.PREVIEW, bg=MGR_ROW,
                             highlightthickness=0, cursor="hand2")
            prev.pack(side="left", padx=(0,6))
            rcol = tk.Frame(inner, bg=MGR_ROW)
            rcol.pack(side="left", fill="x", expand=True)
            hrow = tk.Frame(rcol, bg=MGR_ROW)
            hrow.pack(fill="x")
            tk.Label(hrow, text=state_name, bg=MGR_ROW, fg=col,
                     font=("Segoe UI",9,"bold")).pack(side="left")
            tk.Label(hrow, text=pct_label, bg=MGR_ROW, fg=T_DIM, font=F_TINY).pack(side="right")
            var = tk.StringVar(value=ch.get(key,""))
            self._portrait_vars[key] = var
            name_lbl = tk.Label(rcol, text="", bg=MGR_ROW, fg=T_DIM, font=F_TINY, anchor="w")
            name_lbl.pack(fill="x")
            brow = tk.Frame(rcol, bg=MGR_ROW)
            brow.pack(fill="x", pady=(2,0))
            for text, cmd, tip in [
                ("Browse…", lambda v=var: self._browse(v), "Choose an image"),
                ("All",     lambda v=var: self._use_for_all(v), "Use this image for every state"),
                ("✕",       lambda v=var: v.set(""), "Remove this image"),
            ]:
                b = styled_button(brow, text, BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD, cmd, font=F_TINY)
                b.pack(side="left", padx=(0,3), ipadx=3)
                Tooltip(b, tip)
            prev.bind("<Button-1>", lambda _e, v=var: self._browse(v))
            Tooltip(prev, lambda v=var: portrait_abspath(v.get()) or "Click to choose an image")
            var.trace_add("write", lambda *_a, v=var, p=prev, l=name_lbl: self._draw_preview(v, p, l))
            self._draw_preview(var, prev, name_lbl)

        mk_sep(body, MGR_BORDER, 0)
        opt_row = tk.Frame(body, bg=DLG_BG)
        opt_row.pack(fill="x", pady=(10,2))
        tk.Label(opt_row, text="Desktop window always on top", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._on_top_var = tk.BooleanVar(value=bool(ch.get("always_on_top",False)))
        ToggleSwitch(opt_row, self._on_top_var, bg=DLG_BG).pack(side="right")

        opa_row = tk.Frame(body, bg=DLG_BG)
        opa_row.pack(fill="x", pady=(8,2))
        tk.Label(opa_row, text="Desktop window opacity", bg=DLG_BG, fg=T_SECONDARY,
                 font=F_SMALL).pack(side="left")
        self._opacity_label = tk.Label(opa_row, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY)
        self._opacity_label.pack(side="right")
        self._opacity_var = tk.DoubleVar(value=float(ch.get("opacity", 1.0)))
        def _on_opacity(val):
            self._opacity_label.config(text=f"{int(float(val)*100)} %")
        _on_opacity(self._opacity_var.get())
        tk.Scale(body, variable=self._opacity_var, from_=0.2, to=1.0, resolution=0.05,
                 orient="horizontal", command=_on_opacity, showvalue=False,
                 bg="#5a8090", troughcolor=DLG_ENTRY_BG, width=12, sliderlength=22,
                 highlightthickness=0, bd=0, sliderrelief="flat", cursor="hand2",
                 activebackground=BTN_SAVE_FG).pack(fill="x", pady=(4,0))

        dialog_footer(self, self._submit)
        id_entry.focus_set()
        if ch.get("character_id"):
            self.after(100, self._run_test)

    def _draw_preview(self, var, canvas, label):
        path = portrait_abspath(var.get().strip())
        ok   = bool(path) and os.path.isfile(path)
        canvas.delete("all")
        photo = thumb_photo(path if ok else "", self.PREVIEW, DLG_ENTRY_BG, 6)
        canvas._photo = photo
        canvas.create_image(self.PREVIEW//2, self.PREVIEW//2, image=photo)
        if not var.get().strip():
            canvas.create_text(self.PREVIEW//2, self.PREVIEW//2, text="+", fill=T_MUTED,
                               font=("Segoe UI", 16))
            label.config(text="no image", fg=T_MUTED)
        elif not ok:
            label.config(text="⚠ file not found", fg=HP_INJURED)
        else:
            label.config(text=os.path.basename(path)[:22], fg=T_DIM)

    def _use_for_all(self, src_var):
        v = src_var.get().strip()
        for var in self._portrait_vars.values():
            var.set(v)

    def _extract_id(self) -> str:
        raw = self._vars["character_id"].get().strip()
        m   = re.search(r"dndbeyond\.com/(?:profile/[^/]+/)?characters/(\d+)", raw)
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
            self._test_label.config(text="⚠ Enter a valid character ID or URL.", fg=HP_INJURED)
            return
        self._test_label.config(text="Checking D&D Beyond…", fg=T_DIM)
        self._test_seq += 1
        seq = self._test_seq

        def _work():
            try:
                data = get_character(make_session(cid), cid)
                return ("ok", hp_details(data), data.get("api_name", ""), data.get("avatar_url", ""))
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                if code == 404:        return ("not_found", None, None, None)
                if code in (401, 403): return ("private", None, None, None)
                return ("http_error", code, None, None)
            except Exception as e:
                return ("error", str(e), None, None)

        def _done(result):
            if seq != self._test_seq or not self.winfo_exists():
                return
            kind = result[0]
            if kind == "ok":
                info, api_name, self.avatar_url = result[1], result[2], result[3] or ""
                self._test_label.config(text=f"✓ Found {api_name or 'character'} — HP {hp_text(info)}",
                                        fg=HP_FULL)
                if not self._vars["name"].get().strip() and api_name:
                    self._vars["name"].set(api_name)
            elif kind == "not_found":
                self._test_label.config(text="✗ Character not found — check the ID.", fg=HP_CRIT)
            elif kind == "private":
                self._test_label.config(
                    text="✗ Character is private — on D&D Beyond open the character's "
                         "Home → Privacy and set it to Public.", fg=HP_CRIT)
            elif kind == "http_error":
                self._test_label.config(text=f"✗ D&D Beyond error ({result[1]}) — try again later.",
                                        fg=HP_CRIT)
            else:
                self._test_label.config(text="✗ Could not reach D&D Beyond — check your internet.",
                                        fg=HP_CRIT)

        def _thread():
            result = _work()
            run_on_ui(lambda: _done(result))
        threading.Thread(target=_thread, daemon=True).start()

    def _browse(self, var):
        start = portrait_abspath(var.get().strip())
        path = filedialog.askopenfilename(
            parent=self, initialdir=os.path.dirname(start) if start else _BASE_DIR,
            filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.gif *.bmp"),("All files","*.*")])
        if path:
            var.set(path)

    def _submit(self):
        self._extract_id()
        vals = {k: v.get().strip() for k, v in self._vars.items()}
        if not vals["character_id"]:
            messagebox.showwarning("Required", "Enter the character ID or URL.", parent=self)
            return
        if not vals["name"]:
            messagebox.showwarning("Required", "Enter a name for the character.", parent=self)
            return
        for key, var in self._portrait_vars.items():
            p = var.get().strip()
            if p:
                try:
                    p = make_portable(p, vals, key)
                except OSError as e:
                    messagebox.showwarning("Portrait",
                        f"Could not copy the image into the portraits folder:\n{e}\n\n"
                        "The original location is used instead.", parent=self)
            vals[key] = p
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
        self.transient(parent)
        self.grab_set()
        self.result = None
        body = dialog_frame(self, "Edit game" if game else "Add game")
        field_label(body, "GAME NAME")
        self._name_var = tk.StringVar(value=game.get("name",""))   # NB: not self._name (Tk uses it)
        e = styled_entry(body, self._name_var, width=36)
        e.pack(fill="x", ipady=4, pady=(0,2))
        dialog_footer(self, self._submit)
        e.focus_set()

    def _submit(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Required","Game name is required.",parent=self)
            return
        self.result = {"name": name}
        self.destroy()

# ---------------------------------------------------------------------------
# OBS connection dialog
# ---------------------------------------------------------------------------
class OBSDialog(tk.Toplevel):
    CURRENT = "(current scene)"

    def __init__(self, parent, obs: dict, game_name: str | None = None):
        super().__init__(parent)
        self.title("OBS connection")
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.action = None        # None | "each" | "party"

        body = dialog_frame(self, "OBS connection")
        tk.Label(body, justify="left", wraplength=400, bg=DLG_BG, fg=T_DIM, font=F_TINY,
                 text="In OBS open Tools → WebSocket Server Settings, tick "
                      "\"Enable WebSocket server\", then click \"Show Connect Info\" "
                      "and copy the port and password here.").pack(anchor="w", pady=(0,4))
        self._vars = {}
        for key, label, show in [("host","HOST",""), ("port","PORT",""), ("password","PASSWORD","*")]:
            field_label(body, label)
            var = tk.StringVar(value=str(obs.get(key, "")))
            self._vars[key] = var
            styled_entry(body, var, width=44, show=show).pack(fill="x", ipady=4, pady=(0,2))

        field_label(body, "ADD OVERLAYS TO SCENE", pady=(8,2))
        scene_row = tk.Frame(body, bg=DLG_BG)
        scene_row.pack(fill="x")
        self._scene_var = tk.StringVar(value=obs.get("scene") or self.CURRENT)
        self._scene_menu = tk.OptionMenu(scene_row, self._scene_var, self._scene_var.get())
        self._scene_menu.config(bg=DLG_ENTRY_BG, fg=T_PRIMARY, activebackground=MGR_BORDER2,
                                activeforeground=T_PRIMARY, relief="flat", bd=0,
                                highlightthickness=1, highlightbackground=MGR_BORDER3,
                                font=F_SMALL, anchor="w")
        self._scene_menu["menu"].config(bg=MGR_PILL, fg=T_PRIMARY, font=F_SMALL)
        self._scene_menu.pack(side="left", fill="x", expand=True, ipady=2, padx=(0,6))
        styled_button(scene_row, "Test & load scenes", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                      self._test).pack(side="left", ipady=3, ipadx=6)
        self._status = tk.Label(body, text="", bg=DLG_BG, fg=T_DIM, font=F_TINY,
                                wraplength=400, justify="left")
        self._status.pack(anchor="w", pady=(6,0))

        extra = []
        if game_name:
            tk.Label(body, justify="left", wraplength=400, bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                     text=f"For “{game_name}” you can add one source per character (move them "
                          "around freely) or a single party source with everyone side by side."
                     ).pack(anchor="w", pady=(8,0))
            extra = [("Save & add each character", lambda: self._finish("each")),
                     ("Save & add party source",   lambda: self._finish("party"))]
        dialog_footer(self, lambda: self._finish(None), extra)

    def _values(self) -> dict | None:
        try:
            port = int(self._vars["port"].get().strip())
        except ValueError:
            messagebox.showwarning("OBS", "Port must be a number (usually 4455).", parent=self)
            return None
        scene = self._scene_var.get()
        return {"host": self._vars["host"].get().strip() or "127.0.0.1", "port": port,
                "password": self._vars["password"].get(),
                "scene": "" if scene == self.CURRENT else scene}

    def _test(self):
        obs = self._values()
        if obs is None: return
        self._status.config(text="Connecting…", fg=T_DIM)
        def work():
            try:
                scenes = obs_list_scenes(obs)
                run_on_ui(lambda: self._test_done(scenes, None))
            except Exception as e:
                msg = str(e)
                run_on_ui(lambda: self._test_done(None, msg))
        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, scenes, err):
        if not self.winfo_exists(): return
        if err:
            self._status.config(text=f"✗ {err}", fg=HP_CRIT)
            return
        menu = self._scene_menu["menu"]
        menu.delete(0, "end")
        for name in [self.CURRENT] + scenes:
            menu.add_command(label=name, command=lambda v=name: self._scene_var.set(v))
        if self._scene_var.get() not in [self.CURRENT] + scenes:
            self._scene_var.set(self.CURRENT)
        self._status.config(text=f"✓ Connected — {len(scenes)} scenes found.", fg=HP_FULL)

    def _finish(self, action):
        obs = self._values()
        if obs is None: return
        self.result, self.action = obs, action
        self.destroy()

# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.grab_set()
        self.result = None
        body = dialog_frame(self, "Settings")

        field_label(body, "CHECK D&D BEYOND EVERY … SECONDS")
        row = tk.Frame(body, bg=DLG_BG)
        row.pack(fill="x")
        self._poll = tk.StringVar(value=str(cfg.get("poll_interval", DEFAULT_POLL_INTERVAL)))
        tk.Spinbox(row, from_=MIN_POLL, to=MAX_POLL, textvariable=self._poll, width=5,
                   bg=DLG_ENTRY_BG, fg=T_PRIMARY, buttonbackground=MGR_BORDER2,
                   insertbackground=T_PRIMARY, relief="flat", bd=0, highlightthickness=1,
                   highlightbackground=MGR_BORDER3, font=F_SMALL).pack(side="left", ipady=3)
        tk.Label(row, text=f"  {MIN_POLL}–{MAX_POLL}. Lower = faster updates on stream, but more "
                           "requests to D&D Beyond.", bg=DLG_BG, fg=T_MUTED, font=F_TINY,
                 wraplength=330, justify="left").pack(side="left")

        def toggle_row(text, value, hint="", enabled=True):
            r = tk.Frame(body, bg=DLG_BG)
            r.pack(fill="x", pady=(10,0))
            tk.Label(r, text=text, bg=DLG_BG, fg=T_SECONDARY if enabled else T_MUTED,
                     font=F_SMALL).pack(side="left")
            var = tk.BooleanVar(value=value)
            if enabled:
                ToggleSwitch(r, var, bg=DLG_BG).pack(side="right")
            if hint:
                tk.Label(body, text=hint, bg=DLG_BG, fg=T_MUTED, font=F_TINY, wraplength=420,
                         justify="left").pack(anchor="w")
            return var

        self._updates = toggle_row("Check for new versions at startup",
                                   bool(cfg.get("check_updates", True)))
        self._tray    = toggle_row("✕ hides the app in the system tray",
                                   bool(cfg.get("close_to_tray", False)),
                                   "Off: ✕ quits the app. On: it keeps running in the tray "
                                   "(right-click the tray icon to quit)."
                                   if HAS_TRAY else "Not available in this build.", HAS_TRAY)

        srv = cfg.get("overlay_server") or {}
        field_label(body, "OVERLAY SERVER PORT", pady=(12,2))
        prow = tk.Frame(body, bg=DLG_BG)
        prow.pack(fill="x")
        self._port = tk.StringVar(value=str(srv.get("port", DEFAULT_OVERLAY_PORT)))
        styled_entry(prow, self._port, width=8).pack(side="left", ipady=3)
        tk.Label(prow, text="  takes effect after restarting the app (OBS sources must use the "
                            "new port — use OBS ⚙ to update them).", bg=DLG_BG, fg=T_MUTED,
                 font=F_TINY, wraplength=330, justify="left").pack(side="left")

        mk_sep(body, MGR_BORDER, 0)
        frow = tk.Frame(body, bg=DLG_BG)
        frow.pack(fill="x", pady=(10,0))
        for text, path in [("Open data folder", _BASE_DIR), ("Open log file", LOG_FILE)]:
            styled_button(frow, text, BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD,
                          lambda p=path: open_path(p), font=F_TINY).pack(side="left", padx=(0,6), ipadx=6, ipady=2)
        tk.Label(body, text=_BASE_DIR, bg=DLG_BG, fg=T_MUTED, font=F_TINY, wraplength=420,
                 justify="left").pack(anchor="w", pady=(4,0))
        dialog_footer(self, self._submit)

    def _submit(self):
        try:
            poll = max(MIN_POLL, min(MAX_POLL, int(self._poll.get())))
            port = int(self._port.get())
            if not 1024 <= port <= 65535: raise ValueError
        except ValueError:
            messagebox.showwarning("Settings", f"Check interval must be {MIN_POLL}–{MAX_POLL} and "
                                   "the port 1024–65535.", parent=self)
            return
        self.result = {"poll_interval": poll, "check_updates": self._updates.get(),
                       "close_to_tray": self._tray.get(), "port": port}
        self.destroy()

# ---------------------------------------------------------------------------
# Manager window
# ---------------------------------------------------------------------------
class ManagerWindow:
    def __init__(self, root: tk.Tk, cfg: dict):
        global SAVE_ERROR_HANDLER
        self.root     = root
        self.cfg      = cfg
        self._windows:    dict[str, CharacterWindow] = {}
        self._hp_data:    dict[str, dict]            = {}
        self._status:     dict[str, tuple]           = {}   # cid → (msg, kind)
        self._hp_toggles: dict[str, tk.BooleanVar]   = {}
        self._row_widgets: dict[str, dict]           = {}
        self._save_warned = False
        prefs = cfg.setdefault("sort", {})
        self._sort_mode   = prefs.get("mode", "alpha_asc")
        self._live_on_top = prefs.get("live_on_top", True)

        root.title(f"D&D Health Bar  v{APP_VERSION}  —  Public Edition")
        root.configure(bg=MGR_BG)
        root.resizable(True, True)
        root.minsize(460, 320)
        root.protocol("WM_DELETE_WINDOW", self._on_quit)
        root.report_callback_exception = lambda *a: log.error("UI error", exc_info=a)
        SAVE_ERROR_HANDLER = lambda msg: run_on_ui(lambda: self._on_save_error(msg))

        self._build_ui()
        self._update_sort_btn_styles()
        self._refresh_games()

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=MGR_HEADER)
        hdr.pack(fill="x")
        logo = tk.Label(hdr, text="⚔", bg="#1e2c38", fg="#8ab0c0",
                        font=("Segoe UI",16), width=2, relief="flat",
                        highlightthickness=1, highlightbackground=MGR_BORDER3)
        logo.pack(side="left", padx=(12,8), pady=10)
        tcol = tk.Frame(hdr, bg=MGR_HEADER)
        tcol.pack(side="left")
        tk.Label(tcol, text="D&D Health Bar", bg=MGR_HEADER, fg=T_PRIMARY,
                 font=F_TITLE).pack(anchor="w")
        tk.Label(tcol, text=f"v{APP_VERSION}  ·  public characters only",
                 bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(anchor="w")

        links = tk.Frame(hdr, bg=MGR_HEADER)
        links.pack(side="right", padx=10)
        for text, cmd, tip in [
            ("⚙", self._open_settings, "Settings: check interval, tray, updates, data folder"),
            ("OBS", lambda: self._open_obs_dialog(), "Connect to OBS and add overlays automatically"),
            ("URLs ↗", self._open_overlay_index, "Show all overlay URLs in the browser"),
        ]:
            b = styled_button(links, text, MGR_HEADER, BTN_OPEN_FG, MGR_BORDER3, cmd, font=F_SMALL)
            b.pack(side="left", padx=(4,0), ipadx=6, ipady=2)
            Tooltip(b, tip)
        self._hdr_sep = mk_sep(self.root, MGR_BORDER)

        # Update banner (packed only when a newer version exists)
        self._banner = tk.Frame(self.root, bg="#173a2a")

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
        Tooltip(self._game_btn, "Switch game")
        for txt,col,bdc,cmd,tip in [
            ("✎",BTN_EDIT_BG,BTN_EDIT_BD,self._edit_game,"Rename this game"),
            ("＋",BTN_EDIT_BG,BTN_EDIT_BD,self._add_game,"Add a game"),
            ("✕",DANGER_BG,  DANGER_BD,  self._delete_game,"Delete this game"),
        ]:
            b = styled_button(gbar,txt,col,BTN_EDIT_FG if col!=DANGER_BG else DANGER_FG,
                              bdc,cmd,font=F_MED,width=3)
            b.pack(side="left",padx=(4,0),ipady=5)
            Tooltip(b, tip)
        mk_sep(self.root, MGR_BORDER)

        sbar = tk.Frame(self.root, bg=MGR_HEADER, pady=5)
        sbar.pack(fill="x", padx=10)
        tk.Label(sbar, text="Sort:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY).pack(side="left", padx=(0,4))
        self._sort_btns = {}
        for group, label, tip in [("alpha","A–Z","Sort by name (click again to reverse)"),
                                  ("hp","HP","Sort by current HP (click again to reverse)"),
                                  ("manual","Manual","Your own order — use the arrows")]:
            btn = tk.Button(sbar, text=label, font=F_TINY, cursor="hand2",
                            relief="flat", bd=0, padx=8, pady=2, highlightthickness=1,
                            command=lambda g=group: self._cycle_sort(g))
            btn.pack(side="left", padx=2)
            Tooltip(btn, tip)
            self._sort_btns[group] = btn
        tk.Frame(sbar, bg=MGR_HEADER, width=12).pack(side="left")
        lt = tk.Label(sbar, text="Live on top:", bg=MGR_HEADER, fg=T_DIM, font=F_TINY)
        lt.pack(side="left", padx=(0,4))
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
        bulk_row = tk.Frame(add_frame, bg=MGR_BG)
        bulk_row.pack(fill="x", pady=(0,4))
        self._open_all_btn = styled_button(
            bulk_row, "▶▶  Open all", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
            self._open_all_windows, font=F_SMALL)
        self._open_all_btn.pack(side="left", fill="x", expand=True, ipady=5, padx=(0,4))
        Tooltip(self._open_all_btn, "Go live with every character of this game")
        self._close_all_btn = styled_button(
            bulk_row, "■■  Close all", BTN_CLOSE_BG, BTN_CLOSE_FG, BTN_CLOSE_BD,
            self._close_all_windows, font=F_SMALL)
        self._close_all_btn.pack(side="left", fill="x", expand=True, ipady=5)
        Tooltip(self._close_all_btn, "Stop all characters (overlays fade out)")
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
                                      bg=MGR_HEADER, fg=T_MUTED, font=F_TINY, anchor="w",
                                      justify="left")
        self._status_label.pack(fill="x")
        self._status_bar.bind("<Configure>",
                              lambda e: self._status_label.config(wraplength=max(200, e.width - 10)))

    def flash_status(self, text: str, color=BTN_OPEN_FG, ms: int = 5000):
        self._status_label.config(text=text, fg=color)
        self.root.after(ms, self._update_status_bar)

    # ── Update banner ─────────────────────────────────────────────────────────
    def check_updates_async(self):
        if not self.cfg.get("check_updates", True):
            return
        def work():
            try:
                res = check_for_update()
            except Exception as e:
                log.info("Update check failed: %s", e)
                return
            if res:
                run_on_ui(lambda: self._show_update(*res))
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _show_update(self, tag: str, url: str):
        if self.cfg.get("dismissed_update") == tag:
            return
        for w in self._banner.winfo_children():
            w.destroy()
        tk.Label(self._banner, text=f"⬆  Version {tag.lstrip('v.')} is available",
                 bg="#173a2a", fg=HP_FULL, font=F_MED).pack(side="left", padx=(12,8), pady=6)
        b = styled_button(self._banner, "Download", "#1f4d36", HP_FULL, "#2e6b4c",
                          lambda: webbrowser.open(url), font=F_TINY)
        b.pack(side="left", ipadx=8, ipady=2)
        def dismiss():
            self.cfg["dismissed_update"] = tag
            save_config(self.cfg)
            self._banner.pack_forget()
        x = styled_button(self._banner, "✕", "#173a2a", T_DIM, "#173a2a", dismiss, font=F_TINY)
        x.pack(side="right", padx=8)
        Tooltip(x, "Hide until the next version")
        self._banner.pack(fill="x", after=self._hdr_sep)

    # ── Save errors ───────────────────────────────────────────────────────────
    def _on_save_error(self, msg: str):
        self._status_label.config(text=f"⚠ Settings could not be saved: {msg}", fg=HP_CRIT)
        if not self._save_warned:
            self._save_warned = True
            messagebox.showwarning("D&D Health Bar",
                "Your settings could not be saved.\n\n"
                f"{msg}\n\nIf the folder is synced (e.g. Proton Drive, OneDrive), the sync "
                "client may be holding the file. The app keeps retrying on every change.",
                parent=self.root)

    # ── Games ────────────────────────────────────────────────────────────────
    def _game_menu_popup(self):
        names = [g["name"] for g in self._games()]
        if not names: return
        menu = tk.Menu(self.root, tearoff=0, bg=MGR_PILL, fg=T_PRIMARY,
                       activebackground=MGR_BORDER2, activeforeground=T_PRIMARY,
                       relief="flat", bd=0, font=F_SMALL)
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self._select_game(v))
        menu.tk_popup(self._game_btn.winfo_rootx(),
                      self._game_btn.winfo_rooty() + self._game_btn.winfo_height())

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
        if names and self._game_var.get() not in names:
            self._game_var.set(names[0])
        elif not names:
            self._game_var.set("  No games yet  ")
        self._refresh_chars()

    def _add_game(self):
        dlg = GameDialog(self.root, {})
        self.root.wait_window(dlg)
        if not dlg.result: return
        g = {"id": secrets.token_hex(4), "name": dlg.result["name"], "characters": []}
        self._games().append(g)
        save_config(self.cfg)
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
        if self._sort_mode in ("alpha_asc","alpha_desc"): return "alpha"
        if self._sort_mode in ("hp_asc","hp_desc"):       return "hp"
        if self._sort_mode == "manual":                    return "manual"
        return None

    def _cycle_sort(self, group: str):
        cycle = self._SORT_CYCLES[group]
        if self._sort_group() != group:
            new_mode = cycle[1]
        else:
            cur_idx  = cycle.index(self._sort_mode) if self._sort_mode in cycle else 0
            new_mode = cycle[(cur_idx + 1) % len(cycle)]
        self._sort_mode = new_mode
        self.cfg["sort"]["mode"] = new_mode
        save_config(self.cfg)
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
            btn.config(text=labels[group],
                       bg=BTN_SAVE_BG if active else MGR_ROW,
                       fg=BTN_SAVE_FG if active else T_DIM,
                       highlightbackground=BTN_SAVE_BD if active else MGR_BORDER2)

    def _hp_sort_key(self, c):
        info = self._hp_data.get(c["character_id"])
        pct  = info.get("pct") if info else None
        return pct if pct is not None else None

    def _sorted_characters(self, characters: list) -> list:
        chars     = list(characters)
        live_cids = set(self._windows.keys())
        if self._sort_mode == "alpha_asc":
            chars.sort(key=lambda c: c.get("name","").lower())
        elif self._sort_mode == "alpha_desc":
            chars.sort(key=lambda c: c.get("name","").lower(), reverse=True)
        elif self._sort_mode in ("hp_asc", "hp_desc"):
            known   = [c for c in chars if self._hp_sort_key(c) is not None]
            unknown = [c for c in chars if self._hp_sort_key(c) is None]
            known.sort(key=self._hp_sort_key, reverse=self._sort_mode == "hp_desc")
            chars = known + unknown          # characters without data always last
        if self._live_on_top:
            chars = ([c for c in chars if c["character_id"] in live_cids] +
                     [c for c in chars if c["character_id"] not in live_cids])
        return chars

    def _move_character(self, cid: str, direction: int):
        g = self._current_game()
        if not g: return
        chars        = g["characters"]
        sorted_chars = self._sorted_characters(chars)
        disp_idx     = next((i for i,c in enumerate(sorted_chars) if c["character_id"]==cid), None)
        if disp_idx is None: return
        new_idx = disp_idx + direction
        if new_idx < 0 or new_idx >= len(sorted_chars): return
        other_cid = sorted_chars[new_idx]["character_id"]
        ci = next(i for i,c in enumerate(chars) if c["character_id"]==cid)
        oi = next(i for i,c in enumerate(chars) if c["character_id"]==other_cid)
        chars[ci], chars[oi] = chars[oi], chars[ci]
        save_config(self.cfg)
        self._refresh_chars()

    # ── Character rows ────────────────────────────────────────────────────────
    def _refresh_chars(self):
        """Full rebuild — only when the list structure changes."""
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
        kind = self._status.get(cid, ("", "busy"))[1]
        return {"ok": HP_FULL, "error": HP_CRIT}.get(kind, HP_INJURED)

    def _make_char_row(self, ch, game):
        cid     = ch["character_id"]
        is_open = cid in self._windows
        row = tk.Frame(self._char_frame, bg=MGR_ROW, highlightthickness=1,
                       highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
        row.pack(fill="x", pady=5)
        inner = tk.Frame(row, bg=MGR_ROW)
        inner.pack(fill="x", padx=10, pady=8)

        if self._sort_mode == "manual":
            sorted_chars = self._sorted_characters(game.get("characters", []))
            disp_idx = next((i for i,c in enumerate(sorted_chars) if c["character_id"]==cid), 0)
            arrow_col = tk.Frame(inner, bg=MGR_ROW)
            arrow_col.pack(side="left", padx=(0,4))
            for text, d, disabled in [("↑", -1, disp_idx == 0),
                                      ("↓",  1, disp_idx == len(sorted_chars) - 1)]:
                tk.Button(arrow_col, text=text, font=F_TINY, width=2,
                          bg=MGR_ROW if disabled else BTN_EDIT_BG,
                          fg=MGR_BORDER2 if disabled else BTN_EDIT_FG,
                          relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=MGR_BORDER2,
                          cursor="arrow" if disabled else "hand2",
                          state="disabled" if disabled else "normal",
                          command=lambda c=cid, dd=d: self._move_character(c, dd)
                          ).pack(side="top", pady=(0,1))

        thumb = 38
        cvs = tk.Canvas(inner, width=thumb, height=thumb, bg=MGR_ROW, highlightthickness=0)
        cvs.pack(side="left", padx=(0,8))
        self._draw_thumb(cvs, ch, thumb)

        info = tk.Frame(inner, bg=MGR_ROW)
        info.pack(side="left", fill="x", expand=True)
        name_lbl = tk.Label(info, text=ch.get("name","Unknown"), bg=MGR_ROW,
                            fg=T_PRIMARY, font=F_BOLD, anchor="w")
        name_lbl.pack(anchor="w")
        id_lbl = tk.Label(info, text=cid, bg=MGR_ROW, fg=T_DIM, font=F_TINY, anchor="w")
        id_lbl.pack(anchor="w")

        badge_frame = tk.Frame(inner, bg=MGR_ROW)
        badge_frame.pack(side="left", padx=6)
        hp = self._hp_data.get(cid) if is_open else None
        badge = tk.Label(badge_frame, padx=7, pady=2, highlightthickness=1)
        badge.pack()
        self._style_badge(badge, hp)
        Tooltip(badge, "Current / maximum HP  (+ temporary HP)")

        mini_bar = tk.Canvas(inner, width=56, height=5, bg=MGR_ROW, highlightthickness=0)
        mini_bar.pack(side="left", padx=(0,4))
        self._draw_mini_bar(mini_bar, hp)

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
        tog = ToggleSwitch(tog_col, hp_var, command=_on_hp_toggle, bg=MGR_ROW)
        tog.pack()
        Tooltip(tog, "Show HP numbers on the overlay")

        dot = tk.Canvas(inner, width=10, height=10, bg=MGR_ROW, highlightthickness=0)
        dot.pack(side="left", padx=(0,6))
        dot_oval = dot.create_oval(1,1,9,9, fill=self._status_color(cid), outline="")
        Tooltip(dot, lambda c=cid: self._status.get(c, ("Not live — press ▶", ""))[0]
                if c in self._windows else "Not live — press ▶")

        btns = tk.Frame(inner, bg=MGR_ROW)
        btns.pack(side="right")
        open_btn = styled_button(btns, "▶", BTN_OPEN_BG, BTN_OPEN_FG, BTN_OPEN_BD,
                                 lambda c=ch, g=game: self._toggle_window(c, g), width=3)
        open_btn.pack(side="left", padx=(0,3), ipady=4)
        Tooltip(open_btn, lambda c=cid: "Stop: close the overlay (fades out on stream)"
                if c in self._windows else "Go live: open the overlay and show it on stream")
        more = styled_button(btns, "⋯", BTN_EDIT_BG, BTN_EDIT_FG, BTN_EDIT_BD, None, width=3)
        more.config(command=lambda c=ch, g=game, b=more: self._row_menu(
            c, g, b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
        more.pack(side="left", ipady=4)
        Tooltip(more, "More: add to OBS, copy URL, edit, delete")

        self._row_widgets[cid] = {"row": row, "badge": badge, "dot": dot, "dot_oval": dot_oval,
                                  "mini_bar": mini_bar, "open_btn": open_btn, "thumb": cvs}
        self._style_open_btn(open_btn, is_open)

        # Right-click anywhere on the row → menu; double-click name/picture → edit
        def popup(e, c=ch, g=game): self._row_menu(c, g, e.x_root, e.y_root)
        for w in (row, inner, info, name_lbl, id_lbl, cvs, badge_frame):
            w.bind("<Button-3>", popup)
        for w in (cvs, name_lbl, id_lbl):
            w.bind("<Double-Button-1>", lambda _e, c=ch, g=game: self._edit_character(c, g))
            Tooltip(w, "Double-click to edit · right-click for more")

    def _row_menu(self, ch, game, x, y):
        m = tk.Menu(self.root, tearoff=0, bg=MGR_PILL, fg=T_PRIMARY,
                    activebackground=MGR_BORDER2, activeforeground=T_PRIMARY,
                    relief="flat", bd=0, font=F_SMALL)
        m.add_command(label="Add to OBS", command=lambda: self._send_to_obs([ch]))
        m.add_command(label="Copy overlay URL", command=lambda: self._copy_overlay_url(ch))
        m.add_command(label="Preview overlay in browser", command=lambda: self._preview_overlay(ch))
        m.add_separator()
        m.add_command(label="Edit…", command=lambda: self._edit_character(ch, game))
        m.add_command(label="Delete…", foreground=DANGER_FG,
                      command=lambda: self._delete_character(ch, game))
        m.tk_popup(x, y)

    def _style_open_btn(self, btn, is_open):
        if is_open:
            btn.config(text="■", bg=BTN_CLOSE_BG, fg=BTN_CLOSE_FG,
                       activebackground=BTN_CLOSE_BD, highlightbackground=BTN_CLOSE_BD)
        else:
            btn.config(text="▶", bg=BTN_OPEN_BG, fg=BTN_OPEN_FG,
                       activebackground=BTN_OPEN_BD, highlightbackground=BTN_OPEN_BD)

    def _style_badge(self, badge, hp):
        if hp and hp.get("pct") is not None:
            fg, bg, bd = hp_badge_colors(hp["pct"])
            badge.config(text=hp_text(hp), bg=bg, fg=fg, highlightbackground=bd,
                         font=("Consolas",10,"bold"))
        else:
            badge.config(text="—", bg=HPB_DEAD, fg=T_MUTED, font=F_TINY,
                         highlightbackground=HBB_DEAD)

    def _update_row_state(self, cid: str):
        w = self._row_widgets.get(cid)
        if not w: return
        is_open = cid in self._windows
        try:
            w["row"].config(highlightbackground="#2a4a5a" if is_open else MGR_BORDER2)
            self._style_open_btn(w["open_btn"], is_open)
            if not is_open:
                self._style_badge(w["badge"], None)
                self._draw_mini_bar(w["mini_bar"], None)
            w["dot"].itemconfig(w["dot_oval"], fill=self._status_color(cid))
        except tk.TclError:
            pass

    def _draw_mini_bar(self, canvas: tk.Canvas, hp):
        canvas.delete("all")
        w, h = int(canvas["width"]), int(canvas["height"])
        canvas.create_rectangle(0, 0, w, h, fill=MGR_BORDER2, outline="")
        pct = hp.get("pct") if hp else None
        if pct is None:
            for x in range(0, w, 8):
                canvas.create_rectangle(x, 0, x+4, h, fill="#2a3a44", outline="")
            return
        total = max(hp["mx"], hp["cur"] + hp.get("temp", 0)) or 1
        if hp.get("temp"):
            canvas.create_rectangle(0, 0, int(w * (hp["cur"] + hp["temp"]) / total), h,
                                    fill=HP_TEMP, outline="")
        fw = int(w * hp["cur"] / total)
        if fw > 0:
            canvas.create_rectangle(0, 0, fw, h, fill=hp_bar_color(pct), outline="")

    def _draw_thumb(self, canvas, ch, size):
        canvas.delete("all")
        photo = thumb_photo(resolve_portrait_path(ch, 1.0), size, MGR_ROW, 8)
        canvas._photo = photo
        canvas.create_image(size//2, size//2, image=photo, anchor="center")

    # ── Live windows ──────────────────────────────────────────────────────────
    def _toggle_window(self, ch, game):
        cid = ch["character_id"]
        if cid in self._windows:
            self._close_window(cid)
        else:
            self._open_window(ch)
        self._update_row_state(cid)
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)

    def _open_window(self, ch):
        cid = ch["character_id"]
        self._status[cid] = ("Connecting…", "busy")
        self._windows[cid] = CharacterWindow(
            master=self.root, char=ch,
            on_closed=lambda c=cid: self._on_window_closed(c),
            on_hp_update=self._on_hp_update,
            status_cb=self._on_status_update,
            on_char_changed=self._on_char_changed)
        OVERLAY_HUB.set_live(cid, True)

    def _close_window(self, cid):
        if cid in self._windows:
            self._windows[cid].close()       # → _on_window_closed
        self._update_status_bar()

    def _on_window_closed(self, cid):
        OVERLAY_HUB.set_live(cid, False)
        self._windows.pop(cid, None)
        self._hp_data.pop(cid, None)
        self._status.pop(cid, None)
        save_config(self.cfg)                # saves the window position
        self.root.after(0, lambda c=cid: self._update_row_state(c))
        if self._live_on_top:
            self.root.after(10, self._reorder_rows)
        self.root.after(0, self._update_status_bar)

    def _on_hp_update(self, cid, info: dict):
        """Main thread (called from CharacterWindow's UI callback)."""
        self._hp_data[cid] = info
        OVERLAY_HUB.update_hp(cid, info)
        w = self._row_widgets.get(cid)
        if w:
            try:
                self._style_badge(w["badge"], info)
                self._draw_mini_bar(w["mini_bar"], info)
            except tk.TclError:
                pass
        if self._sort_mode in ("hp_asc", "hp_desc") or self._live_on_top:
            self._reorder_rows()

    def _on_char_changed(self, ch):
        """A worker changed the character (e.g. downloaded its avatar)."""
        save_config(self.cfg)
        w = self._row_widgets.get(ch["character_id"])
        if w:
            self._draw_thumb(w["thumb"], ch, 38)

    def _reorder_rows(self):
        g = self._current_game()
        if not g or not g.get("characters"): return
        new_order = [c["character_id"] for c in self._sorted_characters(g["characters"])]
        rows_to_cid = {id(w["row"]): cid for cid, w in self._row_widgets.items()}
        current = [rows_to_cid.get(id(w)) for w in self._char_frame.pack_slaves()]
        if current == new_order:
            return
        for cid in new_order:
            w = self._row_widgets.get(cid)
            if w:
                try:
                    w["row"].pack_forget()
                    w["row"].pack(fill="x", pady=5)   # must match _make_char_row
                except tk.TclError:
                    pass

    def _on_status_update(self, cid, msg, kind):
        """Called from worker threads."""
        def _do():
            if cid not in self._windows: return
            self._status[cid] = (msg, kind)
            w = self._row_widgets.get(cid)
            if w:
                try: w["dot"].itemconfig(w["dot_oval"], fill=self._status_color(cid))
                except tk.TclError: pass
            self._update_status_bar()
        run_on_ui(_do)

    def _update_status_bar(self):
        if not self._windows:
            self._status_label.config(text="No characters live — press ▶ to go live", fg=T_MUTED)
        else:
            errors = [(cid, m) for cid, (m, k) in self._status.items()
                      if k == "error" and cid in self._windows]
            if errors:
                parts = [f"{self._windows[c].char.get('name','?')}: {m}" for c, m in errors]
                self._status_label.config(text="   ·   ".join(parts), fg=HP_INJURED)
            else:
                names = ", ".join(w.char.get("name", "?") for w in self._windows.values())
                self._status_label.config(text=f"Live: {names}  ·  updates every {poll_interval()}s",
                                          fg=T_DIM)
        g = self._current_game()
        chars = g.get("characters", []) if g else []
        all_open  = bool(chars) and all(c["character_id"] in self._windows for c in chars)
        none_open = not self._windows
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

    # ── OBS / overlay URLs ────────────────────────────────────────────────────
    def _server_ok(self) -> bool:
        if OVERLAY_HUB.port:
            return True
        messagebox.showwarning("Overlay",
            "The overlay server is not running (port in use or disabled in the settings).",
            parent=self.root)
        return False

    def _open_overlay_index(self):
        if self._server_ok():
            webbrowser.open(f"http://127.0.0.1:{OVERLAY_HUB.port}/")

    def _preview_overlay(self, ch):
        if self._server_ok():
            webbrowser.open(OVERLAY_HUB.url_for(ch["character_id"]) + "?always=1&card=1")

    def _copy_overlay_url(self, ch):
        if not self._server_ok(): return
        url = OVERLAY_HUB.url_for(ch["character_id"])
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.flash_status(f"Copied overlay URL for {ch.get('name','?')}: {url}")

    def _open_obs_dialog(self, then=None):
        g   = self._current_game()
        dlg = OBSDialog(self.root, obs_settings(self.cfg),
                        g["name"] if g and g.get("characters") else None)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        self.cfg["obs"] = dlg.result
        save_config(self.cfg)
        if dlg.action == "each" and g:
            self._send_to_obs(g.get("characters", []))
        elif dlg.action == "party" and g:
            self._obs_send([party_obs_item(g)], f"party “{g['name']}”")
        elif then:
            then()

    def _send_to_obs(self, chars: list):
        if not chars or not self._server_ok(): return
        if not self.cfg.get("obs"):
            self._open_obs_dialog(then=lambda: self._send_to_obs(chars))
            return
        g     = self._current_game()
        order = [c["character_id"] for c in (g.get("characters", []) if g else [])]
        items = [character_obs_item(ch, order.index(ch["character_id"])
                                    if ch["character_id"] in order else 0) for ch in chars]
        label = chars[0].get("name", "?") if len(chars) == 1 else f"{len(chars)} characters"
        self._obs_send(items, label)

    def _obs_send(self, items: list, label: str):
        if not self._server_ok(): return
        obs = obs_settings(self.cfg)
        self._status_label.config(text=f"Sending {label} to OBS…", fg=T_DIM)
        def work():
            try:
                scene, created, updated = obs_add_overlays(obs, items)
                run_on_ui(lambda: self._obs_done(label, scene, created, updated, None))
            except Exception as e:
                msg = str(e)
                log.warning("OBS: %s", msg)
                run_on_ui(lambda: self._obs_done(label, None, 0, 0, msg))
        threading.Thread(target=work, daemon=True, name="obs").start()

    def _obs_done(self, label, scene, created, updated, err):
        if err:
            self._status_label.config(text="OBS: failed", fg=HP_CRIT)
            if messagebox.askyesno("OBS", f"{err}\n\nOpen the OBS connection settings?",
                                   parent=self.root):
                self._open_obs_dialog()
            return
        parts = [p for p in (f"{created} added" if created else "",
                             f"{updated} updated" if updated else "") if p]
        self.flash_status(f"OBS: {label} → scene '{scene}' ({', '.join(parts)}). "
                          "Press ▶ to show a character on stream.", HP_FULL, 7000)

    # ── Settings ─────────────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self.root, self.cfg)
        self.root.wait_window(dlg)
        r = dlg.result
        if not r: return
        old_port = (self.cfg.get("overlay_server") or {}).get("port", DEFAULT_OVERLAY_PORT)
        self.cfg["poll_interval"] = r["poll_interval"]
        self.cfg["check_updates"] = r["check_updates"]
        self.cfg["close_to_tray"] = r["close_to_tray"]
        self.cfg.setdefault("overlay_server", {"enabled": True})["port"] = r["port"]
        save_config(self.cfg)
        apply_poll_interval(self.cfg)
        self._setup_tray()
        self._update_status_bar()
        if r["port"] != old_port:
            messagebox.showinfo("Settings", "The new overlay port is used after you restart "
                                "the app.", parent=self.root)

    # ── Character CRUD ────────────────────────────────────────────────────────
    def _ensure_avatar(self, ch, url):
        """Download the D&D Beyond avatar for a character without portraits."""
        if not url or has_custom_portrait(ch):
            return
        def work():
            try:
                rel = download_avatar(url, ch)
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
        if not dlg.result: return
        if any(c["character_id"] == dlg.result["character_id"] for c in g.get("characters", [])):
            messagebox.showwarning("Already added", "This character is already in this game.",
                                   parent=self.root)
            return
        g.setdefault("characters", []).append(dlg.result)
        save_config(self.cfg)
        self._refresh_chars()
        self._ensure_avatar(dlg.result, dlg.avatar_url)

    def _edit_character(self, ch, game):
        old_cid = ch["character_id"]
        dlg = CharacterDialog(self.root, ch.copy())
        self.root.wait_window(dlg)
        if not dlg.result: return
        ch.update(dlg.result)
        save_config(self.cfg)
        cid = ch["character_id"]
        if old_cid in self._windows:
            if cid != old_cid:
                self._close_window(old_cid)
                self._open_window(ch)
            else:
                w = self._windows[cid]
                w.set_title(ch.get("name", ""))
                w.win.attributes("-topmost", bool(ch.get("always_on_top", False)))
                w.win.attributes("-alpha", max(0.2, min(1.0, float(ch.get("opacity", 1.0)))))
                w.reload_portrait((self._hp_data.get(cid) or {}).get("pct"))
        self._refresh_chars()
        self._ensure_avatar(ch, dlg.avatar_url)

    def _delete_character(self, ch, game):
        if not messagebox.askyesno("Delete",
            f"Remove '{ch.get('name','?')}' from this game?", parent=self.root): return
        self._close_window(ch["character_id"])
        game["characters"] = [c for c in game["characters"] if c is not ch]
        save_config(self.cfg)
        self._refresh_chars()

    def _on_quit(self):
        for cid in list(self._windows):
            self._close_window(cid)
        save_config(self.cfg)
        self._stop_tray()
        self.root.destroy()

    # ── System tray ──────────────────────────────────────────────────────────
    _tray = None

    def _setup_tray(self):
        """✕ quits by default; hiding to the tray is opt-in (Settings)."""
        if HAS_TRAY and self.cfg.get("close_to_tray", False):
            self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

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
        self._stop_tray()                    # a stopped Icon can't be re-run
        self._tray = self._make_tray_icon()
        threading.Thread(target=self._tray.run, daemon=True, name="tray").start()

    def _stop_tray(self):
        tray, self._tray = self._tray, None
        if tray:
            try: tray.stop()
            except Exception: pass

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
    setup_logging()
    cfg, notices = load_config()
    srv = cfg.setdefault("overlay_server", {"enabled": True, "port": DEFAULT_OVERLAY_PORT})
    try:
        port = int(srv.get("port", DEFAULT_OVERLAY_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_OVERLAY_PORT
    # Single instance: the first copy may be hidden in the system tray.
    if app_already_running(port):
        r = tk.Tk(); r.withdraw()
        messagebox.showinfo("D&D Health Bar",
            "D&D Health Bar is already running.\n\n"
            "If you can't see it, look in the system tray (bottom-right, near the clock) — "
            "right-click the green ring icon and choose Show.")
        r.destroy()
        return
    if migrate_config(cfg):
        log.info("Config migrated to version %s (portable portraits)", CONFIG_VERSION)
        save_config(cfg)
    apply_poll_interval(cfg)
    OVERLAY_HUB.sync_config(cfg)
    if srv.get("enabled", True):
        start_overlay_server(port)
    root = tk.Tk()
    app  = ManagerWindow(root, cfg)
    app._setup_tray()
    root.after(50, _pump_ui_queue, root)
    for note in notices:
        root.after(300, lambda n=note: messagebox.showwarning("D&D Health Bar", n, parent=root))
    root.after(1500, app.check_updates_async)
    root.mainloop()
    log.info("Exiting")
    logging.shutdown()
    # Make sure no stray background thread keeps the process alive.
    os._exit(0)

if __name__ == "__main__":
    main()
