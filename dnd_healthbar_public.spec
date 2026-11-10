# dnd_healthbar_public.spec — PyInstaller build config
import os
import re
import sys

from PyInstaller.building.build_main import Analysis, EXE, PYZ

version = re.search(r'APP_VERSION\s*=\s*"([\d.]+)"',
                    open(os.path.join("healthbar", "__init__.py"), encoding="utf-8").read()).group(1)

a = Analysis(
    ['dnd_healthbar_public.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PIL._tkinter_finder',
        'requests',
        'websocket',         # OBS integration (websocket-client)
        'pystray',
        'pystray._win32',    # Windows tray backend
        'pystray._xorg',     # Linux tray backend
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# Windows file properties (Explorer → Properties → Details). Together with no
# UPX compression this makes antivirus false alarms less likely.
version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                     StringTable, VarFileInfo, VarStruct,
                                                     VSVersionInfo)
    v = tuple(int(x) for x in version.split(".")) + (0,) * (4 - len(version.split(".")))
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=v, prodvers=v, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
                  StringStruct("CompanyName", "DnD-Player-Healthbars (open source)"),
                  StringStruct("FileDescription", "D&D Health Bar - live HP overlay for D&D Beyond"),
                  StringStruct("FileVersion", version),
                  StringStruct("InternalName", "DnD_HealthBar_Public"),
                  StringStruct("LegalCopyright", "Open source - github.com/piosteiner/DnD-Player-Healthbars"),
                  StringStruct("OriginalFilename", "DnD_HealthBar_Public.exe"),
                  StringStruct("ProductName", "D&D Health Bar"),
                  StringStruct("ProductVersion", version)])]),
              VarFileInfo([VarStruct("Translation", [1033, 1200])])])

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DnD_HealthBar_Public',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX-packed executables trigger more antivirus false alarms
    runtime_tmpdir=None,
    console=False,           # no terminal window on Windows
    version=version_info,
    icon=os.path.join('assets', 'icon.ico') if sys.platform == 'win32' else None,
)
