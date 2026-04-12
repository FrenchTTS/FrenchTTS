# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for FrenchTTSInstaller.exe.
#
# IMPORTANT: build order must be respected:
#   1. dist/FrenchTTS.exe              (main app)
#   2. dist/FrenchTTSUninstaller.exe   (uninstaller)
#   3. dist/build_id.txt               (version string)
#   4. installer/dist/FrenchTTSInstaller.exe  (this spec — bundles the above)
#
# Build (from project root):
#   python -m PyInstaller --clean installer\installer.spec --distpath installer\dist --workpath installer\build

from PyInstaller.utils.hooks import collect_all

# Collect customtkinter fully: theme JSON files, internal modules, dark-detect dep.
ctk_datas, ctk_bins, ctk_hidden = collect_all('customtkinter')

# Collect PIL (Pillow): CTk uses it internally for image rendering.
pil_datas, pil_bins, pil_hidden = collect_all('PIL')

a = Analysis(
    ['installer_main.py'],
    pathex=[],
    binaries=ctk_bins + pil_bins,
    datas=[
        ('../dist/FrenchTTS.exe',              '.'),    # main application
        ('../dist/FrenchTTSUninstaller.exe',   '.'),    # uninstaller (extracted at install time)
        ('../dist/build_id.txt',               '.'),    # version string of the bundled build
        ('../img/icon.ico',                    'img'),  # PE icon / taskbar
        ('../img/icon.png',                    'img'),  # in-window icon image
    ] + ctk_datas + pil_datas,
    hiddenimports=ctk_hidden + pil_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FrenchTTSInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['../img/icon.ico'],
)
