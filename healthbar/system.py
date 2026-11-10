"""Operating-system helpers: autostart, screens, files, bundled resources."""
import logging
import os
import sys
import urllib.parse
import webbrowser

from . import APP_NAME

log = logging.getLogger("dnd_healthbar")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def resource_path(rel: str) -> str:
    """Path of a file bundled with the app (PyInstaller) or in the repo."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


# ── Start with Windows (per-user, no admin rights needed) ───────────────────
def autostart_supported() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def autostart_command(exe: str | None = None) -> str:
    return f'"{exe or sys.executable}" --minimized'


def get_autostart(name: str = APP_NAME) -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool, name: str = APP_NAME, command: str | None = None):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command or autostart_command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


def refresh_autostart_path(name: str = APP_NAME):
    """If autostart is on but the program moved, point it at the new place."""
    if not autostart_supported() or not get_autostart(name):
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            current, _ = winreg.QueryValueEx(k, name)
        if current != autostart_command():
            set_autostart(True, name)
    except OSError as e:
        log.warning("Could not update autostart entry: %s", e)


# ── Screens / files ─────────────────────────────────────────────────────────
def virtual_screen(widget) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the whole desktop across all monitors."""
    if sys.platform == "win32":
        try:
            import ctypes
            gsm = ctypes.windll.user32.GetSystemMetrics
            return gsm(76), gsm(77), gsm(78), gsm(79)
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def position_on_screen(widget, x: int, y: int, width: int = 280) -> bool:
    vx, vy, vw, vh = virtual_screen(widget)
    return vx - width + 60 <= x <= vx + vw - 60 and vy <= y <= vy + vh - 60


def open_path(path: str):
    """Open a folder or file with the system's default program."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                                  # noqa: S606
        else:
            webbrowser.open("file://" + urllib.parse.quote(os.path.abspath(path)))
    except Exception as e:
        log.warning("Could not open %s: %s", path, e)
