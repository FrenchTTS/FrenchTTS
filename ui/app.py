"""
FrenchTTS — main application window.
"""

import asyncio
import datetime
import json
import os
import threading
import webbrowser

import edge_tts
import keyboard
import customtkinter as ctk
import numpy as np
import pystray
import sounddevice as sd
from PIL import Image

from core.constants import (
    VOICES, APP_NAME, APP_URL,
    STATUS_READY, STATUS_LOADING, STATUS_PLAYING, STATUS_ERROR,
    STATUS_RECORDING, STATUS_TRANSCRIBING,
    MAX_HISTORY, DEFAULT_SETTINGS, _BTN_SECONDARY,
    LAST_MP3, CONFIG_FILE, HISTORY_LOG,
    fmt_rate, fmt_pitch,
)
from core.audio import _decode_mp3
from ui.utils import (
    _get_icon_path, make_tray_image,
    _set_window_icon, apply_window_transparency,
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

        # --- STT state ------------------------------------------------------
        self._stt_state = "idle"   # "idle" | "recording" | "transcribing"
        self._listener: STTListener | None = None

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

        self._listener = STTListener(
            on_transcript=self._on_stt_transcript,
            on_state_change=self._on_stt_state_change,
            on_error=self._on_stt_error,
        )
        # Warm up the Whisper model in the background so the first dictation
        # doesn't stall. Runs silently; any failure is deferred to first use.
        threading.Thread(target=_get_model, daemon=True).start()

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

        # Row 2: microphone dictation (full-width, ghost style)
        self.mic_btn = ctk.CTkButton(
            btn_row, text="🎙  Dicter", height=33,
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

    # --- STT / Microphone ---------------------------------------------------

    def _on_mic_toggle(self) -> None:
        """Toggle between recording and stop-to-transcribe.

        Blocked while TTS is playing. The transcribing state disables the
        button itself, so only idle→recording and recording→transcribing
        transitions are reachable here.
        """
        if self._tts_thread and self._tts_thread.is_alive():
            return
        if self._stt_state == "idle":
            self._listener.start_recording()
        elif self._stt_state == "recording":
            self._listener.stop_recording()

    def _on_stt_state_change(self, new_state: str) -> None:
        """Marshal STTListener state change to the main thread."""
        self.after(0, lambda s=new_state: self._apply_stt_state(s))

    def _apply_stt_state(self, state: str) -> None:
        """Apply STT state to the UI — must run on the main thread."""
        self._stt_state = state
        if state == "idle":
            self.mic_btn.configure(
                text="🎙  Dicter",
                state="normal",
                fg_color=_BTN_SECONDARY["fg_color"],
                hover_color=_BTN_SECONDARY["hover_color"],
            )
            if not (self._tts_thread and self._tts_thread.is_alive()):
                self._restore_ui()
        elif state == "recording":
            self.mic_btn.configure(
                text="⏹  Stop",
                state="normal",
                fg_color="#1a5c1a",
                hover_color="#154a15",
            )
            self.speak_btn.configure(state="disabled")
            self.replay_btn.configure(state="disabled")
            self._set_status(STATUS_RECORDING)
        elif state == "transcribing":
            self.mic_btn.configure(state="disabled")
            self._set_status(STATUS_TRANSCRIBING)

    def _on_stt_transcript(self, text: str) -> None:
        """Receive transcript from background thread — marshal to main thread."""
        self.after(0, lambda t=text: self._apply_transcript(t))

    def _apply_transcript(self, text: str) -> None:
        """Insert transcript into textbox and trigger TTS — main thread only."""
        self._set_textbox(text)
        self._on_speak()

    def _on_stt_error(self, message: str) -> None:
        """Show STT errors in the status bar — marshal to main thread."""
        self.after(0, lambda m=message: self._set_status(f"STT: {m}"))

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
        if self._listener:
            self._listener.cancel()
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
