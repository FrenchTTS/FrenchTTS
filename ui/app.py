"""
FrenchTTS — main application window.
"""

import asyncio
import datetime
import json
import os
import tempfile
import threading
import webbrowser

import edge_tts
import keyboard
import customtkinter as ctk
import numpy as np
import pystray
import sounddevice as sd
from PIL import Image

from core.version import BUILD_ID
from core.constants import (
    VOICES, APP_NAME, APP_URL, APP_VERSION_DISPLAY,
    STATUS_READY, STATUS_LOADING, STATUS_PLAYING, STATUS_ERROR,
    STATUS_RECORDING, STATUS_TRANSCRIBING,
    MAX_HISTORY, DEFAULT_SETTINGS, _BTN_SECONDARY,
    LAST_MP3, CONFIG_FILE, HISTORY_LOG,
    fmt_rate, fmt_pitch,
)
from core.audio import _decode_mp3, trim_silence, save_mp3
from core.sounds import (
    ensure_sounds, play_sound,
    SND_RECOGNIZING, SND_RECOGNIZED, SND_NOT_RECOGNIZED,
)
from ui.utils import (
    _get_icon_path, make_tray_image,
    _set_window_icon, apply_window_transparency,
    send_notification,
)
from ui.settings import SettingsWindow
from voice.listener import STTListener, _get_model


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
        self._stop_event = threading.Event()
        # _tts_busy is set while a TTS/replay coroutine is running.
        # Checked in _on_speak/_on_replay/_on_mic_toggle to block concurrent starts.
        self._tts_busy   = threading.Event()
        # Persistent asyncio event loop running in a daemon thread.
        # Avoids the per-call loop creation overhead of the old one-thread-per-TTS model.
        self._loop       = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever,
                         daemon=True, name="tts-loop").start()
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
        self._current_key    = ""   # currently bound replay keysym (Tkinter)
        self._current_stop   = ""   # currently bound stop keysym (Tkinter)
        self._current_stt    = ""   # currently bound STT keysym (Tkinter)
        self._hk_replay      = None # keyboard-lib hotkey handle for global replay
        self._hk_stop        = None # keyboard-lib hotkey handle for global stop
        self._hk_stt         = None # keyboard-lib hotkey handle for STT toggle

        # --- STT state ------------------------------------------------------
        # _stt_triggered_tts is set to True by _apply_transcript so the
        # auto-restart logic knows the TTS came from STT, not a manual input.
        self._stt_state         = "idle"  # "idle"|"listening"|"recording"|"transcribing"
        self._listener:         STTListener | None = None
        self._stt_triggered_tts = False

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
        self.voice_var        = ctk.StringVar(value=list(VOICES.keys())[0])
        self.device_var       = ctk.StringVar()
        self.rate_var         = ctk.IntVar(value=0)
        self.volume_var       = ctk.IntVar(value=100)
        self.pitch_var        = ctk.IntVar(value=0)
        self.opacity_var      = ctk.DoubleVar(value=0.93)
        self.replay_key_var   = ctk.StringVar(value="F2")
        self.stop_key_var     = ctk.StringVar(value="F3")
        self.stt_enabled_var      = ctk.BooleanVar(value=False)
        self.stt_input_var        = ctk.StringVar()
        self.stt_key_var          = ctk.StringVar(value="F1")
        self.stt_auto_restart_var = ctk.BooleanVar(value=False)
        self.stt_notify_var       = ctk.BooleanVar(value=False)
        self._input_device_map:   dict[str, int] = {}
        self.monitor_enabled_var  = ctk.BooleanVar(value=False)
        self.monitor_device_var   = ctk.StringVar()
        self._last_seen_version: str = ""   # loaded by _load_settings

        # --- Boot sequence --------------------------------------------------
        self._build_ui()
        # Let Tkinter compute widget sizes before locking the geometry.
        self.update_idletasks()
        self.geometry(f"490x{self.winfo_reqheight()}")
        self.resizable(False, False)
        _set_window_icon(self)

        ensure_sounds()   # generate audio/*.wav if absent

        self._listener = STTListener(
            on_transcript=self._on_stt_transcript,
            on_state_change=self._on_stt_state_change,
            on_error=self._on_stt_error,
            on_not_recognized=self._on_stt_not_recognized,
        )
        # Warm up the Whisper model in the background so the first dictation
        # doesn't stall. Runs silently; any failure is deferred to first use.
        threading.Thread(target=_get_model, daemon=True).start()

        self._populate_devices()
        self._populate_input_devices()
        self._load_settings()        # overwrites defaults with saved prefs
        self._load_history()
        self._bind_replay_key()      # must run after _load_settings sets replay_key_var
        self._bind_stop_key()
        self._bind_stt_key()         # must run after _load_settings sets stt_key_var
        self._bind_global_hotkeys()  # register replay+stop hotkeys system-wide

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Unmap>", self._on_unmap)
        # Delay _ready so startup Unmap events are ignored.
        self.after(400, lambda: setattr(self, "_ready", True))
        # Delay transparency so the window is composited before DWM is touched.
        self.after(150, lambda: apply_window_transparency(self, self.opacity_var.get()))
        self.after(800, self._check_whats_new)

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
        self.title(f"{APP_NAME} — Synthèse vocale")
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

        # Row 2: microphone → STT → TTS pipeline button (full-width, ghost style).
        # Label is updated after _load_settings to include the configured keybind.
        self.mic_btn = ctk.CTkButton(
            btn_row, text="🎙  STT", height=33,
            font=ctk.CTkFont(size=13),
            **_BTN_SECONDARY,
            command=self._on_mic_toggle)
        self.mic_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

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
        ctk.CTkLabel(
            copy_frame,
            text=f"  {APP_VERSION_DISPLAY}",
            text_color=("gray65", "gray35"),
            font=ctk.CTkFont(size=10)
        ).grid(row=0, column=2)

    # --- Devices ------------------------------------------------------------

    def _populate_input_devices(self, widget=None) -> None:
        """Rebuild the audio input device list from sounddevice.

        Only input-capable devices are included (max_input_channels > 0).
        Falls back to the first available device if the saved selection is gone.
        ``widget`` is the target CTkOptionMenu to update (settings window dropdown).
        """
        self._input_device_map.clear()
        names = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                name = f"{idx}: {dev['name']}"
                self._input_device_map[name] = idx
                names.append(name)

        if self.stt_input_var.get() not in self._input_device_map:
            if names:
                self.stt_input_var.set(names[0])

        target = widget or (
            self._settings_win.stt_input_menu
            if self._settings_win and self._settings_win.winfo_exists()
               and hasattr(self._settings_win, "stt_input_menu") else None)
        if target:
            target.configure(values=names or ["Aucun microphone"])

    def _populate_devices(self, widget=None) -> None:
        """Rebuild the audio output device list from sounddevice.

        Only output-capable devices are included (max_output_channels > 0).
        The display name includes the index so users can distinguish devices
        with identical names (e.g. two instances of the same USB audio chip).

        Auto-selection priority for the primary device:
          1. Keep the current selection if it is still valid.
          2. Prefer any device whose name contains "CABLE" (VB-Cable).
          3. Fall back to the first available output device.

        Auto-selection for the monitor device (headphones) is the inverse:
          prefer the first non-VB-Cable device so it defaults to real speakers.

        ``widget`` is the explicit CTkOptionMenu to update (from a ↺ button
        click). If None, all output dropdowns in the open settings window are
        refreshed simultaneously.
        """
        self._device_map.clear()
        names = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                name = f"{idx}: {dev['name']}"
                self._device_map[name] = idx
                names.append(name)

        # Primary: prefer VB-Cable
        if self.device_var.get() not in self._device_map:
            default = next((n for n in names if "CABLE" in n.upper()),
                           names[0] if names else "")
            if default:
                self.device_var.set(default)

        # Monitor: prefer first non-VB-Cable (real speakers/headphones)
        if self.monitor_device_var.get() not in self._device_map:
            default_mon = next((n for n in names if "CABLE" not in n.upper()),
                               names[0] if names else "")
            if default_mon:
                self.monitor_device_var.set(default_mon)

        if widget:
            widget.configure(values=names or ["Aucun périphérique"])
        else:
            sw = self._settings_win
            if sw and sw.winfo_exists():
                if hasattr(sw, "device_menu"):
                    sw.device_menu.configure(values=names or ["Aucun périphérique"])
                if hasattr(sw, "monitor_device_menu"):
                    sw.monitor_device_menu.configure(values=names or ["Aucun périphérique"])

    # --- Config -------------------------------------------------------------

    def _resolve_device(self, saved_name: str, saved_idx,
                        device_map: dict) -> str | None:
        """Find the best-matching device entry for a saved preference.

        Index-first priority (stable against renames):
        1. Sounddevice index        — survives renames; fails only if devices
                                      are added/removed between sessions.
        2. Exact name match         — fallback when index shifted (new device
                                      plugged in, USB hub reordering, etc.).
        3. Case-insensitive substr  — minor renames / suffix changes
                                      ("Speakers" still matches "Speakers (Realtek)").

        Returns the full ``"N: DeviceName"`` key from *device_map*, or None.
        """
        if not saved_name and saved_idx is None:
            return None
        strip = self._strip_device_idx

        # 1 — index (survives renames)
        if saved_idx is not None:
            match = next(
                (n for n in device_map if device_map[n] == saved_idx), None)
            if match:
                return match

        if saved_name:
            # 2 — exact name
            match = next((n for n in device_map if strip(n) == saved_name), None)
            if match:
                return match

            # 3 — case-insensitive substring
            sl = saved_name.lower()
            match = next(
                (n for n in device_map
                 if sl in strip(n).lower() or strip(n).lower() in sl),
                None)
            if match:
                return match

        return None

    @staticmethod
    def _strip_device_idx(name: str) -> str:
        """Strip the leading 'N: ' sounddevice index prefix for stable storage.

        sounddevice prepends a numeric index that can change whenever devices
        are added, removed, or reordered.  Saving only the name portion makes
        device preferences survive across reboots and hardware changes.
        """
        return name.split(": ", 1)[-1] if ": " in name else name

    def _load_settings(self) -> None:
        """Load config.json and apply values to all Tkinter vars.

        The saved dict is merged on top of DEFAULT_SETTINGS so any key
        absent from the file (e.g. a new setting added in a later version)
        is silently defaulted rather than causing a KeyError.

        Device matching compares only the name portion (index stripped) so a
        device saved as "3: Headphones (Realtek)" is still found after a reboot
        where the same device now appears as "2: Headphones (Realtek)".
        """
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_SETTINGS, **json.load(f)}
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = DEFAULT_SETTINGS.copy()

        if cfg["voice"] in VOICES:
            self.voice_var.set(cfg["voice"])

        strip = self._strip_device_idx

        # Output device
        match = self._resolve_device(
            strip(cfg.get("device", "")), cfg.get("device_idx"), self._device_map)
        if match:
            self.device_var.set(match)

        self.rate_var.set(cfg.get("rate",   0))
        self.volume_var.set(cfg.get("volume", 100))
        self.pitch_var.set(cfg.get("pitch",  0))
        self.opacity_var.set(float(cfg.get("opacity", 0.93)))
        self.replay_key_var.set(str(cfg.get("replay_key", "F2")))
        self.stop_key_var.set(str(cfg.get("stop_key", "F3")))
        self.stt_enabled_var.set(bool(cfg.get("stt_enabled", False)))

        # STT input device
        match = self._resolve_device(
            strip(cfg.get("stt_input_device", "")),
            cfg.get("stt_input_idx"),
            self._input_device_map)
        if match:
            self.stt_input_var.set(match)

        # Apply saved STT enabled state to the button
        if not self.stt_enabled_var.get():
            self.mic_btn.grid_remove()

        self.stt_key_var.set(str(cfg.get("stt_key", "F1")))
        self.stt_auto_restart_var.set(bool(cfg.get("stt_auto_restart", False)))
        self.stt_notify_var.set(bool(cfg.get("stt_notify", False)))

        self.monitor_enabled_var.set(bool(cfg.get("monitor_enabled", False)))

        # Monitor device
        match = self._resolve_device(
            strip(cfg.get("monitor_device", "")),
            cfg.get("monitor_idx"),
            self._device_map)
        if match:
            self.monitor_device_var.set(match)

        self._last_seen_version = str(cfg.get("last_seen_version", ""))

    def _save_settings(self) -> None:
        """Persist current Tkinter var values to config.json.

        Device names are stored WITHOUT the sounddevice index prefix so the
        saved preference remains valid even when the device index changes on
        the next boot (e.g. "3: Headphones" → saved as "Headphones").

        Uses an atomic write (temp file + os.replace) so a crash or power loss
        mid-write never corrupts config.json — the old file is kept intact until
        the new one is fully flushed and renamed.

        Called on window close and on quit-from-tray. OS errors are silently
        ignored to avoid a crash on shutdown.
        """
        strip = self._strip_device_idx
        payload = json.dumps({
            "voice":             self.voice_var.get(),
            "device":            strip(self.device_var.get()),
            "device_idx":        self._device_map.get(self.device_var.get()),
            "rate":              self.rate_var.get(),
            "volume":            self.volume_var.get(),
            "pitch":             self.pitch_var.get(),
            "opacity":           round(self.opacity_var.get(), 2),
            "replay_key":        self.replay_key_var.get(),
            "stop_key":          self.stop_key_var.get(),
            "stt_enabled":       self.stt_enabled_var.get(),
            "stt_input_device":  strip(self.stt_input_var.get()),
            "stt_input_idx":     self._input_device_map.get(self.stt_input_var.get()),
            "monitor_enabled":   self.monitor_enabled_var.get(),
            "monitor_device":    strip(self.monitor_device_var.get()),
            "monitor_idx":       self._device_map.get(self.monitor_device_var.get()),
            "stt_key":           self.stt_key_var.get(),
            "stt_auto_restart":  self.stt_auto_restart_var.get(),
            "stt_notify":        self.stt_notify_var.get(),
            "last_seen_version": self._last_seen_version,
            "version":           BUILD_ID,
        }, indent=2, ensure_ascii=False)
        try:
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(CONFIG_FILE), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, CONFIG_FILE)   # atomic on Windows (same volume)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    # --- What's New ---------------------------------------------------------

    def _check_whats_new(self) -> None:
        """Show the What's New dialog if the build changed since last launch."""
        if BUILD_ID == "dev":
            return
        if self._last_seen_version == BUILD_ID:
            return
        content = self._load_changelog()
        # Mark seen before showing — prevents double-show if the user force-kills the app
        self._last_seen_version = BUILD_ID
        self._save_settings()
        if content:
            from ui.whats_new import WhatsNewWindow
            WhatsNewWindow(self, content)

    def _load_changelog(self) -> str:
        """Read versions/{BUILD_ID}.md and strip YAML frontmatter.  Returns "" if absent."""
        base = sys._MEIPASS if getattr(sys, "frozen", False) \
               else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "versions", f"{BUILD_ID}.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            # Strip "---\n...\n---\n" YAML frontmatter if present
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    text = text[end + 3:].strip()
            return text
        except FileNotFoundError:
            return ""

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

    def _bind_stt_key(self) -> None:
        """Update the Tkinter window binding and button label for the STT hotkey."""
        if self._current_stt:
            try:
                self.unbind(f"<{self._current_stt}>")
            except Exception:
                pass
        key = self.stt_key_var.get()
        self._current_stt = key
        self._update_mic_btn_label()
        try:
            self.bind(f"<{key}>", lambda e: self._on_mic_toggle())
        except Exception:
            pass

    def _update_mic_btn_label(self) -> None:
        """Refresh the mic button label to show the current STT keybind."""
        self.mic_btn.configure(text=f"🎙  STT  ({self.stt_key_var.get()})")

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
        for hk in (self._hk_replay, self._hk_stop, self._hk_stt):
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

        try:
            self._hk_stt = keyboard.add_hotkey(
                self.stt_key_var.get().lower(),
                lambda: self.after(0, self._on_mic_toggle))
        except Exception:
            self._hk_stt = None

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

    def _on_close(self) -> None:
        """Redirect the X-button to the system tray instead of quitting.

        Settings are saved immediately so they survive if the process is
        killed while the app sits in the tray (no Quitter path reached).
        Shows a balloon notification once the tray icon is registered.
        """
        if self._in_tray:
            return
        self._save_settings()
        self._in_tray = True
        self._hide_to_tray()
        self.after(800, self._tray_notify_hidden)

    def _tray_notify(self, message: str, title: str = APP_NAME) -> None:
        """Send a balloon notification.

        Uses the live tray icon when the app is hidden in the tray.
        Falls back to a temporary icon (send_notification) when the main
        window is visible and no tray icon exists yet.
        """
        if self._tray_icon:
            try:
                self._tray_icon.notify(message, title)
                return
            except Exception:
                pass
        send_notification(title, message)

    def _tray_notify_hidden(self) -> None:
        self._tray_notify(
            f"{APP_NAME} continue en arrière-plan.\n"
            "Cliquez sur l'icône pour réouvrir.")

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
        if not text or self._tts_busy.is_set():
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
        _stt_triggered_tts is cleared so a manual stop does not accidentally
        trigger auto-restart on a subsequent normal TTS.
        """
        self._stop_event.set()
        self._stt_triggered_tts = False
        sd.stop()
        self._restore_ui()

    def _on_replay(self) -> None:
        """Replay the last generated audio without re-calling edge-tts."""
        if not os.path.exists(LAST_MP3) or self._tts_busy.is_set():
            return
        self._stop_event.clear()
        self.speak_btn.configure(state="disabled")
        self.replay_btn.configure(state="disabled")
        self._set_status(STATUS_PLAYING)
        self._run_worker(self._replay_async)

    # --- STT / Microphone ---------------------------------------------------

    def _on_mic_toggle(self) -> None:
        """Start VAD listening, or cancel if already in progress.

        A single press is enough: VAD detects end-of-speech automatically.
        A second press during listening or recording cancels without transcribing.
        Blocked while TTS is playing; button is disabled during transcription.
        """
        if self._tts_busy.is_set():
            return
        if self._stt_state == "idle":
            self._listener.device = self._input_device_map.get(self.stt_input_var.get())
            self._listener.start_listening()
        elif self._stt_state in ("listening", "recording"):
            self._listener.cancel()
            self._restore_ui()   # restore speak/replay immediately (no TTS pending)

    def _on_stt_toggle(self) -> None:
        """Show or hide the mic button when STT is enabled/disabled in settings.

        Recomputes the window height after the grid reflows so no blank space
        is left behind when the button is hidden.
        When disabling, any active recording is cancelled immediately.
        When enabling, the button label is refreshed (key may have changed
        while the button was hidden) before restoring its grid position.
        """
        if self.stt_enabled_var.get():
            self._update_mic_btn_label()
            self.mic_btn.grid()
        else:
            if self._listener:
                self._listener.cancel()
            self.mic_btn.grid_remove()
        self.update_idletasks()
        self.geometry(f"490x{self.winfo_reqheight()}")

    def _on_stt_state_change(self, new_state: str) -> None:
        """Marshal STTListener state change to the main thread via after(0)."""
        self.after(0, lambda s=new_state: self._apply_stt_state(s))

    def _apply_stt_state(self, state: str) -> None:
        """Apply an STT state change to the UI — must run on the main thread.

        Button state machine:
          idle         → "🎙 STT (key)" (ghost style, enabled)
          listening    → "👂 En écoute..." (dark green) — mic open, waiting for speech
          recording    → "🔊 Parole..." (red) + recognizing.wav — speech detected
          transcribing → "🎙 STT" (disabled) — Whisper running

        speak_btn / replay_btn are restored by _restore_ui(), called from:
          - _on_mic_toggle (user cancellation)
          - _on_stt_not_recognized / _on_stt_error (end without TTS)
          - _run_worker.finally (TTS finished)
        They are NOT restored here to avoid a race with _apply_transcript.
        """
        self._stt_state = state
        if state == "idle":
            self.mic_btn.configure(
                text=f"🎙  STT  ({self.stt_key_var.get()})",
                state="normal",
                fg_color=_BTN_SECONDARY["fg_color"],
                hover_color=_BTN_SECONDARY["hover_color"],
            )
        elif state == "listening":
            self.mic_btn.configure(
                text="👂  En écoute...",
                state="normal",
                fg_color="#145214",
                hover_color="#0f3d0f",
            )
            self.speak_btn.configure(state="disabled")
            self.replay_btn.configure(state="disabled")
            self._set_status("À l'écoute...")
        elif state == "recording":
            self.mic_btn.configure(
                text="🔊  Parole...",
                state="normal",
                fg_color="#6e1212",
                hover_color="#521010",
            )
            self._set_status(STATUS_RECORDING)
            play_sound(SND_RECOGNIZING)
        elif state == "transcribing":
            self.mic_btn.configure(
                text="🎙  STT",
                state="disabled",
            )
            self._set_status(STATUS_TRANSCRIBING)

    def _on_stt_transcript(self, text: str) -> None:
        """Receive transcript from background thread — marshal to main thread."""
        self.after(0, lambda t=text: self._apply_transcript(t))

    def _apply_transcript(self, text: str) -> None:
        """Play recognized sound, insert transcript, then launch TTS pipeline.

        Runs on the main thread. TTS via _on_speak() starts immediately after
        so the user hears both the confirmation sound and the speech output.
        _restore_ui() is called by _run_worker's finally block when TTS ends.
        """
        play_sound(SND_RECOGNIZED)
        self._set_textbox(text)
        if self.stt_notify_var.get():
            self._tray_notify(text, "STT — Retranscription")
        self._stt_triggered_tts = True
        self._on_speak()

    def _on_stt_not_recognized(self) -> None:
        """Called when Whisper returns no usable text — marshal to main thread."""
        def _ui():
            play_sound(SND_NOT_RECOGNIZED)
            self._set_status("STT: Aucun texte détecté.")
            self._restore_ui()
        self.after(0, _ui)

    def _on_stt_error(self, message: str) -> None:
        """Called on system-level STT failures (mic, model, crash) — marshal."""
        def _ui():
            self._set_status(f"STT: {message}")
            self._restore_ui()
            if self._in_tray:
                self._tray_notify(f"Erreur STT — {message}")
        self.after(0, _ui)

    def _maybe_auto_restart_stt(self) -> None:
        """Re-trigger STT listening if auto-restart is enabled and TTS came from STT.

        Called from _run_worker's finally block (main thread via after(0)).
        Does nothing if TTS was triggered manually (_stt_triggered_tts is False).
        Does nothing if the user has disabled auto-restart or STT entirely.
        """
        if not self._stt_triggered_tts:
            return
        self._stt_triggered_tts = False
        if self.stt_auto_restart_var.get() and self.stt_enabled_var.get():
            self._on_mic_toggle()

    def _shutdown(self) -> None:
        """Save state and destroy the application.

        Called from the window close button and from the tray Quit item.
        Global hotkeys are removed first to prevent callbacks firing on a
        partially destroyed window. sd.stop() ensures no audio lingers.
        self.after(0, self.destroy) defers destruction so this method can
        safely be called from a non-Tkinter thread (tray or keyboard callback).
        """
        for hk in (self._hk_replay, self._hk_stop, self._hk_stt):
            if hk is not None:
                try:
                    keyboard.remove_hotkey(hk)
                except Exception:
                    pass
        self._save_settings()
        try:
            os.remove(LAST_MP3)
        except OSError:
            pass
        self._stop_event.set()
        sd.stop()
        if self._listener:
            self._listener.cancel()
        if self._tray_icon:
            self._tray_icon.stop()
        self._loop.call_soon_threadsafe(self._loop.stop)
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
        """Submit a TTS coroutine to the persistent event loop.

        The persistent loop (self._loop) runs in a dedicated daemon thread for
        the app's lifetime, eliminating per-call thread and loop startup costs.
        _tts_busy is set immediately so that re-entrant calls are blocked even
        before the coroutine is scheduled on the loop.
        """
        self._tts_busy.set()

        async def _wrapper():
            try:
                await coro_factory()
            except Exception as e:
                self.after(0, lambda: self._set_status(
                    f"{STATUS_ERROR}: {str(e)[:80]}"))
            finally:
                self._tts_busy.clear()
                if not self._stop_event.is_set():
                    self.after(0, self._restore_ui)
                    self.after(0, self._maybe_auto_restart_stt)

        asyncio.run_coroutine_threadsafe(_wrapper(), self._loop)

    async def _tts_async(self, text: str) -> None:
        """Stream TTS audio from edge-tts, persist it, then play it.

        Volume is stored as 0–100 in config but edge-tts expects a signed
        percent offset relative to 100 (e.g. 80 → "-20%", 100 → "+0%").
        Decode runs in a thread-pool executor so the event loop is not blocked.
        The file save also runs in the executor concurrently with silence trimming.
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

        loop = asyncio.get_running_loop()
        data = bytes(mp3_buffer)

        # Decode PCM off the event loop thread (CPU-bound).
        # Save to disk concurrently so replay is ready as soon as audio starts.
        pcm, samplerate = await loop.run_in_executor(None, _decode_mp3, data)
        loop.run_in_executor(None, save_mp3, LAST_MP3, data)

        pcm = trim_silence(pcm)
        if not pcm.size:
            return

        self._set_status(STATUS_PLAYING)
        await self._play_pcm(pcm, samplerate)

    async def _replay_async(self) -> None:
        """Load last.mp3 from disk and play it without re-generating TTS."""
        with open(LAST_MP3, "rb") as f:
            data = f.read()
        pcm, samplerate = _decode_mp3(data)
        await self._play_pcm(pcm, samplerate)

    async def _play_pcm(self, pcm: np.ndarray, samplerate: int) -> None:
        """Play PCM on the primary device and optionally on the monitor device.

        latency='low' asks PortAudio for the smallest stable buffer, shaving
        20–40 ms off the device-open → first-sample delay on Windows WASAPI.

        The wait loop runs in the thread-pool executor so the event loop is
        free to service other coroutines. _stop_event.wait(0.005) gives 5 ms
        stop resolution — 10× tighter than the old 50 ms asyncio.sleep poll.
        """
        primary_idx = self._device_map.get(self.device_var.get())
        sd.play(pcm, samplerate=samplerate, device=primary_idx,
                blocking=False, latency='low')

        # --- Optional monitor stream ----------------------------------------
        monitor_stream = None
        if self.monitor_enabled_var.get():
            m_idx = self._device_map.get(self.monitor_device_var.get())
            if m_idx is not None and m_idx != primary_idx:
                try:
                    monitor_stream = sd.OutputStream(
                        samplerate=samplerate, device=m_idx,
                        channels=1, dtype="int16", latency='low')
                    monitor_stream.start()
                    threading.Thread(
                        target=self._write_monitor_pcm,
                        args=(monitor_stream, pcm),
                        daemon=True).start()
                except Exception:
                    if monitor_stream is not None:
                        try:
                            monitor_stream.close()
                        except Exception:
                            pass
                    monitor_stream = None

        # --- Wait in executor: 5 ms resolution, event loop stays free -------
        stop = self._stop_event

        def _wait() -> bool:
            """Return True if stopped by user, False if finished naturally."""
            while True:
                if stop.wait(timeout=0.005):
                    return True
                try:
                    if not sd.get_stream().active:
                        return False
                except Exception:
                    return False

        stopped = await asyncio.get_running_loop().run_in_executor(None, _wait)

        if stopped:
            sd.stop()
            if monitor_stream is not None:
                try:
                    monitor_stream.abort()
                except Exception:
                    pass
            return

        if monitor_stream is not None:
            try:
                monitor_stream.stop()
                monitor_stream.close()
            except Exception:
                pass

    def _write_monitor_pcm(self, stream: "sd.OutputStream", pcm: np.ndarray) -> None:
        """Write PCM to the monitor OutputStream — runs on a daemon thread.

        write() blocks until all data is consumed by PortAudio. If the stream
        is aborted externally (via abort() from the stop handler), a
        PortAudioError is raised here and silently swallowed so the thread
        exits cleanly without printing a traceback.
        """
        try:
            stream.write(pcm)
        except Exception:
            pass
