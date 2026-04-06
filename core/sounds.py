"""
FrenchTTS — audio feedback tones for STT events.

Generates simple sine-wave WAV files on first run if the audio/ folder does
not contain them. Replace any file with a custom WAV at any time — the app
only writes them when they are absent.
"""

import math
import os
import struct
import sys
import threading
import wave
import winsound


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _audio_dir() -> str:
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "audio")


# Absolute paths for the three feedback sounds
AUDIO_DIR       = _audio_dir()
SND_RECOGNIZING    = os.path.join(AUDIO_DIR, "recognizing.wav")
SND_RECOGNIZED     = os.path.join(AUDIO_DIR, "recognized.wav")
SND_NOT_RECOGNIZED = os.path.join(AUDIO_DIR, "not_recognized.wav")


# ---------------------------------------------------------------------------
# WAV generation
# ---------------------------------------------------------------------------

def _write_tone(path: str, freqs: list, duration: float,
                volume: float = 0.35, sample_rate: int = 44100) -> None:
    """Write a multi-frequency sine mix to a 16-bit mono WAV file.

    ``freqs`` is a list of (hz, relative_amplitude) pairs.
    A 10 ms linear fade-in/out prevents clicks at the edges.
    """
    n    = int(sample_rate * duration)
    fade = int(sample_rate * 0.010)
    total_amp = max(sum(a for _, a in freqs), 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n):
            env    = min(i, n - i, fade) / fade
            sample = sum(amp * math.sin(2 * math.pi * hz * i / sample_rate)
                         for hz, amp in freqs)
            val    = int(32767 * volume * env * sample / total_amp)
            w.writeframes(struct.pack("<h", max(-32768, min(32767, val))))


def ensure_sounds() -> None:
    """Create default feedback tones inside ``audio/`` if files are absent."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    defaults = {
        SND_RECOGNIZING:    ([(880, 1.0), (1320, 0.5)], 0.12),  # bright ping
        SND_RECOGNIZED:     ([(523, 1.0), (659, 0.8), (784, 0.6)], 0.20),  # C-E-G chord
        SND_NOT_RECOGNIZED: ([(330, 1.0)], 0.22),  # low brief tone
    }
    for path, (freqs, dur) in defaults.items():
        if not os.path.exists(path):
            try:
                _write_tone(path, freqs, dur)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play_sound(path: str) -> None:
    """Play a WAV file asynchronously on the Windows default audio output.

    winsound routes through the Windows audio mixer on its own channel,
    independently of any sounddevice streams (TTS output, mic input).
    SND_NODEFAULT suppresses the system beep if the file is missing.
    """
    if not os.path.exists(path):
        return
    threading.Thread(
        target=winsound.PlaySound,
        args=(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT),
        daemon=True,
    ).start()
