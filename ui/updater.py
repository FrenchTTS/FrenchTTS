"""
FrenchTTS — auto-updater splash and self-replacement logic.

Windows locks an executable while it is running, so the process cannot
replace its own .exe directly. The workaround: download the new build
alongside the current one, write a .bat that waits for this process to
exit (2 s timeout), moves the new file over the old one, relaunches, and
then deletes itself.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import customtkinter as ctk

from core.constants import APP_NAME, APP_VERSION, GITHUB_REPO, _BTN_SECONDARY
from ui.utils import apply_window_transparency, _set_window_icon


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _version_tuple(v: str) -> tuple[int, ...]:
    """Convert a dotted version string to a comparable integer tuple.

    Uses only the stdlib so no ``packaging`` dependency is needed.

    Examples::

        _version_tuple("1.2.3") == (1, 2, 3)
        _version_tuple("1.10.0") > _version_tuple("1.9.0")  # True
    """
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------------------
# Self-replacement
# ---------------------------------------------------------------------------

def _apply_update(close_fn, new_exe: str) -> None:
    """Schedule a .bat-based self-replacement and close the current window.

    ``close_fn`` is called last so Tkinter releases the OS file lock before
    the .bat tries to overwrite the executable. Passing a callable (rather
    than the app object) keeps this function usable from any window.
    """
    current  = sys.executable
    bat_path = current + "_update.bat"
    bat_content = (
        "@echo off\n"
        "timeout /t 2 /nobreak >nul\n"
        f'move /y "{new_exe}" "{current}"\n'
        f'start "" "{current}"\n'
        'del "%~f0"\n'
    )
    try:
        with open(bat_path, "w", encoding="ascii") as f:
            f.write(bat_content)
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        return
    close_fn()


# ---------------------------------------------------------------------------
# Updater splash
# ---------------------------------------------------------------------------

class UpdaterSplash(ctk.CTk):
    """Lightweight splash shown before the main app window when running as .exe.

    Mirrors the Discord update pattern: the splash appears first, checks for a
    newer GitHub release, downloads and applies it silently if found, then either
    destroys itself so ``main()`` can open the main app (no update / error) or
    closes after scheduling the .bat swap (update applied — the .bat relaunches).

    Error states (no internet, server unreachable, download interrupted, asset
    missing) are surfaced to the user with a retry/skip prompt instead of
    silently falling through.

    ``_launch_app`` is read by ``main()`` after ``mainloop()`` returns to decide
    whether to create FrenchTTSApp.
    ``_pending_download`` stores the (url, size) of the asset so that "Réessayer"
    after a download failure re-downloads directly without re-running the API check.
    """

    def __init__(self):
        super().__init__()
        self._launch_app       = True   # False only when an update is applied
        self._pending_download = None   # (url, size) set once a download begins

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(APP_NAME)
        self.resizable(False, False)
        # Prevent accidental close mid-download (would leave a partial .exe on disk)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build()
        self._recenter()
        _set_window_icon(self)
        self.after(150, lambda: apply_window_transparency(self, 0.93))
        self.after(300, self._start_check)

    # --- Layout -------------------------------------------------------------

    def destroy(self) -> None:
        """Cancel all pending after() callbacks before destroying the window.

        CTk schedules internal polling callbacks (e.g. _check_dpi_scaling) that
        keep rescheduling themselves. If the window is destroyed while one of
        those is still queued, Tkinter raises "invalid command name" errors in
        the terminal. Cancelling every pending after ID first silences them.
        This is invisible in the built .exe (no console) but noisy in dev mode.
        """
        try:
            for after_id in self.tk.call("after", "info").split():
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        super().destroy()

    def _build(self) -> None:
        """Construct the splash: title, status label, progress bar, error panel."""
        self.columnconfigure(0, weight=1)
        self.configure(padx=40)

        ctk.CTkLabel(
            self, text=APP_NAME,
            font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, pady=(28, 6))

        self._status_lbl = ctk.CTkLabel(
            self,
            text="Vérification des mises à jour...",
            text_color=("gray50", "gray55"),
            font=ctk.CTkFont(size=11))
        self._status_lbl.grid(row=1, column=0, pady=(0, 14))

        # Indeterminate while checking; switches to determinate while downloading
        self._progress = ctk.CTkProgressBar(self, mode="indeterminate", width=240)
        self._progress.grid(row=2, column=0, pady=(0, 28))
        self._progress.start()

        # Error panel — hidden initially; shown when a retryable failure occurs
        self._error_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._error_frame.columnconfigure(0, weight=1)

        self._error_lbl = ctk.CTkLabel(
            self._error_frame, text="",
            text_color=("#c0392b", "#e05555"),
            font=ctk.CTkFont(size=11),
            wraplength=260, justify="center")
        self._error_lbl.grid(row=0, column=0, pady=(0, 12))

        btn_row = ctk.CTkFrame(self._error_frame, fg_color="transparent")
        btn_row.grid(row=1, column=0)
        ctk.CTkButton(
            btn_row, text="Réessayer", width=110,
            command=self._on_retry
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="Continuer sans mise à jour", width=190,
            **_BTN_SECONDARY,
            command=self._on_skip
        ).grid(row=0, column=1)

        # Pre-place in the grid but hide immediately so it takes no space
        self._error_frame.grid(row=3, column=0, pady=(0, 22))
        self._error_frame.grid_remove()

    def _recenter(self) -> None:
        """Recompute the window size and re-center on screen.

        Called after layout changes (initial render, error panel appearing/
        disappearing) so the window never clips its content.
        """
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 320)
        h = self.winfo_reqheight()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # --- Error state --------------------------------------------------------

    def _show_error(self, message: str) -> None:
        """Switch the splash into error state with a Réessayer / Continuer prompt."""
        self._progress.stop()
        self._progress.grid_remove()
        self._status_lbl.configure(text="")
        self._error_lbl.configure(text=message)
        self._error_frame.grid()
        self.after(0, self._recenter)

    def _on_retry(self) -> None:
        """Reset to the checking state and resume from where the failure occurred."""
        self._error_frame.grid_remove()
        self._status_lbl.configure(text="Vérification des mises à jour...")
        self._progress.configure(mode="indeterminate")
        self._progress.grid()
        self._progress.start()
        self.after(0, self._recenter)
        # If we failed mid-download, skip the API check and retry the download directly
        if self._pending_download:
            url, size = self._pending_download
            threading.Thread(
                target=self._download, args=(url, size), daemon=True).start()
        else:
            self._start_check()

    def _on_skip(self) -> None:
        """Dismiss the splash and open the main app without updating."""
        self._launch_app = True
        self.destroy()

    # --- Update check -------------------------------------------------------

    def _start_check(self) -> None:
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        """Fetch the latest GitHub release on a background thread.

        In dev test mode (``--update`` flag without ``sys.frozen``) the API is
        bypassed and a fake update is simulated so the full UI flow — including
        progress animation and error states — can be exercised locally.
        """
        if "--update" in sys.argv and not getattr(sys, "frozen", False):
            time.sleep(0.6)   # mimic API round-trip
            t = _version_tuple(APP_VERSION)
            fake_tag = ".".join(str(x) for x in (t[:-1] + (t[-1] + 1,)))
            self.after(0, lambda: self._status_lbl.configure(
                text=f"Mise à jour v{fake_tag} en cours..."))
            self._simulate_download()
            return

        # --- Real check -----------------------------------------------------
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
        except OSError:
            # urllib.error.URLError is a subclass of OSError; covers no internet,
            # DNS failure, and connection refused.
            self.after(0, lambda: self._show_error(
                "Impossible de vérifier les mises à jour.\n"
                "Vérifiez votre connexion internet."))
            return
        except Exception:
            self.after(0, lambda: self._show_error(
                "Erreur inattendue lors de la vérification."))
            return

        try:
            tag = data["tag_name"].lstrip("v")
        except (KeyError, AttributeError):
            # Malformed API response — treat as up to date
            self.after(0, lambda: self._status_lbl.configure(text="À jour."))
            self.after(600, self.destroy)
            return

        if _version_tuple(tag) > _version_tuple(APP_VERSION):
            asset = next(
                (a for a in data.get("assets", [])
                 if a["name"] == f"{APP_NAME}.exe"),
                None)
            if asset is None:
                self.after(0, lambda: self._show_error(
                    f"Mise à jour v{tag} disponible,\n"
                    "mais le fichier est introuvable sur le serveur."))
                return
            dl_url  = asset["browser_download_url"]
            dl_size = asset.get("size", 0)
            self.after(0, lambda: self._status_lbl.configure(
                text=f"Mise à jour v{tag} en cours..."))
            self._pending_download = (dl_url, dl_size)
            self._download(dl_url, dl_size)
            return

        # Already on the latest version
        self.after(0, lambda: self._status_lbl.configure(text="À jour."))
        self.after(600, self.destroy)

    # --- Download -----------------------------------------------------------

    def _download(self, url: str, total_size: int) -> None:
        """Download the release asset in 8 KB chunks (runs on the check thread)."""
        exe_dir = os.path.dirname(sys.executable)
        new_exe = os.path.join(exe_dir, f"{APP_NAME}_new.exe")
        self.after(0, lambda: self._progress.stop())
        self.after(0, lambda: self._progress.configure(mode="determinate"))
        self.after(0, lambda: self._progress.set(0))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
            with urllib.request.urlopen(req, timeout=60) as resp:
                downloaded = 0
                with open(new_exe, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = downloaded / total_size
                            self.after(0, lambda p=pct: self._set_progress(p))
        except OSError:
            self.after(0, lambda: self._show_error(
                "Téléchargement interrompu.\n"
                "Vérifiez votre connexion internet."))
            return
        except Exception:
            self.after(0, lambda: self._show_error(
                "Erreur lors du téléchargement."))
            return

        # Success — clear the pending marker, then apply or simulate
        self._pending_download = None
        if getattr(sys, "frozen", False):
            self._launch_app = False
            self.after(0, lambda: _apply_update(self.destroy, new_exe))
        else:
            # Dev mode: show result without touching any executable
            self.after(0, lambda: self._status_lbl.configure(
                text="[Test] Mise à jour simulée."))
            self.after(1200, self.destroy)

    def _simulate_download(self) -> None:
        """Animate the progress bar over ~2 s without a real download (dev mode)."""
        self.after(0, lambda: self._progress.stop())
        self.after(0, lambda: self._progress.configure(mode="determinate"))
        self.after(0, lambda: self._progress.set(0))
        steps = 40
        for i in range(1, steps + 1):
            frac  = i / steps
            delay = int(i * 2000 / steps)
            self.after(delay, lambda p=frac: self._set_progress(p))
        self.after(2200, lambda: self._status_lbl.configure(text="[Test] Mise à jour simulée."))
        self.after(3200, self.destroy)

    def _set_progress(self, fraction: float) -> None:
        """Update the progress bar and status label (main thread only)."""
        self._progress.set(fraction)
        self._status_lbl.configure(text=f"Mise à jour... {int(fraction * 100)} %")
