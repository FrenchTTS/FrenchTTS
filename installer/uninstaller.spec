# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for FrenchTTSUninstaller.exe.
#
# Uses only stdlib + ctypes — no customtkinter, no tkinter — so the output exe
# is as small as possible (this exe is bundled inside FrenchTTSInstaller.exe).
#
# Build (from project root):
#   python -m PyInstaller --clean installer\uninstaller.spec --distpath dist --workpath build\uninstaller

a = Analysis(
    ['uninstaller_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'PIL', 'numpy'],
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
    name='FrenchTTSUninstaller',
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
