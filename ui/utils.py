"""
FrenchTTS — window utilities and Windows acrylic blur.

All helpers here are pure utilities with no dependency on other local modules,
so any UI file can import them without risk of circular imports.
"""

import ctypes
import os
import sys
import threading
import time

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _get_icon_path() -> str | None:
    """Return the absolute path to ``img/icon.ico``, or None if not found.

    When running as a PyInstaller one-file bundle, all bundled data is
    extracted to ``sys._MEIPASS`` at launch. When running from source the
    path is resolved relative to this file's parent so the working directory
    does not matter.
    """
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "img", "icon.ico")
    return path if os.path.exists(path) else None


def _safe_iconbitmap(window, path: str) -> None:
    """Call ``iconbitmap`` without raising — some Tkinter builds reject .ico."""
    try:
        window.iconbitmap(path)
    except Exception:
        pass


def _set_window_icon(window) -> None:
    """Schedule ``iconbitmap`` on any CTk window with the correct delay.

    CTkToplevel internally calls ``iconbitmap("")`` roughly 200 ms after
    construction to reset its icon to the CTk default. A plain ``after(0)``
    call therefore loses the race. Using 450 ms for CTkToplevel instances
    reliably wins it; 80 ms is sufficient for the main CTk window which
    does not have this internal reset behaviour.
    """
    ico = _get_icon_path()
    if not ico:
        return
    delay = 450 if isinstance(window, ctk.CTkToplevel) else 80
    window.after(delay, lambda: _safe_iconbitmap(window, ico))


def _safe_open(path: str) -> None:
    """Open ``path`` with its default OS handler (Explorer on Windows).

    Used to open the config folder from the settings window. The try/except
    is a no-op guard for headless or sandboxed environments.
    """
    try:
        os.startfile(path)
    except Exception:
        pass


def make_tray_image() -> Image.Image:
    """Draw a fallback tray icon with Pillow when ``img/icon.ico`` is absent.

    The icon is a simple microphone silhouette on a blue circle, sized 64×64
    as required by most system tray implementations.
    """
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(70, 130, 200, 255))
    draw.rounded_rectangle([24, 12, 40, 36], radius=8, fill=(255, 255, 255, 220))
    draw.arc([18, 28, 46, 46], start=0, end=180, fill=(255, 255, 255, 220), width=3)
    draw.line([32, 46, 32, 54], fill=(255, 255, 255, 220), width=3)
    draw.line([24, 54, 40, 54], fill=(255, 255, 255, 220), width=3)
    return img


# ---------------------------------------------------------------------------
# Windows acrylic blur
#
# ``SetWindowCompositionAttribute`` is an undocumented Win32 API available
# from Windows 10 build 1803 onward. We use attribute 19 (WCA_ACCENT_POLICY)
# with accent state 4 (ACCENT_ENABLE_ACRYLICBLURBEHIND).
#
# GradientColor is an ABGR 32-bit integer. The default 0xD0202020 gives a
# semi-transparent dark overlay (alpha=0xD0 ≈ 82%) on top of the blur.
#
# The entire call is wrapped in try/except so the app runs gracefully on
# builds that do not support the API (older Win10, Wine, etc.).
# ---------------------------------------------------------------------------

class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState",   ctypes.c_uint),
                ("AccentFlags",   ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId",   ctypes.c_uint)]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_uint),
                ("pData",     ctypes.c_void_p),
                ("cbData",    ctypes.c_size_t)]


def _apply_acrylic(hwnd: int, color_abgr: int = 0xD0202020) -> None:
    """Push an ACCENT_ENABLE_ACRYLICBLURBEHIND policy to a Win32 HWND."""
    try:
        accent = _AccentPolicy()
        accent.AccentState   = 4           # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = color_abgr
        data = _WinCompAttrData()
        data.Attribute = 19                # WCA_ACCENT_POLICY
        data.pData     = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.cbData    = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass


def send_notification(title: str, message: str) -> None:
    """Show a one-shot balloon notification via a temporary tray icon.

    Creates a pystray icon, fires the notification, then destroys the icon
    after 5 seconds.  The worker thread is intentionally non-daemon so the
    notification can outlive ``main()`` returning — needed when the updater
    closes the splash and the process is about to exit.
    """
    ico        = _get_icon_path()
    icon_image = Image.open(ico) if ico and os.path.exists(ico) else make_tray_image()

    def _worker() -> None:
        try:
            icon = pystray.Icon(title, icon_image, title)

            def _setup(ic: pystray.Icon) -> None:
                time.sleep(0.4)          # wait for shell registration
                ic.notify(message, title)
                time.sleep(5)            # keep icon alive for notification duration
                ic.stop()

            icon.run(setup=_setup)       # blocking; returns when _setup calls stop()
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=False).start()


def force_taskbar_presence(window) -> None:
    """Force a window to appear in the Windows taskbar.

    Needed for two cases:
    - ``overrideredirect(True)`` windows (no native titlebar): Windows omits
      them from the taskbar unless ``WS_EX_APPWINDOW`` is explicitly set.
    - ``transient()`` toplevels: Tkinter's transient call sets an owner HWND,
      which causes Windows to suppress the taskbar button by default.

    ``SetWindowPos`` with ``SWP_FRAMECHANGED`` tells the shell to re-evaluate
    the extended style without moving or resizing the window.
    """
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


def apply_window_transparency(window, opacity: float) -> None:
    """Set window alpha and, when opacity < 1.0, enable acrylic blur.

    Passing opacity=1.0 is the 'disabled' state: the window is fully opaque
    and ``_apply_acrylic`` is never called, so there is no residual blur.

    Note: ``GetParent`` is used instead of ``winfo_id`` directly because
    Tkinter embeds its canvas in a child HWND; the acrylic effect must be
    applied to the top-level frame HWND to work correctly.
    """
    alpha = round(max(0.1, min(1.0, opacity)), 2)
    window.wm_attributes("-alpha", alpha)
    if alpha < 0.999:
        try:
            _apply_acrylic(ctypes.windll.user32.GetParent(window.winfo_id()))
        except Exception:
            pass
