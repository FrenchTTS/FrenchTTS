"""
FrenchTTS — settings window.
"""

import customtkinter as ctk

from core.constants import (APP_NAME, VOICES, _BTN_SECONDARY,
                            fmt_rate, fmt_pitch, fmt_volume, BASE_DIR)
from ui.utils import _set_window_icon, apply_window_transparency, _safe_open

_WIN_W = 560   # settings window width
_MAX_H = 760   # maximum settings window height before the scrollbar kicks in


class SettingsWindow(ctk.CTkToplevel):
    """Non-modal settings panel that shares Tkinter vars with FrenchTTSApp.

    All sliders and menus write directly into the app's StringVar / IntVar /
    DoubleVar instances, so changes take effect immediately without an explicit
    "Apply" step.

    Layout
    ------
    row 0  — "Paramètres" header label (fixed, not scrolled)
    row 1  — CTkScrollableFrame containing all setting sections (weight=1)
    row 2  — footer buttons (fixed, always visible)

    The scrollable frame is capped at _MAX_H so the window never grows taller
    than the screen while still fitting all controls.
    """

    def __init__(self, app: "FrenchTTSApp"):
        super().__init__(app)
        self._app = app
        self.title(f"Paramètres — {APP_NAME}")
        self.geometry(f"{_WIN_W}x1")
        self.resizable(False, False)
        self.transient(app)
        self._capturing_key = False
        self._capture_var  = None
        self._capture_lbl  = None
        self._capture_btn  = None
        self._capture_post = None
        self._build()
        self.update_idletasks()
        h = min(self.winfo_reqheight(), _MAX_H)
        self.geometry(f"{_WIN_W}x{h}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _set_window_icon(self)
        self.after(50,  self.lift)
        self.after(120, lambda: apply_window_transparency(self, self._app.opacity_var.get()))

    # --- Layout -------------------------------------------------------------

    def _build(self) -> None:
        """Build the settings layout.

        The outer window provides a fixed header and footer.
        All sections (rows 1–N) live inside self._frm (CTkScrollableFrame).

        Columns inside the scroll frame:
          col 0  fixed width (minsize=148) for labels
          col 1  expandable for controls
          col 2  narrow for auxiliary buttons (↺)
        """
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)   # scroll frame expands vertically

        # ── Fixed header ────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Paramètres",
                     font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, pady=(14, 6))

        # ── Scrollable content ───────────────────────────────────────────────
        frm = ctk.CTkScrollableFrame(
            self, corner_radius=0, border_width=0, fg_color="transparent")
        frm.grid(row=1, column=0, sticky="nsew")
        frm.columnconfigure(0, minsize=165, weight=0)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=0)
        self._frm = frm

        LBL = dict(padx=(16, 8), pady=5, sticky="w")
        CTL = dict(padx=(0, 14), pady=5)

        # ── Section: Voice & Devices ─────────────────────────────────────────
        self._section_label(row=0, text="Voix & Périphériques")

        ctk.CTkLabel(frm, text="Voix :").grid(row=1, column=0, **LBL)
        ctk.CTkOptionMenu(frm, variable=self._app.voice_var,
                          values=list(VOICES.keys())
                          ).grid(row=1, column=1, columnspan=2, sticky="ew", **CTL)

        ctk.CTkLabel(frm, text="Sortie TTS :").grid(row=2, column=0, **LBL)
        self.device_menu = ctk.CTkOptionMenu(
            frm, variable=self._app.device_var, values=[])
        self.device_menu.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=5)
        ctk.CTkButton(frm, text="↺", width=32,
                      command=lambda: self._app._populate_devices(widget=self.device_menu)
                      ).grid(row=2, column=2, padx=(0, 14), pady=5)
        self._app._populate_devices(widget=self.device_menu)

        ctk.CTkLabel(frm, text="Casque :").grid(row=3, column=0, **LBL)
        casque_frame = ctk.CTkFrame(frm, fg_color="transparent")
        casque_frame.grid(row=3, column=1, columnspan=2, sticky="ew", **CTL)
        casque_frame.columnconfigure(0, weight=1)
        self.monitor_device_menu = ctk.CTkOptionMenu(
            casque_frame, variable=self._app.monitor_device_var, values=[])
        self.monitor_device_menu.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(casque_frame, text="↺", width=32,
                      command=lambda: self._app._populate_devices(
                          widget=self.monitor_device_menu)
                      ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkSwitch(casque_frame, text="",
                      variable=self._app.monitor_enabled_var,
                      onvalue=True, offvalue=False, width=46,
                      ).grid(row=0, column=2)
        self._app._populate_devices(widget=self.monitor_device_menu)

        self._separator(row=4)

        # ── Section: Voice settings ───────────────────────────────────────────
        self._section_label(row=5, text="Paramètres vocaux")

        for r, label, var, lo, hi, fmt in [
            (6, "Vitesse :", self._app.rate_var,   -50,  100, fmt_rate),
            (7, "Volume :",  self._app.volume_var,   0,  100, fmt_volume),
            (8, "Pitch :",   self._app.pitch_var,  -100, 100, fmt_pitch),
        ]:
            ctk.CTkLabel(frm, text=label).grid(row=r, column=0, **LBL)
            self._slider_row(row=r, var=var, from_=lo, to=hi, fmt=fmt)

        self._separator(row=9)

        # ── Section: Interface ────────────────────────────────────────────────
        self._section_label(row=10, text="Interface")

        ctk.CTkLabel(frm, text="Opacité :").grid(row=11, column=0, **LBL)
        op_frame = ctk.CTkFrame(frm, fg_color="transparent")
        op_frame.grid(row=11, column=1, columnspan=2, sticky="ew", **CTL)
        op_frame.columnconfigure(0, weight=1)
        self._opacity_lbl = ctk.CTkLabel(
            op_frame, text=f"{int(self._app.opacity_var.get() * 100)}%",
            width=40, anchor="w")
        ctk.CTkSlider(op_frame, from_=0.4, to=1.0,
                      variable=self._app.opacity_var,
                      command=self._on_opacity_change
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._opacity_lbl.grid(row=0, column=1)

        self._separator(row=12)

        # ── Section: Keyboard shortcuts ───────────────────────────────────────
        self._section_label(row=13, text="Raccourcis clavier")

        self._replay_key_lbl, self._replay_key_btn = self._hotkey_row(
            row=14, label="Touche Redire :",
            var=self._app.replay_key_var,
            post_fn=lambda: (self._app._bind_replay_key(),
                             self._app._bind_global_hotkeys()),
            lbl_kw=LBL, ctl_kw=CTL)

        self._stop_key_lbl, self._stop_key_btn = self._hotkey_row(
            row=15, label="Touche Arrêter :",
            var=self._app.stop_key_var,
            post_fn=lambda: (self._app._bind_stop_key(),
                             self._app._bind_global_hotkeys()),
            lbl_kw=LBL, ctl_kw=CTL)

        self._separator(row=16)

        # ── Section: STT ─────────────────────────────────────────────────────
        self._section_label(row=17, text="STT — Reconnaissance vocale")
        ctk.CTkLabel(
            frm,
            text="STT (Speech-to-Text) : micro → texte   •   TTS (Text-to-Speech) : texte → voix",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).grid(row=18, column=0, columnspan=3, padx=16, pady=(0, 3), sticky="w")

        ctk.CTkLabel(frm, text="Activer :").grid(row=19, column=0, **LBL)
        stt_sw_frame = ctk.CTkFrame(frm, fg_color="transparent")
        stt_sw_frame.grid(row=19, column=1, columnspan=2, sticky="w", **CTL)
        ctk.CTkSwitch(
            stt_sw_frame, text="",
            variable=self._app.stt_enabled_var,
            command=self._app._on_stt_toggle,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        self._stt_key_lbl, self._stt_key_btn = self._hotkey_row(
            row=20, label="Touche STT :",
            var=self._app.stt_key_var,
            post_fn=lambda: (self._app._bind_stt_key(),
                             self._app._bind_global_hotkeys()),
            lbl_kw=LBL, ctl_kw=CTL)

        ctk.CTkLabel(frm, text="Redémarrage auto :").grid(row=21, column=0, **LBL)
        stt_ar_frame = ctk.CTkFrame(frm, fg_color="transparent")
        stt_ar_frame.grid(row=21, column=1, columnspan=2, sticky="w", **CTL)
        ctk.CTkSwitch(
            stt_ar_frame, text="",
            variable=self._app.stt_auto_restart_var,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(frm, text="Microphone :").grid(row=22, column=0, **LBL)
        self.stt_input_menu = ctk.CTkOptionMenu(
            frm, variable=self._app.stt_input_var, values=[])
        self.stt_input_menu.grid(row=22, column=1, sticky="ew", padx=(0, 4), pady=5)
        ctk.CTkButton(frm, text="↺", width=32,
                      command=lambda: self._app._populate_input_devices(
                          widget=self.stt_input_menu)
                      ).grid(row=22, column=2, padx=(0, 14), pady=5)
        self._app._populate_input_devices(widget=self.stt_input_menu)

        # ── Fixed footer ────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=(8, 12))
        ctk.CTkButton(btn_frame, text="Dossier config", width=140,
                      **_BTN_SECONDARY,
                      command=lambda: _safe_open(BASE_DIR)
                      ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Fermer", width=120,
                      command=self.destroy
                      ).grid(row=0, column=1)

    # --- Widget helpers (all target self._frm) --------------------------------

    def _hotkey_row(self, row: int, label: str, var: ctk.StringVar,
                    post_fn, lbl_kw: dict, ctl_kw: dict):
        """Build a hotkey capture row inside the scroll frame."""
        ctk.CTkLabel(self._frm, text=label).grid(row=row, column=0, **lbl_kw)
        frame = ctk.CTkFrame(self._frm, fg_color="transparent")
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

    def _separator(self, row: int, pady: tuple = (8, 2)) -> None:
        ctk.CTkFrame(self._frm, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=row, column=0, columnspan=3,
                            sticky="ew", padx=14, pady=pady)

    def _section_label(self, row: int, text: str) -> None:
        ctk.CTkLabel(
            self._frm, text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"),
            anchor="w",
        ).grid(row=row, column=0, columnspan=3,
               padx=16, pady=(8, 0), sticky="w")

    def _slider_row(self, row: int, var: ctk.IntVar, from_: int, to: int, fmt) -> None:
        frame = ctk.CTkFrame(self._frm, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=6)
        frame.columnconfigure(0, weight=1)
        lbl = ctk.CTkLabel(frame, text=fmt(var.get()), width=56, anchor="w")
        ctk.CTkSlider(frame, from_=from_, to=to, variable=var,
                      command=lambda v, _l=lbl, _f=fmt: _l.configure(text=_f(int(v)))
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        lbl.grid(row=0, column=1)

    # --- Event handlers -------------------------------------------------------

    def _on_opacity_change(self, value: float) -> None:
        val = round(float(value), 2)
        self._opacity_lbl.configure(text=f"{int(val * 100)}%")
        apply_window_transparency(self._app, val)
        apply_window_transparency(self, val)

    def _start_key_capture(self, var: ctk.StringVar, lbl, btn, post_fn) -> None:
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
        self.unbind("<KeyPress>")
        self._capturing_key = False
        self._capture_btn.configure(text="Changer", state="normal")
        if event.keysym == "Escape":
            return
        self._capture_var.set(event.keysym)
        self._capture_lbl.configure(text=event.keysym)
        self._capture_post()

