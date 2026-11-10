# Changelog

## 2.3.1

First release of the 2.3 line (the 2.3.0 build stopped at a failing test and
was never published). Includes everything below plus:

- Fix: "Start with Windows" now works on profiles where Windows' autostart
  registry key doesn't exist yet.

**New**
- **Manual characters** for NPCs, monsters and companions that aren't on
  D&D Beyond: set max HP, then damage / heal from the app (click the HP badge,
  or mouse wheel ±1). Damage uses temporary HP first. They show on stream like
  everyone else.
- **One-click update**: "Update now" downloads the new version (checked
  against GitHub's checksum), replaces the program and restarts.
- **Start with Windows** (minimised) — in ⚙ Settings.
- **Colour-blind friendly colours** (blue → yellow → orange → magenta) for the
  app and the overlays — in ⚙ Settings, or `?palette=cb` per overlay.
- New overlay options: **`style=bar`** (compact bars with names, no portraits —
  great for big parties) and **`name=1`** (name under the portrait).
- **Copy diagnostics** (⋯ menu) collects what D&D Beyond reports for a
  character, for troubleshooting.
- The app remembers the **last selected game**.
- New app icon; the .exe now carries proper version information.

**Changed**
- **0 HP is no longer "dead"**: a character at 0 HP is *dying* (Critical
  portrait, pulsing red glow, death saves) or *stable*, and only *dead* after
  three failed death saves. Manual NPCs die at 0 HP.
- All live characters are checked by **one shared connection** — fewer
  requests to D&D Beyond with a full party.
- The .exe is no longer UPX-compressed, which makes antivirus false alarms
  less likely.

**Under the hood**
- The code is split into modules (`healthbar/` package); 40 automated tests,
  including an end-to-end check of the self-update.

## 2.2.0

**OBS**
- **Add overlays to OBS automatically** via OBS's built-in WebSocket server
  (**OBS** button in the header) — one source per character, or one
  **party source** with the whole group side by side.
- Overlays update **instantly** (server-sent events) instead of once a second.
- Overlays scale to fit any source size — nothing gets cut off any more.

**On stream**
- **Temporary HP** is shown as a blue segment and `+N` instead of being added
  to max HP (no more "55 / 55" for a 50 HP character with 5 temp HP).
- **Damage and healing are animated**: a trailing bar, red flash and shake on
  hits, green glow on heals. At 0 HP the portrait turns grey and **death
  saves** appear; **conditions** (Poisoned, Prone, …) are shown as tags
  (`?conditions=0` hides them).
- The **D&D Beyond avatar** is used automatically for characters without
  portraits.

**Your data**
- **Portable folder**: portraits are stored relative to the app folder and new
  ones are copied into `portraits/`, so the folder can be moved, renamed or
  synced. Existing settings are converted automatically.
- **Safe saving**: settings are written atomically with an automatic `.bak`
  backup. A damaged settings file is restored from the backup and kept aside
  instead of being overwritten.
- A **log file** (`dnd_healthbar.log`) records problems; failed saves are shown
  in the app.

**App**
- **Update notice** when a new version is on GitHub.
- **Settings** (⚙): check interval, close-to-tray, update check, overlay port,
  open data folder / log file.
- Tidier character rows: ▶ plus a **⋯ menu** (or right-click) for OBS, URL,
  edit and delete; double-click to edit; **tooltips** everywhere; Enter/Esc in
  dialogs.
- Character dialog shows **portrait previews**, "use for all states" and clear
  buttons, and explains how to make a private character public.
- Gentler retries: waits grow (5 s → 2 min) on errors, D&D Beyond rate limits
  are respected, and private characters show a clear message.
- Faster lists thanks to cached thumbnails.

**Fixes**
- HP sort crashed for characters without HP data.

**Project**
- Tests run on GitHub before every release; release notes come from this file.
- Removed the discontinued cookie-based edition.

## 2.1.1

- Closing the manager really quits (hiding to the tray is opt-in).
- Only one copy of the app can run; the overlay port can't be shared.

## 2.1.0

- OBS browser-source overlays served by the app.
- Overlay windows remember their position.
- Max HP includes per-level bonuses (Tough, Hill Dwarf, Draconic Resilience).
- Many fixes (error messages, HP sort, transparent portraits, thread safety).
