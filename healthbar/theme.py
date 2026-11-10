"""Colours, fonts, HP states and image helpers."""
import os

from PIL import Image, ImageChops, ImageDraw, ImageTk

# ── Manager / dialog palette ────────────────────────────────────────────────
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
OK_FG         = "#00e676"     # success messages
WARN_FG       = "#ffb300"
ERR_FG        = "#f44336"
HP_TEMP       = "#4fc3f7"
OVL_BG        = "#293136"
OVL_BAR_BG    = "#1e272e"
BTN_OPEN_BG   = "#1a3848";  BTN_OPEN_FG  = "#60b0d0";  BTN_OPEN_BD  = "#2a5060"
BTN_CLOSE_BG  = "#3a1818";  BTN_CLOSE_FG = "#e07070";  BTN_CLOSE_BD = "#5a2222"
BTN_EDIT_BG   = "#1e2c38";  BTN_EDIT_FG  = "#7aaabb";  BTN_EDIT_BD  = "#344858"
BTN_SAVE_BG   = "#1a3848";  BTN_SAVE_FG  = "#60c0d8";  BTN_SAVE_BD  = "#2a5060"
BTN_CANCEL_BG = "#1e2c38";  BTN_CANCEL_FG= "#7aaabb";  BTN_CANCEL_BD= "#344858"
BTN_HEAL_BG   = "#173a2a";  BTN_HEAL_FG  = "#4cd98a";  BTN_HEAL_BD  = "#2e6b4c"
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
F_BADGE  = ("Consolas", 10, "bold")

# ── Overlay geometry (design pixels) ────────────────────────────────────────
BAR_H      = 32
BAR_PAD    = 12
CORNER_R   = 14
OVL_W      = 280
CARD_H     = 340      # portrait + bar
CARD_H_NUM = 370      # ... with HP numbers
PARTY_GAP  = 16

# ── HP states and palettes ──────────────────────────────────────────────────
# Threshold states come from the HP percentage; dying / stable / dead are
# decided by death saves (player characters) or 0 HP (manual NPCs).
STATE_LABELS = {"full": "Unscathed", "scratched": "Scratched", "injured": "Injured",
                "bloodied": "Bloodied", "critical": "Critical", "dying": "Dying",
                "stable": "Stable", "dead": "Dead", "unknown": "—"}

PALETTES = {
    "default":    {"full": "#00e676", "scratched": "#40e880", "injured": "#ffb300",
                   "bloodied": "#ff6b00", "critical": "#f44336", "dying": "#f44336",
                   "stable": "#f44336", "dead": "#555555", "unknown": "#3a4a54"},
    # Blue → yellow → orange → magenta: distinguishable with red-green colour blindness
    "colorblind": {"full": "#1e88e5", "scratched": "#42a5f5", "injured": "#fdd835",
                   "bloodied": "#fb8c00", "critical": "#d81b60", "dying": "#d81b60",
                   "stable": "#d81b60", "dead": "#555555", "unknown": "#3a4a54"},
}
_palette = "default"

def set_palette(name: str):
    global _palette
    _palette = name if name in PALETTES else "default"

def palette_name() -> str:
    return _palette

def hp_state(pct) -> str:
    if pct is None: return "unknown"
    if pct <= 0:    return "dead"
    if pct < 0.25:  return "critical"
    if pct < 0.50:  return "bloodied"
    if pct < 0.75:  return "injured"
    if pct < 1.0:   return "scratched"
    return "full"

def display_state(info: dict | None) -> str:
    """State to show for an HP info dict (see ddb.hp_details/manual_info).
    At 0 HP a player character is *dying* (making death saves), *stable*, or
    *dead* after three failed saves; a manual NPC at 0 HP is dead."""
    if not info or info.get("pct") is None:
        return "unknown"
    if info.get("cur", 0) <= 0:
        if info.get("npc"):
            return "dead"
        ds = info.get("death_saves") or {}
        if ds.get("fail", 0) >= 3:
            return "dead"
        return "stable" if ds.get("stable") else "dying"
    return hp_state(info["pct"])

def state_color(state: str) -> str:
    return PALETTES[_palette].get(state, PALETTES[_palette]["unknown"])

def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i+2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))

def badge_colors(state: str) -> tuple[str, str, str]:
    """(foreground, background, border) for the HP badge in a manager row."""
    if state == "unknown":
        return T_MUTED, "#181818", "#282828"
    c = state_color(state)
    return c, _mix(c, "#000000", 0.85), _mix(c, "#000000", 0.7)

def hp_text(info: dict | None, sep: str = " / ") -> str:
    if not info or info.get("pct") is None:
        return "—"
    t = f"{info['cur']}{sep}{info['mx']}"
    if info.get("temp"):
        t += f"  +{info['temp']}"
    return t

# ── Image helpers ───────────────────────────────────────────────────────────
def round_image(img: Image.Image, radius: int) -> Image.Image:
    img  = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], radius=radius, fill=255)
    # Combine with the existing alpha so transparent areas stay transparent
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

_thumb_cache: dict = {}

def thumb_photo(path: str, size: int, bg: str, radius: int = 8):
    """Small rounded thumbnail, cached per file + modification time so lists
    don't re-decode every image on each refresh. Main thread only."""
    import tkinter
    owner = id(tkinter._default_root)          # images belong to one Tk interpreter
    try:
        key = (owner, path, os.path.getmtime(path), size, bg, radius) if path \
              else (owner, "", 0, size, bg, radius)
    except OSError:
        key, path = (owner, "", 0, size, bg, radius), ""
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

def draw_pill(c, x0: float, x1: float, h: int, color: str):
    """Horizontal bar segment with rounded ends on a Tk canvas."""
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

def make_icon(size: int = 256) -> Image.Image:
    """App icon: a heart above a health bar on a dark rounded square."""
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8*s, 8*s, 248*s, 248*s], radius=48*s, fill="#1e2c38",
                        outline="#344858", width=max(1, int(6*s)))
    # heart
    d.ellipse([52*s, 44*s, 132*s, 124*s], fill="#f44336")
    d.ellipse([124*s, 44*s, 204*s, 124*s], fill="#f44336")
    d.polygon([(56*s, 100*s), (200*s, 100*s), (128*s, 176*s)], fill="#f44336")
    d.ellipse([74*s, 62*s, 100*s, 88*s], fill="#ff8a80")
    # health bar
    d.rounded_rectangle([40*s, 192*s, 216*s, 222*s], radius=15*s, fill="#0f1720")
    d.rounded_rectangle([40*s, 192*s, 160*s, 222*s], radius=15*s, fill="#00e676")
    return img
