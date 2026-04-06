"""
FrenchTTS — window utilities and Windows acrylic blur.

All helpers here are pure utilities with no dependency on other local modules,
so any UI file can import them without risk of circular imports.
"""

import ctypes
import os
import sys

import customtkinter as ctk
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
