"""
FrenchTTSInstaller — installer and update helper.

FrenchTTS.exe, FrenchTTSUninstaller.exe and build_id.txt are bundled inside
this exe via PyInstaller --add-data.

First-install mode  (no args, user double-click, no existing install):
  Shows a dark CTk splash — Install UI.
  Extracts bundled FrenchTTS.exe + FrenchTTSUninstaller.exe to INSTALL_DIR,
  creates a Desktop shortcut and a Start Menu folder, then launches the app.

Reinstall / manual-update mode  (no args, existing installation found):
  Same CTk splash — Update UI.
  Shows current installed version → new version.
  Replaces the exe and uninstaller in INSTALL_DIR, refreshes shortcuts.

Silent update mode  (called by the running app auto-updater):
  FrenchTTSInstaller.exe --pid PID --target CURRENT_EXE_PATH
  Headless — no UI. Waits for PID to exit, swaps FrenchTTS.exe, refreshes
  the uninstaller alongside it, then relaunches the app.
"""

import argparse
import ctypes
import json
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


def _new_version() -> str:
    """Read the version of the bundled FrenchTTS.exe from build_id.txt."""
    try:
        with open(_bundled("build_id.txt"), encoding="utf-8") as f:
            v = f.read().strip()
        return f"prod-{v}" if v and v != "dev" else "dev"
    except Exception:
        return ""


def _installed_version() -> str:
    """Read the currently installed version from the app's config.json."""
    try:
        cfg = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            APP_NAME, "config.json")
        with open(cfg, encoding="utf-8") as f:
            data = json.load(f)
        # "version" key is written by _save_settings; fall back to last_seen_version
        v = data.get("version") or data.get("last_seen_version") or ""
        if not v or v == "dev":
            return ""
        return f"prod-{v}" if not v.startswith("prod-") else v
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Silent update mode  (headless, no UI)
# ---------------------------------------------------------------------------

def _do_update(pid: int, target: str) -> None:
    """Wait for the old process, swap FrenchTTS.exe, refresh the uninstaller."""
    _wait_pid(pid)
    _copy_retry(_bundled(f"{APP_NAME}.exe"), target)

    # Refresh uninstaller alongside the app exe (best-effort)
    uninst_src = _bundled(f"{APP_NAME}Uninstaller.exe")
    if os.path.isfile(uninst_src):
        uninst_dst = os.path.join(os.path.dirname(target), f"{APP_NAME}Uninstaller.exe")
        _copy_retry(uninst_src, uninst_dst)

    if os.path.isfile(target):
        subprocess.Popen([target], creationflags=subprocess.DETACHED_PROCESS)


# ---------------------------------------------------------------------------
# Interactive install / update mode  (CTk splash, matching FrenchTTS DA)
# ---------------------------------------------------------------------------

def _do_install() -> None:
    """Show a dark CTk splash and run the install or reinstall steps."""
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # ── Detect mode ──────────────────────────────────────────────────────────
    target_exe      = os.path.join(INSTALL_DIR, f"{APP_NAME}.exe")
    target_uninst   = os.path.join(INSTALL_DIR, f"{APP_NAME}Uninstaller.exe")
    desktop_lnk     = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
    sm_app_lnk      = os.path.join(START_MENU_DIR, f"{APP_NAME}.lnk")
    sm_uninst_lnk   = os.path.join(START_MENU_DIR, f"Désinstaller {APP_NAME}.lnk")
    uninst_src      = _bundled(f"{APP_NAME}Uninstaller.exe")

    is_update = os.path.isfile(target_exe)
    new_v     = _new_version()
    cur_v     = _installed_version() if is_update else ""

    if is_update:
        win_title   = f"{APP_NAME} — Mise à jour"
        if cur_v and new_v:
            init_status = f"{cur_v}  →  {new_v}"
        elif new_v:
            init_status = f"→  {new_v}"
        else:
            init_status = "Cliquez sur Mettre à jour pour commencer."
        btn_label   = "Mettre à jour"
    else:
        win_title   = f"{APP_NAME} — Installation"
        init_status = "Cliquez sur Installer pour commencer."
        btn_label   = "Installer"

    # ── Window ───────────────────────────────────────────────────────────────
    splash = ctk.CTk()
    splash.title(win_title)
    splash.overrideredirect(True)
    splash.resizable(False, False)
    splash.protocol("WM_DELETE_WINDOW", lambda: None)
    splash.configure(padx=40)
    splash.geometry("360x1")

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

    # ── Drag — whole window draggable (all non-interactive widgets + canvas) ─
    drag = {"x": 0, "y": 0}

    def _drag_start(e):
        drag["x"] = e.x_root - splash.winfo_x()
        drag["y"] = e.y_root - splash.winfo_y()

    def _drag_move(e):
        splash.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    # Bind drag to the CTk internal canvas (window background) + every widget
    # that doesn't need its own click handling.
    def _bind_drag(*widgets):
        for w in widgets:
            try:
                w.bind("<ButtonPress-1>", _drag_start, add="+")
                w.bind("<B1-Motion>",     _drag_move,  add="+")
            except Exception:
                pass

    # ── Layout ───────────────────────────────────────────────────────────────
    splash.columnconfigure(0, weight=1)

    title_lbl = ctk.CTkLabel(
        splash, text=APP_NAME,
        font=ctk.CTkFont(size=20, weight="bold"),
    )
    title_lbl.grid(row=0, column=0, pady=(28, 6))

    status_lbl = ctk.CTkLabel(
        splash, text=init_status,
        text_color=("gray50", "gray55"),
        font=ctk.CTkFont(size=11),
    )
    status_lbl.grid(row=1, column=0, pady=(0, 14))

    bar = ctk.CTkProgressBar(splash, mode="determinate", width=240)
    bar.set(0)
    bar.grid(row=2, column=0, pady=(0, 14))

    action_btn = ctk.CTkButton(splash, text=btn_label, width=140)
    action_btn.grid(row=3, column=0, pady=(0, 28))

    # Resize window to fit actual content height, then center on screen
    splash.update_idletasks()
    h = splash.winfo_reqheight()
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    splash.geometry(f"360x{h}+{(sw - 360) // 2}+{(sh - h) // 2}")

    # Bind drag AFTER widgets are built (so CTk canvas exists)
    splash.after(10, lambda: _bind_drag(splash, splash._canvas if hasattr(splash, '_canvas') else splash,
                                        title_lbl, status_lbl, bar))

    # ── Installation steps ───────────────────────────────────────────────────
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

            done = "Mise à jour terminée !" if is_update else "Installation terminée !"
            splash.after(0, lambda: status_lbl.configure(text=done))
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
        action_btn.configure(state="normal")

    def _start() -> None:
        action_btn.configure(state="disabled")
        status_lbl.configure(text="En cours…")
        threading.Thread(target=_worker, daemon=True).start()

    action_btn.configure(command=lambda: splash.after(50, _start))
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
