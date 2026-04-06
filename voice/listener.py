"""
voice/listener.py — Microphone capture → faster-whisper STT pipeline.

Public surface
--------------
STTListener(on_transcript, on_state_change, on_error, on_not_recognized)
    .device              — int | None; set before start_recording()
    .start_recording()   — open mic stream, begin buffering audio
    .stop_recording()    — close stream, launch transcription thread
    .cancel()            — abort recording or transcription silently
    .is_busy             — True while recording or transcribing
"""

import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from core.constants import (
    STT_MODEL_DIR, STT_MODEL_SIZE, STT_LANGUAGE,
    STT_DEVICE, STT_COMPUTE, STT_SAMPLE_RATE, STT_CHANNELS,
)


# ---------------------------------------------------------------------------
# Module-level model singleton (lazy-loaded on first dictation)
# ---------------------------------------------------------------------------

_model: "WhisperModel | None" = None
_model_lock = threading.Lock()


def _get_model(model_size: str = STT_MODEL_SIZE) -> WhisperModel:
    """Return the cached WhisperModel, loading it on first call.

    Thread-safe via _model_lock. First call takes ~2–4 s on a modern CPU;
    subsequent calls return immediately. ``download_root`` pins the model cache
    to %APPDATA%/FrenchTTS/stt_models so it survives PyInstaller temp dirs.
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
    """Manages microphone capture and transcription as background operations.

    Threading model
    ---------------
    - ``start_recording`` opens a ``sd.InputStream`` whose callback runs on
      PortAudio's own thread, appending float32 audio chunks to a list.
    - ``stop_recording`` closes the stream and launches a daemon thread that
      loads the model (once), transcribes, and invokes the callbacks.
    - All callbacks are called from background threads — callers must marshal
      them to the Tkinter main thread via ``after(0, ...)``.

    Parameters
    ----------
    on_transcript : callable(str)
        Delivered when transcription succeeds with a non-empty result.
    on_state_change : callable(str)
        Delivers "idle", "recording", or "transcribing" on every state change.
    on_error : callable(str)
        Delivers a human-readable French error message on system failures
        (mic unavailable, model load failure, transcription crash).
    on_not_recognized : callable()
        Delivered when transcription produces no usable text (empty result
        or VAD filtered everything). Distinct from on_error so the caller
        can play a different sound without string-matching error messages.
    """

    def __init__(self, on_transcript, on_state_change, on_error,
                 on_not_recognized=None):
        self._on_transcript     = on_transcript
        self._on_state_change   = on_state_change
        self._on_error          = on_error
        self._on_not_recognized = on_not_recognized or (lambda: on_error("Aucun texte détecté."))

        self._state         = "idle"  # "idle" | "recording" | "transcribing"
        self._audio_chunks: list[np.ndarray] = []
        self._stream:       "sd.InputStream | None" = None
        self._cancel_flag   = threading.Event()

        # Set before start_recording() to choose a specific input device.
        # None = system default microphone.
        self.device: "int | None" = None

    # --- Public API (called from the main thread) ----------------------------

    @property
    def is_busy(self) -> bool:
        return self._state != "idle"

    def start_recording(self) -> None:
        """Open a sounddevice InputStream on ``self.device`` and buffer audio.

        float32 at STT_SAMPLE_RATE (16 kHz) mono is Whisper's native format;
        capturing at this rate avoids a resample step in the worker.
        """
        if self._state != "idle":
            return
        self._cancel_flag.clear()
        self._audio_chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=STT_SAMPLE_RATE,
                channels=STT_CHANNELS,
                dtype="float32",
                device=self.device,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._on_error(f"Microphone inaccessible : {exc}")
            return
        self._set_state("recording")

    def stop_recording(self) -> None:
        """Close the stream and launch the transcription daemon thread."""
        if self._state != "recording":
            return
        self._close_stream()
        self._set_state("transcribing")
        threading.Thread(target=self._transcribe_worker, daemon=True).start()

    def cancel(self) -> None:
        """Abort recording or transcription without producing a transcript."""
        self._cancel_flag.set()
        self._close_stream()
        if self._state != "idle":
            self._set_state("idle")

    # --- Internal helpers ----------------------------------------------------

    def _audio_callback(self, indata: np.ndarray, frames, time, status) -> None:
        """PortAudio stream callback — runs on PortAudio's internal thread.

        ``indata`` is a (frames, channels) float32 view. We copy it before
        appending because sounddevice reuses the underlying buffer each call.
        """
        self._audio_chunks.append(indata.copy())

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

    def _transcribe_worker(self) -> None:
        """Concatenate audio buffers, run Whisper, deliver the transcript.

        Runs entirely on a daemon thread. None of the calls here touch
        Tkinter — all callbacks must be marshalled by the caller via after(0).

        Whisper settings for French accuracy
        -------------------------------------
        temperature=0           deterministic; no random sampling
        beam_size=5 / best_of=5 thorough search without being slow
        condition_on_previous_text=False
                                prevents hallucination carry-over between segments
        initial_prompt          primes Whisper to expect French text, improving
                                diacritic accuracy (accents, cédilles, liaisons)
        no_speech_threshold=0.6 drops segments Whisper isn't confident are speech
        compression_ratio_threshold=2.4
                                rejects repetitive hallucinations
        vad_filter              removes leading/trailing silence from audio before
                                feeding to Whisper, reducing false detections
        """
        if self._cancel_flag.is_set():
            self._set_state("idle")
            return

        if not self._audio_chunks:
            self._set_state("idle")
            self._on_not_recognized()
            return

        # Whisper expects a 1-D float32 array at STT_SAMPLE_RATE
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
