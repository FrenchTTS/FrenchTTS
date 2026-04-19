"""
FrenchTTS — audio decoding and PCM utilities.
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


def trim_silence(pcm: np.ndarray, threshold: int = 200) -> np.ndarray:
    """Strip leading silence from int16 PCM.

    Only the leading silence is removed. The natural trailing silence from
    edge-tts is preserved so the hardware buffer has time to drain and the
    last phoneme is not clipped.

    threshold: amplitude in int16 units (0–32 768).  200 ≈ −44 dB, which
    catches the digital silence padding edge-tts prepends to every stream
    without clipping soft speech onsets.
    """
    above = np.where(np.abs(pcm) > threshold)[0]
    if not above.size:
        return pcm
    return pcm[above[0]:]


def decode_and_trim(data: bytes) -> tuple[np.ndarray, int]:
    """Decode MP3 and strip leading silence in a single executor call."""
    pcm, sr = _decode_mp3(data)
    return trim_silence(pcm), sr


def save_mp3(path: str, data: bytes) -> None:
    """Write raw MP3 bytes to *path*, silently ignoring OS errors."""
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        pass
