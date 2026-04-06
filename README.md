<p align="center">
  <img src="img/logo.png" alt="FrenchTTS" width="600"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/platform-Windows-informational?style=flat-square" alt="Windows"/>
  <img src="https://img.shields.io/badge/TTS-edge--tts-blueviolet?style=flat-square" alt="edge-tts"/>
  <img src="https://img.shields.io/badge/STT-faster--whisper-orange?style=flat-square" alt="faster-whisper"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT"/>
</p>

<p align="center">
  Realistic French TTS for Windows — no API key, no subscription, no compromise on voice quality.<br/>
  Built for VoiceChat via <strong>VB-Cable</strong> or any virtual audio device.<br/>
  Includes an optional <strong>STT pipeline</strong> (mic → faster-whisper → speech) for hands-free dictation.
</p>

---

## Why FrenchTTS?

Finding a good French TTS in 2026 is surprisingly painful.

Most free solutions sound robotic, rely on outdated speech engines, or require you to paste text into a web interface and manually download the output. Paid alternatives _(ElevenLabs, Azure, Google Cloud)_ do sound great — but they all require an API key, a credit card, and start billing once you exceed a free tier.

On the open-source side, offline models like Kokoro or XTTS exist, but they demand a GPU, several GB of model weights, and non-trivial setup just to get started.

**FrenchTTS bridges that gap.** It uses Microsoft Edge's neural TTS engine — the same one powering the Read Aloud feature built into Edge browser — through the `edge-tts` library. No account, no key, no install beyond `pip`. The voices are genuinely neural-quality, indistinguishable from a paid service for most use cases, and the latency is low enough for real-time roleplay.

The app wraps it in a clean dark-mode desktop UI with audio device routing, so you can pipe the output directly into voicechat (Discord, FiveM, TeamSpeak, ...) via VB-Cable without touching any config file or third-party tool.

---

## Features

- **Neural voices** — 8 French voices (France, Belgium, Canada, Switzerland) streamed from Microsoft Edge, no key required
- **Device selector** — route audio to any output, auto-detects VB-Cable
- **Monitor output** — optionally hear the TTS in your headphones simultaneously on a second device
- **Voice controls** — adjustable speed, volume, and pitch
- **Input history** — navigate previous texts with `↑` / `↓` (shell-style)
- **Replay** — one-click or configurable hotkey (default `F2`) replays the last speech
- **Global hotkeys** — Replay, Stop, and STT work even when the app is not focused
- **STT pipeline** — mic → VAD → faster-whisper → TTS, hands-free dictation (disabled by default)
  - Energy-based VAD: starts recording automatically when you speak, stops on silence
  - Configurable keybind (default `F1`) shown on the button
  - Auto-restart mode: re-activates the mic after each TTS playback
- **System tray** — minimizes to tray, restores on double-click
- **Acrylic blur** — Windows 10/11 native background blur with adjustable opacity
- **Persistent config** — all settings and history saved in `%APPDATA%\FrenchTTS`
- **Auto-updater** — checks GitHub Releases at launch and self-replaces when frozen as `.exe`
- **Buildable as `.exe`** — single-file PyInstaller bundle via `build.bat`

---

## Voices

| Display name      | Region      | Gender | Voice ID                              |
| ----------------- | ----------- | ------ | ------------------------------------- |
| FR - Vivienne     | France      | Female | `fr-FR-VivienneMultilingualNeural`    |
| FR - Denise       | France      | Female | `fr-FR-DeniseNeural`                  |
| FR - Eloise       | France      | Female | `fr-FR-EloiseNeural`                  |
| FR-BE - Charline  | Belgium     | Female | `fr-BE-CharlineNeural`                |
| FR-CA - Sylvie    | Canada      | Female | `fr-CA-SylvieNeural`                  |
| FR-CH - Ariane    | Switzerland | Female | `fr-CH-ArianeNeural`                  |
| FR - Remy         | France      | Male   | `fr-FR-RemyMultilingualNeural`        |
| FR-CA - Antoine   | Canada      | Male   | `fr-CA-AntoineNeural`                 |

All voices are neural quality, streamed in real time from Microsoft Edge TTS servers.

---

## Requirements

- Windows 10 / 11
- Python 3.10+
- Internet connection (TTS voices stream from Microsoft's servers; STT runs fully offline)

---

## Quick start

##### Automatically

```bash
# Clone and launch — dependencies install automatically
git clone https://github.com/FrenchTTS/FrenchTTS.git
pushd FrenchTTS
launch.bat
```

##### Manually

```bash
pip install -r requirements.txt
python main.py
```

---

## Build as .exe

```bash
build.bat
```

Produces `dist/FrenchTTS.exe` as a self-contained single-file executable.
Requires `img/icon.ico` to be present before building.

---

## Usage

| Action                  | How                                                          |
| ----------------------- | ------------------------------------------------------------ |
| Speak text              | Type → `Enter` or click **Parler**                           |
| Insert newline          | `Shift + Enter`                                              |
| Stop playback           | **Arrêter** or configured hotkey (default `F3`)              |
| Replay last audio       | **Redire (F2)** or configured hotkey (default `F2`)          |
| Navigate history        | `↑` / `↓` in the text box                                   |
| Open settings           | **⚙ Paramètres**                                            |
| Minimize to tray        | Minimize the window                                          |
| Start / stop STT        | **🎙 STT (F1)** button or configured hotkey (default `F1`)  |

> **Global hotkeys** (Replay, Stop, STT) fire even when the app is minimized or not focused.

---

## STT — Speech-to-Text

> **STT is disabled by default.** Enable it in **⚙ Paramètres → STT — Reconnaissance vocale → Activer**.

STT uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper `small` model, CPU, int8) for offline French transcription.

**Flow:** press the STT button (or `F1`) → speak → silence is detected automatically → text is transcribed → TTS plays it back.

**First use:** the Whisper model (~460 MB) is downloaded once to `%APPDATA%\FrenchTTS\stt_models` and cached for all future sessions.

**Settings:**

| Option             | Description                                                    |
| ------------------ | -------------------------------------------------------------- |
| Activer            | Show/hide the STT button                                       |
| Touche STT         | Keybind to toggle listening (default `F1`)                     |
| Redémarrage auto   | Automatically re-activates the mic after each TTS playback     |
| Microphone         | Input device for VAD/transcription                             |

---

## VB-Cable setup

Example with [Discord](https://discord.com):

1. Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
2. In FrenchTTS → **⚙ Paramètres → Sortie TTS** → `CABLE Input (VB-Audio Virtual Cable)`
3. In Discord → Settings → Voice → **Input Device** → `CABLE Output (VB-Audio Virtual Cable)`

To also hear the output in your own headphones, enable **Casque** in settings and select your headphone device.

---

## Data & file structure

```
%APPDATA%\FrenchTTS\
├── config.json            # voice, device, sliders, hotkeys, opacity, STT settings
├── stt_models\            # faster-whisper model cache (downloaded on first STT use)
└── history\
    ├── last.mp3           # most recently generated audio
    └── lasts.log          # spoken text history (JSON array, max 100 entries)
```

```
FrenchTTS/
├── core/
│   ├── audio.py           # MP3 → PCM decoding
│   ├── constants.py       # paths, voices, settings defaults, formatters
│   └── sounds.py          # STT audio feedback tones
├── ui/
│   ├── app.py             # FrenchTTSApp — main window + TTS pipeline
│   ├── settings.py        # SettingsWindow
│   ├── updater.py         # UpdaterSplash, self-replacement logic
│   └── utils.py           # window icons, acrylic blur, tray image
├── voice/
│   └── listener.py        # mic capture → VAD → faster-whisper STT pipeline
├── audio/                 # STT feedback WAV tones (auto-generated if absent)
├── img/
│   ├── icon.ico
│   ├── icon.png
│   └── logo.png
├── main.py
├── requirements.txt
├── launch.bat
└── build.bat
```

---

## Dependencies

| Package           | Role                                              |
| ----------------- | ------------------------------------------------- |
| `edge-tts`        | Neural TTS via Microsoft Edge servers             |
| `faster-whisper`  | Offline French STT (Whisper model, CPU, int8)     |
| `customtkinter`   | Modern dark-mode UI                               |
| `sounddevice`     | PCM playback with per-device routing              |
| `miniaudio`       | In-memory MP3 decode (no ffmpeg needed)           |
| `numpy`           | PCM buffer handling                               |
| `keyboard`        | System-wide hotkeys (works when app not focused)  |
| `pystray`         | System tray icon                                  |
| `Pillow`          | Tray image fallback                               |

---

## License

MIT — © [FrenchTTS](https://frenchtts.github.io)
