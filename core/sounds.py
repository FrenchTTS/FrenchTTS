"""
FrenchTTS — audio feedback tones for STT events.

WAV files are shipped in audio/ and bundled into the frozen exe via
PyInstaller --add-data. No runtime generation — the files are always present.
"""

import os
import sys
import threading
import winsound


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _audio_dir() -> str:
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "audio")


# Absolute paths for the three feedback sounds
AUDIO_DIR          = _audio_dir()
SND_RECOGNIZING    = os.path.join(AUDIO_DIR, "recognizing.wav")
SND_RECOGNIZED     = os.path.join(AUDIO_DIR, "recognized.wav")
SND_NOT_RECOGNIZED = os.path.join(AUDIO_DIR, "not_recognized.wav")


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
