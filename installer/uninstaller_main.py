"""
FrenchTTSUninstaller — removes FrenchTTS and all its associated files.

Uses only Win32 MessageBoxW (via ctypes stdlib) for dialogs — no tkinter,
no customtkinter — so the bundled exe stays as small as possible.

Removes:
  - INSTALL_DIR  (%LOCALAPPDATA%\\FrenchTTS)   via a temp .bat (self-exe lock)
  - APPDATA_DIR  (%APPDATA%\\FrenchTTS)         config, history, STT models
  - Desktop shortcut
  - Start Menu folder

The INSTALL_DIR (which contains this exe) is deleted by a temp .bat that runs
after this process exits, sidestepping the Windows file-lock on a running exe.
"""

import ctypes
import os
import shutil
import subprocess
import tempfile

APP_NAME = "FrenchTTS"

INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
APPDATA_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
START_MENU_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME)
DESKTOP_LNK = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")

_u32 = ctypes.windll.user32
MB_OK            = 0x0
MB_YESNO         = 0x4
MB_ICONQUESTION  = 0x20
MB_ICONINFO      = 0x40
MB_ICONERROR     = 0x10
IDYES = 6


def _msgbox(text: str, title: str = APP_NAME, flags: int = MB_ICONINFO | MB_OK) -> int:
    return _u32.MessageBoxW(0, text, title, flags)


def _confirm() -> bool:
    return _msgbox(
        f"Voulez-vous vraiment désinstaller {APP_NAME} ?\n\n"
        "Cela supprimera l'application, ses fichiers de configuration\n"
        "et les modèles STT téléchargés.",
        f"Désinstaller {APP_NAME}",
        MB_YESNO | MB_ICONQUESTION,
    ) == IDYES


def _kill_app() -> None:
    """Terminate any running FrenchTTS.exe instance (best-effort)."""
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", f"{APP_NAME}.exe"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _remove(path: str) -> None:
    """Remove a file or directory tree, ignoring errors."""
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _schedule_install_dir_removal() -> None:
    """Write a temp .bat that deletes INSTALL_DIR after this process exits.

    Necessary because this exe lives inside INSTALL_DIR — Windows holds a
    file lock on a running exe so rd /s /q would fail immediately.
    The batch waits ~2 s (via ping) for the lock to be released, then deletes
    the directory and self-destructs.
    """
    bat = (
        "@echo off\r\n"
        "ping -n 3 127.0.0.1 > nul\r\n"
        f'rd /s /q "{INSTALL_DIR}"\r\n'
        'del "%~f0"\r\n'
    )
    try:
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="frenchtts_rm_")
        with os.fdopen(fd, "w", encoding="ascii", errors="replace") as f:
            f.write(bat)
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        pass


def main() -> None:
    if not _confirm():
        return

    _kill_app()
    _remove(DESKTOP_LNK)
    _remove(START_MENU_DIR)
    _remove(APPDATA_DIR)

    _msgbox(f"{APP_NAME} a été désinstallé avec succès.")
    _schedule_install_dir_removal()


if __name__ == "__main__":
    main()
