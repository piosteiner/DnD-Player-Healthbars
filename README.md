# D&D Beyond Live Health Bar

Live HP overlay synced to D&D Beyond — for your desktop and for OBS — with
per-character portraits that change with health state, temporary HP, damage
and healing animations, death saves and conditions. NPCs and monsters that
aren't on D&D Beyond can be added too.

---
DISCLAIMER
This project is uses the code from Power Word Spill's https://github.com/powerwordspill/healthbar but adapted to implement the health bars in a digital environment. With v.2.0.0 this project also abandoned the the idea of relying on session cookies to access private character data, and instead only works with public character sheets. The original project is no longer maintained, and this fork is intended to be a more secure and privacy-conscious alternative. Having a public character sheet is the only requirement to use this project, and it is recommended to set your character sheet to public on D&D Beyond for security reasons. If you use the old version which uses session cookies, you are at risk of exposing your D&D Beyond account to anyone who can read the cookie file.

This project was created with the help of Anthropic's Claude AI.
---

## Public characters only

The app reads **public** D&D Beyond character sheets anonymously — no login,
no cookies, nothing that could give anyone access to your account. On D&D
Beyond open the character → **Home → Privacy** and set it to **Public**.

The earlier "full edition", which stored a D&D Beyond session cookie (a full
login token) in a plain-text file, has been discontinued and removed for
security reasons.

---

## Download & install

Go to the [Releases](../../releases) page and download the file for your OS:

| OS      | File                       |
|---------|----------------------------|
| Windows | `DnD_HealthBar_Public.exe` |
| Linux   | `DnD_HealthBar_Public`     |

Put it in a folder of its own (e.g. `Documents\Health Bar`) and run it — no
installation, no Python required.

**"Windows protected your PC"?** The program isn't signed with a paid
certificate, so Windows SmartScreen may warn the first time you run a new
version. Click **More info → Run anyway**. The code is open source; the file's
properties show its name and version.

**Updating:** when a new version is out, a green bar appears in the app —
click **Update now** and it downloads the new version, replaces itself and
restarts. Your settings and portraits are not touched. (Or download it
manually and replace the file while the app is closed.)

### Everything in one folder

```
Health Bar\
  DnD_HealthBar_Public.exe
  dnd_healthbar_public.json      ← settings + characters
  dnd_healthbar_public.json.bak  ← automatic backup of the previous save
  dnd_healthbar.log              ← log file, useful when something goes wrong
  portraits\                     ← your portrait images
```

Portraits you choose are copied into `portraits\` and stored relative to the
folder, so you can move, rename, back up or sync (OneDrive, Proton Drive, …)
the whole folder. Settings are saved safely: if the file is ever damaged, the
app restores the backup automatically and keeps the damaged copy aside.

---

## Using the app

- **＋ next to the game name** adds a game (campaign). The app remembers which
  game you had open.
- **＋ Add character** adds a character:
  - **D&D Beyond character** — paste the character URL; HP comes from D&D Beyond.
  - **Manual — NPC, monster, companion** — enter max/current HP yourself.
    Click the HP badge to **damage / heal** (Enter = damage, Shift+Enter =
    heal; damage uses temporary HP first), or scroll the mouse wheel over the
    badge for ±1. Manual characters show on stream like everyone else.
- **▶** makes a character *live*: the overlay appears and follows HP. **■**
  stops it. **▶▶ Open all** / **■■ Close all** for the whole party.
- **⋯** (or right-click a row): add to OBS, copy overlay URL, preview, edit,
  copy diagnostics, delete. Double-click a character to edit it.
- The **HP** switch shows the numbers on the overlay.
- **⚙ Settings**: check interval (default 5 s), **colour-blind friendly
  colours**, **start with Windows** (minimised), update check, whether ✕ hides
  the app in the system tray, overlay port, open data folder / log file.
- Only one copy of the app runs at a time.

### Health states and portraits

| State      | When                                                   |
|------------|--------------------------------------------------------|
| Unscathed  | 100 %                                                  |
| Scratched  | 75 – 100 %                                             |
| Injured    | 50 – 75 %                                              |
| Bloodied   | 25 – 50 %                                              |
| Critical   | below 25 %                                             |
| Dying      | 0 HP, making death saves (uses the *Critical* portrait) |
| Stable     | 0 HP, stabilised                                       |
| Dead       | three failed death saves (manual NPCs: 0 HP)           |

Portraits are optional per state; a state without one uses the nearest state
that has one, and with none at all the character's **D&D Beyond avatar** is
used. Images are scaled to fit a square without cropping. "All" in the edit
dialog uses one image for every state.

### Something looks wrong?

**⋯ → Copy diagnostics** copies what D&D Beyond reports for that character
and what the app calculated from it — paste it into a GitHub issue. The log
file (⚙ → Open log file) helps too.

---

## Using with OBS Studio

The app serves each character as a small web page that OBS shows as a
**Browser Source**: transparent background, instant updates, works while the
app's windows are minimised, and scales to whatever size you give the source.

### Recommended: let the app add the sources

1. In OBS: **Tools → WebSocket Server Settings** → tick **Enable WebSocket
   server** → **Show Connect Info** shows the port and password.
2. In the app click **OBS**, enter port and password, click **Test & load
   scenes** and choose the scene (or leave *(current scene)*).
3. Click **Save & add each character** (one source per character) or **Save &
   add party source** (one source with the whole party side by side). Adding
   again updates the sources instead of duplicating them.
4. Press **▶** on a character — it fades in on stream; **■** fades it out.

The WebSocket password is stored in the settings file; it only grants control
of OBS on your own PC.

### Manual setup and options

Click **URLs ↗** for all overlay URLs with recommended sizes, then add a
**Browser** source in OBS.

| URL                                        | Shows                     |
|--------------------------------------------|---------------------------|
| `http://127.0.0.1:7777/overlay/<char id>`  | one character (280 × 340) |
| `http://127.0.0.1:7777/party/<game id>`    | the whole party           |

Add options to the URL, e.g. `…/party/a1b2c3d4?style=bar&layout=column`:

| Option            | Effect                                                    |
|-------------------|-----------------------------------------------------------|
| `style=bar`       | compact bars with names, no portraits — good for big groups |
| `name=1`          | show the name under the portrait                          |
| `layout=column`   | stack the party vertically                                |
| `card=1`          | dark card background, like the desktop window             |
| `always=1`        | stay visible even when the character isn't live           |
| `palette=cb`      | colour-blind friendly colours (or set it in ⚙ for everything) |
| `conditions=0`    | hide condition tags                                       |

### What the overlay shows

- HP bar in the state colour; **temporary HP** as a blue extension and `+N`.
- **Damage**: white trailing bar, red flash and a short shake. **Healing**:
  green glow.
- **Dying**: greyed portrait with a pulsing red glow and the death saves.
  **Stable** shows a badge; **dead** turns the portrait grey.
- **Conditions** such as Poisoned or Prone as small tags.

The server only listens on `127.0.0.1` (your own PC). If port 7777 is taken it
uses the next free one.

### Alternative: Window Capture

All the app's windows share the same window class, so OBS's default matching
falls back to the **manager** window when a character window isn't open yet.
If you use Window Capture, set **Window Match Priority → "Window title must
match"**. Overlay windows reopen where you left them.

---

## Config file (`dnd_healthbar_public.json`)

Normally edited through the app. Contains no D&D Beyond credentials.

```json
{
  "games": [
    {
      "id": "a1b2c3d4",
      "name": "My Campaign",
      "characters": [
        {
          "name": "Thorin", "character_id": "2222222", "source": "dndbeyond",
          "show_hp_numbers": false, "always_on_top": false, "opacity": 1.0,
          "window_pos": [100, 100],
          "portrait_unscathed": "portraits/Thorin_2222222/unscathed.png",
          "avatar": "portraits/Thorin_2222222/avatar.png"
        },
        {
          "name": "Goblin Boss", "character_id": "npc1a2b3c4d", "source": "manual",
          "max_hp": 21, "current_hp": 21, "temp_hp": 0
        }
      ]
    }
  ],
  "last_game": "a1b2c3d4",
  "poll_interval": 5,
  "palette": "default",
  "close_to_tray": false,
  "check_updates": true,
  "sort": { "mode": "alpha_asc", "live_on_top": true },
  "overlay_server": { "enabled": true, "port": 7777 },
  "obs": { "host": "127.0.0.1", "port": 4455, "password": "", "scene": "" }
}
```

---

## Development

```
pip install -r requirements-dev.txt
python dnd_healthbar_public.py        # run from source
python -m pytest tests                # run the tests
pyinstaller dnd_healthbar_public.spec # build the executable
```

Pushing a tag `vX.Y.Z` runs the tests, builds Windows and Linux binaries and
publishes a GitHub release with the matching section of
[CHANGELOG.md](CHANGELOG.md) as release notes.

```
dnd_healthbar_public.py     ← launcher (runs healthbar.app.main)
healthbar/
  config.py                 ← data folder, settings, portraits, logging
  theme.py                  ← colours, HP states, image helpers, icon
  ddb.py                    ← D&D Beyond API, HP maths, shared poller, NPCs
  overlay.py                ← browser-source server for OBS
  obs.py                    ← OBS WebSocket client
  updater.py                ← update check + self-update
  system.py                 ← autostart, screens, files
  app.py                    ← entry point
  ui/                       ← manager window, desktop overlay, dialogs, widgets
assets/                     ← icon
tests/                      ← pytest suite
dnd_healthbar_public.spec   ← PyInstaller build config
.github/                    ← CI workflow + release-notes script
```
