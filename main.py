"""
FrenchTTS — Realistic French neural TTS for Windows.

Architecture overview
---------------------
The application is intentionally kept in a single file to make it easy for
contributors to understand end-to-end without jumping between modules.

Threading model
~~~~~~~~~~~~~~~
Tkinter is single-threaded by design; every UI mutation must happen on the
main thread. TTS generation and audio playback are async/IO-bound operations
that cannot block the main thread. The solution used here:

  1. ``_run_worker(coro_factory)`` spawns a daemon thread.
  2. That thread creates its own asyncio event loop (``asyncio.new_event_loop``)
     because the main thread's loop — if any — belongs to Tkinter internals.
  3. All callbacks that touch widgets are posted back via ``self.after(0, fn)``.
  4. ``threading.Event`` (``_stop_event``) is the shared stop signal; it is
     checked at every yield point inside the async coroutines.

Audio pipeline
~~~~~~~~~~~~~~
  edge-tts stream  →  MP3 bytearray (in RAM)  →  miniaudio decode  →
  numpy int16 PCM  →  sounddevice non-blocking play

No temporary files are created during playback. The only intentional disk
write is ``history/last.mp3``, which persists the last generated audio so
the replay feature works across sessions.

Adding a new voice
~~~~~~~~~~~~~~~~~~
Add an entry to the ``VOICES`` dict at the top of this file:

    "Display Name (fr-FR)": "fr-FR-SomeNeural",

The display name appears in the settings dropdown; the value is passed
directly to ``edge_tts.Communicate``. Run ``edge-tts --list-voices`` to
discover available voice IDs.

Transparency / acrylic blur
~~~~~~~~~~~~~~~~~~~~~~~~~~~
The blur effect uses the undocumented ``SetWindowCompositionAttribute`` Win32
API (attribute 19, ``WCA_ACCENT_POLICY``). It works on Windows 10 build 1803+
and Windows 11. On unsupported builds the call is silently ignored — the
window stays visible, just without blur. ``opacity = 1.0`` skips the API call
entirely, acting as a soft "disabled" state.

PyInstaller bundle
~~~~~~~~~~~~~~~~~~
Run ``build.bat``. The entire ``img/`` directory is bundled via
``--add-data "img;img"``. At runtime, ``_get_icon_path`` resolves against
``sys._MEIPASS`` when frozen, and against ``__file__`` otherwise.
"""

import asyncio
import ctypes
import ctypes.wintypes
import datetime
import json
import os
import sys
import threading
import webbrowser

import keyboard
import customtkinter as ctk
import edge_tts
import miniaudio
import numpy as np
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths
#
# All user data lives under %APPDATA%\FrenchTTS so the app never writes
# next to its own executable (important for UAC-restricted installs and
# the PyInstaller bundle, which may unpack to Program Files).
# ---------------------------------------------------------------------------

APPDATA     = os.environ.get("APPDATA", os.path.expanduser("~"))
BASE_DIR    = os.path.join(APPDATA, "FrenchTTS")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
LAST_MP3    = os.path.join(HISTORY_DIR, "last.mp3")   # overwritten each generation
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
HISTORY_LOG = os.path.join(HISTORY_DIR, "lasts.log")  # JSON array of past texts
os.makedirs(BASE_DIR,    exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keys are the display names shown in the settings dropdown.
# Values are passed verbatim to edge_tts.Communicate as the ``voice`` param.
# Run ``edge-tts --list-voices | grep fr-FR`` to discover additional voices.
VOICES: dict[str, str] = {
    # Female
    "Denise (fr-FR)":  "fr-FR-DeniseNeural",
    "Eloise (fr-FR)":  "fr-FR-EloiseNeural",
    # Male
    "Henri (fr-FR)":   "fr-FR-HenriNeural",
    "Alain (fr-FR)":   "fr-FR-AlainNeural",
    "Claude (fr-FR)":  "fr-FR-ClaudeNeural",
    "Jerome (fr-FR)":  "fr-FR-JeromeNeural",
    "Maurice (fr-FR)": "fr-FR-MauriceNeural",
    "Yves (fr-FR)":    "fr-FR-YvesNeural",
}

# Single source of truth for the application name and public URL.
# Change these two lines to rebrand the entire app.
APP_NAME = "FrenchTTS"
APP_URL  = "https://frenchtts.github.io"

STATUS_READY   = "Prêt"
STATUS_LOADING = "Chargement..."
STATUS_PLAYING = "En cours..."
STATUS_ERROR   = "Erreur"

# Maximum number of past texts kept in memory and persisted to lasts.log.
# Raising this has negligible RAM impact (plain strings) but keeps the
# JSON file small and the Up/Down navigation snappy.
MAX_HISTORY = 100

# Merged into the on-disk config at load time so missing keys always have
# a safe fallback without wiping the user's existing preferences.
DEFAULT_SETTINGS: dict = {
    "voice":      list(VOICES.keys())[0],
    "device":     "",    # empty → auto-select (prefers VB-Cable if found)
    "rate":       0,     # percent offset, e.g. +20 = 20% faster
    "volume":     100,   # 0–100; converted to a signed edge-tts offset at runtime
    "pitch":      0,     # Hz offset, e.g. -10 = 10 Hz lower
    "opacity":    0.93,  # 1.0 = fully opaque (acrylic disabled)
    "replay_key": "F2",  # Tkinter keysym, e.g. "F2", "F5" — also used as keyboard lib hotkey
    "stop_key":   "F3",  # same format; triggers Arrêter globally
}

# Ghost-style button appearance reused for secondary actions in both windows.
# Stored as a dict so it can be unpacked with ** into CTkButton calls,
# keeping the button declarations DRY without a wrapper function.
_BTN_SECONDARY = dict(
    fg_color=("gray75", "#2c2c2c"),
    hover_color=("gray65", "#383838"),
    border_width=1,
    border_color=("gray60", "#454545"),
)

# ---------------------------------------------------------------------------
# Formatters
#
# edge-tts expects signed string params like "+20%", "-10Hz".
# These converters are passed directly to _slider_row so the live label
# always shows the same representation that gets sent to the API.
# ---------------------------------------------------------------------------

def _fmt_signed(v: int, unit: str) -> str:
    """Return a signed string such as '+20%' or '-10Hz'."""
    return f"+{v}{unit}" if v >= 0 else f"{v}{unit}"

fmt_rate   = lambda v: _fmt_signed(int(v), "%")
fmt_pitch  = lambda v: _fmt_signed(int(v), "Hz")
fmt_volume = lambda v: f"{int(v)}%"

# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    """Decode raw MP3 bytes into a (pcm, sample_rate) pair.

    Uses miniaudio so there is no dependency on ffmpeg or any system codec.
    Output is always mono int16 PCM at 24 000 Hz, which matches the sample
    rate used by edge-tts and avoids a resample step in sounddevice.
    """
    decoded = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000)
    return np.frombuffer(decoded.samples, dtype=np.int16), decoded.sample_rate

# ---------------------------------------------------------------------------
# Window utilities
# ---------------------------------------------------------------------------

def _get_icon_path() -> str | None:
    """Return the absolute path to ``img/icon.ico``, or None if not found.

    When running as a PyInstaller one-file bundle, all bundled data is
    extracted to ``sys._MEIPASS`` at launch. When running from source the
    path is resolved relative to this file so the working directory does
    not matter.
    """
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.abspath(__file__))
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
    as required by most system tray implementations. This is only used if the
    user has not provided an icon.ico, so it is intentionally minimal.
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
# Reduce the alpha byte for a more transparent look.
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
    This avoids needing a separate toggle — the slider range (0.4–1.0) is
    enough to express both states.

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

# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------

class SettingsWindow(ctk.CTkToplevel):
    """Non-modal settings panel that shares Tkinter vars with FrenchTTSApp.

    All sliders and menus write directly into the app's StringVar / IntVar /
    DoubleVar instances, so changes take effect immediately without an
    explicit "Apply" step. The only actions that require explicit handlers are
    opacity (must also update the window blur) and the hotkey capture (needs
    a temporary KeyPress grab).

    The window auto-sizes to its content via ``update_idletasks`` +
    ``winfo_reqheight`` so adding new rows does not require adjusting a
    hard-coded height constant.
    """

    def __init__(self, app: "FrenchTTSApp"):
        super().__init__(app)
        self._app = app
        self.title(f"Paramètres — {APP_NAME}")
        # Start at height=1 so the window does not flash at the wrong size
        # before we measure and fix it after _build().
        self.geometry("460x1")
        self.transient(app)           # always on top of the main window
        self._capturing_key = False   # guard against re-entrant key capture
        # State used during key capture; set by _start_key_capture
        self._capture_var  = None
        self._capture_lbl  = None
        self._capture_btn  = None
        self._capture_post = None
        self._build()
        self.update_idletasks()
        self.geometry(f"460x{self.winfo_reqheight()}")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _set_window_icon(self)
        self.after(50,  self.lift)
        # Delay transparency so the window is fully drawn first; applying it
        # immediately sometimes causes a transparent flash on slower machines.
        self.after(120, lambda: apply_window_transparency(self, self._app.opacity_var.get()))

    # --- Layout -------------------------------------------------------------

    def _build(self) -> None:
        """Populate the settings grid.

        Layout uses three columns:
          col 0  fixed-width (minsize=140) for labels — ensures all labels
                 share the same left edge regardless of text length.
          col 1  stretchy for controls (sliders, menus).
          col 2  narrow for auxiliary buttons (device refresh).

        ``LBL`` and ``CTL`` dicts are grid kwargs applied to every label and
        control respectively, making horizontal alignment consistent across
        all rows with a single change here.
        """
        self.columnconfigure(0, minsize=140, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)

        LBL = dict(padx=(20, 8), pady=7, sticky="w")
        CTL = dict(padx=(0, 16), pady=7)

        ctk.CTkLabel(self, text="Paramètres",
                     font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, pady=(16, 10))

        # --- Voice selector -------------------------------------------------
        ctk.CTkLabel(self, text="Voix :").grid(row=1, column=0, **LBL)
        ctk.CTkOptionMenu(self, variable=self._app.voice_var,
                          values=list(VOICES.keys())
                          ).grid(row=1, column=1, columnspan=2, sticky="ew", **CTL)

        # --- Audio output device --------------------------------------------
        # The refresh button re-queries sounddevice so hotplugged devices
        # (e.g. a USB headset plugged in after launch) appear without restart.
        ctk.CTkLabel(self, text="Sortie :").grid(row=2, column=0, **LBL)
        self.device_menu = ctk.CTkOptionMenu(self, variable=self._app.device_var, values=[])
        self.device_menu.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=7)
        ctk.CTkButton(self, text="↺", width=32,
                      command=lambda: self._app._populate_devices(widget=self.device_menu)
                      ).grid(row=2, column=2, padx=(0, 16), pady=7)
        self._app._populate_devices(widget=self.device_menu)

        # --- Voice parameter sliders ----------------------------------------
        # Each row is (grid_row, label_text, tkvar, min, max, formatter).
        # Adding a new slider only requires adding a tuple here.
        for row, label, var, lo, hi, fmt in [
            (3, "Vitesse :", self._app.rate_var,   -50,  100, fmt_rate),
            (4, "Volume :",  self._app.volume_var,   0,  100, fmt_volume),
            (5, "Pitch :",   self._app.pitch_var,  -100, 100, fmt_pitch),
        ]:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, **LBL)
            self._slider_row(row=row, var=var, from_=lo, to=hi, fmt=fmt)

        self._separator(row=6)

        # --- Opacity slider --------------------------------------------------
        # Range 0.4–1.0. At exactly 1.0 the acrylic call is skipped, acting
        # as a clean "off" state (see apply_window_transparency).
        ctk.CTkLabel(self, text="Opacité :").grid(row=7, column=0, **LBL)
        op_frame = ctk.CTkFrame(self, fg_color="transparent")
        op_frame.grid(row=7, column=1, columnspan=2, sticky="ew", **CTL)
        op_frame.columnconfigure(0, weight=1)
        self._opacity_lbl = ctk.CTkLabel(
            op_frame, text=f"{int(self._app.opacity_var.get() * 100)}%",
            width=40, anchor="w")
        ctk.CTkSlider(op_frame, from_=0.4, to=1.0,
                      variable=self._app.opacity_var,
                      command=self._on_opacity_change
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._opacity_lbl.grid(row=0, column=1)

        # --- Hotkey capture rows --------------------------------------------
        # Both rows share the same _start_key_capture mechanism. The caller
        # passes the target var, label widget, and a post-capture callback
        # so the same handler works for any hotkey without duplication.
        self._replay_key_lbl, self._replay_key_btn = self._hotkey_row(
            row=8, label="Touche Redire :",
            var=self._app.replay_key_var,
            post_fn=lambda: (self._app._bind_replay_key(),
                             self._app._bind_global_hotkeys()),
            lbl_kw=LBL, ctl_kw=CTL)

        self._stop_key_lbl, self._stop_key_btn = self._hotkey_row(
            row=9, label="Touche Arrêter :",
            var=self._app.stop_key_var,
            post_fn=lambda: (self._app._bind_stop_key(),
                             self._app._bind_global_hotkeys()),
            lbl_kw=LBL, ctl_kw=CTL)

        self._separator(row=10)

        # --- Footer buttons -------------------------------------------------
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=11, column=0, columnspan=3, pady=(10, 14))
        ctk.CTkButton(btn_frame, text="Dossier config", width=140,
                      **_BTN_SECONDARY,
                      command=lambda: _safe_open(BASE_DIR)
                      ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Fermer", width=120,
                      command=self.destroy
                      ).grid(row=0, column=1)

    def _hotkey_row(self, row: int, label: str, var: ctk.StringVar,
                    post_fn, lbl_kw: dict, ctl_kw: dict):
        """Build a hotkey capture row and return (key_label, change_button).

        Reused for both the replay and stop hotkeys. ``post_fn`` is called
        after a new key is captured; it should rebind Tkinter and global hooks.
        """
        ctk.CTkLabel(self, text=label).grid(row=row, column=0, **lbl_kw)
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", **ctl_kw)
        key_lbl = ctk.CTkLabel(
            frame, text=var.get(),
            font=ctk.CTkFont(size=13, weight="bold"), width=60, anchor="w")
        key_lbl.grid(row=0, column=0, padx=(0, 10))
        key_btn = ctk.CTkButton(frame, text="Changer", width=100)
        key_btn.configure(
            command=lambda: self._start_key_capture(var, key_lbl, key_btn, post_fn))
        key_btn.grid(row=0, column=1)
        return key_lbl, key_btn

    def _separator(self, row: int, pady: tuple = (10, 4)) -> None:
        """Insert a 1 px horizontal rule spanning all three columns."""
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=row, column=0, columnspan=3,
                            sticky="ew", padx=16, pady=pady)

    def _slider_row(self, row: int, var: ctk.IntVar, from_: int, to: int, fmt) -> None:
        """Place a CTkSlider + live value label in columns 1–2 of the given row.

        The label is updated on every slider move via the ``command`` callback.
        The ``_l`` and ``_f`` default-arg trick captures the current loop
        values so each lambda closes over its own label and formatter rather
        than the last iteration's.
        """
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=7)
        frame.columnconfigure(0, weight=1)
        lbl = ctk.CTkLabel(frame, text=fmt(var.get()), width=56, anchor="w")
        ctk.CTkSlider(frame, from_=from_, to=to, variable=var,
                      command=lambda v, _l=lbl, _f=fmt: _l.configure(text=_f(int(v)))
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        lbl.grid(row=0, column=1)

    # --- Event handlers -----------------------------------------------------

    def _on_opacity_change(self, value: float) -> None:
        """Apply the new opacity to both windows live as the slider moves."""
        val = round(float(value), 2)
        self._opacity_lbl.configure(text=f"{int(val * 100)}%")
        apply_window_transparency(self._app, val)
        apply_window_transparency(self, val)

    def _start_key_capture(self, var: ctk.StringVar, lbl, btn, post_fn) -> None:
        """Enter key-capture mode for any hotkey row.

        Stores the target widgets and callbacks so ``_on_key_captured`` knows
        what to update. The guard flag prevents re-entrant captures (e.g. the
        user clicking two "Changer" buttons before pressing a key).
        """
        if self._capturing_key:
            return
        self._capturing_key = True
        self._capture_var  = var
        self._capture_lbl  = lbl
        self._capture_btn  = btn
        self._capture_post = post_fn
        btn.configure(text="Appuyez...", state="disabled")
        self.bind("<KeyPress>", self._on_key_captured)
        self.focus_set()

    def _on_key_captured(self, event) -> None:
        """Handle the keypress during hotkey capture.

        Escape cancels without changing anything. Any other key is applied
        to the stored var/label pair and ``post_fn`` is called to propagate
        the change (Tkinter rebind + global keyboard hook re-registration).
        """
        self.unbind("<KeyPress>")
        self._capturing_key = False
        self._capture_btn.configure(text="Changer", state="normal")
        if event.keysym == "Escape":
            return
        self._capture_var.set(event.keysym)
        self._capture_lbl.configure(text=event.keysym)
        self._capture_post()

    def update_devices(self, names: list) -> None:
        """Refresh the device dropdown values (called from FrenchTTSApp)."""
        self.device_menu.configure(values=names or ["Aucun périphérique"])


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class FrenchTTSApp(ctk.CTk):
    """Root application window.

    Responsibilities
    ----------------
    - Build and own the main UI (text box, four action buttons, status bar).
    - Manage shared Tkinter vars consumed by both this window and SettingsWindow.
    - Drive the TTS pipeline: text → edge-tts stream → MP3 buffer → PCM playback.
    - Persist and restore user settings and text history across sessions.
    - Handle minimize-to-tray and restore via pystray.
    """

    def __init__(self):
        super().__init__()

        # --- Internal state -------------------------------------------------
        # _stop_event is set by _on_stop / _shutdown to abort ongoing audio.
        # Worker threads check it at every async yield point.
        self._stop_event    = threading.Event()
        # Only one TTS or replay thread runs at a time; we keep a reference
        # to check is_alive() before launching a new one.
        self._tts_thread:   threading.Thread | None = None
        # Maps dropdown display strings ("2: CABLE Input ...") to device
        # indices accepted by sounddevice. Rebuilt on demand via ↺.
        self._device_map:   dict[str, int] = {}
        self._settings_win: SettingsWindow | None = None
        self._tray_icon:    pystray.Icon | None = None
        # _in_tray prevents _on_unmap from firing recursively while the
        # window is being withdrawn.
        self._in_tray       = False
        # _ready gates _on_unmap so that the very first Unmap event fired
        # during startup (before the window is fully shown) does not trigger
        # an immediate tray minimise.
        self._ready         = False
        self._current_key   = ""   # currently bound replay keysym (Tkinter)
        self._current_stop  = ""   # currently bound stop keysym (Tkinter)
        self._hk_replay     = None # keyboard-lib hotkey handle for global replay
        self._hk_stop       = None # keyboard-lib hotkey handle for global stop

        # --- Text input history (Up/Down navigation) ------------------------
        # Mirrors the behaviour of a shell: Up walks backwards through
        # previously spoken texts, Down returns toward the present.
        # _draft saves whatever the user was typing before they started
        # navigating, so pressing Down all the way back restores it.
        self._history:     list[str] = []
        self._history_idx: int       = 0   # points past the end when not navigating
        self._draft:       str       = ""

        # --- Tkinter vars shared with SettingsWindow ------------------------
        # These are declared here (not in _build_ui) so SettingsWindow can
        # bind to them before the UI is fully constructed.
        self.voice_var      = ctk.StringVar(value=list(VOICES.keys())[0])
        self.device_var     = ctk.StringVar()
        self.rate_var       = ctk.IntVar(value=0)
        self.volume_var     = ctk.IntVar(value=100)
        self.pitch_var      = ctk.IntVar(value=0)
        self.opacity_var    = ctk.DoubleVar(value=0.93)
        self.replay_key_var = ctk.StringVar(value="F2")
        self.stop_key_var   = ctk.StringVar(value="F3")

        # --- Boot sequence --------------------------------------------------
        self._build_ui()
        # Let Tkinter compute widget sizes before locking the geometry.
        self.update_idletasks()
        self.geometry(f"490x{self.winfo_reqheight()}")
        self.resizable(False, False)
        _set_window_icon(self)

        self._populate_devices()
        self._load_settings()        # overwrites defaults with saved prefs
        self._load_history()
        self._bind_replay_key()      # must run after _load_settings sets replay_key_var
        self._bind_stop_key()
        self._bind_global_hotkeys()  # register both hotkeys system-wide

        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.bind("<Unmap>", self._on_unmap)
        # Delay _ready so startup Unmap events are ignored.
        self.after(400, lambda: setattr(self, "_ready", True))
        # Delay transparency so the window is composited before DWM is touched.
        self.after(150, lambda: apply_window_transparency(self, self.opacity_var.get()))

    # --- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the main window widgets.

        Layout (3 rows, 1 column):
          row 0  body frame  — textbox + 2×2 button grid
          row 1  separator   — 1 px horizontal rule
          row 2  footer      — status label (left) + copyright link (right)

        The body and footer share the same padx (14 px) so their contents
        align with each other. The window height is not set here; it is
        measured via winfo_reqheight() after update_idletasks() in __init__.
        """
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(APP_NAME)
        self.geometry("490x1")   # height=1 → auto-sized after build
        self.columnconfigure(0, weight=1)

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        body.columnconfigure(0, weight=1)

        # Text input
        # <Return> triggers speech; <Shift-Return> inserts a literal newline
        # (default behaviour, no handler needed — lambda e: None suppresses
        # the built-in Return binding from leaking through).
        # <Up> / <Down> navigate the spoken-text history.
        self.text_box = ctk.CTkTextbox(
            body, height=76, wrap="word",
            font=ctk.CTkFont(size=13),
            border_width=1, border_color=("gray70", "#3a3a3a"))
        self.text_box.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.text_box.bind("<Return>",       self._on_enter_key)
        self.text_box.bind("<Shift-Return>", lambda e: None)
        self.text_box.bind("<Up>",           self._on_history_up)
        self.text_box.bind("<Down>",         self._on_history_down)

        # Button grid (2 rows × 2 columns, equal-width columns)
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        # Row 0: primary actions
        self.speak_btn = ctk.CTkButton(
            btn_row, text="Parler  ↵", height=33,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_speak)
        self.speak_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=(0, 4))

        self.stop_btn = ctk.CTkButton(
            btn_row, text=f"Arrêter ({self.stop_key_var.get()})", height=33,
            font=ctk.CTkFont(size=13),
            fg_color="#6e1212", hover_color="#521010",
            command=self._on_stop)
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=(0, 4))

        # Row 1: secondary actions (ghost style via _BTN_SECONDARY)
        # replay_btn is disabled until last.mp3 exists (no audio to replay yet).
        self.replay_btn = ctk.CTkButton(
            btn_row, text=f"Redire ({self.replay_key_var.get()})", height=33,
            font=ctk.CTkFont(size=13),
            **_BTN_SECONDARY,
            state="normal" if os.path.exists(LAST_MP3) else "disabled",
            command=self._on_replay)
        self.replay_btn.grid(row=1, column=0, sticky="ew", padx=(0, 3))

        ctk.CTkButton(
            btn_row, text="⚙  Paramètres", height=33,
            font=ctk.CTkFont(size=13),
            **_BTN_SECONDARY,
            command=self._open_settings
        ).grid(row=1, column=1, sticky="ew", padx=(3, 0))

        # Separator
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=1, column=0, sticky="ew")

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 8))
        footer.columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            footer, text=STATUS_READY,
            text_color=("gray50", "gray55"),
            font=ctk.CTkFont(size=11))
        self.status_label.grid(row=0, column=0, sticky="w")

        # Clickable copyright link with hover colour change
        # Copyright: plain "YYYY © " text + clickable APP_NAME link.
        # Two separate labels so only the name is interactive, not the whole line.
        copy_frame = ctk.CTkFrame(footer, fg_color="transparent")
        copy_frame.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            copy_frame,
            text=f"{datetime.date.today().year} © ",
            text_color=("gray55", "gray40"),
            font=ctk.CTkFont(size=11)
        ).grid(row=0, column=0)
        link = ctk.CTkLabel(
            copy_frame,
            text=APP_NAME,
            text_color=("gray55", "gray40"),
            font=ctk.CTkFont(size=11),
            cursor="hand2")
        link.grid(row=0, column=1)
        link.bind("<Button-1>", lambda e: webbrowser.open(APP_URL))
        link.bind("<Enter>",    lambda e: link.configure(text_color=("gray35", "gray65")))
        link.bind("<Leave>",    lambda e: link.configure(text_color=("gray55", "gray40")))

    # --- Devices ------------------------------------------------------------

    def _populate_devices(self, widget=None) -> None:
        """Rebuild the audio output device list from sounddevice.

        Only output-capable devices are included (max_output_channels > 0).
        The display name includes the index so users can distinguish devices
        with identical names (e.g. two instances of the same USB audio chip).

        Auto-selection priority:
          1. Keep the current selection if it is still valid.
          2. Prefer any device whose name contains "CABLE" (VB-Cable).
          3. Fall back to the first available output device.

        ``widget`` is the target CTkOptionMenu to update. If None and the
        settings window is open, its device_menu is updated instead.
        """
        self._device_map.clear()
        names = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                name = f"{idx}: {dev['name']}"
                self._device_map[name] = idx
                names.append(name)

        if self.device_var.get() not in self._device_map:
            default = next((n for n in names if "CABLE" in n.upper()),
                           names[0] if names else "")
            if default:
                self.device_var.set(default)

        target = widget or (
            self._settings_win.device_menu
            if self._settings_win and self._settings_win.winfo_exists() else None)
        if target:
            target.configure(values=names or ["Aucun périphérique"])

    # --- Config -------------------------------------------------------------

    def _load_settings(self) -> None:
        """Load config.json and apply values to all Tkinter vars.

        The saved dict is merged on top of DEFAULT_SETTINGS so any key
        absent from the file (e.g. a new setting added in a later version)
        is silently defaulted rather than causing a KeyError.

        Device matching uses substring search because the index prefix
        ("2: ") may change between sessions if devices are added/removed.
        """
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_SETTINGS, **json.load(f)}
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = DEFAULT_SETTINGS.copy()

        if cfg["voice"] in VOICES:
            self.voice_var.set(cfg["voice"])
        saved = cfg["device"]
        if saved:
            # Match on the device name portion, ignoring the index prefix
            match = next((n for n in self._device_map if saved in n), None)
            if match:
                self.device_var.set(match)
        self.rate_var.set(cfg["rate"])
        self.volume_var.set(cfg["volume"])
        self.pitch_var.set(cfg["pitch"])
        self.opacity_var.set(float(cfg.get("opacity", 0.93)))
        self.replay_key_var.set(str(cfg.get("replay_key", "F2")))
        self.stop_key_var.set(str(cfg.get("stop_key", "F3")))

    def _save_settings(self) -> None:
        """Persist current Tkinter var values to config.json.

        Called on window close and on quit-from-tray. Failures (permission
        error, disk full) are silently ignored to avoid a crash on shutdown.
        """
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "voice":      self.voice_var.get(),
                    "device":     self.device_var.get(),
                    "rate":       self.rate_var.get(),
                    "volume":     self.volume_var.get(),
                    "pitch":      self.pitch_var.get(),
                    "opacity":    round(self.opacity_var.get(), 2),
                    "replay_key": self.replay_key_var.get(),
                    "stop_key":   self.stop_key_var.get(),
                }, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # --- Replay key ---------------------------------------------------------

    def _bind_replay_key(self) -> None:
        """Update the Tkinter window binding and button label for the replay hotkey.

        The Tkinter binding covers the case where the app is focused.
        Global coverage is handled separately by ``_bind_global_hotkeys``.
        """
        if self._current_key:
            try:
                self.unbind(f"<{self._current_key}>")
            except Exception:
                pass
        key = self.replay_key_var.get()
        self._current_key = key
        self.replay_btn.configure(text=f"Redire ({key})")
        try:
            self.bind(f"<{key}>", lambda e: self._on_replay())
        except Exception:
            pass

    def _bind_stop_key(self) -> None:
        """Update the Tkinter window binding and button label for the stop hotkey."""
        if self._current_stop:
            try:
                self.unbind(f"<{self._current_stop}>")
            except Exception:
                pass
        key = self.stop_key_var.get()
        self._current_stop = key
        self.stop_btn.configure(text=f"Arrêter ({key})")
        try:
            self.bind(f"<{key}>", lambda e: self._on_stop())
        except Exception:
            pass

    def _bind_global_hotkeys(self) -> None:
        """Register system-wide hotkeys via the keyboard library.

        These fire even when the application is not focused (e.g. while on
        Discord or another window). The keyboard library runs callbacks on its
        own thread, so all Tkinter calls are marshalled via ``after(0, ...)``.

        Keys are converted to lowercase because the keyboard library expects
        'f2' not 'F2'. Invalid or unsupported keysyms are silently ignored so
        a misconfigured hotkey does not break the rest of the app.
        """
        # Remove previously registered handles before re-registering
        for hk in (self._hk_replay, self._hk_stop):
            if hk is not None:
                try:
                    keyboard.remove_hotkey(hk)
                except Exception:
                    pass

        try:
            self._hk_replay = keyboard.add_hotkey(
                self.replay_key_var.get().lower(),
                lambda: self.after(0, self._on_replay))
        except Exception:
            self._hk_replay = None

        try:
            self._hk_stop = keyboard.add_hotkey(
                self.stop_key_var.get().lower(),
                lambda: self.after(0, self._on_stop))
        except Exception:
            self._hk_stop = None

    # --- Settings window ----------------------------------------------------

    def _open_settings(self) -> None:
        """Open the settings window, or focus it if already open.

        A single instance is enforced via winfo_exists(); creating a second
        CTkToplevel on top of the first would leave an orphaned window.
        """
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsWindow(self)

    # --- System tray --------------------------------------------------------

    def _on_unmap(self, event) -> None:
        """Intercept window minimise and redirect to system tray.

        The ``_ready`` and ``_in_tray`` guards prevent this handler from
        firing during startup or while the window is already hidden.
        ``event.widget is not self`` filters child-widget Unmap events that
        bubble up to the root window.
        """
        if not self._ready or event.widget is not self or self._in_tray:
            return
        self._in_tray = True
        # Small delay lets the minimise animation finish before withdraw().
        self.after(10, self._hide_to_tray)

    def _hide_to_tray(self) -> None:
        """Withdraw the window and create the system tray icon.

        The settings window (if open) is closed first because CTkToplevel
        windows do not auto-hide when their parent is withdrawn.
        pystray.Icon.run() is blocking, so it runs in a daemon thread.
        The thread dies automatically when the process exits.
        """
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.destroy()
        self.withdraw()
        ico      = _get_icon_path()
        icon_img = Image.open(ico) if ico else make_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem(f"Ouvrir {APP_NAME}", self._restore_from_tray, default=True),
            pystray.Menu.SEPARATOR,
            # Tray callbacks run on pystray's thread, not the Tkinter thread.
            # We use self.after(0, ...) to marshal _shutdown back to Tkinter.
            pystray.MenuItem("Quitter", lambda i, it: self.after(0, self._shutdown)),
        )
        self._tray_icon = pystray.Icon(APP_NAME, icon_img, APP_NAME, menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _restore_from_tray(self, icon=None, item=None) -> None:
        """Stop the tray icon and restore the main window.

        Transparency is re-applied after 200 ms because DWM sometimes drops
        the acrylic effect when a window is un-withdrawn.
        """
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        self._in_tray = False
        self.after(0,   self.deiconify)
        self.after(50,  self.lift)
        self.after(200, lambda: apply_window_transparency(self, self.opacity_var.get()))

    # --- UI handlers --------------------------------------------------------

    def _on_enter_key(self, event) -> str:
        """Trigger speech on Return and suppress the default newline insertion."""
        self._on_speak()
        return "break"

    def _on_speak(self) -> None:
        """Validate input then launch the TTS thread as early as possible.

        Order is intentional: the network request to edge-tts starts first
        so it runs concurrently with the UI updates and the disk write in
        _push_history, shaving off any sequential overhead before audio begins.
        """
        text = self.text_box.get("1.0", "end-1c").strip()
        if not text or (self._tts_thread and self._tts_thread.is_alive()):
            return
        self._stop_event.clear()
        self._run_worker(lambda: self._tts_async(text))  # network starts immediately
        self.text_box.delete("1.0", "end")
        self.speak_btn.configure(state="disabled")
        self.replay_btn.configure(state="disabled")
        self._set_status(STATUS_LOADING)
        self._push_history(text)  # disk write happens while network is already running

    def _on_stop(self) -> None:
        """Immediately halt audio playback and reset the UI.

        Setting _stop_event causes the async polling loop inside _play_pcm
        to call sd.stop() on its next iteration. Calling sd.stop() here too
        ensures the audio stops even if the thread hasn't reached that check yet.
        """
        self._stop_event.set()
        sd.stop()
        self._restore_ui()

    def _on_replay(self) -> None:
        """Replay the last generated audio without re-calling edge-tts."""
        if not os.path.exists(LAST_MP3) or (self._tts_thread and self._tts_thread.is_alive()):
            return
        self._stop_event.clear()
        self.speak_btn.configure(state="disabled")
        self.replay_btn.configure(state="disabled")
        self._set_status(STATUS_PLAYING)
        self._run_worker(self._replay_async)

    def _shutdown(self) -> None:
        """Save state and destroy the application.

        Called from the window close button and from the tray Quit item.
        Global hotkeys are removed first to prevent callbacks firing on a
        partially destroyed window. sd.stop() ensures no audio lingers.
        self.after(0, self.destroy) defers destruction so this method can
        safely be called from a non-Tkinter thread (tray or keyboard callback).
        """
        for hk in (self._hk_replay, self._hk_stop):
            if hk is not None:
                try:
                    keyboard.remove_hotkey(hk)
                except Exception:
                    pass
        self._save_settings()
        self._history.clear()
        self._save_history()
        try:
            os.remove(LAST_MP3)
        except OSError:
            pass
        self._stop_event.set()
        sd.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    def _set_status(self, text: str) -> None:
        """Thread-safe status bar update via after(0)."""
        self.after(0, lambda: self.status_label.configure(text=text))

    def _restore_ui(self) -> None:
        """Re-enable action buttons and reset the status bar after playback ends.

        replay_btn is only enabled when last.mp3 exists on disk, preserving
        the correct disabled state for a fresh install with no prior audio.
        Called from _on_stop (main thread) and from the worker finally block
        (worker thread) — after(0) makes both safe.
        """
        self.after(0, lambda: self.speak_btn.configure(state="normal"))
        self.after(0, lambda: self.replay_btn.configure(
            state="normal" if os.path.exists(LAST_MP3) else "disabled"))
        self._set_status(STATUS_READY)

    # --- Text history -------------------------------------------------------

    def _load_history(self) -> None:
        """Deserialise lasts.log into self._history and reset the index.

        The file is a flat JSON array of strings. Entries are capped at
        MAX_HISTORY on load to handle files produced by older versions that
        may have had a different limit.
        """
        try:
            with open(HISTORY_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._history = [str(t) for t in data][-MAX_HISTORY:]
        except (FileNotFoundError, json.JSONDecodeError):
            self._history = []
        # Start the index past the end so the first Up press fetches the last entry.
        self._history_idx = len(self._history)

    def _save_history(self) -> None:
        """Serialise self._history to lasts.log, silently ignoring IO errors."""
        try:
            with open(HISTORY_LOG, "w", encoding="utf-8") as f:
                json.dump(self._history[-MAX_HISTORY:], f, ensure_ascii=False)
        except OSError:
            pass

    def _push_history(self, text: str) -> None:
        """Append a new entry, skip if it duplicates the previous one, then save.

        Consecutive duplicate suppression avoids cluttering the history when
        the user sends the same line multiple times in a row. Non-consecutive
        duplicates are kept so the full conversation is preserved.
        """
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            self._save_history()
        # Always reset the pointer to the end so the next Up starts from the newest entry.
        self._history_idx = len(self._history)
        self._draft = ""

    def _on_history_up(self, event) -> str:
        """Navigate to the previous history entry (shell Up-arrow behaviour).

        On the first Up press the current textbox content is saved as _draft
        so it can be restored if the user presses Down all the way back.
        Returns "break" to suppress Tkinter's default cursor-movement behaviour.
        """
        if not self._history:
            return "break"
        if self._history_idx == len(self._history):
            self._draft = self.text_box.get("1.0", "end-1c")
        if self._history_idx > 0:
            self._history_idx -= 1
            self._set_textbox(self._history[self._history_idx])
        return "break"

    def _on_history_down(self, event) -> str:
        """Navigate toward the present; restore the draft when past the last entry."""
        if self._history_idx >= len(self._history):
            return "break"
        self._history_idx += 1
        text = self._draft if self._history_idx == len(self._history) \
               else self._history[self._history_idx]
        self._set_textbox(text)
        return "break"

    def _set_textbox(self, text: str) -> None:
        """Replace the full textbox content with ``text``."""
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)

    # --- TTS / Playback -----------------------------------------------------

    def _run_worker(self, coro_factory) -> None:
        """Spawn a daemon thread that runs an async coroutine factory.

        A new event loop is created per thread because asyncio loops are not
        thread-safe and the main thread does not run one. ``coro_factory`` is
        a zero-argument callable that returns a coroutine, allowing closures
        to capture parameters (e.g. the text string for _tts_async).

        The ``finally`` block runs even if the coroutine raises, ensuring
        buttons are always re-enabled. It checks _stop_event first so that
        an intentional stop (via _on_stop) does not re-enable the UI before
        the user has had a chance to see the reset from _on_stop itself.
        """
        def target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coro_factory())
            except Exception as e:
                self._set_status(f"{STATUS_ERROR}: {str(e)[:80]}")
            finally:
                loop.close()
                if not self._stop_event.is_set():
                    self._restore_ui()
        self._tts_thread = threading.Thread(target=target, daemon=True)
        self._tts_thread.start()

    async def _tts_async(self, text: str) -> None:
        """Stream TTS audio from edge-tts, persist it, then play it.

        The MP3 stream arrives in variable-size chunks. Each chunk is checked
        against _stop_event so the user can abort mid-stream without waiting
        for the full download. Only "audio" chunks carry PCM data; "WordBoundary"
        chunks (timing metadata) are ignored.

        Volume is stored as 0–100 in config but edge-tts expects a signed
        percent offset relative to 100 (e.g. 80 → "-20%", 100 → "+0%").
        """
        voice  = VOICES[self.voice_var.get()]
        rate   = fmt_rate(self.rate_var.get())
        offset = self.volume_var.get() - 100
        volume = f"+{offset}%" if offset >= 0 else f"{offset}%"
        pitch  = fmt_pitch(self.pitch_var.get())

        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
        mp3_buffer  = bytearray()
        async for chunk in communicate.stream():
            if self._stop_event.is_set():
                return
            if chunk["type"] == "audio":
                mp3_buffer.extend(chunk["data"])

        if self._stop_event.is_set() or not mp3_buffer:
            return

        # Overwrite last.mp3 so replay always reflects the most recent speech.
        try:
            with open(LAST_MP3, "wb") as f:
                f.write(bytes(mp3_buffer))
        except OSError:
            pass

        pcm, samplerate = _decode_mp3(bytes(mp3_buffer))
        self._set_status(STATUS_PLAYING)
        await self._play_pcm(pcm, samplerate)

    async def _replay_async(self) -> None:
        """Load last.mp3 from disk and play it without re-generating TTS."""
        with open(LAST_MP3, "rb") as f:
            data = f.read()
        pcm, samplerate = _decode_mp3(data)
        await self._play_pcm(pcm, samplerate)

    async def _play_pcm(self, pcm: np.ndarray, samplerate: int) -> None:
        """Play a PCM array non-blocking and poll until the stream finishes.

        ``sd.play`` is non-blocking so we loop with a 50 ms sleep, checking
        _stop_event each iteration. This keeps the thread responsive to stop
        requests while avoiding the CPU overhead of a busy-wait. 50 ms was
        chosen as a balance between responsiveness and overhead; it means the
        user waits at most 50 ms after clicking Arrêter for audio to cut out.

        ``sd.get_stream().active`` raises RuntimeError if no stream exists
        (e.g. device disconnected mid-playback); the except clause treats that
        as a clean end of playback.
        """
        device_idx = self._device_map.get(self.device_var.get())
        sd.play(pcm, samplerate=samplerate, device=device_idx, blocking=False)
        while True:
            if self._stop_event.is_set():
                sd.stop()
                return
            try:
                if not sd.get_stream().active:
                    break
            except Exception:
                break
            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = FrenchTTSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
