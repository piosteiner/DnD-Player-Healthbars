"""D&D Beyond API, HP maths, the shared poller and manual (NPC) characters."""
import json
import logging
import threading
import time

import requests

from . import APP_VERSION, config

log = logging.getLogger("dnd_healthbar")

CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"
ORIGIN        = "https://www.dndbeyond.com"
UA            = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

# D&D Beyond condition ids (the standard 5e conditions, alphabetical)
CONDITION_NAMES = {1: "Blinded", 2: "Charmed", 3: "Deafened", 4: "Exhaustion",
                   5: "Frightened", 6: "Grappled", 7: "Incapacitated", 8: "Invisible",
                   9: "Paralyzed", 10: "Petrified", 11: "Poisoned", 12: "Prone",
                   13: "Restrained", 14: "Stunned", 15: "Unconscious"}

NO_SAVES = {"fail": 0, "success": 0, "stable": False}

# ── API ─────────────────────────────────────────────────────────────────────
def make_session(character_id: str) -> requests.Session:
    """Visit a public character page to collect the Geo cookie the API needs."""
    session = requests.Session()
    session.get(f"{ORIGIN}/characters/{character_id}", headers={"User-Agent": UA}, timeout=10)
    return session

def fetch_raw(session: requests.Session, character_id: str) -> dict:
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
    return resp.json().get("data", {})

def get_character(session: requests.Session, character_id: str) -> dict:
    return parse_character(fetch_raw(session, character_id))

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
                value = mod.get("value") or mod.get("fixedValue")
                if mod.get("type") == "bonus":
                    con_score += int(value or 0)
                elif mod.get("type") == "set" and value is not None:
                    con_set = max(con_set or 0, int(value))      # e.g. Amulet of Health
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
            levels = total_level
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
    """HP info dict used everywhere (manager, desktop window, overlay)."""
    pct, cur, mx = calculate_hp(d)
    return {"pct": pct, "cur": cur, "mx": mx,
            "temp": max(0, d.get("temporaryHitPoints", 0)) if pct is not None else 0,
            "death_saves": dict(d.get("deathSaves") or NO_SAVES),
            "conditions": list(d.get("conditions") or []),
            "npc": False}

def diagnostics(character_id: str) -> str:
    """What D&D Beyond returns for a character, plus what the app makes of it.
    Shared by the user when something looks wrong."""
    raw    = fetch_raw(make_session(character_id), character_id)
    parsed = parse_character(raw)
    deco   = raw.get("decorations") or {}
    hp_mods = [{k: m.get(k) for k in ("type", "subType", "value", "fixedValue", "componentId")}
               for src, mods in (raw.get("modifiers") or {}).items() for m in (mods or [])
               if m.get("subType") in ("constitution-score", "hit-points-per-level", "hit-points")]
    report = {
        "app_version": APP_VERSION,
        "character_id": character_id,
        "name": raw.get("name"),
        "hp_fields": {k: raw.get(k) for k in ("baseHitPoints", "bonusHitPoints", "overrideHitPoints",
                                              "removedHitPoints", "temporaryHitPoints")},
        "classes": [{"name": (c.get("definition") or {}).get("name"), "level": c.get("level")}
                    for c in raw.get("classes", [])],
        "stats": raw.get("stats"), "bonusStats": raw.get("bonusStats"),
        "overrideStats": raw.get("overrideStats"),
        "hp_modifiers": hp_mods,
        "avatar_url": deco.get("avatarUrl") or raw.get("avatarUrl"),
        "decorations_keys": sorted(deco.keys()),
        "deathSaves": raw.get("deathSaves"),
        "conditions": raw.get("conditions"),
        "result": hp_details(parsed),
    }
    return json.dumps(report, indent=2, ensure_ascii=False)

# ── Manual characters (NPCs, monsters, companions) ──────────────────────────
def is_manual(ch: dict) -> bool:
    return ch.get("source") == "manual"

def manual_info(ch: dict) -> dict:
    mx   = max(1, int(ch.get("max_hp") or 1))
    cur  = max(0, min(mx, int(ch.get("current_hp", mx))))
    temp = max(0, int(ch.get("temp_hp") or 0))
    return {"pct": cur / mx, "cur": cur, "mx": mx, "temp": temp,
            "death_saves": dict(NO_SAVES), "conditions": list(ch.get("conditions") or []),
            "npc": True}

def apply_hp_change(ch: dict, kind: str, amount: int):
    """Change a manual character's HP. Damage uses temporary HP first (5e)."""
    amount = max(0, int(amount))
    mx   = max(1, int(ch.get("max_hp") or 1))
    cur  = max(0, min(mx, int(ch.get("current_hp", mx))))
    temp = max(0, int(ch.get("temp_hp") or 0))
    if kind == "damage":
        absorbed = min(temp, amount)
        temp -= absorbed
        cur = max(0, cur - (amount - absorbed))
    elif kind == "heal":
        cur = min(mx, cur + amount)
    elif kind == "temp":
        temp = amount                       # temporary HP doesn't stack
    elif kind == "max":
        mx = max(1, amount)
        cur = min(cur, mx)
    elif kind == "set":
        cur = min(mx, amount)
    else:
        raise ValueError(kind)
    ch["max_hp"], ch["current_hp"], ch["temp_hp"] = mx, cur, temp

# ── Shared poller ───────────────────────────────────────────────────────────
def backoff_delay(errors: int, base: int = 5, cap: int = 120) -> int:
    """5, 10, 20, 40, 80, 120, 120 … seconds."""
    return min(cap, base * 2 ** (max(1, min(errors, 7)) - 1))

class _Sub:
    def __init__(self, cid, on_data, on_status):
        self.cid, self.on_data, self.on_status = cid, on_data, on_status
        self.next_due   = 0.0
        self.errors     = 0
        self.auth_fails = 0
        self.fetched    = False

class Poller:
    """One background thread polls every live character with one shared
    session — fewer requests to D&D Beyond than one connection per character."""

    def __init__(self):
        self._lock    = threading.Lock()
        self._wake    = threading.Event()
        self._subs: dict[str, _Sub] = {}
        self._thread  = None
        self._session = None
        self.sessions_created = 0          # for tests / diagnostics

    def reset(self):
        with self._lock:
            self._subs.clear()
        self._session = None
        self.sessions_created = 0

    def add(self, cid: str, on_data, on_status):
        with self._lock:
            self._subs[cid] = _Sub(cid, on_data, on_status)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="poller")
                self._thread.start()
        self._wake.set()

    def remove(self, cid: str):
        with self._lock:
            self._subs.pop(cid, None)

    def poll_now(self):
        """Check every live character immediately (e.g. after settings change)."""
        with self._lock:
            for s in self._subs.values():
                s.next_due = 0
        self._wake.set()

    def _active(self, s) -> bool:
        with self._lock:
            return self._subs.get(s.cid) is s

    def _run(self):
        while True:
            with self._lock:
                subs = list(self._subs.values())
            now = time.monotonic()
            for s in subs:
                if s.next_due <= now and self._active(s):
                    self._poll(s)
            with self._lock:
                nxt = min((s.next_due for s in self._subs.values()), default=None)
            wait = 1.0 if nxt is None else max(0.05, nxt - time.monotonic())
            self._wake.wait(wait)
            self._wake.clear()

    def _status(self, s, msg, kind="busy"):
        try:
            s.on_status(msg, kind)
        except Exception:
            log.exception("status callback failed")

    def _poll(self, s: _Sub):
        cid, delay = s.cid, None
        try:
            if self._session is None:
                self._status(s, "Connecting…")
                self._session = make_session(cid)
                self.sessions_created += 1
            if not s.fetched:
                self._status(s, "Fetching HP…")
            data = get_character(self._session, cid)
            s.errors = s.auth_fails = 0
            s.fetched = True
            if self._active(s):
                s.on_data(data)
                self._status(s, f"Live · checking every {config.poll_interval()}s", "ok")
            delay = config.poll_interval()
        except requests.exceptions.HTTPError as e:
            # NB: a Response is falsy for 4xx/5xx, so test against None
            resp = e.response
            code = resp.status_code if resp is not None else 0
            if code in (401, 403):
                s.auth_fails += 1
                if s.auth_fails == 1:            # maybe the session expired — renew once
                    log.info("[%s] %s, renewing session", cid, code)
                    self._session = None
                    self._status(s, "Refreshing session…")
                    delay = 1
                else:
                    self._status(s, "⚠ Character is private — make it public on D&D Beyond", "error")
                    delay = backoff_delay(s.auth_fails, base=30, cap=300)
            elif code == 404:
                self._status(s, "⚠ Character not found — check the ID", "error")
                delay = 60
            elif code == 429:
                s.errors += 1
                try:
                    retry_after = int(resp.headers.get("Retry-After", "0"))
                except (ValueError, AttributeError):
                    retry_after = 0
                delay = max(retry_after, backoff_delay(s.errors, base=30, cap=300))
                log.warning("[%s] rate limited, waiting %ss", cid, delay)
                self._status(s, f"⚠ D&D Beyond asks us to slow down — retrying in {delay}s", "error")
            else:
                s.errors += 1
                delay = backoff_delay(s.errors)
                log.warning("[%s] HTTP %s, retry in %ss", cid, code, delay)
                self._status(s, f"⚠ Connection problem (HTTP {code}) — retrying in {delay}s", "error")
        except Exception as e:
            s.errors += 1
            self._session = None
            delay = backoff_delay(s.errors)
            log.warning("[%s] %s: %s — retry in %ss", cid, type(e).__name__, e, delay)
            self._status(s, f"⚠ No connection — retrying in {delay}s", "error")
        s.next_due = time.monotonic() + (delay or config.poll_interval())

POLLER = Poller()
