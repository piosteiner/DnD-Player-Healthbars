# D&D Beyond Live Health Bar

Live HP overlay synced to D&D Beyond, with per-character portraits that
change based on health state.

---
DISCLAIMER
This project is uses the code from Power Word Spill's https://github.com/powerwordspill/healthbar but adapted to implement the health bars in a digital environment. With v.2.0.0 this project also abandoned the the idea of relying on session cookies to access private character data, and instead only works with public character sheets. The original project is no longer maintained, and this fork is intended to be a more secure and privacy-conscious alternative. Having a public character sheet is the only requirement to use this project, and it is recommended to set your character sheet to public on D&D Beyond for security reasons. If you use the old version which uses session cookies, you are at risk of exposing your D&D Beyond account to anyone who can read the cookie file.

This project was created with the help of Anthropic's Claude AI.
---

## ⚠ Public Edition only — full edition discontinued

This project originally shipped two editions:

- **Full edition** — supported both public and private D&D Beyond characters,
  but required a session cookie from your D&D Beyond account to authenticate.
- **Public edition** — works with public characters only, requires no login
  and no credentials of any kind.

**The full edition has been discontinued.** The session cookie it relied on
is a full D&D Beyond authentication token. Storing it in a plain-text JSON
file on disk creates a real security risk — anyone or anything that can read
that file (other users, malware, cloud sync services) gets complete access to
your D&D Beyond account, including any saved payment methods and all your
campaign data.

The public edition avoids this entirely by authenticating anonymously using
only a temporary geographic cookie that carries no account access. There is
no credential to steal.

**The recommendation is simple: set your character sheet to public on D&D
Beyond and use the public edition.** Public characters still show live HP,
all health states, and all portraits — the only thing that changes is your
character sheet URL becomes visible to anyone who knows it.

---

## Downloading a release

Go to the [Releases](../../releases) page and download the public edition
for your OS:

| OS      | File                          |
|---------|-------------------------------|
| Windows | `DnD_HealthBar_Public.exe`    |
| Linux   | `DnD_HealthBar_Public`        |

Run it directly — no installation, no Python required.

On first launch it creates **`dnd_healthbar_public.json`** next to the
binary. This is your config file and contains no sensitive data.


## Config file (`dnd_healthbar_public.json`)

Lives next to the executable. Editable in any text editor.
**Contains no sensitive data.**

```json
{
  "games": [
    {
      "name": "My Campaign",
      "characters": [
        {
          "name":               "Thorin",
          "character_id":       "2222222",
          "always_on_top":      false,
          "show_hp_numbers":    false,
          "opacity":            1.0,
          "portrait_unscathed": "/path/to/full.png",
          "portrait_scratched": "/path/to/scratched.png",
          "portrait_injured":   "/path/to/injured.png",
          "portrait_bloodied":  "/path/to/bloodied.png",
          "portrait_critical":  "/path/to/critical.png",
          "portrait_dead":      "/path/to/dead.png"
        }
      ]
    }
  ],
  "sort": {
    "mode": "alpha_asc",
    "live_on_top": true
  }
}
```

### Health state thresholds

| State      | HP range   |
|------------|------------|
| Unscathed  | 100 %      |
| Scratched  | 75 – 100 % |
| Injured    | 50 – 75 %  |
| Bloodied   | 25 – 50 %  |
| Critical   |  0 – 25 %  |
| Dead       | 0 %        |

Portraits are optional per state. If a state has no portrait the app falls
back to the nearest state that does.

### Portrait aspect ratio

The portrait area is square (280 × 280 px). Any aspect ratio works — images
are scaled to fit without cropping. A tall portrait gets side bars, a wide
one gets top/bottom bars. For best results use square images.

---

## System tray

Install `pystray` to enable minimize-to-tray:
```
pip install pystray
```
When installed, closing the manager window sends it to the system tray
instead of quitting. Right-click the tray icon to show or quit.

This is included automatically in the pre-built binaries from the
Releases page.

---

## Project layout

```
dnd_healthbar_public.py       ← full source
dnd_healthbar_public.spec     ← PyInstaller build config
.github/workflows/build.yml   ← GitHub Actions CI/CD
.gitignore                    ← keeps config files out of git
README.md                     ← this file
```
