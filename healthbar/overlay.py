"""Browser-source overlay server for OBS (localhost only).

  /overlay/<cid>        one character          /party/<game id>   whole party
  /events/...           server-sent events     /api/...           JSON
  /portrait/<cid>/<key> fitted, rounded PNG    /                  URL index
"""
import html
import http.server
import io
import json
import logging
import os
import re
import threading
import urllib.parse
import urllib.request

from PIL import Image

from . import config, ddb, theme

log = logging.getLogger("dnd_healthbar")

DEFAULT_PORT = 7777
PING_REPLY   = b"dnd-healthbar"
CID_RE       = r"[0-9a-z]+"            # D&D Beyond ids are digits; manual ids "npc…"


class OverlayHub:
    """Thread-safe snapshot of everything the overlays need. Written from the
    Tk main thread, read by server threads, which are woken on changes."""

    def __init__(self):
        self._cond = threading.Condition()
        self.reset()

    def reset(self):
        with self._cond:
            self._chars: dict[str, dict] = {}
            self._games: list[dict] = []
            self._live:  dict[str, dict] = {}
            self._img_cache: dict = {}
            self.version = 0
            self.port: int | None = None
            self._cond.notify_all()

    def url_for(self, cid: str) -> str | None:
        return f"http://127.0.0.1:{self.port}/overlay/{cid}" if self.port else None

    def party_url(self, gid: str) -> str | None:
        return f"http://127.0.0.1:{self.port}/party/{gid}" if self.port else None

    def _bump(self):                       # caller holds self._cond
        self.version += 1
        self._cond.notify_all()

    def wait_change(self, since: int, timeout: float) -> int:
        with self._cond:
            self._cond.wait_for(lambda: self.version != since, timeout)
            return self.version

    # writers (main thread)
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
                     "show_hp_numbers": bool(ch.get("show_hp_numbers", False)),
                     "npc": ddb.is_manual(ch)}
                for k in config.IMAGE_KEYS:
                    s[k] = config.portrait_abspath(ch.get(k, ""))
                snap[cid] = s
            games.append({"id": g.get("id", ""), "name": g.get("name", ""), "cids": cids})
        snap["__palette__"] = {"name": theme.palette_name()}
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

    # readers (server threads)
    def characters(self) -> list[tuple[str, dict]]:
        with self._cond:
            return [(k, v) for k, v in self._chars.items() if not k.startswith("__")]

    def games(self) -> list[dict]:
        with self._cond:
            return [dict(g) for g in self._games]

    def state_for(self, cid: str) -> dict | None:
        with self._cond:
            ch = self._chars.get(cid)
            if ch is None or cid.startswith("__"):
                return None
            ch   = dict(ch)
            live = cid in self._live
            hp   = dict(self._live.get(cid, {}))
        loaded = "pct" in hp
        state  = theme.display_state(hp) if loaded else "unknown"
        key    = config.resolve_portrait_key(ch, state if loaded else "full")
        try:
            ver = int(os.path.getmtime(ch[key])) if key else 0
        except OSError:
            ver = 0
        return {"cid": cid, "name": ch["name"], "live": live, "loaded": loaded,
                "pct": hp.get("pct") if loaded else None,
                "cur": hp.get("cur", 0), "mx": hp.get("mx", 0), "temp": hp.get("temp", 0),
                "death_saves": hp.get("death_saves") or dict(ddb.NO_SAVES),
                "conditions": hp.get("conditions") or [],
                "state": state, "color": theme.state_color(state),
                "show_hp_numbers": ch["show_hp_numbers"],
                "portrait": key, "portrait_v": ver}

    def party_state(self, gid: str) -> dict | None:
        with self._cond:
            g = next((x for x in self._games if x["id"] == gid), None)
        if g is None:
            return None
        return {"name": g["name"],
                "characters": [s for s in (self.state_for(c) for c in g["cids"]) if s]}

    def portrait_png(self, cid: str, key: str) -> bytes | None:
        """Portrait fitted + rounded like the desktop window, 2x resolution,
        transparent background. Cached per file modification time."""
        if key not in config.IMAGE_KEYS or cid.startswith("__"):
            return None
        with self._cond:
            path = (self._chars.get(cid) or {}).get(key, "")
        if not path or not os.path.isfile(path):
            return None
        cache_key = (path, os.path.getmtime(path))
        with self._cond:
            if cache_key in self._img_cache:
                return self._img_cache[cache_key]
        size = theme.OVL_W * 2
        img  = theme.round_image(theme.fit_image(Image.open(path), size, (0, 0, 0, 0)),
                                 theme.CORNER_R * 2)
        buf  = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
        with self._cond:
            if len(self._img_cache) > 64:
                self._img_cache.clear()
            self._img_cache[cache_key] = data
        return data


HUB = OverlayHub()

# One page for a single character (/overlay/<cid>) and a party (/party/<gid>).
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
  body.bar .pwrap{display:none}
  .pwrap::after{content:"";position:absolute;inset:0;border-radius:calc(var(--u)*14);pointer-events:none}
  .portrait{display:block;width:100%;height:100%;object-fit:contain;transition:filter .8s ease}
  .portrait.empty{visibility:hidden}
  .card.dying .portrait{filter:grayscale(.55) brightness(.8)}
  .card.dying .pwrap::after{animation:dying 1.8s ease-in-out infinite}
  .card.dead .portrait{filter:grayscale(1) brightness(.55)}
  .card.hit .portrait{animation:shake .4s ease}
  .name{display:none;color:#dce8f0;font:600 calc(var(--u)*16) "Segoe UI",sans-serif;
        margin:calc(var(--u)*8) calc(var(--u)*12) 0;white-space:nowrap;overflow:hidden;
        text-overflow:ellipsis;text-align:center;
        text-shadow:0 0 calc(var(--u)*3) #000,0 0 calc(var(--u)*3) #000}
  body.names .name, body.bar .name{display:block}
  body.bar .name{text-align:left}
  .chips{position:absolute;left:calc(var(--u)*8);right:calc(var(--u)*8);top:calc(var(--u)*8);
         display:flex;flex-wrap:wrap;gap:calc(var(--u)*4)}
  .chip{font-size:calc(var(--u)*11);font-weight:600;padding:calc(var(--u)*2) calc(var(--u)*7);
        border-radius:calc(var(--u)*9);background:rgba(40,20,60,.85);color:#ecdcff;
        border:calc(var(--u)*1) solid rgba(190,150,255,.5);white-space:nowrap}
  .saves{position:absolute;left:0;right:0;bottom:calc(var(--u)*8);display:none;
         justify-content:center;gap:calc(var(--u)*5);align-items:center}
  .saves.on{display:flex}
  .extras{display:none}
  body.bar .extras{display:flex;justify-content:space-between;align-items:center;
                   height:calc(var(--u)*22);margin-top:calc(var(--u)*6);overflow:hidden}
  body.bar .chips, body.bar .saves{position:static}
  body.bar .chips{flex-wrap:nowrap;overflow:hidden}
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
  @keyframes dying{0%,100%{box-shadow:inset 0 0 0 0 rgba(244,67,54,0)}
                   50%{box-shadow:inset 0 0 calc(var(--u)*40) calc(var(--u)*4) rgba(244,67,54,.55)}}
</style></head>
<body><div id="stage"></div>
<script>
  const parts  = location.pathname.split("/").filter(Boolean);   // overlay|party, id
  const party  = parts[0] === "party";
  const params = new URLSearchParams(location.search);
  const flag   = k => params.get(k) === "1";
  const bar    = params.get("style") === "bar";
  const column = params.get("layout") === "column";
  const names  = flag("name") || bar;
  const always = flag("always");
  const showCond = params.get("conditions") !== "0";
  const PALETTES = {
    default: {full:"#00e676",scratched:"#40e880",injured:"#ffb300",bloodied:"#ff6b00",
              critical:"#f44336",dying:"#f44336",stable:"#f44336",dead:"#555555",unknown:"#3a4a54"},
    cb:      {full:"#1e88e5",scratched:"#42a5f5",injured:"#fdd835",bloodied:"#fb8c00",
              critical:"#d81b60",dying:"#d81b60",stable:"#d81b60",dead:"#555555",unknown:"#3a4a54"}};
  const pal = PALETTES[params.get("palette")] || null;          // else: colour from the app
  for (const [on, cls] of [[flag("card"), "cardbg"], [column, "column"], [bar, "bar"], [names, "names"]])
    if (on) document.body.classList.add(cls);
  const stage = document.getElementById("stage");
  const cards = {};
  let n = 1, showNums = false;

  function fit() {
    let ch = bar ? 30 + 56 + 28 : 340 + (names ? 30 : 0);
    if (showNums) ch += 30;
    const W = column ? 280 : n * 280 + (n - 1) * 16;
    const H = column ? n * ch + (n - 1) * 16 : ch;
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
    c.img  = el("img", "portrait empty", pw); c.img.alt = "";
    c.name = el("div", "name", c.root);
    const hp = el("div", "hp", c.root);
    c.track = el("div", "track", hp);
    c.trail = el("div", "trail", c.track);
    c.temp  = el("div", "temp", c.track);
    c.fill  = el("div", "fill", c.track);
    c.nums  = el("div", "nums", hp);
    const extras = el("div", "extras", hp);
    const host = bar ? extras : pw;                 // where chips / death saves go
    c.chips = el("div", "chips", host);
    c.saves = el("div", "saves", host);
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
    c.name.textContent = s.name;
    const src = s.portrait ? `/portrait/${s.cid}/${s.portrait}?v=${s.portrait_v}` : "";
    if (src !== c.src) {
      c.src = src;
      if (src) { c.img.src = src; c.img.classList.remove("empty"); }
      else     { c.img.removeAttribute("src"); c.img.classList.add("empty"); }
    }
    c.root.classList.toggle("dead", s.state === "dead");
    c.root.classList.toggle("dying", s.state === "dying");
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
      c.fill.style.backgroundColor = pal ? pal[s.state] : s.color;
      c.nums.textContent = `${s.cur}  /  ${s.mx}`;
      if (s.temp) el("span", "t", c.nums).textContent = `  +${s.temp}`;
    }
    c.nums.style.display = s.show_hp_numbers ? "block" : "none";
    c.chips.replaceChildren();
    if (showCond && s.loaded) for (const name of s.conditions) el("span", "chip", c.chips).textContent = name;
    const ds = s.death_saves || {};
    const showSaves = s.loaded && (s.state === "dying" || s.state === "stable");
    c.saves.classList.toggle("on", showSaves);
    c.saves.replaceChildren();
    if (showSaves) {
      if (s.state === "stable") el("span", "stable", c.saves).textContent = "STABLE";
      else {
        for (let i = 0; i < 3; i++) el("span", "pip s" + (i < ds.success ? " on" : ""), c.saves);
        el("span", "sep", c.saves);
        for (let i = 0; i < 3; i++) el("span", "pip f" + (i < ds.fail ? " on" : ""), c.saves);
      }
    }
  }
  function render(list) {
    n = Math.max(1, list.length);
    showNums = list.some(s => s.show_hp_numbers);
    fit();
    const seen = new Set();
    for (const s of list) {
      const c = cards[s.cid] || makeCard(s.cid);
      stage.appendChild(c.root);
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


def _index_html() -> str:
    chars = dict(HUB.characters())
    blocks = []
    for g in HUB.games():
        rows = []
        purl = HUB.party_url(g["id"]) or ""
        n    = max(1, len(g["cids"]))
        ph   = theme.CARD_H_NUM if any(chars.get(c, {}).get("show_hp_numbers") for c in g["cids"]) else theme.CARD_H
        rows.append(
            f'<tr class="party"><td><b>Whole party</b><br><small>{n * 280 + (n - 1) * theme.PARTY_GAP} × '
            f'{ph}</small></td><td><code>{html.escape(purl)}</code></td>'
            f'<td><button data-url="{html.escape(purl)}">Copy</button> '
            f'<a href="{html.escape(purl)}?always=1&card=1" target="_blank">Preview</a></td></tr>')
        for cid in g["cids"]:
            ch  = chars.get(cid, {})
            url = HUB.url_for(cid) or ""
            rows.append(
                f'<tr><td>{html.escape(ch.get("name", cid))}{" <small>(NPC)</small>" if ch.get("npc") else ""}'
                f'<br><small>280 × {theme.CARD_H_NUM if ch.get("show_hp_numbers") else theme.CARD_H}</small></td>'
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
  p,small,li{{color:#82a0b0}} p,ul{{max-width:780px}}
  table{{border-collapse:collapse;margin-top:8px}}
  td,th{{padding:8px 12px;border-bottom:1px solid #243040;text-align:left;vertical-align:top}}
  th{{color:#7ea6b6;font-size:12px;text-transform:uppercase}}
  tr.party td{{background:#1a2632}}
  code{{color:#60c0d8}} a{{color:#60b0d0}}
  button{{background:#1a3848;color:#60c0d8;border:1px solid #2a5060;padding:4px 10px;cursor:pointer}}
</style></head><body>
<h1>D&amp;D Health Bar — OBS overlays</h1>
<p>Easiest: use <b>OBS</b> in the app to add these automatically. Manually: in OBS add a
<b>Browser</b> source, paste a URL and use the size shown (any size works — the overlay
scales to fit). A character appears when you press ▶ in the app and fades out on ■.</p>
<p>Add options to the end of a URL, e.g. <code>?style=bar&amp;layout=column</code>:</p>
<ul>
<li><code>style=bar</code> compact bars with names, no portraits (great for big parties)</li>
<li><code>name=1</code> show the name under the portrait</li>
<li><code>layout=column</code> stack the party vertically</li>
<li><code>card=1</code> dark card background · <code>always=1</code> always visible</li>
<li><code>palette=cb</code> colour-blind friendly colours · <code>conditions=0</code> hide conditions</li>
</ul>
{body}
<script>
document.querySelectorAll("button[data-url]").forEach(b => b.onclick = async () => {{
  await navigator.clipboard.writeText(b.dataset.url);
  b.textContent = "Copied!"; setTimeout(() => b.textContent = "Copy", 1500);
}});
</script></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "DnDHealthBar"

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/ping":
                return self._send(200, "text/plain", PING_REPLY)
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", _index_html().encode("utf-8"))
            if re.fullmatch(rf"/(overlay/{CID_RE}|party/[0-9a-f]+)/?", path):
                return self._send(200, "text/html; charset=utf-8", OVERLAY_HTML.encode("utf-8"))
            m = re.fullmatch(rf"/api/({CID_RE})", path)
            if m and m.group(1) != "party":
                return self._json(HUB.state_for(m.group(1)))
            m = re.fullmatch(r"/api/party/([0-9a-f]+)", path)
            if m:
                return self._json(HUB.party_state(m.group(1)))
            m = re.fullmatch(r"/events/party/([0-9a-f]+)", path)
            if m:
                gid = m.group(1)
                return self._sse(lambda: HUB.party_state(gid) or {"characters": []})
            m = re.fullmatch(rf"/events/({CID_RE})", path)
            if m:
                cid = m.group(1)
                return self._sse(lambda: {"characters": [s for s in [HUB.state_for(cid)] if s]})
            m = re.fullmatch(rf"/portrait/({CID_RE})/(portrait_[a-z]+|avatar)", path)
            if m:
                data = HUB.portrait_png(m.group(1), m.group(2))
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
        """Server-sent events: push the state now and on every change."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b"retry: 2000\n\n")
        self.wfile.flush()
        seen = None
        while True:
            ver = HUB.wait_change(seen if seen is not None else -1, 15)
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


def start_server(port: int) -> int | None:
    """Start on 127.0.0.1 (tries `port` .. `port`+9). Returns the port or None."""
    for p in range(port, port + 10):
        try:
            srv = _ExclusiveHTTPServer(("127.0.0.1", p), _Handler)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True, name="overlay-server").start()
        HUB.port = p
        log.info("Overlay server on http://127.0.0.1:%d/", p)
        return p
    log.error("Could not start overlay server on ports %d-%d", port, port + 9)
    return None
