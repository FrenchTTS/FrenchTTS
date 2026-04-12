"""
FrenchTTSInstaller — installer and update helper.

FrenchTTS.exe is bundled inside this exe via PyInstaller --add-data.

First-install mode (no args, user double-click):
  Extracts bundled FrenchTTS.exe → installs to %LOCALAPPDATA%\\FrenchTTS\\
  → creates a desktop shortcut → launches it.

Update mode (called by the running FrenchTTS.exe auto-updater):
  FrenchTTSInstaller.exe --pid PID --target CURRENT_EXE_PATH
  Waits for PID to exit (Win32 WaitForSingleObject), extracts bundled
  FrenchTTS.exe from sys._MEIPASS, copies it to CURRENT_EXE_PATH, relaunches.
"""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time

APP_NAME    = "FrenchTTS"
INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    APP_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_pid(pid: int, timeout_ms: int = 30_000) -> None:
    """Block until the given Windows process exits (or timeout elapses)."""
    SYNCHRONIZE = 0x00100000
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        k32.WaitForSingleObject(handle, timeout_ms)
        k32.CloseHandle(handle)


def _copy_retry(src: str, dst: str, attempts: int = 10) -> None:
    """Copy src → dst, retrying up to ``attempts`` times on OSError."""
    for _ in range(attempts):
        try:
            shutil.copy2(src, dst)
            return
        except OSError:
            time.sleep(0.4)


def _bundled_exe() -> str:
    """Absolute path to FrenchTTS.exe inside our PyInstaller _MEIPASS."""
    return os.path.join(sys._MEIPASS, f"{APP_NAME}.exe")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _do_update(pid: int, target: str) -> None:
    """Update mode: wait for old process, swap exe, relaunch."""
    _wait_pid(pid)
    _copy_retry(_bundled_exe(), target)
    if os.path.isfile(target):
        subprocess.Popen([target], creationflags=subprocess.DETACHED_PROCESS)


def _do_install() -> None:
    """First-install mode: show a minimal UI, extract bundled exe, create shortcut."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title(f"{APP_NAME} — Installation")
    root.resizable(False, False)
    root.geometry("360x145")

    tk.Label(
        root, text=f"Installation de {APP_NAME}",
        font=("Segoe UI", 11, "bold")
    ).pack(pady=(18, 4))

    status = tk.StringVar(value="Prêt.")
    tk.Label(root, textvariable=status, font=("Segoe UI", 9)).pack()

    bar = ttk.Progressbar(root, length=300, mode="indeterminate")
    bar.pack(pady=8)

    def _run() -> None:
        bar.start()
        status.set("Installation en cours...")
        try:
            os.makedirs(INSTALL_DIR, exist_ok=True)
            target = os.path.join(INSTALL_DIR, f"{APP_NAME}.exe")
            shutil.copy2(_bundled_exe(), target)

            # Desktop shortcut via PowerShell (best-effort)
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            lnk = os.path.join(desktop, f"{APP_NAME}.lnk")
            ps = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{lnk}'); "
                f"$s.TargetPath = '{target}'; $s.Save()"
            )
            subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            status.set("Installation terminée !")
            bar.stop()
            root.after(800, lambda: (
                subprocess.Popen([target], creationflags=subprocess.DETACHED_PROCESS),
                root.destroy(),
            ))
        except Exception as exc:
            bar.stop()
            messagebox.showerror("Erreur d'installation", str(exc))
            root.destroy()

    tk.Button(
        root, text="Installer", font=("Segoe UI", 9),
        command=lambda: root.after(50, _run),
    ).pack(pady=(0, 12))

    root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--pid",    type=int, default=None)
    ap.add_argument("--target", default=None)
    args, _ = ap.parse_known_args()

    if args.pid is not None and args.target is not None:
        _do_update(args.pid, args.target)
    else:
        _do_install()


if __name__ == "__main__":
    main()
