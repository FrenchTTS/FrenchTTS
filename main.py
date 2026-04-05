import asyncio
import ctypes
import ctypes.wintypes
import datetime
import json
import os
import sys
import threading
import webbrowser

import customtkinter as ctk
import edge_tts
import miniaudio
import numpy as np
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPDATA     = os.environ.get("APPDATA", os.path.expanduser("~"))
BASE_DIR    = os.path.join(APPDATA, "FrenchTTS")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
LAST_MP3    = os.path.join(HISTORY_DIR, "last.mp3")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
HISTORY_LOG = os.path.join(HISTORY_DIR, "lasts.log")
os.makedirs(BASE_DIR,    exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

STATUS_READY   = "Prêt"
STATUS_LOADING = "Chargement..."
STATUS_PLAYING = "En cours..."
STATUS_ERROR   = "Erreur"
MAX_HISTORY    = 100

DEFAULT_SETTINGS: dict = {
    "voice":      list(VOICES.keys())[0],
    "device":     "",
    "rate":       0,
    "volume":     100,
    "pitch":      0,
    "opacity":    0.93,
    "replay_key": "F2",
}

# Shared secondary button style (ghost-like, used in both windows)
_BTN_SECONDARY = dict(
    fg_color=("gray75", "#2c2c2c"),
    hover_color=("gray65", "#383838"),
    border_width=1,
    border_color=("gray60", "#454545"),
)

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_signed(v: int, unit: str) -> str:
    return f"+{v}{unit}" if v >= 0 else f"{v}{unit}"

fmt_rate   = lambda v: _fmt_signed(int(v), "%")
fmt_pitch  = lambda v: _fmt_signed(int(v), "Hz")
fmt_volume = lambda v: f"{int(v)}%"

# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    """Decode MP3 bytes to int16 PCM using miniaudio (no ffmpeg required)."""
    decoded = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1, sample_rate=24000)
    return np.frombuffer(decoded.samples, dtype=np.int16), decoded.sample_rate

# ---------------------------------------------------------------------------
# Window utilities
# ---------------------------------------------------------------------------

def _get_icon_path() -> str | None:
    """Resolve img/icon.ico whether running from source or as a PyInstaller bundle."""
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "img", "icon.ico")
    return path if os.path.exists(path) else None

def _safe_iconbitmap(window, path: str) -> None:
    try:
        window.iconbitmap(path)
    except Exception:
        pass

def _set_window_icon(window) -> None:
    """Apply icon.ico to any CTk window.

    CTkToplevel resets its own icon ~200 ms after init; the 450 ms delay
    ensures our call wins that race.
    """
    ico = _get_icon_path()
    if not ico:
        return
    delay = 450 if isinstance(window, ctk.CTkToplevel) else 80
    window.after(delay, lambda: _safe_iconbitmap(window, ico))

def _safe_open(path: str) -> None:
    """Open a path in the OS default application (Explorer, Finder, etc.)."""
    try:
        os.startfile(path)
    except Exception:
        pass

def make_tray_image() -> Image.Image:
    """Programmatic fallback tray icon when icon.ico is unavailable."""
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(70, 130, 200, 255))
    draw.rounded_rectangle([24, 12, 40, 36], radius=8, fill=(255, 255, 255, 220))
    draw.arc([18, 28, 46, 46], start=0, end=180, fill=(255, 255, 255, 220), width=3)
    draw.line([32, 46, 32, 54], fill=(255, 255, 255, 220), width=3)
    draw.line([24, 54, 40, 54], fill=(255, 255, 255, 220), width=3)
    return img

# ---------------------------------------------------------------------------
# Windows acrylic blur  (SetWindowCompositionAttribute)
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
    """Enable ACCENT_ENABLE_ACRYLICBLURBEHIND on a Win32 HWND."""
    try:
        accent = _AccentPolicy()
        accent.AccentState   = 4       # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = color_abgr
        data = _WinCompAttrData()
        data.Attribute = 19            # WCA_ACCENT_POLICY
        data.pData     = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.cbData    = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass

def apply_window_transparency(window, opacity: float) -> None:
    """Set window alpha and enable acrylic blur when opacity < 1.0."""
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
    def __init__(self, app: "FrenchTTSApp"):
        super().__init__(app)
        self._app = app
        self.title("Paramètres — FrenchTTS")
        self.geometry("460x1")
        self.transient(app)
        self._capturing_key = False
        self._build()
        self.update_idletasks()
        self.geometry(f"460x{self.winfo_reqheight()}")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _set_window_icon(self)
        self.after(50,  self.lift)
        self.after(120, lambda: apply_window_transparency(self, self._app.opacity_var.get()))

    # --- Layout -------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, minsize=140, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)

        LBL = dict(padx=(20, 8), pady=7, sticky="w")
        CTL = dict(padx=(0, 16), pady=7)

        ctk.CTkLabel(self, text="Paramètres",
                     font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, pady=(16, 10))

        # Voice selector
        ctk.CTkLabel(self, text="Voix :").grid(row=1, column=0, **LBL)
        ctk.CTkOptionMenu(self, variable=self._app.voice_var,
                          values=list(VOICES.keys())
                          ).grid(row=1, column=1, columnspan=2, sticky="ew", **CTL)

        # Audio output device with refresh button
        ctk.CTkLabel(self, text="Sortie :").grid(row=2, column=0, **LBL)
        self.device_menu = ctk.CTkOptionMenu(self, variable=self._app.device_var, values=[])
        self.device_menu.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=7)
        ctk.CTkButton(self, text="↺", width=32,
                      command=lambda: self._app._populate_devices(widget=self.device_menu)
                      ).grid(row=2, column=2, padx=(0, 16), pady=7)
        self._app._populate_devices(widget=self.device_menu)

        # Voice parameter sliders
        for row, label, var, lo, hi, fmt in [
            (3, "Vitesse :", self._app.rate_var,   -50,  100, fmt_rate),
            (4, "Volume :",  self._app.volume_var,   0,  100, fmt_volume),
            (5, "Pitch :",   self._app.pitch_var,  -100, 100, fmt_pitch),
        ]:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, **LBL)
            self._slider_row(row=row, var=var, from_=lo, to=hi, fmt=fmt)

        self._separator(row=6)

        # Opacity  (1.0 = fully opaque / effect disabled)
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

        # Replay hotkey capture
        ctk.CTkLabel(self, text="Touche Redire :").grid(row=8, column=0, **LBL)
        key_frame = ctk.CTkFrame(self, fg_color="transparent")
        key_frame.grid(row=8, column=1, columnspan=2, sticky="ew", **CTL)
        self._key_lbl = ctk.CTkLabel(
            key_frame, text=self._app.replay_key_var.get(),
            font=ctk.CTkFont(size=13, weight="bold"), width=60, anchor="w")
        self._key_lbl.grid(row=0, column=0, padx=(0, 10))
        self._key_btn = ctk.CTkButton(
            key_frame, text="Changer", width=100, command=self._start_key_capture)
        self._key_btn.grid(row=0, column=1)

        self._separator(row=9)

        # Footer buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=10, column=0, columnspan=3, pady=(10, 14))
        ctk.CTkButton(btn_frame, text="Dossier config", width=140,
                      **_BTN_SECONDARY,
                      command=lambda: _safe_open(BASE_DIR)
                      ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Fermer", width=120,
                      command=self.destroy
                      ).grid(row=0, column=1)

    def _separator(self, row: int, pady: tuple = (10, 4)) -> None:
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=row, column=0, columnspan=3,
                            sticky="ew", padx=16, pady=pady)

    def _slider_row(self, row: int, var: ctk.IntVar, from_: int, to: int, fmt) -> None:
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
        val = round(float(value), 2)
        self._opacity_lbl.configure(text=f"{int(val * 100)}%")
        apply_window_transparency(self._app, val)
        apply_window_transparency(self, val)

    def _start_key_capture(self) -> None:
        if self._capturing_key:
            return
        self._capturing_key = True
        self._key_btn.configure(text="Appuyez...", state="disabled")
        self.bind("<KeyPress>", self._on_key_captured)
        self.focus_set()

    def _on_key_captured(self, event) -> None:
        self.unbind("<KeyPress>")
        self._capturing_key = False
        self._key_btn.configure(text="Changer", state="normal")
        if event.keysym == "Escape":
            return
        self._app.replay_key_var.set(event.keysym)
        self._key_lbl.configure(text=event.keysym)
        self._app._bind_replay_key()

    def update_devices(self, names: list) -> None:
        self.device_menu.configure(values=names or ["Aucun périphérique"])

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class FrenchTTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self._stop_event   = threading.Event()
        self._tts_thread:  threading.Thread | None = None
        self._device_map:  dict[str, int] = {}
        self._settings_win: SettingsWindow | None = None
        self._tray_icon:   pystray.Icon | None = None
        self._in_tray      = False
        self._ready        = False
        self._current_key  = ""

        # Text history for Up/Down navigation (shell-like)
        self._history:     list[str] = []
        self._history_idx: int       = 0
        self._draft:       str       = ""

        # Tkinter vars shared with SettingsWindow
        self.voice_var      = ctk.StringVar(value=list(VOICES.keys())[0])
        self.device_var     = ctk.StringVar()
        self.rate_var       = ctk.IntVar(value=0)
        self.volume_var     = ctk.IntVar(value=100)
        self.pitch_var      = ctk.IntVar(value=0)
        self.opacity_var    = ctk.DoubleVar(value=0.93)
        self.replay_key_var = ctk.StringVar(value="F2")

        self._build_ui()
        self.update_idletasks()
        self.geometry(f"490x{self.winfo_reqheight()}")
        self.resizable(False, False)
        _set_window_icon(self)

        self._populate_devices()
        self._load_settings()
        self._load_history()
        self._bind_replay_key()

        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.bind("<Unmap>", self._on_unmap)
        self.after(400, lambda: setattr(self, "_ready", True))
        self.after(150, lambda: apply_window_transparency(self, self.opacity_var.get()))

    # --- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("FrenchTTS")
        self.geometry("490x1")
        self.columnconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        body.columnconfigure(0, weight=1)

        self.text_box = ctk.CTkTextbox(
            body, height=76, wrap="word",
            font=ctk.CTkFont(size=13),
            border_width=1, border_color=("gray70", "#3a3a3a"))
        self.text_box.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.text_box.bind("<Return>",       self._on_enter_key)
        self.text_box.bind("<Shift-Return>", lambda e: None)
        self.text_box.bind("<Up>",           self._on_history_up)
        self.text_box.bind("<Down>",         self._on_history_down)

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        self.speak_btn = ctk.CTkButton(
            btn_row, text="Parler  ↵", height=33,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_speak)
        self.speak_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=(0, 4))

        ctk.CTkButton(
            btn_row, text="Arrêter", height=33,
            font=ctk.CTkFont(size=13),
            fg_color="#6e1212", hover_color="#521010",
            command=self._on_stop
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=(0, 4))

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

        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=1, column=0, sticky="ew")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 8))
        footer.columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            footer, text=STATUS_READY,
            text_color=("gray50", "gray55"),
            font=ctk.CTkFont(size=11))
        self.status_label.grid(row=0, column=0, sticky="w")

        link = ctk.CTkLabel(
            footer,
            text=f"{datetime.date.today().year} © neanrie.link",
            text_color=("gray55", "gray40"),
            font=ctk.CTkFont(size=11),
            cursor="hand2")
        link.grid(row=0, column=1, sticky="e")
        link.bind("<Button-1>", lambda e: webbrowser.open("https://neanrie.link"))
        link.bind("<Enter>",    lambda e: link.configure(text_color=("gray35", "gray65")))
        link.bind("<Leave>",    lambda e: link.configure(text_color=("gray55", "gray40")))

    # --- Devices ------------------------------------------------------------

    def _populate_devices(self, widget=None) -> None:
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
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_SETTINGS, **json.load(f)}
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = DEFAULT_SETTINGS.copy()

        if cfg["voice"] in VOICES:
            self.voice_var.set(cfg["voice"])
        saved = cfg["device"]
        if saved:
            match = next((n for n in self._device_map if saved in n), None)
            if match:
                self.device_var.set(match)
        self.rate_var.set(cfg["rate"])
        self.volume_var.set(cfg["volume"])
        self.pitch_var.set(cfg["pitch"])
        self.opacity_var.set(float(cfg.get("opacity", 0.93)))
        self.replay_key_var.set(str(cfg.get("replay_key", "F2")))

    def _save_settings(self) -> None:
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
                }, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # --- Replay key ---------------------------------------------------------

    def _bind_replay_key(self) -> None:
        if self._current_key:
            try:
                self.unbind(f"<{self._current_key}>")
            except Exception:
                pass
        key = self.replay_key_var.get()
        self._current_key = key
        try:
            self.bind(f"<{key}>", lambda e: self._on_replay())
            self.replay_btn.configure(text=f"Redire ({key})")
        except Exception:
            pass

    # --- Settings window ----------------------------------------------------

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsWindow(self)

    # --- System tray --------------------------------------------------------

    def _on_unmap(self, event) -> None:
        if not self._ready or event.widget is not self or self._in_tray:
            return
        self._in_tray = True
        self.after(10, self._hide_to_tray)

    def _hide_to_tray(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.destroy()
        self.withdraw()
        ico      = _get_icon_path()
        icon_img = Image.open(ico) if ico else make_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir FrenchTTS", self._restore_from_tray, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda i, it: self.after(0, self._shutdown)),
        )
        self._tray_icon = pystray.Icon("FrenchTTS", icon_img, "FrenchTTS", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _restore_from_tray(self, icon=None, item=None) -> None:
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        self._in_tray = False
        self.after(0,   self.deiconify)
        self.after(50,  self.lift)
        self.after(200, lambda: apply_window_transparency(self, self.opacity_var.get()))

    # --- UI handlers --------------------------------------------------------

    def _on_enter_key(self, event) -> str:
        self._on_speak()
        return "break"

    def _on_speak(self) -> None:
        text = self.text_box.get("1.0", "end-1c").strip()
        if not text or (self._tts_thread and self._tts_thread.is_alive()):
            return
        self._push_history(text)
        self._stop_event.clear()
        self.speak_btn.configure(state="disabled")
        self.replay_btn.configure(state="disabled")
        self._set_status(STATUS_LOADING)
        self._run_worker(lambda: self._tts_async(text))

    def _on_stop(self) -> None:
        self._stop_event.set()
        sd.stop()
        self._restore_ui()

    def _on_replay(self) -> None:
        if not os.path.exists(LAST_MP3) or (self._tts_thread and self._tts_thread.is_alive()):
            return
        self._stop_event.clear()
        self.speak_btn.configure(state="disabled")
        self.replay_btn.configure(state="disabled")
        self._set_status(STATUS_PLAYING)
        self._run_worker(self._replay_async)

    def _shutdown(self) -> None:
        """Persist state and cleanly terminate the application."""
        self._save_settings()
        self._stop_event.set()
        sd.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    def _set_status(self, text: str) -> None:
        self.after(0, lambda: self.status_label.configure(text=text))

    def _restore_ui(self) -> None:
        """Re-enable action buttons and reset the status bar."""
        self.after(0, lambda: self.speak_btn.configure(state="normal"))
        self.after(0, lambda: self.replay_btn.configure(
            state="normal" if os.path.exists(LAST_MP3) else "disabled"))
        self._set_status(STATUS_READY)

    # --- Text history -------------------------------------------------------

    def _load_history(self) -> None:
        try:
            with open(HISTORY_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._history = [str(t) for t in data][-MAX_HISTORY:]
        except (FileNotFoundError, json.JSONDecodeError):
            self._history = []
        self._history_idx = len(self._history)

    def _save_history(self) -> None:
        try:
            with open(HISTORY_LOG, "w", encoding="utf-8") as f:
                json.dump(self._history[-MAX_HISTORY:], f, ensure_ascii=False)
        except OSError:
            pass

    def _push_history(self, text: str) -> None:
        """Append text to history, skipping consecutive duplicates."""
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            self._save_history()
        self._history_idx = len(self._history)
        self._draft = ""

    def _on_history_up(self, event) -> str:
        if not self._history:
            return "break"
        if self._history_idx == len(self._history):
            self._draft = self.text_box.get("1.0", "end-1c")
        if self._history_idx > 0:
            self._history_idx -= 1
            self._set_textbox(self._history[self._history_idx])
        return "break"

    def _on_history_down(self, event) -> str:
        if self._history_idx >= len(self._history):
            return "break"
        self._history_idx += 1
        text = self._draft if self._history_idx == len(self._history) \
               else self._history[self._history_idx]
        self._set_textbox(text)
        return "break"

    def _set_textbox(self, text: str) -> None:
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)

    # --- TTS / Playback -----------------------------------------------------

    def _run_worker(self, coro_factory) -> None:
        """Spawn a daemon thread that runs an async coroutine factory."""
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

        try:
            with open(LAST_MP3, "wb") as f:
                f.write(bytes(mp3_buffer))
        except OSError:
            pass

        pcm, samplerate = _decode_mp3(bytes(mp3_buffer))
        self._set_status(STATUS_PLAYING)
        await self._play_pcm(pcm, samplerate)

    async def _replay_async(self) -> None:
        with open(LAST_MP3, "rb") as f:
            data = f.read()
        pcm, samplerate = _decode_mp3(data)
        await self._play_pcm(pcm, samplerate)

    async def _play_pcm(self, pcm: np.ndarray, samplerate: int) -> None:
        """Play PCM audio through the selected output device, polling until done."""
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
