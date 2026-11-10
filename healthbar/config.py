"""Data folder, settings file (atomic + backup), portraits, logging.

Everything lives in one folder next to the program, so it can be moved,
copied or synced as a whole:

  Health Bar/
    DnD_HealthBar_Public.exe
    dnd_healthbar_public.json      settings + characters (+ .bak backup)
    dnd_healthbar.log              log file
    portraits/<name>_<id>/...      portrait images (paths stored relative)
"""
import hashlib
import io
import json
import logging
import logging.handlers
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.parse

import requests
from PIL import Image

from . import APP_VERSION

log = logging.getLogger("dnd_healthbar")

CONFIG_NAME       = "dnd_healthbar_public.json"
LOG_NAME          = "dnd_healthbar.log"
PORTRAITS_DIRNAME = "portraits"
CONFIG_VERSION    = 2

DEFAULT_POLL_INTERVAL = 5
MIN_POLL, MAX_POLL    = 2, 60
POLL_INTERVAL         = DEFAULT_POLL_INTERVAL

# Read by other modules as config.BASE_DIR etc. (rebound by set_base_dir)
BASE_DIR = CONFIG_FILE = LOG_FILE = ""
SAVE_ERROR_HANDLER = None          # callable(message), set by the UI
_save_blocked: str | None = None
_save_lock = threading.Lock()

def _default_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def set_base_dir(path: str):
    """Point the app at a data folder (startup and tests)."""
    global BASE_DIR, CONFIG_FILE, LOG_FILE, _save_blocked
    BASE_DIR     = os.path.abspath(path)
    CONFIG_FILE  = os.path.join(BASE_DIR, CONFIG_NAME)
    LOG_FILE     = os.path.join(BASE_DIR, LOG_NAME)
    _save_blocked = None

set_base_dir(_default_base_dir())

# ── Logging ──────────────────────────────────────────────────────────────────
def setup_logging():
    """Small rotating log next to the program (the .exe has no console)."""
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=512_000,
                                                  backupCount=1, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    sys.excepthook = lambda t, v, tb: log.error("Uncaught error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.error(
        "Uncaught error in thread %s", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    log.info("D&D Health Bar %s starting (data folder: %s)", APP_VERSION, BASE_DIR)

# ── Portraits ───────────────────────────────────────────────────────────────
PORTRAIT_KEYS = ["portrait_unscathed", "portrait_scratched", "portrait_injured",
                 "portrait_bloodied", "portrait_critical", "portrait_dead"]
IMAGE_KEYS    = PORTRAIT_KEYS + ["avatar"]
STATE_TO_KEY  = {"full": "portrait_unscathed", "scratched": "portrait_scratched",
                 "injured": "portrait_injured", "bloodied": "portrait_bloodied",
                 "critical": "portrait_critical", "dying": "portrait_critical",
                 "stable": "portrait_critical", "dead": "portrait_dead",
                 "unknown": "portrait_unscathed"}

def portrait_abspath(p: str) -> str:
    """Stored path (relative to the data folder, or legacy absolute) → absolute."""
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(BASE_DIR, p))

def _is_inside_base(p: str) -> bool:
    try:
        a = os.path.normcase(os.path.abspath(p))
        b = os.path.normcase(BASE_DIR)
        return os.path.commonpath([a, b]) == b
    except ValueError:            # different drives
        return False

def _to_relative(p: str) -> str:
    return os.path.relpath(os.path.abspath(p), BASE_DIR).replace(os.sep, "/")

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
    """Copy an image into the character's portrait folder; identical images
    are stored once. Returns the relative path."""
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
    """Absolute path → relative path inside the data folder (copying the image
    in if it lives elsewhere). Missing files are left untouched."""
    if not p or not os.path.isabs(p):
        return p
    if _is_inside_base(p):
        return _to_relative(p)
    if os.path.isfile(p):
        return import_portrait(p, ch, key.replace("portrait_", ""))
    return p

def download_avatar(url: str, ch: dict) -> str | None:
    """Save a D&D Beyond avatar into the character's portrait folder."""
    u = urllib.parse.urlsplit(url or "")
    if u.scheme != "https" or not (u.hostname or "").endswith("dndbeyond.com"):
        return None
    r = requests.get(url, headers={"User-Agent": f"DnD-Health-Bar/{APP_VERSION}"}, timeout=15)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    img.load()                                      # validate
    folder_rel = character_folder(ch)
    os.makedirs(portrait_abspath(folder_rel), exist_ok=True)
    rel = f"{folder_rel}/avatar.png"
    img.convert("RGBA").save(portrait_abspath(rel), "PNG")
    return rel

def has_custom_portrait(ch: dict) -> bool:
    return any(ch.get(k) and os.path.isfile(portrait_abspath(ch[k])) for k in PORTRAIT_KEYS)

def resolve_portrait_key(char: dict, state: str) -> str:
    """Best portrait slot for a state: the ideal slot first, then alternately
    the nearest healthier / worse slot, then the D&D Beyond avatar."""
    idx   = PORTRAIT_KEYS.index(STATE_TO_KEY.get(state, "portrait_unscathed"))
    n     = len(PORTRAIT_KEYS)
    order = [idx]
    for off in range(1, n):
        if idx - off >= 0: order.append(idx - off)
        if idx + off < n:  order.append(idx + off)
    for i in order:
        p = char.get(PORTRAIT_KEYS[i], "")
        if p and os.path.isfile(portrait_abspath(p)):
            return PORTRAIT_KEYS[i]
    p = char.get("avatar", "")
    if p and os.path.isfile(portrait_abspath(p)):
        return "avatar"
    return ""

def resolve_portrait_path(char: dict, state: str) -> str:
    key = resolve_portrait_key(char, state)
    return portrait_abspath(char.get(key, "")) if key else ""

# ── Settings file ───────────────────────────────────────────────────────────
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
    """(config, notices). A damaged file is never overwritten: it is renamed
    aside and the automatic backup is used instead."""
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
    """Write atomically (temp file + rename), keeping the previous version as
    .bak. Retries briefly if a sync client holds the file."""
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
    from . import overlay                      # late import: overlay imports config
    overlay.HUB.sync_config(cfg)
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

def apply_settings(cfg: dict):
    """Apply settings that live in module state (poll interval, palette)."""
    global POLL_INTERVAL
    try:
        v = int(cfg.get("poll_interval", DEFAULT_POLL_INTERVAL))
    except (TypeError, ValueError):
        v = DEFAULT_POLL_INTERVAL
    POLL_INTERVAL = max(MIN_POLL, min(MAX_POLL, v))
    from . import theme
    theme.set_palette(cfg.get("palette", "default"))
