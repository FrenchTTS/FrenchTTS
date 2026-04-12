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


def _set_dark_titlebar(hwnd: int) -> None:
    """Apply the immersive dark title bar on Windows 10 build 18985+."""
    try:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
    except Exception:
        pass


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
    """First-install mode: dark-themed installer matching the FrenchTTS DA."""
    import tkinter as tk
    import tkinter.ttk as ttk
    from tkinter import messagebox

    # --- Window --------------------------------------------------------------
    root = tk.Tk()
    root.title(f"{APP_NAME} — Installation")
    root.resizable(False, False)
    root.configure(bg="#1c1c1c")

    WIN_W, WIN_H = 380, 210
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{WIN_W}x{WIN_H}+{(sw - WIN_W) // 2}+{(sh - WIN_H) // 2}")

    # Dark title bar
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    _set_dark_titlebar(hwnd)

    # Window icon (.ico — shown in taskbar and title bar)
    ico_path = os.path.join(sys._MEIPASS, "img", "icon.ico")
    if os.path.isfile(ico_path):
        try:
            root.iconbitmap(ico_path)
        except Exception:
            pass

    # --- In-window icon image (48×48) ---------------------------------------
    icon_img = None
    png_path = os.path.join(sys._MEIPASS, "img", "icon.png")
    if os.path.isfile(png_path):
        try:
            from PIL import Image as _Img, ImageTk as _ITk
            pil = _Img.open(png_path).resize((48, 48), _Img.LANCZOS)
            icon_img = _ITk.PhotoImage(pil)
        except Exception:
            pass

    # --- Progress bar style -------------------------------------------------
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "FT.Horizontal.TProgressbar",
        troughcolor="#2c2c2c",
        background="#3a7ebf",
        darkcolor="#3a7ebf",
        lightcolor="#3a7ebf",
        bordercolor="#2c2c2c",
    )

    # --- Layout -------------------------------------------------------------
    header = tk.Frame(root, bg="#1c1c1c")
    header.pack(pady=(24, 8))

    if icon_img:
        lbl_icon = tk.Label(header, image=icon_img, bg="#1c1c1c")
        lbl_icon.image = icon_img   # prevent GC
        lbl_icon.pack(side="left", padx=(0, 10))

    tk.Label(
        header, text=APP_NAME,
        font=("Segoe UI", 14, "bold"),
        fg="#ffffff", bg="#1c1c1c",
    ).pack(side="left")

    status_var = tk.StringVar(value="Cliquez sur Installer pour commencer.")
    tk.Label(
        root, textvariable=status_var,
        font=("Segoe UI", 9),
        fg="#888888", bg="#1c1c1c",
    ).pack(pady=(0, 8))

    bar = ttk.Progressbar(
        root, length=300, mode="indeterminate",
        style="FT.Horizontal.TProgressbar",
    )
    bar.pack(pady=(0, 14))

    install_btn = tk.Button(
        root, text="Installer",
        font=("Segoe UI", 9, "bold"),
        bg="#3a7ebf", fg="#ffffff",
        activebackground="#2e6da4", activeforeground="#ffffff",
        relief="flat", padx=24, pady=7, cursor="hand2", bd=0,
    )
    install_btn.pack()

    # --- Install logic ------------------------------------------------------
    def _run() -> None:
        install_btn.configure(state="disabled")
        bar.start()
        status_var.set("Installation en cours...")
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

            status_var.set("Installation terminée !")
            bar.stop()
            bar.configure(mode="determinate")
            bar["value"] = 100
            root.after(900, lambda: (
                subprocess.Popen([target], creationflags=subprocess.DETACHED_PROCESS),
                root.destroy(),
            ))
        except Exception as exc:
            bar.stop()
            install_btn.configure(state="normal")
            status_var.set(f"Erreur : {exc}")
            messagebox.showerror("Erreur d'installation", str(exc), parent=root)

    install_btn.configure(command=lambda: root.after(50, _run))
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
