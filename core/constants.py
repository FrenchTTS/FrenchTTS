"""
FrenchTTS — shared constants, paths, and formatter utilities.

This module is intentionally dependency-free (stdlib ``os`` / ``sys`` only) so
every other module can import from it without risk of circular imports.
"""

import os
import sys

from core.version import BUILD_ID

# ---------------------------------------------------------------------------
# Paths
#
# All user data lives under %APPDATA%\FrenchTTS so the app never writes
# next to its own executable (important for UAC-restricted installs and
# the PyInstaller bundle, which may unpack to Program Files).
# ---------------------------------------------------------------------------

APPDATA     = os.environ.get("APPDATA", os.path.expanduser("~"))
BASE_DIR    = os.path.join(APPDATA, "FrenchTTS")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
LAST_MP3    = os.path.join(HISTORY_DIR, "last.mp3")   # overwritten each generation
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
HISTORY_LOG = os.path.join(HISTORY_DIR, "lasts.log")  # JSON array of past texts
os.makedirs(BASE_DIR,    exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Application identity
#
# Single source of truth for the name and public URL.
# BUILD_ID comes from core/version.py: "dev" in source, a 7-char commit SHA
# in a frozen exe (written by the GitHub Actions workflow before building).
# APP_VERSION_DISPLAY is shown in the copyright footer.
# ---------------------------------------------------------------------------

# Keys are the display names shown in the settings dropdown.
# Values are passed verbatim to edge_tts.Communicate as the ``voice`` param.
# Run ``edge-tts --list-voices | grep fr-FR`` to discover additional voices.
VOICES: dict[str, str] = {
    # Female
    "FR - Vivienne": "fr-FR-VivienneMultilingualNeural",
    "FR - Denise":  "fr-FR-DeniseNeural",
    "FR - Eloise":  "fr-FR-EloiseNeural",
    "FR-BE - Charline": "fr-BE-CharlineNeural",
    "FR-CA - Sylvie": "fr-CA-SylvieNeural",
    "FR-CH - Ariane": "fr-CH-ArianeNeural",

    # Male
    "FR - Remy": "fr-FR-RemyMultilingualNeural",
    "FR-CA - Antoine": "fr-CA-AntoineNeural"
}

APP_NAME = "FrenchTTS"
APP_URL  = "https://frenchtts.github.io"

# "prod-4d45892" in a frozen release build, "dev-latest" in all other cases.
# The BUILD_ID != "dev" guard prevents "prod-dev" appearing if someone runs
# build.bat without git (or git is unavailable) and the SHA injection falls back.
APP_VERSION_DISPLAY = (
    f"prod-{BUILD_ID}"
    if getattr(sys, "frozen", False) and BUILD_ID != "dev"
    else "dev-latest"
)

GITHUB_REPO = "FrenchTTS/FrenchTTS"  # owner/repo for the GitHub Releases API

# ---------------------------------------------------------------------------
# UI state
# ---------------------------------------------------------------------------

STATUS_READY   = "Prêt"
STATUS_LOADING = "Chargement..."
STATUS_PLAYING = "En cours..."
STATUS_ERROR   = "Erreur"

# Maximum number of past texts kept in memory and persisted to lasts.log.
MAX_HISTORY = 100

# Merged into the on-disk config at load time so missing keys always have
# a safe fallback without wiping the user's existing preferences.
DEFAULT_SETTINGS: dict = {
    "voice":      list(VOICES.keys())[0],
    "device":     "",    # empty → auto-select (prefers VB-Cable if found)
    "rate":       0,     # percent offset, e.g. +20 = 20% faster
    "volume":     100,   # 0–100; converted to a signed edge-tts offset at runtime
    "pitch":      0,     # Hz offset, e.g. -10 = 10 Hz lower
    "opacity":    0.93,  # 1.0 = fully opaque (acrylic disabled)
    "replay_key":      "F2",     # Tkinter keysym — also used as keyboard lib hotkey
    "stop_key":        "F3",     # same format; triggers the Stop action globally
    "stt_enabled":      False,  # show/hide the STT button (disabled by default)
    "stt_input_device": "",    # empty → system default microphone
    "stt_key":          "F1",  # keybind to toggle STT (Tkinter keysym)
    "stt_auto_restart": False, # re-trigger listening after each TTS playback
    "stt_notify":       False, # tray balloon with transcribed text (tray-only, disabled by default)
    "monitor_enabled":  False, # play TTS audio on a second output device
    "monitor_device":   "",    # empty → auto-select first non-VB-Cable output
    "last_seen_version": "",   # BUILD_ID of the last version whose changelog was shown
}

# Ghost-style button appearance reused for secondary actions in both windows.
# Stored as a dict so it can be unpacked with ** into CTkButton calls.
_BTN_SECONDARY = dict(
    fg_color=("gray75", "#2c2c2c"),
    hover_color=("gray65", "#383838"),
    border_width=1,
    border_color=("gray60", "#454545"),
)

# ---------------------------------------------------------------------------
# Formatters
#
# edge-tts expects signed string params like "+20%", "-10Hz".
# These converters are shared between SettingsWindow (live slider labels)
# and FrenchTTSApp (building the Communicate call).
# ---------------------------------------------------------------------------

def _fmt_signed(v: int, unit: str) -> str:
    """Return a signed string such as '+20%' or '-10Hz'."""
    return f"+{v}{unit}" if v >= 0 else f"{v}{unit}"

fmt_rate   = lambda v: _fmt_signed(int(v), "%")
fmt_pitch  = lambda v: _fmt_signed(int(v), "Hz")
fmt_volume = lambda v: f"{int(v)}%"

# ---------------------------------------------------------------------------
# STT (Speech-to-Text) — faster-whisper configuration
# ---------------------------------------------------------------------------

STT_MODEL_DIR   = os.path.join(BASE_DIR, "stt_models")
STT_MODEL_SIZE  = "small"   # "tiny" | "base" | "small"
STT_LANGUAGE    = "fr"
STT_DEVICE      = "cpu"     # "cpu" only; "cuda" would need torch
STT_COMPUTE     = "int8"    # fastest on CPU with negligible WER loss
STT_SAMPLE_RATE = 16000     # Hz — Whisper's native input rate
STT_CHANNELS    = 1         # mono

os.makedirs(STT_MODEL_DIR, exist_ok=True)

STATUS_RECORDING    = "Enregistrement..."
STATUS_TRANSCRIBING = "Transcription..."
