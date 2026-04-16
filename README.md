<p align="center">
  <img src="img/logo.png" alt="FrenchTTS" width="600"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/platform-Windows-informational?style=flat-square" alt="Windows"/>
  <img src="https://img.shields.io/badge/TTS-edge--tts-blueviolet?style=flat-square" alt="edge-tts"/>
  <img src="https://img.shields.io/badge/STT-faster--whisper-orange?style=flat-square" alt="faster-whisper"/>
  <img src="https://img.shields.io/badge/Twitch-OBS%20overlay-9146ff?style=flat-square" alt="Twitch/OBS"/>
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square" alt="AGPL-3.0"/>
</p>

<p align="center">
  Realistic French TTS for Windows — no API key, no subscription, no compromise on voice quality.<br/>
  Built for VoiceChat via <strong>VB-Cable</strong> or any virtual audio device.<br/>
  Includes an optional <strong>STT pipeline</strong> (mic → faster-whisper → speech) for hands-free dictation.<br/>
  Streaming-ready with a built-in <strong>Twitch / OBS mode</strong> — live overlay, channel-point TTS, and a local REST API.
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
  - Optional tray notification showing the transcribed text
- **System tray** — closing the window hides to tray (balloon notification confirms); restores on double-click; quit via tray menu
- **Acrylic blur** — Windows 10/11 native background blur with adjustable opacity
- **Resource controls** _(Performances)_ — CPU core throttle (affinity mask), Windows process priority (Normal / Below Normal / Idle), and RAM working-set soft cap; all live, all saved to config
- **Twitch / OBS mode** _(disabled by default, zero overhead when off)_
  - **OBS Browser Source overlay** — real-time word-by-word karaoke display, synchronized with audio playback via WebSocket
  - **Local REST API** — `POST /api/speak`, `/api/voice`, `/api/pitch`, `GET /api/status`; callable from StreamElements, Streamlabs, curl, or any tool
  - **Integrated Twitch bot** — connects directly via IRC/PubSub; reacts to channel-point redemptions by title (`TTS`, `Voix TTS`, `Pitch TTS`, …)
  - **Configurable appearance** — overlay background (color, opacity, toggle), text color, all live-synced
  - **Per-feature toggles** — disable overlay, speak, voice, or pitch independently to save resources
- **Persistent config** — all settings and history saved in `%APPDATA%\UseVoice\FrenchTTS`; atomic writes prevent corruption on crash
- **Auto-updater** — checks GitHub Releases at launch, downloads `FrenchTTSInstaller.exe`, self-replaces silently; versioned by commit SHA (`prod-XXXXXXX`)
- **Installer** — dark-themed CTk installer with progress steps; creates Desktop shortcut, Start Menu folder, and `FrenchTTSUninstaller.exe`
- **Uninstaller** — removes app, config, STT models, shortcuts, and Start Menu entries
- **What's New dialog** — shown once after each update with the release changelog
- **Buildable as `.exe`** — 3-step PyInstaller build via `build.bat`

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

##### Dev mode (no updater splash)

```bash
git clone https://github.com/UseVoice/FrenchTTS.git
cd FrenchTTS
pip install -r requirements.txt
python main.py
```

Or use the helper scripts at the project root:

| Script                  | What it does                                      |
| ----------------------- | ------------------------------------------------- |
| `setup.bat`             | Install all pip dependencies                      |
| `launch - dev.bat`      | Run `python main.py` directly, no updater splash  |
| `launch - update.bat`   | Run with `--update` flag to simulate an update    |
| `launch - installer.bat`| Test the installer or uninstaller interactively   |

---

## Build as `.exe`

```bash
build.bat
```

Three-step build — each artifact is a prerequisite for the next:

| Step | Output | Notes |
| ---- | ------ | ----- |
| 1 | `dist\FrenchTTS.exe` | Main app; git SHA injected as build ID |
| 2 | `dist\FrenchTTSUninstaller.exe` | Tiny stdlib-only uninstaller |
| 3 | `installer\dist\FrenchTTSInstaller.exe` | Bundles both exes; this is the release asset |

To publish a release, trigger the **Build & Release** workflow manually from the GitHub Actions UI. It builds all three artifacts, tags the release `prod-<sha>`, and attaches `FrenchTTSInstaller.exe` as the only release asset.

Write `versions/<sha>.md` beforehand if you want a custom What's New changelog (auto-generated otherwise from conventional commits).

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
| Hide to tray            | Click the window's close button (×)                          |
| Quit                    | Right-click the tray icon → **Quitter**                      |
| Start / stop STT        | **🎙 STT (F1)** button or configured hotkey (default `F1`)  |

> **Global hotkeys** (Replay, Stop, STT) fire even when the app is minimized or not focused.

---

## STT — Speech-to-Text

> **STT is disabled by default.** Enable it in **⚙ Paramètres → STT — Reconnaissance vocale → Activer**.

STT uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper `small` model, CPU, int8) for offline French transcription.

**Flow:** press the STT button (or `F1`) → speak → silence is detected automatically → text is transcribed → TTS plays it back.

**First use:** the Whisper model (~460 MB) is downloaded once to `%APPDATA%\UseVoice\FrenchTTS\stt_models` and cached for all future sessions.

**Settings:**

| Option             | Description                                                                 |
| ------------------ | --------------------------------------------------------------------------- |
| Activer            | Show/hide the STT button                                                    |
| Touche STT         | Keybind to toggle listening (default `F1`)                                  |
| Redémarrage auto   | Automatically re-activates the mic after each TTS playback                  |
| Notif. texte       | Show a tray balloon with the transcribed text (title: "STT — Retranscription") |
| Microphone         | Input device for VAD/transcription                                          |

---

## Twitch / OBS

> **Disabled by default.** Enable in **⚙ Paramètres → Twitch / OBS → Activer**.

When enabled, FrenchTTS starts a local HTTP server (default port **7681**) that provides:

### OBS Browser Source overlay

Add `http://localhost:7681` as a **Browser Source** in OBS (recommended size: 1920 × 200 px).

Each time the TTS speaks, words appear one by one in sync with the audio, then fade out. The overlay uses a WebSocket connection and reconnects automatically.

**Appearance** is configurable in **Paramètres → Twitch / OBS → Apparence de l'overlay**:

| Option | Description |
|---|---|
| Fond sous texte | Toggle background on/off |
| Opacité du fond | Background transparency (0–100 %) |
| Couleur du fond | Background colour (native colour picker or hex) |
| Couleur du texte | Word colour |

Changes are pushed live to all connected OBS sources — no refresh needed.

### Local REST API

| Method | Route | Body | Description |
|---|---|---|---|
| `POST` | `/api/speak` | `{"text":"…", "voice"?:"…", "pitch"?:N, "duration"?:N}` | Trigger TTS |
| `POST` | `/api/voice` | `{"voice":"FR - Denise", "duration"?:30}` | Temporary voice change |
| `POST` | `/api/pitch` | `{"pitch":-20, "duration"?:30}` | Temporary pitch change (Hz, −100→+100) |
| `GET`  | `/api/status` | — | `{"speaking": bool, "voice":"…", "pitch":N}` |

`voice` and `pitch` overrides restore automatically after `duration` seconds (default: configurable in settings, default 30 s).

### Integrated Twitch bot

Enable in **Paramètres → Twitch / OBS → Bot Twitch intégré**. Requires an OAuth token obtained from `dev.twitch.tv` (a guided setup is available directly in settings).

The bot subscribes to PubSub channel-point redemptions. Reward titles are matched case-insensitively:

| Reward title | Action |
|---|---|
| `TTS` / `Lire TTS` / `Dire` / `Parler` | Reads the viewer's input |
| `Voix TTS` / `Changer Voix` / `Voice TTS` | Changes voice temporarily |
| `Pitch TTS` / `Changer Pitch` | Changes pitch temporarily (integer Hz) |

Input text is capped at 300 characters per redemption.

---

## Performances (resource management)

Available in **⚙ Paramètres → Performances**.

| Setting | Description | Default |
| ------- | ----------- | ------- |
| **Cœurs CPU** | Limits the process to N logical CPUs via `SetProcessAffinityMask`. Slider from 1 to the number of logical CPUs on your machine. | 75 % of cores |
| **Priorité CPU** | Windows process priority class — `Normale`, `En dessous de la normale`, or `Basse (arrière-plan)`. Lower values reduce CPU scheduler share and may noticeably slow TTS generation. | Normale |
| **RAM max** | Soft working-set cap in MB via `SetProcessWorkingSetSizeEx`. Windows will page out memory above this limit when the system is under pressure. 4096 MB = Illimité (no cap). | 1024 MB |

All three settings are applied immediately on change and persisted to `config.json`.

---

## VB-Cable setup

Example with [Discord](https://discord.com):

1. Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
2. In FrenchTTS → **⚙ Paramètres → Sortie TTS** → `CABLE Input (VB-Audio Virtual Cable)`
3. In Discord → Settings → Voice → **Input Device** → `CABLE Output (VB-Audio Virtual Cable)`

To also hear the output in your own headphones, enable **Casque** in settings and select your headphone device.

---

## Installation

Download `FrenchTTSInstaller.exe` from the [latest release](https://github.com/UseVoice/FrenchTTS/releases/latest) and run it.

The installer:
- Extracts `FrenchTTS.exe` to `%LOCALAPPDATA%\UseVoice\FrenchTTS\`
- Creates a Desktop shortcut
- Creates a **Start Menu** folder (`FrenchTTS`) with shortcuts for the app and the uninstaller
- Extracts `FrenchTTSUninstaller.exe` alongside the app

To uninstall, run **Désinstaller FrenchTTS** from the Start Menu (or `FrenchTTSUninstaller.exe` directly). It removes the app, all configuration, STT models, and shortcuts.

---

## Data & file structure

```
%APPDATA%\UseVoice\FrenchTTS\
├── config.json            # voice, device, sliders, hotkeys, opacity, STT & performance settings
├── stt_models\            # faster-whisper model cache (downloaded on first STT use)
└── history\
    ├── last.mp3           # most recently generated audio
    └── lasts.log          # spoken text history (JSON array, max 100 entries)

%LOCALAPPDATA%\UseVoice\FrenchTTS\
├── FrenchTTS.exe          # installed application
└── FrenchTTSUninstaller.exe
```

```
FrenchTTS/
├── core/
│   ├── audio.py           # MP3 → PCM decoding, silence trimming
│   ├── constants.py       # paths, voices, settings defaults, formatters
│   ├── sounds.py          # STT audio feedback tones
│   └── version.py         # BUILD_ID — "dev" in source, SHA in release exe
├── installer/
│   ├── installer_main.py  # CTk installer + silent updater helper
│   ├── installer.spec     # PyInstaller spec (bundles app + uninstaller)
│   ├── uninstaller_main.py# Win32 stdlib uninstaller
│   └── uninstaller.spec   # PyInstaller spec (stdlib-only, small)
├── twitch/
│   ├── server.py          # aiohttp HTTP + WebSocket server (overlay, /api/* routes)
│   ├── manager.py         # TwitchManager lifecycle, feature flags, temp overrides
│   ├── bot.py             # twitchio IRC bot, PubSub channel-point handler
│   └── static/
│       ├── overlay.html   # OBS Browser Source — karaoke word-by-word display
│       └── callback.html  # OAuth redirect landing page — shows access_token to copy
├── ui/
│   ├── app.py             # FrenchTTSApp — main window + TTS pipeline
│   ├── settings.py        # SettingsWindow (collapsible sections, Twitch modals)
│   ├── updater.py         # UpdaterSplash, self-replacement logic
│   ├── utils.py           # window icons, acrylic blur, tray notifications, Win32 resource helpers
│   └── whats_new.py       # What's New dialog shown after updates
├── voice/
│   └── listener.py        # mic capture → VAD → faster-whisper STT pipeline
├── versions/
│   └── <sha>.md           # changelog shown in What's New after each update
├── img/
│   ├── icon.ico
│   ├── icon.png
│   └── logo.png
├── main.py
├── requirements.txt
├── build.bat
├── setup.bat
├── launch - dev.bat
├── launch - update.bat
└── launch - installer.bat
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
| `pystray`         | System tray icon and balloon notifications        |
| `Pillow`          | Tray image and CTk internal rendering             |
| `aiohttp`         | Local HTTP + WebSocket server for Twitch/OBS mode |
| `twitchio`        | Twitch IRC/PubSub bot for channel-point events    |

> `aiohttp` and `twitchio` are only imported when Twitch mode is enabled. They add no startup overhead otherwise.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

© 2026 UseVoice

You are free to use, modify, and distribute this software, provided that:
- The source code remains available.
- Any modifications are released under the same AGPL-3.0 license.
- If the software is used over a network (e.g., as a SaaS), the corresponding source code must be made publicly available.

For full details, see the [LICENSE](LICENSE) file or visit:
https://www.gnu.org/licenses/agpl-3.0.html
