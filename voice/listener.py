"""
voice/listener.py — Microphone capture → VAD → faster-whisper STT pipeline.

Flow
----
1. start_listening() ouvre le stream micro et démarre la détection vocale (VAD).
2. Le callback PortAudio calcule l'énergie RMS de chaque bloc (~64 ms).
   - Quand l'énergie dépasse SPEECH_THR pendant CONFIRM_FRAMES blocs consécutifs
     → parole confirmée : on_state_change("recording") est appelé, recognizing.wav joue.
   - Quand l'énergie repasse sous SPEECH_THR pendant SILENCE_FRAMES blocs
     → fin d'énoncé détectée : _vad_done est signalé.
3. _vad_watcher() (thread daemon) attend _vad_done, ferme le stream et lance
   _transcribe_worker() dans un nouveau thread daemon.
4. _transcribe_worker() appelle Whisper puis on_transcript ou on_not_recognized.

Aucun deuxième clic nécessaire — c'est le silence qui déclenche la transcription.

Public surface
--------------
STTListener(on_transcript, on_state_change, on_error, on_not_recognized)
    .device             — int | None  ; set avant start_listening()
    .start_listening()  — ouvre le micro, lance la VAD
    .cancel()           — abandonne sans produire de transcript
    .is_busy            — True si état ≠ "idle"
"""

import collections
import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from core.constants import (
    STT_MODEL_DIR, STT_MODEL_SIZE, STT_LANGUAGE,
    STT_DEVICE, STT_COMPUTE, STT_SAMPLE_RATE, STT_CHANNELS,
)


# ---------------------------------------------------------------------------
# Constantes VAD
# ---------------------------------------------------------------------------

BLOCKSIZE         = 1024  # frames par callback PortAudio  (~64 ms à 16 kHz)
SPEECH_THR        = 0.012 # seuil RMS pour classifier un bloc comme parole
CONFIRM_FRAMES    = 3     # blocs consécutifs au-dessus du seuil pour confirmer (~192 ms)
SILENCE_FRAMES    = 12    # blocs consécutifs sous le seuil pour finir  (~768 ms)
PREROLL_FRAMES    = 5     # blocs gardés avant le début de parole pour contexte (~320 ms)
MAX_RECORD_FRAMES = int(30 * STT_SAMPLE_RATE / BLOCKSIZE)  # arrêt auto après 30 s


# ---------------------------------------------------------------------------
# Singleton modèle Whisper
# ---------------------------------------------------------------------------

_model: "WhisperModel | None" = None
_model_lock = threading.Lock()


def _get_model(model_size: str = STT_MODEL_SIZE) -> WhisperModel:
    """Retourne le WhisperModel en cache, le charge au premier appel.

    Thread-safe via _model_lock. Premier appel : ~2–4 s selon le CPU.
    download_root pointe vers %APPDATA%/FrenchTTS/stt_models pour survivre
    aux répertoires temporaires de PyInstaller.
    """
    global _model
    with _model_lock:
        if _model is None:
            _model = WhisperModel(
                model_size,
                device=STT_DEVICE,
                compute_type=STT_COMPUTE,
                download_root=STT_MODEL_DIR,
            )
    return _model


# ---------------------------------------------------------------------------
# STTListener
# ---------------------------------------------------------------------------

class STTListener:
    """Gère la capture micro et la transcription en arrière-plan.

    Modèle de threads
    -----------------
    - start_listening() ouvre un sd.InputStream ; le callback PortAudio tourne
      sur le thread interne de PortAudio.
    - La VAD met à jour des compteurs dans le callback (pas de lock nécessaire
      car un seul thread écrit ces valeurs) et signale la fin via threading.Event.
    - _vad_watcher() tourne en daemon et attend le signal avant de fermer le
      stream et de lancer _transcribe_worker().
    - Tous les callbacks fournis par l'appelant sont invoqués depuis des threads
      non-Tkinter ; l'appelant doit les marshaller via after(0, ...).

    Paramètres
    ----------
    on_transcript : callable(str)
        Appelé quand la transcription produit un texte non vide.
    on_state_change : callable(str)
        Appelé à chaque changement d'état : "idle", "listening", "recording",
        "transcribing". Peut être appelé depuis le thread PortAudio.
    on_error : callable(str)
        Message d'erreur lisible (micro inaccessible, crash Whisper…).
    on_not_recognized : callable()
        Appelé quand Whisper ne produit aucun texte (VAD a tout filtré, etc.).
    """

    def __init__(self, on_transcript, on_state_change, on_error,
                 on_not_recognized=None):
        self._on_transcript     = on_transcript
        self._on_state_change   = on_state_change
        self._on_error          = on_error
        self._on_not_recognized = on_not_recognized or (
            lambda: on_error("Aucun texte détecté."))

        self._state        = "idle"
        self._cancel_flag  = threading.Event()
        self._stream:      "sd.InputStream | None" = None

        # Périphérique d'entrée ; None = micro système par défaut.
        self.device: "int | None" = None

        # État VAD — réinitialisé par _reset_vad() avant chaque écoute
        self._vad_speech      = False
        self._vad_confirm_n   = 0
        self._vad_silence_n   = 0
        self._speech_notified = False
        self._preroll:        collections.deque = collections.deque(maxlen=PREROLL_FRAMES)
        self._speech_chunks:  list = []
        self._audio_chunks:   list = []
        self._vad_done:       threading.Event = threading.Event()

    # --- API publique (appelée depuis le thread principal) ------------------

    @property
    def is_busy(self) -> bool:
        return self._state != "idle"

    def start_listening(self) -> None:
        """Ouvre le stream micro et démarre la détection vocale (VAD).

        Aucun clic supplémentaire n'est nécessaire : le silence détecté après
        la parole déclenche automatiquement la transcription. Pour interrompre,
        appeler cancel().
        """
        if self._state != "idle":
            return
        self._reset_vad()
        try:
            self._stream = sd.InputStream(
                samplerate=STT_SAMPLE_RATE,
                channels=STT_CHANNELS,
                dtype="float32",
                device=self.device,
                blocksize=BLOCKSIZE,
                callback=self._vad_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._on_error(f"Microphone inaccessible : {exc}")
            return
        self._set_state("listening")
        threading.Thread(target=self._vad_watcher, daemon=True).start()

    def cancel(self) -> None:
        """Abandonne l'écoute ou la transcription sans produire de résultat."""
        self._cancel_flag.set()
        self._vad_done.set()   # débloque _vad_watcher si en attente
        self._close_stream()
        if self._state != "idle":
            self._set_state("idle")

    # --- Callback VAD (thread PortAudio) ------------------------------------

    def _vad_callback(self, indata: np.ndarray, frames: int,
                      time_info, status) -> None:
        """Analyse l'énergie RMS de chaque bloc audio en temps réel.

        Appelé par PortAudio sur son propre thread interne. Aucune opération
        bloquante ni appel à l'API sounddevice ici (règle PortAudio).
        On signale la fin de parole via threading.Event pour que _vad_watcher
        ferme le stream proprement depuis un thread séparé.
        """
        if self._cancel_flag.is_set():
            return

        chunk  = indata.copy()
        energy = float(np.sqrt(np.mean(chunk ** 2)))

        if not self._vad_speech:
            # Phase d'attente : on accumule un pre-roll et on cherche l'onset
            self._preroll.append(chunk)
            if energy > SPEECH_THR:
                self._vad_confirm_n += 1
                if self._vad_confirm_n >= CONFIRM_FRAMES:
                    # Parole confirmée
                    self._vad_speech = True
                    self._vad_silence_n = 0
                    # pre-roll + bloc courant (déjà dans deque) = début de l'énoncé
                    self._speech_chunks = list(self._preroll)
                    if not self._speech_notified:
                        self._speech_notified = True
                        self._state = "recording"
                        self._on_state_change("recording")
            else:
                self._vad_confirm_n = 0
        else:
            # Phase d'enregistrement : accumule et surveille le silence
            self._speech_chunks.append(chunk)
            if energy < SPEECH_THR:
                self._vad_silence_n += 1
                if self._vad_silence_n >= SILENCE_FRAMES:
                    self._vad_done.set()
            else:
                self._vad_silence_n = 0
            # Arrêt auto après 30 secondes pour éviter un buffer sans fin
            if len(self._speech_chunks) >= MAX_RECORD_FRAMES:
                self._vad_done.set()

    # --- Thread watcher (daemon) -------------------------------------------

    def _vad_watcher(self) -> None:
        """Attend la fin de parole détectée par la VAD, puis transcrit.

        Tourne en daemon. Ferme le stream depuis ce thread (sûr, contrairement
        au callback) et démarre _transcribe_worker dans un nouveau daemon.
        """
        self._vad_done.wait()
        if self._cancel_flag.is_set():
            self._close_stream()
            self._set_state("idle")
            return

        self._audio_chunks = list(self._speech_chunks)
        self._close_stream()
        self._set_state("transcribing")
        threading.Thread(target=self._transcribe_worker, daemon=True).start()

    # --- Transcription (daemon) --------------------------------------------

    def _transcribe_worker(self) -> None:
        """Concatène les chunks audio, appelle Whisper, livre le résultat.

        Réglages pour le français
        --------------------------
        temperature=0                   sortie déterministe
        beam_size=5 / best_of=5        recherche large sans surcoût excessif
        condition_on_previous_text=False évite les hallucinations en cascade
        initial_prompt                   amorce Whisper vers le français
                                         (accents, cédilles, liaisons)
        no_speech_threshold=0.6         rejette les segments peu confiants
        compression_ratio_threshold=2.4 détecte les répétitions hallucinatoires
        vad_filter                       filtre le silence résiduel en post-hoc
        """
        if self._cancel_flag.is_set():
            self._set_state("idle")
            return

        if not self._audio_chunks:
            self._set_state("idle")
            self._on_not_recognized()
            return

        audio = np.concatenate(self._audio_chunks, axis=0).flatten()

        try:
            model = _get_model()
        except Exception as exc:
            self._set_state("idle")
            self._on_error(f"Impossible de charger le modèle STT : {exc}")
            return

        if self._cancel_flag.is_set():
            self._set_state("idle")
            return

        try:
            segments, _info = model.transcribe(
                audio,
                language=STT_LANGUAGE,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt="Transcription en français :",
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.5,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 600,
                    "speech_pad_ms": 400,
                },
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            self._set_state("idle")
            self._on_error(f"Erreur de transcription : {exc}")
            return

        self._set_state("idle")
        if text:
            self._on_transcript(text)
        else:
            self._on_not_recognized()

    # --- Helpers internes ---------------------------------------------------

    def _reset_vad(self) -> None:
        """Remet à zéro tous les compteurs et buffers VAD avant une nouvelle écoute."""
        self._cancel_flag.clear()
        self._vad_speech      = False
        self._vad_confirm_n   = 0
        self._vad_silence_n   = 0
        self._speech_notified = False
        self._preroll         = collections.deque(maxlen=PREROLL_FRAMES)
        self._speech_chunks   = []
        self._audio_chunks    = []
        self._vad_done        = threading.Event()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _set_state(self, new_state: str) -> None:
        self._state = new_state
        self._on_state_change(new_state)
