"""Entry point: settings, single instance, overlay server, main window."""
import logging
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

from PIL import ImageTk

from . import APP_VERSION, config, overlay, system, theme
from .ui.common import pump_ui_queue
from .ui.manager import ManagerWindow

log = logging.getLogger("dnd_healthbar")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    minimized    = "--minimized" in argv
    after_update = "--after-update" in argv

    config.setup_logging()
    cfg, notices = config.load_config()
    srv = cfg.setdefault("overlay_server", {"enabled": True, "port": overlay.DEFAULT_PORT})
    try:
        port = int(srv.get("port", overlay.DEFAULT_PORT))
    except (TypeError, ValueError):
        port = overlay.DEFAULT_PORT

    if after_update:                     # the old version may still be shutting down
        deadline = time.monotonic() + 20
        while overlay.app_already_running(port) and time.monotonic() < deadline:
            time.sleep(0.5)
        log.info("Started after update to %s", APP_VERSION)

    # Single instance: the first copy may be hidden in the system tray.
    if overlay.app_already_running(port):
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("D&D Health Bar",
                            "D&D Health Bar is already running.\n\nIf you can't see it, look in the "
                            "system tray (bottom-right, near the clock) — right-click the icon and "
                            "choose Show.")
        r.destroy()
        return

    if config.migrate_config(cfg):
        log.info("Config migrated to version %s", config.CONFIG_VERSION)
        config.save_config(cfg)
    config.apply_settings(cfg)
    overlay.HUB.sync_config(cfg)
    if srv.get("enabled", True):
        overlay.start_server(port)
    system.refresh_autostart_path()

    root = tk.Tk()
    try:
        icon = ImageTk.PhotoImage(theme.make_icon(64))
        root.iconphoto(True, icon)       # also used by every other window
        root._icon = icon
    except tk.TclError:
        pass
    app = ManagerWindow(root, cfg)
    app._setup_tray()
    root.after(50, pump_ui_queue, root)
    for note in notices:
        root.after(300, lambda n=note: messagebox.showwarning("D&D Health Bar", n, parent=root))
    if after_update:
        root.after(500, lambda: app.flash_status(f"✓ Updated to version {APP_VERSION}", theme.OK_FG, 8000))
    if minimized:
        root.after(100, app.start_minimized)
    root.after(1500, app.check_updates_async)
    root.mainloop()
    log.info("Exiting")
    logging.shutdown()
    os._exit(0)          # make sure no background thread keeps the process alive
