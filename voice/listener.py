"""
voice/listener.py — Microphone capture → VAD → faster-whisper STT pipeline.

Flow
----
1. start_listening() opens the mic stream and starts voice activity detection (VAD).
2. The PortAudio callback computes the RMS energy of each block (~64 ms).
   - When energy exceeds SPEECH_THR for CONFIRM_FRAMES consecutive blocks
     → speech confirmed: on_state_change("recording") is called, recognizing.wav plays.
   - When energy drops below SPEECH_THR for SILENCE_FRAMES consecutive blocks
     → end of utterance detected: _vad_done is signalled.
3. _vad_watcher() (daemon thread) waits for _vad_done, closes the stream, and
   launches _transcribe_worker() in a new daemon thread.
4. _transcribe_worker() calls Whisper then invokes on_transcript or on_not_recognized.

No second click needed — silence triggers transcription automatically.

Public surface
--------------
STTListener(on_transcript, on_state_change, on_error, on_not_recognized)
    .device             — int | None  ; set before start_listening()
    .start_listening()  — open the mic, start VAD
    .cancel()           — abort without producing a transcript
    .is_busy            — True when state != "idle"
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
# VAD constants
# ---------------------------------------------------------------------------

BLOCKSIZE         = 1024  # frames per PortAudio callback  (~64 ms at 16 kHz)
SPEECH_THR        = 0.012 # RMS energy threshold to classify a block as speech
CONFIRM_FRAMES    = 2     # consecutive blocks above threshold to confirm speech (~128 ms)
SILENCE_FRAMES    = 8     # consecutive blocks below threshold to end utterance (~512 ms)
PREROLL_FRAMES    = 5     # blocks kept before speech onset for context (~320 ms)
MAX_RECORD_FRAMES = int(30 * STT_SAMPLE_RATE / BLOCKSIZE)  # auto-stop after 30 s


# ---------------------------------------------------------------------------
# Whisper model singleton
# ---------------------------------------------------------------------------

_model: "WhisperModel | None" = None
_model_lock = threading.Lock()


def _get_model(model_size: str = STT_MODEL_SIZE) -> WhisperModel:
    """Return the cached WhisperModel, loading it on the first call.

    Thread-safe via _model_lock. First call takes ~2–4 s on CPU.
    download_root points to %APPDATA%/FrenchTTS/stt_models so the model
    survives PyInstaller's temporary extraction directory.
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
    """Manages microphone capture and background transcription.

    Threading model
    ---------------
    - start_listening() opens an sd.InputStream; the PortAudio callback runs
      on PortAudio's internal thread.
    - VAD updates counters inside the callback (no lock needed since only one
      thread writes these values) and signals end-of-speech via threading.Event.
    - _vad_watcher() runs as a daemon and waits for the signal before closing
      the stream and launching _transcribe_worker().
    - All caller-provided callbacks are invoked from non-Tkinter threads;
      the caller must marshal them via after(0, ...).

    Parameters
    ----------
    on_transcript : callable(str)
        Called when transcription produces non-empty text.
    on_state_change : callable(str)
        Called on each state change: "idle", "listening", "recording",
        "transcribing". May be called from the PortAudio thread.
    on_error : callable(str)
        Human-readable error message (inaccessible mic, Whisper crash, etc.).
    on_not_recognized : callable()
        Called when Whisper returns no text (VAD filtered everything, etc.).
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

        # Input device index; None = system default microphone.
        self.device: "int | None" = None

        # VAD state — reset by _reset_vad() before each listening session
        self._vad_speech      = False
        self._vad_confirm_n   = 0
        self._vad_silence_n   = 0
        self._speech_notified = False
        self._preroll:        collections.deque = collections.deque(maxlen=PREROLL_FRAMES)
        self._speech_chunks:  list = []
        self._audio_chunks:   list = []
        self._vad_done:       threading.Event = threading.Event()

    # --- Public API (called from the main thread) ---------------------------

    @property
    def is_busy(self) -> bool:
        return self._state != "idle"

    def start_listening(self) -> None:
        """Open the mic stream and start voice activity detection.

        No additional click is needed: silence detected after speech
        triggers transcription automatically. Call cancel() to abort.
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
        """Abort listening or transcription without producing a result."""
        self._cancel_flag.set()
        self._vad_done.set()   # unblock _vad_watcher if waiting
        self._close_stream()
        if self._state != "idle":
            self._set_state("idle")

    # --- VAD callback (PortAudio thread) ------------------------------------

    def _vad_callback(self, indata: np.ndarray, frames: int,
                      time_info, status) -> None:
        """Analyse RMS energy of each audio block in real time.

        Called by PortAudio on its internal thread. No blocking operations
        and no sounddevice API calls here (PortAudio callback rule).
        End-of-speech is signalled via threading.Event so _vad_watcher can
        close the stream safely from a separate thread.
        """
        if self._cancel_flag.is_set():
            return

        chunk  = indata.copy()
        energy = float(np.sqrt(np.mean(chunk ** 2)))

        if not self._vad_speech:
            # Waiting phase: accumulate pre-roll and look for speech onset
            self._preroll.append(chunk)
            if energy > SPEECH_THR:
                self._vad_confirm_n += 1
                if self._vad_confirm_n >= CONFIRM_FRAMES:
                    # Speech confirmed
                    self._vad_speech = True
                    self._vad_silence_n = 0
                    # pre-roll + current block (already in deque) = start of utterance
                    self._speech_chunks = list(self._preroll)
                    if not self._speech_notified:
                        self._speech_notified = True
                        self._state = "recording"
                        self._on_state_change("recording")
            else:
                self._vad_confirm_n = 0
        else:
            # Recording phase: accumulate audio and watch for silence
            self._speech_chunks.append(chunk)
            if energy < SPEECH_THR:
                self._vad_silence_n += 1
                if self._vad_silence_n >= SILENCE_FRAMES:
                    self._vad_done.set()
            else:
                self._vad_silence_n = 0
            # Auto-stop after 30 seconds to prevent an unbounded buffer
            if len(self._speech_chunks) >= MAX_RECORD_FRAMES:
                self._vad_done.set()

    # --- Watcher thread (daemon) --------------------------------------------

    def _vad_watcher(self) -> None:
        """Wait for end-of-speech detected by VAD, then transcribe.

        Runs as a daemon. Closes the stream from this thread (safe, unlike
        from the callback) and starts _transcribe_worker in a new daemon.
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

    # --- Transcription (daemon) ---------------------------------------------

    def _transcribe_worker(self) -> None:
        """Concatenate audio chunks, call Whisper, deliver the result.

        Whisper settings for French
        ---------------------------
        temperature=0                    deterministic output
        beam_size=1                      greedy decoding — 4× faster than beam=5,
                                         negligible WER loss for short utterances
        condition_on_previous_text=False prevents cascading hallucinations
        initial_prompt                   primes Whisper toward colloquial French
                                         including accents, contractions, slang
        no_speech_threshold=0.45        rejects low-confidence segments
        compression_ratio_threshold=2.4 detects hallucinatory repetitions
        vad_filter=False                 our energy VAD already stripped silence
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
                beam_size=1,           # greedy decoding: 4× faster, negligible WER loss
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=(
                    "Transcription fidèle du français parlé, incluant le langage "
                    "familier et les jurons. Exemples : ça, c'est, j'ai, t'as, t'es, "
                    "y'a, ouais, putain, merde, bordel, oh là là, quoi, enfin."
                ),
                no_speech_threshold=0.45,
                compression_ratio_threshold=2.4,
                vad_filter=False,      # energy VAD already stripped silence before this
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

    # --- Internal helpers ---------------------------------------------------

    def _reset_vad(self) -> None:
        """Reset all VAD counters and buffers before a new listening session."""
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
