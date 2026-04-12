"""
FrenchTTS — entry point.

Run ``python main.py`` to launch the app in development mode (no updater).
Run ``python main.py --update`` to test the updater splash locally.
Build with ``build.bat`` to produce a self-contained FrenchTTS.exe.

Module layout
-------------
core/constants.py      — paths, voices, settings defaults, formatters
core/audio.py          — MP3 → PCM decoding
ui/utils.py       — window icons, acrylic blur, tray image
ui/updater.py     — UpdaterSplash, _apply_update
ui/settings.py    — SettingsWindow
ui/app.py         — FrenchTTSApp (main window + TTS pipeline)
voice/listener.py — mic capture → faster-whisper STT → TTS pipeline
"""

import sys

from ui.updater import UpdaterSplash
from ui.app import FrenchTTSApp


def main() -> None:
    # The updater splash runs when frozen (.exe) or when --update is passed on
    # the command line (dev testing only). In normal dev mode it is skipped so
    # developers are never blocked by a version check on every run.
    run_updater = getattr(sys, "frozen", False) or "--update" in sys.argv
    if run_updater:
        splash = UpdaterSplash()
        splash.mainloop()
        if not splash._launch_app:
            return  # update applied; the installer will relaunch the new exe
    app = FrenchTTSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
