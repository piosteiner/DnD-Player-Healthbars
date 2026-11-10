"""D&D Health Bar — live HP overlays for public D&D Beyond characters.

Modules
  config     data folder, settings file, portraits, logging
  theme      colours, HP states, image helpers
  ddb        D&D Beyond API, HP maths, shared poller, manual characters
  overlay    browser-source server for OBS
  obs        OBS WebSocket client
  updater    update check + one-click self-update
  system     Windows helpers (autostart, screens, resources)
  ui/        Tk user interface
  app        entry point
"""

APP_NAME    = "D&D Health Bar"
APP_VERSION = "2.3.0"
GITHUB_REPO = "piosteiner/DnD-Player-Healthbars"
