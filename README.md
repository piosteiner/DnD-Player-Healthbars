# D&D Health Bar

Live HP overlay synced to D&D Beyond, with per-character portraits that
change based on health state.

---

## Downloading a release (no Python needed)

Go to the [Releases](../../releases) page of this repository and download
the file for your OS:

| OS      | File                |
|---------|---------------------|
| Windows | `DnD_HealthBar.exe` |
| Linux   | `DnD_HealthBar`     |

Run it directly — no installation required.  
On first launch it creates **`dnd_healthbar.json`** next to the binary.
This is your config file and is never overwritten by updates.

---

## Setting up the repository (one-time)

1. [Create a new GitHub repository](https://github.com/new) (can be private).
2. Upload these files to the root of the repo:
   ```
   dnd_healthbar.py
   dnd_healthbar.spec
   .github/workflows/build.yml
   README.md
   ```
3. That's it. GitHub Actions is now configured.

---

## Publishing a new release (how to trigger a build)

Whenever you want to ship a new version:

1. Update `APP_VERSION = "x.y.z"` in `dnd_healthbar.py`.
2. Commit and push the file to GitHub.
3. Create and push a matching version tag:
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
4. GitHub Actions automatically:
   - Builds `DnD_HealthBar.exe` on a Windows runner
   - Builds `DnD_HealthBar` on a Linux runner
   - Creates a Release page with both files attached

The build takes about 3–5 minutes. Check the **Actions** tab on GitHub
to watch progress or see any errors.

---

## Updating the app (for end users)

1. Go to the [Releases](../../releases) page.
2. Download the new binary for your OS.
3. Replace the old binary with the new one.

Your `dnd_healthbar.json` config is **never affected** by updates.

---

## Config file (`dnd_healthbar.json`)

Lives next to the executable. Editable in any text editor.

```json
{
  "games": [
    {
      "id":   "1234567",
      "name": "My Campaign",
      "characters": [
        {
          "name":               "Thorin",
          "user_id":            "1111111",
          "character_id":       "2222222",
          "cookie_header":      "CobaltSession=...",
          "always_on_top":      false,
          "portrait_unscathed": "/path/to/full.png",
          "portrait_scratched": "/path/to/scratched.png",
          "portrait_injured":   "/path/to/injured.png",
          "portrait_bloodied":  "/path/to/bloodied.png",
          "portrait_critical":  "/path/to/critical.png",
          "portrait_dead":      "/path/to/dead.png"
        }
      ]
    }
  ]
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

Portraits are all optional. If a state has no portrait the app falls back
to the nearest healthier state that does have one.

### Cookie header

Copy the `Cookie:` value from your browser's DevTools Network tab while
on D&D Beyond. It may change over time — re-enter it in the character
settings dialog if the connection stops working.

---

## Project layout

```
dnd_healthbar.py           ← full source
dnd_healthbar.spec         ← PyInstaller build config
.github/
  workflows/
    build.yml              ← GitHub Actions CI/CD
README.md                  ← this file
```
