"""
FrenchTTS — audio decoding utilities.

Kept separate from the UI so future audio helpers (e.g. microphone capture,
PCM resampling) have a natural home without growing the UI modules.
"""

import miniaudio
import numpy as np


def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    """Decode raw MP3 bytes into a (pcm, sample_rate) pair.

    Uses miniaudio so there is no dependency on ffmpeg or any system codec.
    Output is always mono int16 PCM at 24 000 Hz, which matches the sample
    rate used by edge-tts and avoids a resample step in sounddevice.
    """
    decoded = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000)
    return np.frombuffer(decoded.samples, dtype=np.int16), decoded.sample_rate
