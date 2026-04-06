"""
FrenchTTS — settings window.
"""

import customtkinter as ctk

from core.constants import (APP_NAME, VOICES, _BTN_SECONDARY,
                            fmt_rate, fmt_pitch, fmt_volume, BASE_DIR)
from ui.utils import _set_window_icon, apply_window_transparency, _safe_open


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

        # --- STT (Micro → TTS) section --------------------------------------
        # Row 11: enable/disable toggle
        ctk.CTkLabel(self, text="Micro → TTS :").grid(row=11, column=0, **LBL)
        stt_sw_frame = ctk.CTkFrame(self, fg_color="transparent")
        stt_sw_frame.grid(row=11, column=1, columnspan=2, sticky="w", **CTL)
        ctk.CTkSwitch(
            stt_sw_frame, text="Activé",
            variable=self._app.stt_enabled_var,
            command=self._app._on_stt_toggle,
            onvalue=True, offvalue=False,
        ).grid(row=0, column=0, sticky="w")

        # Row 12: input device selector — mirrors the output device row above.
        # ↺ re-queries sounddevice in case a USB mic was plugged in after launch.
        ctk.CTkLabel(self, text="Microphone :").grid(row=12, column=0, **LBL)
        self.stt_input_menu = ctk.CTkOptionMenu(
            self, variable=self._app.stt_input_var, values=[])
        self.stt_input_menu.grid(row=12, column=1, sticky="ew", padx=(0, 4), pady=7)
        ctk.CTkButton(self, text="↺", width=32,
                      command=lambda: self._app._populate_input_devices(
                          widget=self.stt_input_menu)
                      ).grid(row=12, column=2, padx=(0, 16), pady=7)
        self._app._populate_input_devices(widget=self.stt_input_menu)

        self._separator(row=13)

        # --- Footer buttons -------------------------------------------------
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=14, column=0, columnspan=3, pady=(10, 14))
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
