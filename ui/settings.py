"""
FrenchTTS — settings window (collapsible sections).
"""

import os
import webbrowser

import customtkinter as ctk

from core.constants import (APP_NAME, VOICES, _BTN_SECONDARY,
                            fmt_rate, fmt_pitch, fmt_volume, BASE_DIR,
                            PROCESS_PRIORITY_LABELS)
from ui.utils import _set_window_icon, apply_window_transparency, _safe_open, force_taskbar_presence

_WIN_W = 560
_MAX_H = 720


class SettingsWindow(ctk.CTkToplevel):
    """Non-modal settings panel. Changes apply immediately (no Apply button)."""

    _LBL = dict(padx=(16, 8), pady=5, sticky="w")
    _CTL = dict(padx=(0, 14), pady=5)

    def __init__(self, app: "FrenchTTSApp"):
        super().__init__(app)
        self._app = app
        self.title(f"{APP_NAME} - Paramètres")
        self.geometry(f"{_WIN_W}x1")
        self.resizable(False, False)
        self.transient(app)
        self._capturing_key   = False
        self._capture_var     = None
        self._capture_lbl     = None
        self._capture_btn     = None
        self._capture_post    = None
        self._token_visible   = False
        self._build()
        self.geometry(f"{_WIN_W}x{_MAX_H}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _set_window_icon(self)
        self.after(50,  self.lift)
        self.after(120, lambda: apply_window_transparency(self, self._app.opacity_var.get()))
        self.after(250, lambda: force_taskbar_presence(self))

    def destroy(self) -> None:
        try:
            for aid in self.tk.call("after", "info").split():
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        super().destroy()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Paramètres",
                     font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, pady=(14, 6))

        # Scrollable frame — sections packed vertically inside
        frm = ctk.CTkScrollableFrame(
            self, corner_radius=0, border_width=0, fg_color="transparent")
        frm.grid(row=1, column=0, sticky="nsew")
        self._frm = frm

        # ── Voix & Périphériques ───────────────────────────────────────────
        sc = self._section(frm, "Voix & Périphériques", expanded=True)

        ctk.CTkLabel(sc, text="Voix :").grid(row=0, column=0, **self._LBL)
        ctk.CTkOptionMenu(sc, variable=self._app.voice_var,
                          values=list(VOICES.keys())
                          ).grid(row=0, column=1, columnspan=2, sticky="ew", **self._CTL)

        ctk.CTkLabel(sc, text="Sortie TTS :").grid(row=1, column=0, **self._LBL)
        self.device_menu = ctk.CTkOptionMenu(
            sc, variable=self._app.device_var, values=[])
        self.device_menu.grid(row=1, column=1, sticky="ew", padx=(0, 4), pady=5)
        ctk.CTkButton(sc, text="↺", width=32,
                      command=lambda: self._app._populate_devices(widget=self.device_menu)
                      ).grid(row=1, column=2, padx=(0, 14), pady=5)
        self._app._populate_devices(widget=self.device_menu)

        ctk.CTkLabel(sc, text="Casque :").grid(row=2, column=0, **self._LBL)
        casque_frame = ctk.CTkFrame(sc, fg_color="transparent")
        casque_frame.grid(row=2, column=1, columnspan=2, sticky="ew", **self._CTL)
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

        # ── Paramètres vocaux ──────────────────────────────────────────────
        sc = self._section(frm, "Paramètres vocaux", expanded=True)

        for r, label, var, lo, hi, fmt in [
            (0, "Vitesse :", self._app.rate_var,   -50,  100, fmt_rate),
            (1, "Volume :",  self._app.volume_var,   0,  100, fmt_volume),
            (2, "Pitch :",   self._app.pitch_var,  -100, 100, fmt_pitch),
        ]:
            ctk.CTkLabel(sc, text=label).grid(row=r, column=0, **self._LBL)
            self._slider_row(sc, row=r, var=var, from_=lo, to=hi, fmt=fmt)

        # ── Interface ──────────────────────────────────────────────────────
        sc = self._section(frm, "Interface", expanded=False)

        ctk.CTkLabel(sc, text="Opacité :").grid(row=0, column=0, **self._LBL)
        op_frame = ctk.CTkFrame(sc, fg_color="transparent")
        op_frame.grid(row=0, column=1, columnspan=2, sticky="ew", **self._CTL)
        op_frame.columnconfigure(0, weight=1)
        self._opacity_lbl = ctk.CTkLabel(
            op_frame, text=f"{int(self._app.opacity_var.get() * 100)}%",
            width=40, anchor="w")
        ctk.CTkSlider(op_frame, from_=0.4, to=1.0,
                      variable=self._app.opacity_var,
                      command=self._on_opacity_change
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._opacity_lbl.grid(row=0, column=1)

        # ── Raccourcis clavier ─────────────────────────────────────────────
        sc = self._section(frm, "Raccourcis clavier", expanded=False)

        self._replay_key_lbl, self._replay_key_btn = self._hotkey_row(
            sc, row=0, label="Touche Redire :",
            var=self._app.replay_key_var,
            post_fn=lambda: (self._app._bind_replay_key(),
                             self._app._bind_global_hotkeys()))

        self._stop_key_lbl, self._stop_key_btn = self._hotkey_row(
            sc, row=1, label="Touche Arrêter :",
            var=self._app.stop_key_var,
            post_fn=lambda: (self._app._bind_stop_key(),
                             self._app._bind_global_hotkeys()))

        # ── STT — Reconnaissance vocale ────────────────────────────────────
        sc = self._section(frm, "STT — Reconnaissance vocale", expanded=False)

        ctk.CTkLabel(
            sc,
            text="STT (Speech-to-Text) : micro → texte   •   TTS (Text-to-Speech) : texte → voix",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=16, pady=(0, 3), sticky="w")

        ctk.CTkLabel(sc, text="Activer :").grid(row=1, column=0, **self._LBL)
        stt_sw = ctk.CTkFrame(sc, fg_color="transparent")
        stt_sw.grid(row=1, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(
            stt_sw, text="",
            variable=self._app.stt_enabled_var,
            command=self._app._on_stt_toggle,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        self._stt_key_lbl, self._stt_key_btn = self._hotkey_row(
            sc, row=2, label="Touche STT :",
            var=self._app.stt_key_var,
            post_fn=lambda: (self._app._bind_stt_key(),
                             self._app._bind_global_hotkeys()))

        ctk.CTkLabel(sc, text="Redémarrage auto :").grid(row=3, column=0, **self._LBL)
        stt_ar = ctk.CTkFrame(sc, fg_color="transparent")
        stt_ar.grid(row=3, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(stt_ar, text="",
                      variable=self._app.stt_auto_restart_var,
                      onvalue=True, offvalue=False, width=46,
                      ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(sc, text="Notif. texte :").grid(row=4, column=0, **self._LBL)
        stt_notif = ctk.CTkFrame(sc, fg_color="transparent")
        stt_notif.grid(row=4, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(stt_notif, text="",
                      variable=self._app.stt_notify_var,
                      onvalue=True, offvalue=False, width=46,
                      ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            stt_notif,
            text="Affiche le texte reconnu en notification",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
        ).grid(row=0, column=1, padx=(8, 0), sticky="w")

        ctk.CTkLabel(sc, text="Microphone :").grid(row=5, column=0, **self._LBL)
        self.stt_input_menu = ctk.CTkOptionMenu(
            sc, variable=self._app.stt_input_var, values=[])
        self.stt_input_menu.grid(row=5, column=1, sticky="ew", padx=(0, 4), pady=5)
        ctk.CTkButton(sc, text="↺", width=32,
                      command=lambda: self._app._populate_input_devices(
                          widget=self.stt_input_menu)
                      ).grid(row=5, column=2, padx=(0, 14), pady=5)
        self._app._populate_input_devices(widget=self.stt_input_menu)

        # ── Performances ───────────────────────────────────────────────────
        sc = self._section(frm, "Performances  (Ordinateur Patate 😉)", expanded=False)

        ncpus = os.cpu_count() or 1
        ctk.CTkLabel(sc, text="Cœurs CPU :").grid(row=0, column=0, **self._LBL)
        cpu_frame = ctk.CTkFrame(sc, fg_color="transparent")
        cpu_frame.grid(row=0, column=1, columnspan=2, sticky="ew", **self._CTL)
        cpu_frame.columnconfigure(0, weight=1)
        self._cpu_lbl = ctk.CTkLabel(
            cpu_frame,
            text=self._fmt_cores(self._app.cpu_cores_var.get(), ncpus),
            width=100, anchor="w")
        ctk.CTkSlider(
            cpu_frame,
            from_=1, to=max(ncpus, 2), number_of_steps=max(ncpus - 1, 1),
            variable=self._app.cpu_cores_var,
            command=lambda v: self._on_cpu_change(int(round(v)), ncpus),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._cpu_lbl.grid(row=0, column=1)
        ctk.CTkLabel(
            sc,
            text=("Limite les cœurs CPU utilisés par l'app  •  "
                  "Minimum recommandé : 2 (1 sans STT)"),
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 6), sticky="w")

        priority_labels = list(PROCESS_PRIORITY_LABELS.values())
        ctk.CTkLabel(sc, text="Priorité CPU :").grid(row=2, column=0, **self._LBL)
        ctk.CTkOptionMenu(
            sc,
            variable=self._app.process_priority_var,
            values=priority_labels,
            command=self._on_priority_change,
        ).grid(row=2, column=1, columnspan=2, sticky="ew", **self._CTL)
        ctk.CTkLabel(
            sc,
            text=("⚠  Réduire la priorité peut baisser la vitesse et la qualité "
                  "de la synthèse — évitez Basse sauf usage très léger"),
            font=ctk.CTkFont(size=10),
            text_color=("#b35900", "#cc7722"),
            anchor="w",
            wraplength=480,
            justify="left",
        ).grid(row=3, column=0, columnspan=3, padx=16, pady=(0, 6), sticky="w")

        ctk.CTkLabel(sc, text="RAM max :").grid(row=4, column=0, **self._LBL)
        ram_frame = ctk.CTkFrame(sc, fg_color="transparent")
        ram_frame.grid(row=4, column=1, columnspan=2, sticky="ew", **self._CTL)
        ram_frame.columnconfigure(0, weight=1)
        self._ram_lbl = ctk.CTkLabel(
            ram_frame,
            text=self._fmt_memory(self._app.max_memory_var.get()),
            width=80, anchor="w")
        ctk.CTkSlider(
            ram_frame,
            from_=256, to=4096, number_of_steps=15,
            variable=self._app.max_memory_var,
            command=lambda v: self._on_memory_change(
                max(256, min(4096, round(int(v) / 256) * 256))),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._ram_lbl.grid(row=0, column=1)
        ctk.CTkLabel(
            sc,
            text=("⚠  Trop bas peut ralentir ou déstabiliser l'app  •  "
                  "4096 Mo = Illimité"),
            font=ctk.CTkFont(size=10),
            text_color=("#b35900", "#cc7722"),
            anchor="w",
        ).grid(row=5, column=0, columnspan=3, padx=16, pady=(0, 6), sticky="w")

        # ── Twitch / OBS ───────────────────────────────────────────────────
        sc = self._section(frm, "Twitch / OBS", expanded=False)

        ctk.CTkLabel(
            sc,
            text="Overlay OBS temps réel + API locale pour les channel points",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=16, pady=(2, 4), sticky="w")

        # Master enable
        ctk.CTkLabel(sc, text="Activer :").grid(row=1, column=0, **self._LBL)
        tw_sw = ctk.CTkFrame(sc, fg_color="transparent")
        tw_sw.grid(row=1, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(
            tw_sw, text="",
            variable=self._app.twitch_enabled_var,
            command=self._on_twitch_toggle,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        # Port + open overlay button
        ctk.CTkLabel(sc, text="Port :").grid(row=2, column=0, **self._LBL)
        port_frame = ctk.CTkFrame(sc, fg_color="transparent")
        port_frame.grid(row=2, column=1, columnspan=2, sticky="ew", **self._CTL)
        ctk.CTkEntry(
            port_frame, textvariable=self._app.twitch_port_var, width=80,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            port_frame, text="Ouvrir overlay", width=130,
            **_BTN_SECONDARY,
            command=self._open_overlay,
        ).grid(row=0, column=1, padx=(8, 0))

        # Apparence de l'overlay sub-section
        app_sc = self._subsection(sc, row=3, title="Apparence de l'overlay",
                                  expanded=True)

        ctk.CTkLabel(app_sc, text="Fond sous texte :").grid(
            row=0, column=0, **self._LBL)
        bg_sw_frame = ctk.CTkFrame(app_sc, fg_color="transparent")
        bg_sw_frame.grid(row=0, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(
            bg_sw_frame, text="",
            variable=self._app.twitch_overlay_bg_var,
            command=self._sync_overlay_appearance,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(app_sc, text="Opacité du fond :").grid(
            row=1, column=0, **self._LBL)
        bg_op_frame = ctk.CTkFrame(app_sc, fg_color="transparent")
        bg_op_frame.grid(row=1, column=1, columnspan=2, sticky="ew", **self._CTL)
        bg_op_frame.columnconfigure(0, weight=1)
        self._bg_op_lbl = ctk.CTkLabel(
            bg_op_frame,
            text=f"{int(self._app.twitch_overlay_bg_opacity_var.get() * 100)}%",
            width=40, anchor="w")
        ctk.CTkSlider(
            bg_op_frame, from_=0.0, to=1.0,
            variable=self._app.twitch_overlay_bg_opacity_var,
            command=lambda v: (
                self._bg_op_lbl.configure(text=f"{int(float(v) * 100)}%"),
                self._sync_overlay_appearance(),
            ),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._bg_op_lbl.grid(row=0, column=1)

        ctk.CTkLabel(app_sc, text="Couleur du fond :").grid(
            row=2, column=0, **self._LBL)
        self._color_picker_row(
            app_sc, row=2,
            var=self._app.twitch_overlay_bg_color_var,
            on_change=self._sync_overlay_appearance,
        )

        ctk.CTkLabel(app_sc, text="Couleur du texte :").grid(
            row=3, column=0, **self._LBL)
        self._color_picker_row(
            app_sc, row=3,
            var=self._app.twitch_overlay_text_color_var,
            on_change=self._sync_overlay_appearance,
        )

        # Fonctionnalités sub-section
        feat_sc = self._subsection(sc, row=4, title="Fonctionnalités actives",
                                   expanded=True)
        for r, label, var, hint in [
            (0, "Overlay OBS",         self._app.twitch_feat_overlay_var,
             "Affiche le texte en temps réel dans OBS"),
            (1, "TTS via points",      self._app.twitch_feat_speak_var,
             "Les viewers peuvent déclencher le TTS"),
            (2, "Changement de voix",  self._app.twitch_feat_voice_var,
             "Changer la voix temporairement"),
            (3, "Changement de pitch", self._app.twitch_feat_pitch_var,
             "Changer le pitch temporairement"),
        ]:
            row_fr = ctk.CTkFrame(feat_sc, fg_color="transparent")
            row_fr.grid(row=r, column=0, columnspan=3, sticky="ew",
                        padx=(0, 12), pady=2)
            ctk.CTkSwitch(
                row_fr, text=label,
                variable=var,
                command=lambda v=var: self._on_feat_toggle(v),
                onvalue=True, offvalue=False, width=46,
                font=ctk.CTkFont(size=12),
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                row_fr, text=hint,
                font=ctk.CTkFont(size=10),
                text_color=("gray50", "gray50"),
            ).grid(row=0, column=1, padx=(8, 0), sticky="w")

        # Temp duration
        ctk.CTkLabel(sc, text="Durée modif. temp. :").grid(row=5, column=0, **self._LBL)
        dur_frame = ctk.CTkFrame(sc, fg_color="transparent")
        dur_frame.grid(row=5, column=1, columnspan=2, sticky="ew", **self._CTL)
        dur_frame.columnconfigure(0, weight=1)
        self._dur_lbl = ctk.CTkLabel(
            dur_frame,
            text=self._fmt_duration(self._app.twitch_temp_duration_var.get()),
            width=50, anchor="w")
        ctk.CTkSlider(
            dur_frame, from_=5, to=120, number_of_steps=23,
            variable=self._app.twitch_temp_duration_var,
            command=lambda v: (
                self._app.twitch_temp_duration_var.set(int(round(v))),
                self._dur_lbl.configure(text=self._fmt_duration(int(round(v)))),
                self._sync_twitch_temp_duration(),
            ),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._dur_lbl.grid(row=0, column=1)

        # Bot Twitch sub-section
        bot_sc = self._subsection(sc, row=6, title="Bot Twitch intégré",
                                  expanded=False,
                                  info_cmd=self._show_rewards_guide)

        ctk.CTkLabel(
            bot_sc,
            text="Connexion directe à Twitch — écoute les channel points automatiquement",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(2, 4), sticky="w")

        ctk.CTkLabel(bot_sc, text="Activer :").grid(row=1, column=0, **self._LBL)
        bot_sw = ctk.CTkFrame(bot_sc, fg_color="transparent")
        bot_sw.grid(row=1, column=1, columnspan=2, sticky="w", **self._CTL)
        ctk.CTkSwitch(
            bot_sw, text="",
            variable=self._app.twitch_bot_enabled_var,
            command=self._on_bot_toggle,
            onvalue=True, offvalue=False, width=46,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(bot_sc, text="Chaîne :").grid(row=2, column=0, **self._LBL)
        self._channel_entry = ctk.CTkEntry(
            bot_sc, textvariable=self._app.twitch_channel_var,
            placeholder_text="nomdelachaîne")
        self._channel_entry.grid(row=2, column=1, columnspan=2,
                                 sticky="ew", **self._CTL)

        ctk.CTkLabel(bot_sc, text="Token OAuth :").grid(row=3, column=0, **self._LBL)
        tok_frame = ctk.CTkFrame(bot_sc, fg_color="transparent")
        tok_frame.grid(row=3, column=1, columnspan=2, sticky="ew", **self._CTL)
        tok_frame.columnconfigure(0, weight=1)
        self._token_entry = ctk.CTkEntry(
            tok_frame, textvariable=self._app.twitch_oauth_token_var,
            placeholder_text="oauth:xxxxxxxx", show="*")
        self._token_entry.grid(row=0, column=0, sticky="ew")
        self._token_show_btn = ctk.CTkButton(
            tok_frame, text="Voir", width=50,
            **_BTN_SECONDARY,
            command=self._toggle_token_visibility)
        self._token_show_btn.grid(row=0, column=1, padx=(6, 0))

        ctk.CTkButton(
            bot_sc,
            text="Comment obtenir un token OAuth ?  ℹ",
            height=26,
            fg_color="transparent",
            text_color=("gray40", "#9b84ff"),
            hover_color=("gray88", "#1a1a2e"),
            font=ctk.CTkFont(size=11),
            anchor="w",
            command=self._show_token_guide,
        ).grid(row=4, column=0, columnspan=3, padx=12, pady=(2, 6), sticky="w")

        # ── Footer ─────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=(8, 12))
        ctk.CTkButton(btn_frame, text="Dossier config", width=140,
                      **_BTN_SECONDARY,
                      command=lambda: _safe_open(BASE_DIR)
                      ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Fermer", width=120,
                      command=self.destroy
                      ).grid(row=0, column=1)

    # ------------------------------------------------------------------
    # Section helpers
    # ------------------------------------------------------------------

    def _section(self, parent, title: str, expanded: bool = True,
                 info_cmd=None) -> ctk.CTkFrame:
        """Pack a collapsible section. Returns the content frame (grid layout)."""
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="x")

        # Thin separator above header
        ctk.CTkFrame(outer, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).pack(fill="x", padx=14, pady=(6, 0))

        # Header row
        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.pack(fill="x")

        arrow = ctk.CTkLabel(
            hdr, text="▼" if expanded else "▶",
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "gray55"),
            width=16, cursor="hand2",
        )
        arrow.pack(side="left", padx=(16, 4), pady=(6, 4))

        title_lbl = ctk.CTkLabel(
            hdr, text=title,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"),
            anchor="w", cursor="hand2",
        )
        title_lbl.pack(side="left", pady=(6, 4))

        if info_cmd:
            ctk.CTkButton(
                hdr, text="ℹ", width=26, height=22,
                fg_color="transparent",
                hover_color=("gray75", "#2c2c2c"),
                text_color=("gray50", "gray65"),
                font=ctk.CTkFont(size=11),
                command=info_cmd,
            ).pack(side="left", padx=(6, 0), pady=(6, 4))

        # Invisible spacer so entire header row is clickable
        spacer = ctk.CTkLabel(hdr, text="", cursor="hand2")
        spacer.pack(side="left", fill="x", expand=True)

        # Content frame (grid layout inside)
        content = ctk.CTkFrame(outer, fg_color="transparent")
        content.columnconfigure(0, minsize=165, weight=0)
        content.columnconfigure(1, weight=1)
        content.columnconfigure(2, weight=0)

        state = [expanded]
        if expanded:
            content.pack(fill="x", pady=(0, 6))

        def _toggle(event=None):
            if state[0]:
                content.pack_forget()
                arrow.configure(text="▶")
            else:
                content.pack(fill="x", pady=(0, 6))
                arrow.configure(text="▼")
            state[0] = not state[0]

        for w in (arrow, title_lbl, spacer):
            w.bind("<Button-1>", _toggle)

        return content

    def _subsection(self, parent, row: int, title: str,
                    expanded: bool = True, info_cmd=None) -> ctk.CTkFrame:
        """Grid a collapsible sub-section spanning all 3 columns. Returns the content frame."""
        outer = ctk.CTkFrame(
            parent,
            fg_color=("gray92", "#222222"),
            corner_radius=6,
            border_width=1,
            border_color=("gray78", "#383838"),
        )
        outer.grid(row=row, column=0, columnspan=3,
                   sticky="ew", padx=12, pady=(4, 6))
        outer.columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.pack(fill="x")

        arrow = ctk.CTkLabel(
            hdr, text="▼" if expanded else "▶",
            font=ctk.CTkFont(size=9),
            text_color=("gray40", "gray60"),
            width=14, cursor="hand2",
        )
        arrow.pack(side="left", padx=(10, 4), pady=(5, 4))

        title_lbl = ctk.CTkLabel(
            hdr, text=title,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray40", "gray60"),
            anchor="w", cursor="hand2",
        )
        title_lbl.pack(side="left", pady=(5, 4))

        if info_cmd:
            ctk.CTkButton(
                hdr, text="ℹ", width=24, height=20,
                fg_color="transparent",
                hover_color=("gray82", "#2a2a2a"),
                text_color=("gray45", "gray65"),
                font=ctk.CTkFont(size=10),
                command=info_cmd,
            ).pack(side="left", padx=(6, 0))

        spacer = ctk.CTkLabel(hdr, text="", cursor="hand2")
        spacer.pack(side="left", fill="x", expand=True)

        # Content
        content = ctk.CTkFrame(outer, fg_color="transparent")
        content.columnconfigure(0, minsize=140, weight=0)
        content.columnconfigure(1, weight=1)
        content.columnconfigure(2, weight=0)

        state = [expanded]
        if expanded:
            content.pack(fill="x", padx=4, pady=(0, 6))

        def _toggle(event=None):
            if state[0]:
                content.pack_forget()
                arrow.configure(text="▶")
            else:
                content.pack(fill="x", padx=4, pady=(0, 6))
                arrow.configure(text="▼")
            state[0] = not state[0]

        for w in (arrow, title_lbl, spacer):
            w.bind("<Button-1>", _toggle)

        return content

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _hotkey_row(self, parent, row: int, label: str,
                    var: ctk.StringVar, post_fn) -> tuple:
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, **self._LBL)
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", **self._CTL)
        key_lbl = ctk.CTkLabel(
            frame, text=var.get(),
            font=ctk.CTkFont(size=13, weight="bold"), width=60, anchor="w")
        key_lbl.grid(row=0, column=0, padx=(0, 10))
        key_btn = ctk.CTkButton(frame, text="Changer", width=100)
        key_btn.configure(
            command=lambda: self._start_key_capture(var, key_lbl, key_btn, post_fn))
        key_btn.grid(row=0, column=1)
        return key_lbl, key_btn

    def _slider_row(self, parent, row: int, var: ctk.IntVar,
                    from_: int, to: int, fmt) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="ew",
                   padx=(0, 14), pady=6)
        frame.columnconfigure(0, weight=1)
        lbl = ctk.CTkLabel(frame, text=fmt(var.get()), width=56, anchor="w")
        ctk.CTkSlider(frame, from_=from_, to=to, variable=var,
                      command=lambda v, _l=lbl, _f=fmt: _l.configure(text=_f(int(v)))
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        lbl.grid(row=0, column=1)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_cores(n: int, total: int) -> str:
        if n >= total:
            return f"Tous ({total})"
        return f"{n} / {total} cœur{'s' if n > 1 else ''}"

    def _on_cpu_change(self, n: int, total: int) -> None:
        self._app.cpu_cores_var.set(n)
        self._cpu_lbl.configure(text=self._fmt_cores(n, total))
        self._app._apply_cpu_affinity()

    def _on_priority_change(self, label: str) -> None:
        self._app.process_priority_var.set(label)
        self._app._apply_process_priority()

    @staticmethod
    def _fmt_memory(mb: int) -> str:
        if mb >= 4096:
            return "Illimité"
        if mb >= 1024:
            return f"{mb / 1024:.1f} Go"
        return f"{mb} Mo"

    def _on_memory_change(self, mb: int) -> None:
        self._app.max_memory_var.set(mb)
        self._ram_lbl.configure(text=self._fmt_memory(mb))
        self._app._apply_memory_limit()

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

    # ------------------------------------------------------------------
    # Twitch / OBS handlers
    # ------------------------------------------------------------------

    def _on_twitch_toggle(self) -> None:
        """Start or stop the Twitch/OBS server when the master toggle changes."""
        if self._app.twitch_enabled_var.get():
            self._app._start_twitch()
        else:
            self._app._stop_twitch()
        self._app._save_settings()

    def _on_bot_toggle(self) -> None:
        """Handle bot enable toggle — show info modal if token is missing."""
        if self._app.twitch_bot_enabled_var.get():
            token = self._app.twitch_oauth_token_var.get().strip()
            if not token:
                # Token absent: revert toggle, show informational modal
                TwitchBotSetupModal(self, on_cancel=self._cancel_bot_enable)
                return
            self._apply_bot_enable()
        else:
            # Bot disabled — restart server without bot
            if self._app.twitch_enabled_var.get():
                self._app._stop_twitch()
                self._app._start_twitch()
            self._app._save_settings()

    def _apply_bot_enable(self) -> None:
        """Confirm the bot activation after OAuth modal."""
        self._app.twitch_bot_enabled_var.set(True)
        if self._app.twitch_enabled_var.get():
            self._app._stop_twitch()
            self._app._start_twitch()
        self._app._save_settings()

    def _cancel_bot_enable(self) -> None:
        """Revert the bot toggle when the modal is dismissed."""
        self._app.twitch_bot_enabled_var.set(False)

    def _on_feat_toggle(self, var: ctk.BooleanVar) -> None:
        # BooleanVar is not hashable in Python 3.12 — use id() as key
        mapping = {
            id(self._app.twitch_feat_overlay_var): "twitch_feat_overlay",
            id(self._app.twitch_feat_speak_var):   "twitch_feat_speak",
            id(self._app.twitch_feat_voice_var):   "twitch_feat_voice",
            id(self._app.twitch_feat_pitch_var):   "twitch_feat_pitch",
        }
        key = mapping.get(id(var))
        if key and self._app._twitch_manager:
            self._app._twitch_manager.update_config(key, var.get())
        self._app._save_settings()

    def _open_overlay(self) -> None:
        """Open the OBS overlay page in the default browser."""
        webbrowser.open(f"http://localhost:{self._app.twitch_port_var.get()}")

    def _sync_twitch_temp_duration(self) -> None:
        """Push the updated temp-duration value to a running TwitchManager."""
        if self._app._twitch_manager:
            self._app._twitch_manager.temp_duration = (
                self._app.twitch_temp_duration_var.get())
        self._app._save_settings()

    def _toggle_token_visibility(self) -> None:
        self._token_visible = not self._token_visible
        self._token_entry.configure(show="" if self._token_visible else "*")
        self._token_show_btn.configure(
            text="Cacher" if self._token_visible else "Voir")

    def _show_rewards_guide(self) -> None:
        TwitchRewardsGuideModal(self)

    def _show_token_guide(self) -> None:
        TwitchTokenGuideModal(self)

    def _color_picker_row(self, parent, row: int,
                          var: ctk.StringVar, on_change) -> ctk.CTkButton:
        """Swatch button + hex entry. Returns the swatch for colour updates."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=1, columnspan=2, sticky="w", **self._CTL)

        swatch = ctk.CTkButton(
            frame, text="", width=36, height=28,
            fg_color=var.get() or "#000000",
            hover_color=var.get() or "#000000",
            corner_radius=4,
            command=lambda: self._pick_color(var, swatch, on_change),
        )
        swatch.grid(row=0, column=0)

        entry = ctk.CTkEntry(frame, textvariable=var, width=88)
        entry.grid(row=0, column=1, padx=(8, 0))
        entry.bind("<Return>",   lambda e: self._apply_hex(var, swatch, on_change))
        entry.bind("<FocusOut>", lambda e: self._apply_hex(var, swatch, on_change))

        return swatch

    def _pick_color(self, var: ctk.StringVar, swatch: ctk.CTkButton,
                    on_change) -> None:
        from tkinter import colorchooser
        current = var.get().strip() or "#000000"
        result  = colorchooser.askcolor(color=current, parent=self,
                                        title="Choisir une couleur")
        if result and result[1]:
            hex_color = result[1]
            var.set(hex_color)
            swatch.configure(fg_color=hex_color, hover_color=hex_color)
            on_change()

    def _apply_hex(self, var: ctk.StringVar, swatch: ctk.CTkButton,
                   on_change) -> None:
        color = var.get().strip()
        if not color.startswith("#"):
            color = "#" + color
            var.set(color)
        if len(color) not in (4, 7):
            return
        try:
            swatch.configure(fg_color=color, hover_color=color)
            on_change()
        except Exception:
            pass

    def _sync_overlay_appearance(self) -> None:
        import asyncio
        app = self._app
        cfg = {
            "bg":         app.twitch_overlay_bg_var.get(),
            "bg_color":   app.twitch_overlay_bg_color_var.get(),
            "bg_opacity": round(app.twitch_overlay_bg_opacity_var.get(), 2),
            "text_color": app.twitch_overlay_text_color_var.get(),
        }
        if app._twitch_manager and app._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    app._twitch_manager.broadcast_config(cfg),
                    app._loop,
                )
            except Exception:
                pass
        app._save_settings()

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        if seconds >= 60:
            m, s = divmod(seconds, 60)
            return f"{m}m{s:02d}s" if s else f"{m} min"
        return f"{seconds}s"


# ---------------------------------------------------------------------------
# Modal — OAuth bot setup
# ---------------------------------------------------------------------------

class TwitchBotSetupModal(ctk.CTkToplevel):
    """Shown when the bot is toggled on without a token. Reverts the toggle on close."""

    def __init__(self, parent_settings: SettingsWindow, on_cancel) -> None:
        super().__init__(parent_settings._app)
        self._settings  = parent_settings
        self._on_cancel = on_cancel

        self.title("Token OAuth requis")
        self.geometry("480x310")
        self.resizable(False, False)
        self.transient(parent_settings)
        self.grab_set()
        self._build()
        _set_window_icon(self)
        self.after(50, self.lift)
        self.after(120, lambda: apply_window_transparency(
            self, parent_settings._app.opacity_var.get()))

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Token OAuth requis",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
                     ).grid(row=0, column=0, pady=(18, 4), padx=22, sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                "Le bot Twitch a besoin d'un token OAuth pour se connecter à "
                "votre chaîne.\n\n"
                "Entrez votre token dans :\n"
                "Paramètres  →  Twitch / OBS  →  Bot Twitch intégré  →  Token OAuth\n\n"
                "Réactivez ensuite le bot une fois le token enregistré."
            ),
            wraplength=436, justify="left", anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, padx=22, pady=(0, 12), sticky="ew")

        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 10))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.grid(row=3, column=0, pady=(0, 18))
        ctk.CTkButton(
            bf, text="Comment obtenir un token ?  ℹ",
            width=200, **_BTN_SECONDARY,
            command=lambda: TwitchTokenGuideModal(self._settings),
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(bf, text="Fermer", width=100,
                      command=self._close).grid(row=0, column=1)

    def _close(self) -> None:
        self._on_cancel()
        self.destroy()

    def destroy(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()


# ---------------------------------------------------------------------------
# Modal — Channel points rewards guide
# ---------------------------------------------------------------------------

class TwitchRewardsGuideModal(ctk.CTkToplevel):

    def __init__(self, parent_settings: SettingsWindow) -> None:
        super().__init__(parent_settings._app)
        self.title("Configurer les récompenses Channel Points")
        self.geometry("530x520")
        self.resizable(False, False)
        self.transient(parent_settings)
        self.grab_set()
        self._build()
        _set_window_icon(self)
        self.after(50, self.lift)
        self.after(120, lambda: apply_window_transparency(
            self, parent_settings._app.opacity_var.get()))

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Configurer les récompenses",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
                     ).grid(row=0, column=0, pady=(18, 4), padx=22, sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                "Pour que le bot réponde aux channel points, créez des "
                "récompenses personnalisées dans votre tableau de bord Twitch."
            ),
            wraplength=486, justify="left", anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, padx=22, pady=(0, 10), sticky="ew")

        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 10))

        steps = [
            ("1. Tableau de bord Twitch",
             "Allez sur twitch.tv → menu profil → Tableau de bord du créateur"),
            ("2. Points de chaîne → Gérer",
             "Dans le menu latéral : Communauté → Points de chaîne → Gérer"),
            ("3. Créer une récompense personnalisée",
             "Cliquez sur  +  et remplissez le nom et le coût en points"),
            ("4. Activer la saisie de texte",
             "Cochez « Demander au spectateur de saisir du texte »"),
        ]
        for i, (title, desc) in enumerate(steps):
            ctk.CTkLabel(self, text=title,
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
                         ).grid(row=3 + i * 2, column=0,
                                padx=22, pady=(6, 0), sticky="w")
            ctk.CTkLabel(self, text=desc,
                         font=ctk.CTkFont(size=11), anchor="w",
                         text_color=("gray35", "gray65"),
                         ).grid(row=4 + i * 2, column=0,
                                padx=32, pady=(0, 2), sticky="w")

        r = 3 + len(steps) * 2
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=r, column=0, sticky="ew", padx=22, pady=(8, 8))

        ctk.CTkLabel(
            self, text="Noms de récompenses reconnus par le bot :",
            font=ctk.CTkFont(size=11, weight="bold"), anchor="w",
        ).grid(row=r + 1, column=0, padx=22, sticky="w")

        table = (
            "  TTS  /  Lire TTS  /  Dire  /  Parler       →  Lit le texte saisi\n"
            "  Voix TTS  /  Changer Voix  /  Voice TTS    →  Change la voix\n"
            "  Pitch TTS  /  Changer Pitch                →  Change le pitch (valeur en Hz)"
        )
        ctk.CTkLabel(
            self, text=table,
            font=ctk.CTkFont(size=10, family="Courier New"),
            anchor="w", justify="left",
            text_color=("gray35", "gray65"),
        ).grid(row=r + 2, column=0, padx=28, pady=(4, 10), sticky="w")

        ctk.CTkButton(
            self,
            text="Ouvrir le tableau de bord Twitch →",
            fg_color="transparent",
            text_color=("gray40", "#9b84ff"),
            hover_color=("gray88", "#1a1a2e"),
            font=ctk.CTkFont(size=11, underline=True),
            anchor="w",
            command=lambda: webbrowser.open(
                "https://www.twitch.tv/dashboard/channel-points"),
        ).grid(row=r + 3, column=0, padx=18, sticky="w")

        ctk.CTkButton(self, text="Fermer", width=110,
                      command=self.destroy
                      ).grid(row=r + 4, column=0, pady=(8, 18))

    def destroy(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()


# ---------------------------------------------------------------------------
# Modal — OAuth token creation guide
# ---------------------------------------------------------------------------

class TwitchTokenGuideModal(ctk.CTkToplevel):
    """Guide: create a Twitch app → generate OAuth token → copy access_token."""

    _SCOPES = "chat:read+chat:edit+channel:read:redemptions"

    def __init__(self, parent) -> None:
        app = getattr(parent, "_app", None) or getattr(
            getattr(parent, "_settings", None), "_app", None)
        super().__init__(app or parent)
        # Build the redirect URI using the configured port so Twitch lands on our server
        port           = app.twitch_port_var.get() if app else 7681
        self._redirect = f"http://localhost:{port}/callback"
        self._app      = app
        self.title("Obtenir un token OAuth Twitch")
        self.geometry("550x570")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._client_id_var = ctk.StringVar()
        self._build()
        _set_window_icon(self)
        self.after(50, self.lift)
        if app:
            self.after(120, lambda: apply_window_transparency(
                self, app.opacity_var.get()))

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Obtenir un token OAuth Twitch",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).grid(row=0, column=0, pady=(18, 4), padx=22, sticky="w")

        # ── Étape 1 : créer l'application ─────────────────────────────────
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=1, column=0, sticky="ew", padx=22, pady=(4, 8))

        ctk.CTkLabel(
            self, text="Étape 1 — Créer une application Twitch",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=2, column=0, padx=22, sticky="w")

        ctk.CTkButton(
            self, text="Créer une application sur dev.twitch.tv →",
            height=28,
            fg_color="transparent",
            text_color=("gray40", "#9b84ff"),
            hover_color=("gray88", "#1a1a2e"),
            font=ctk.CTkFont(size=11, underline=True),
            anchor="w",
            command=lambda: webbrowser.open(
                "https://dev.twitch.tv/console/apps/create"),
        ).grid(row=3, column=0, padx=18, sticky="w", pady=(2, 6))

        # Form guidance table
        tbl = ctk.CTkFrame(
            self,
            fg_color=("gray92", "#1e1e1e"),
            corner_radius=6,
            border_width=1,
            border_color=("gray78", "#363636"),
        )
        tbl.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 8))
        tbl.columnconfigure(1, weight=1)

        fields = [
            ("Nom de l'application :", "FrenchTTS"),
            ("URL de redirection OAuth :", self._redirect),
            ("Catégorie :",              "Chat Bot"),
        ]
        for r, (label, value) in enumerate(fields):
            py_top = 7 if r == 0 else 3
            py_bot = 7 if r == len(fields) - 1 else 3
            ctk.CTkLabel(
                tbl, text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w", width=195,
            ).grid(row=r, column=0, padx=(12, 4),
                   pady=(py_top, py_bot), sticky="w")

            vf = ctk.CTkFrame(tbl, fg_color="transparent")
            vf.grid(row=r, column=1, sticky="ew",
                    padx=(0, 10), pady=(py_top, py_bot))

            val_lbl = ctk.CTkLabel(
                vf, text=value,
                font=ctk.CTkFont(size=11, family="Courier New"),
                text_color=("gray20", "gray85"),
                anchor="w", cursor="hand2",
            )
            val_lbl.grid(row=0, column=0, sticky="w")

            copied_lbl = ctk.CTkLabel(
                vf, text="",
                font=ctk.CTkFont(size=10),
                text_color=("#2e9e4f", "#4ec97a"),
                anchor="w",
            )
            copied_lbl.grid(row=0, column=1, padx=(8, 0), sticky="w")

            val_lbl.bind(
                "<Button-1>",
                lambda e, v=value, lbl=copied_lbl: self._copy_value(v, lbl),
            )

        # ── Étape 2 : générer le token ─────────────────────────────────────
        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=5, column=0, sticky="ew", padx=22, pady=(4, 8))

        ctk.CTkLabel(
            self, text="Étape 2 — Générer votre token",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=6, column=0, padx=22, sticky="w")

        ctk.CTkLabel(
            self,
            text='Une fois l\'app créée, cliquez sur "Gérer" et copiez le Client ID :',
            font=ctk.CTkFont(size=11), anchor="w",
        ).grid(row=7, column=0, padx=22, pady=(4, 0), sticky="w")

        cid_frame = ctk.CTkFrame(self, fg_color="transparent")
        cid_frame.grid(row=8, column=0, padx=22, pady=(6, 6), sticky="ew")
        cid_frame.columnconfigure(0, weight=1)

        ctk.CTkEntry(
            cid_frame,
            textvariable=self._client_id_var,
            placeholder_text="Collez votre Client ID ici…",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            cid_frame, text="Ouvrir →", width=82,
            command=self._open_oauth_url,
        ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(
            self,
            text=(
                "Le navigateur s'ouvrira sur la page d'autorisation Twitch.\n"
                "Après avoir cliqué « Autoriser », l'URL affichera :\n"
                "  http://localhost/#access_token=XXXXXXXX&…\n"
                "Copiez la valeur après  access_token=  et collez-la\n"
                "dans le champ « Token OAuth » des paramètres."
            ),
            font=ctk.CTkFont(size=10),
            text_color=("gray40", "gray60"),
            justify="left", anchor="w",
        ).grid(row=9, column=0, padx=22, pady=(0, 8), sticky="w")

        ctk.CTkFrame(self, height=1, corner_radius=0,
                     fg_color=("gray80", "#363636")
                     ).grid(row=10, column=0, sticky="ew", padx=22, pady=(2, 8))

        ctk.CTkButton(
            self, text="Fermer", width=110,
            command=self.destroy,
        ).grid(row=11, column=0, pady=(0, 18))

    def _copy_value(self, value: str, feedback_lbl: ctk.CTkLabel) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        feedback_lbl.configure(text="✓ Copié !")
        self.after(1500, lambda: feedback_lbl.configure(text=""))

    def _open_oauth_url(self) -> None:
        client_id = self._client_id_var.get().strip()
        if not client_id:
            return
        url = (
            "https://id.twitch.tv/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={self._redirect}"
            "&response_type=token"
            f"&scope={self._SCOPES}"
        )
        webbrowser.open(url)

    def destroy(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()
