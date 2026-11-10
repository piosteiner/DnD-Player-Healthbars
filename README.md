# D&D Beyond Live Health Bar

Live HP overlay synced to D&D Beyond — for your desktop and for OBS — with
per-character portraits that change with health state, temporary HP, damage
and healing animations, death saves and conditions.

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
installation, no Python required. The app tells you when a new version is
available.

**Updating:** close the app (✕ quits it) and replace the program file. Your
settings and portraits are not touched.

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
the whole folder and everything keeps working. Settings are saved safely: if
the file is ever damaged, the app restores the backup automatically and keeps
the damaged copy aside.

---

## Using the app

- **＋ next to the game name** adds a game (campaign); **＋ Add character**
  adds a character — paste the D&D Beyond character URL.
- **▶** makes a character *live*: HP is fetched from D&D Beyond and the overlay
  appears. **■** stops it. **▶▶ Open all** / **■■ Close all** for the whole party.
- **⋯** (or right-click a row): add to OBS, copy overlay URL, preview, edit,
  delete. Double-click a character to edit it.
- The **HP** switch shows the numbers on the overlay.
- **⚙ Settings**: how often D&D Beyond is checked (default every 5 s), whether
  ✕ hides the app in the system tray instead of quitting, update check, overlay
  port, and buttons to open the data folder and the log file.
- Only one copy of the app runs at a time.

### Portraits

Optional, per health state:

| State      | HP range   |
|------------|------------|
| Unscathed  | 100 %      |
| Scratched  | 75 – 100 % |
| Injured    | 50 – 75 %  |
| Bloodied   | 25 – 50 %  |
| Critical   |  0 – 25 %  |
| Dead       | 0 %        |

A state without an image uses the nearest state that has one; with no images
at all, the character's **D&D Beyond avatar** is used. Images are scaled to
fit a square without cropping — square images look best. "All" in the edit
dialog uses one image for every state.

---

## Using with OBS Studio

The app serves each character as a small web page that OBS shows as a
**Browser Source**: transparent background, works while the app's windows are
minimised or covered, and scales to whatever size you give the source.

### Recommended: let the app add the sources

1. In OBS: **Tools → WebSocket Server Settings** → tick **Enable WebSocket
   server** → **Show Connect Info** shows the port and password.
2. In the app click **OBS**, enter port and password, click **Test & load
   scenes** and choose the scene (or leave *(current scene)*).
3. Click **Save & add each character** (one source per character, which you
   can arrange freely) or **Save & add party source** (one source with the
   whole party side by side). Sources are named `HP Overlay - <name>` /
   `HP Party - <game>`; adding again updates them instead of duplicating.
   Single characters can also be added via **⋯ → Add to OBS**.
4. Press **▶** on a character — it fades in on stream and updates instantly;
   **■** fades it out.

The WebSocket password is stored in the settings file; it only grants control
of OBS on your own PC.

### Manual

Click **URLs ↗** for all overlay URLs with the recommended sizes, then in OBS
add **Sources → + → Browser** with that URL and size.

| URL                                        | Shows                    |
|--------------------------------------------|--------------------------|
| `http://127.0.0.1:7777/overlay/<char id>`  | one character (280 × 340) |
| `http://127.0.0.1:7777/party/<game id>`    | the whole party          |

| Option            | Effect                                          |
|-------------------|-------------------------------------------------|
| `?card=1`         | dark card background, like the desktop window   |
| `?always=1`       | stay visible even when the character isn't live |
| `?layout=column`  | stack the party vertically                      |
| `?conditions=0`   | hide condition tags                             |

### What the overlay shows

- HP bar in the health-state colour; **temporary HP** as a blue extension
  and `+N` next to the numbers.
- On **damage** a white trailing bar, red flash and a short shake; on
  **healing** a green glow.
- At **0 HP** the portrait turns grey and **death saves** appear
  (or *STABLE*).
- **Conditions** such as Poisoned or Prone as small tags.

The server only listens on `127.0.0.1` (your own PC). If port 7777 is taken
it uses the next free one (up to 7786).

### Alternative: Window Capture

All the app's windows share the same window class and program, so OBS's
default matching falls back to the **manager** window when a character window
isn't open yet. If you use Window Capture, set **Window Match Priority →
"Window title must match"** in the source's properties. Overlay windows reopen
where you last left them.

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
          "name": "Thorin",
          "character_id": "2222222",
          "show_hp_numbers": false,
          "always_on_top": false,
          "opacity": 1.0,
          "window_pos": [100, 100],
          "portrait_unscathed": "portraits/Thorin_2222222/unscathed.png",
          "portrait_injured": "portraits/Thorin_2222222/injured.png",
          "avatar": "portraits/Thorin_2222222/avatar.png"
        }
      ]
    }
  ],
  "poll_interval": 5,
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
dnd_healthbar_public.py       ← full source
dnd_healthbar_public.spec     ← PyInstaller build config
tests/                        ← pytest suite
requirements*.txt             ← dependencies
CHANGELOG.md                  ← release notes
.github/workflows/build.yml   ← tests, builds, releases
```
