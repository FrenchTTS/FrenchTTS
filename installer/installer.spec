# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for FrenchTTSInstaller.exe.
#
# IMPORTANT: build order must be respected:
#   1. dist/FrenchTTS.exe           (main app)
#   2. dist/FrenchTTSUninstaller.exe (uninstaller)
#   3. installer/dist/FrenchTTSInstaller.exe  (this spec — bundles the above)
#
# Build (from project root):
#   python -m PyInstaller --clean installer\installer.spec --distpath installer\dist --workpath installer\build

a = Analysis(
    ['installer_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../dist/FrenchTTS.exe',              '.'),    # main application
        ('../dist/FrenchTTSUninstaller.exe',   '.'),    # uninstaller (extracted at install time)
        ('../dist/build_id.txt',               '.'),    # version string of the bundled build
        ('../img/icon.ico',                    'img'),  # PE icon / taskbar
        ('../img/icon.png',                    'img'),  # (reserved for future in-window display)
    ],
    hiddenimports=[],
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
