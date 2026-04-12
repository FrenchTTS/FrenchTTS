# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for FrenchTTSInstaller.exe.
#
# IMPORTANT: FrenchTTS.exe must be built first (dist/FrenchTTS.exe exists)
# before this spec can be used.  build.bat and the CI workflow enforce this order.

a = Analysis(
    ['installer_main.py'],
    pathex=[],
    binaries=[],
    datas=[('../dist/FrenchTTS.exe', '.')],  # bundle the main app inside the installer
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
