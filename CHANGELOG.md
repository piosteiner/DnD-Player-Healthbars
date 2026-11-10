# Changelog

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
