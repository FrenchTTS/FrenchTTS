"""
FrenchTTSInstaller — installer and update helper.

FrenchTTS.exe and FrenchTTSUninstaller.exe are bundled inside this exe via
PyInstaller --add-data.

First-install mode (no args, user double-click):
  Shows a dark CTk splash matching the FrenchTTS DA.
  Extracts bundled FrenchTTS.exe + FrenchTTSUninstaller.exe to INSTALL_DIR,
  creates a Desktop shortcut and a Start Menu folder, then launches the app.

Update mode (called by the running FrenchTTS.exe auto-updater):
  FrenchTTSInstaller.exe --pid PID --target CURRENT_EXE_PATH
  Headless — no UI. Waits for PID to exit (Win32 WaitForSingleObject),
  extracts bundled FrenchTTS.exe from sys._MEIPASS, copies it to CURRENT_EXE_PATH,
  refreshes FrenchTTSUninstaller.exe alongside it, then relaunches.
"""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time

APP_NAME    = "FrenchTTS"
INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
START_MENU_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME)


# ---------------------------------------------------------------------------
# Shared helpers
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


def _bundled(name: str) -> str:
    """Absolute path to a file inside the PyInstaller _MEIPASS directory."""
    return os.path.join(sys._MEIPASS, name)


def _create_shortcut(target: str, lnk_path: str) -> None:
    """Create a Windows .lnk shortcut via PowerShell (best-effort)."""
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk_path}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.IconLocation = '{target},0'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-Command", ps],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _force_taskbar(window) -> None:
    """Apply WS_EX_APPWINDOW so a borderless window appears in the taskbar."""
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        GWL_EXSTYLE      = -20
        WS_EX_APPWINDOW  = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Update mode  (headless, no UI)
# ---------------------------------------------------------------------------

def _do_update(pid: int, target: str) -> None:
    """Wait for the old process, swap FrenchTTS.exe, refresh the uninstaller."""
    _wait_pid(pid)
    _copy_retry(_bundled(f"{APP_NAME}.exe"), target)

    # Refresh the uninstaller alongside the app exe (best-effort)
    uninst_src = _bundled(f"{APP_NAME}Uninstaller.exe")
    if os.path.isfile(uninst_src):
        uninst_dst = os.path.join(os.path.dirname(target), f"{APP_NAME}Uninstaller.exe")
        _copy_retry(uninst_src, uninst_dst)

    if os.path.isfile(target):
        subprocess.Popen([target], creationflags=subprocess.DETACHED_PROCESS)


# ---------------------------------------------------------------------------
# Install mode  (CTk splash, matching FrenchTTS DA)
# ---------------------------------------------------------------------------

def _do_install() -> None:
    """Show a dark splash, run steps, launch the installed app."""
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # ── Window ───────────────────────────────────────────────────────────────
    splash = ctk.CTk()
    splash.title(f"{APP_NAME} — Installation")
    splash.overrideredirect(True)
    splash.resizable(False, False)
    splash.protocol("WM_DELETE_WINDOW", lambda: None)
    splash.configure(padx=40)

    # Size: same width as updater splash; auto-height from content
    splash.geometry("360x1")
    splash.update_idletasks()

    splash.after(150, lambda: splash.wm_attributes("-alpha", 0.93))
    splash.after(200, lambda: _force_taskbar(splash))

    # ── Cancel pending after() callbacks on close (silence CTk internals) ────
    _orig_destroy = splash.destroy

    def _destroy() -> None:
        try:
            for aid in splash.tk.call("after", "info").split():
                try:
                    splash.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        _orig_destroy()

    splash.destroy = _destroy

    # ── Drag (borderless window) ─────────────────────────────────────────────
    drag = {"x": 0, "y": 0}

    def _drag_start(e):
        drag["x"] = e.x_root - splash.winfo_x()
        drag["y"] = e.y_root - splash.winfo_y()

    def _drag_move(e):
        splash.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    # ── Layout ───────────────────────────────────────────────────────────────
    splash.columnconfigure(0, weight=1)

    title_lbl = ctk.CTkLabel(
        splash, text=APP_NAME,
        font=ctk.CTkFont(size=20, weight="bold"),
    )
    title_lbl.grid(row=0, column=0, pady=(28, 6))
    title_lbl.bind("<ButtonPress-1>", _drag_start)
    title_lbl.bind("<B1-Motion>",     _drag_move)

    status_lbl = ctk.CTkLabel(
        splash, text="Cliquez sur Installer pour commencer.",
        text_color=("gray50", "gray55"),
        font=ctk.CTkFont(size=11),
    )
    status_lbl.grid(row=1, column=0, pady=(0, 14))

    bar = ctk.CTkProgressBar(splash, mode="determinate", width=240)
    bar.set(0)
    bar.grid(row=2, column=0, pady=(0, 14))

    install_btn = ctk.CTkButton(splash, text="Installer", width=140)
    install_btn.grid(row=3, column=0, pady=(0, 28))

    # Resize to fit content now that all widgets are placed
    splash.update_idletasks()
    h = splash.winfo_reqheight()
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    splash.geometry(f"360x{h}+{(sw - 360) // 2}+{(sh - h) // 2}")

    # ── Installation paths ───────────────────────────────────────────────────
    target_exe      = os.path.join(INSTALL_DIR, f"{APP_NAME}.exe")
    target_uninst   = os.path.join(INSTALL_DIR, f"{APP_NAME}Uninstaller.exe")
    desktop_lnk     = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
    sm_app_lnk      = os.path.join(START_MENU_DIR, f"{APP_NAME}.lnk")
    sm_uninst_lnk   = os.path.join(START_MENU_DIR, f"Désinstaller {APP_NAME}.lnk")

    uninst_src = _bundled(f"{APP_NAME}Uninstaller.exe")

    STEPS = [
        ("Copie de FrenchTTS.exe…",
         lambda: _copy_retry(_bundled(f"{APP_NAME}.exe"), target_exe)),

        ("Copie du désinstalleur…",
         lambda: _copy_retry(uninst_src, target_uninst) if os.path.isfile(uninst_src) else None),

        ("Raccourci Bureau…",
         lambda: _create_shortcut(target_exe, desktop_lnk)),

        ("Menu Démarrer…", lambda: (
            os.makedirs(START_MENU_DIR, exist_ok=True),
            _create_shortcut(target_exe,    sm_app_lnk),
            _create_shortcut(target_uninst, sm_uninst_lnk) if os.path.isfile(uninst_src) else None,
        )),
    ]

    # ── Worker thread ────────────────────────────────────────────────────────
    def _worker() -> None:
        try:
            os.makedirs(INSTALL_DIR, exist_ok=True)
            n = len(STEPS)
            for i, (msg, fn) in enumerate(STEPS):
                splash.after(0, lambda m=msg: status_lbl.configure(text=m))
                fn()
                frac = (i + 1) / n
                splash.after(0, lambda p=frac: bar.set(p))
                time.sleep(0.2)

            splash.after(0, lambda: status_lbl.configure(text="Installation terminée !"))
            splash.after(0, lambda: bar.set(1.0))
            splash.after(900, lambda: (
                subprocess.Popen([target_exe], creationflags=subprocess.DETACHED_PROCESS),
                splash.destroy(),
            ))
        except Exception as exc:
            splash.after(0, lambda e=str(exc): _on_error(e))

    def _on_error(msg: str) -> None:
        status_lbl.configure(text=f"Erreur : {msg}")
        bar.set(0)
        install_btn.configure(state="normal")

    def _start() -> None:
        install_btn.configure(state="disabled")
        status_lbl.configure(text="Installation en cours…")
        threading.Thread(target=_worker, daemon=True).start()

    install_btn.configure(command=lambda: splash.after(50, _start))
    splash.mainloop()


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
