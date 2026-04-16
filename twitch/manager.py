from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.app import FrenchTTSApp


class TwitchManager:

    def __init__(self, app: "FrenchTTSApp") -> None:
        self.app:           "FrenchTTSApp" = app
        self.ws_clients:    set            = set()
        self.port:          int            = 7681
        self.temp_duration: int            = 30
        self.config:        dict           = {}

        self._runner:      Any | None                      = None
        self._bot_thread:  threading.Thread | None         = None
        self._bot_loop:    asyncio.AbstractEventLoop | None = None
        self._temp_tasks:  dict[str, asyncio.Task]         = {}

    async def start(self, settings: dict) -> None:
        from aiohttp import web
        from twitch.server import build_app

        self.config        = dict(settings)
        self.port          = int(settings.get("twitch_port", 7681))
        self.temp_duration = int(settings.get("twitch_temp_duration", 30))

        aio_app      = build_app(self)
        self._runner = web.AppRunner(aio_app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "localhost", self.port)
        try:
            await site.start()
        except OSError as exc:
            print(f"[Twitch] Cannot bind port {self.port}: {exc}")
            return

        if settings.get("twitch_bot_enabled") and settings.get("twitch_channel"):
            self._start_bot(settings)

    async def stop(self) -> None:
        for ws in list(self.ws_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self.ws_clients.clear()

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        for task in self._temp_tasks.values():
            task.cancel()
        self._temp_tasks.clear()

        if self._bot_loop and self._bot_loop.is_running():
            self._bot_loop.call_soon_threadsafe(self._bot_loop.stop)
        if self._bot_thread and self._bot_thread.is_alive():
            self._bot_thread.join(timeout=3)
        self._bot_loop   = None
        self._bot_thread = None

    def update_config(self, key: str, value: Any) -> None:
        self.config[key] = value

    # Feature flags

    def feat_overlay(self) -> bool:
        return self.config.get("twitch_feat_overlay", True)

    def feat_speak(self) -> bool:
        return self.config.get("twitch_feat_speak", True)

    def feat_voice(self) -> bool:
        return self.config.get("twitch_feat_voice", True)

    def feat_pitch(self) -> bool:
        return self.config.get("twitch_feat_pitch", True)

    # Broadcasting

    def get_overlay_config(self) -> dict:
        return {
            "type":       "config",
            "bg":         self.config.get("twitch_overlay_bg", True),
            "bg_color":   self.config.get("twitch_overlay_bg_color", "#000000"),
            "bg_opacity": self.config.get("twitch_overlay_bg_opacity", 0.65),
            "text_color": self.config.get("twitch_overlay_text_color", "#ffffff"),
        }

    async def broadcast(self, event: dict) -> None:
        if not self.feat_overlay() or not self.ws_clients:
            return
        text = json.dumps(event, ensure_ascii=False)
        for ws in list(self.ws_clients):
            try:
                await ws.send_str(text)
            except Exception:
                self.ws_clients.discard(ws)

    async def broadcast_config(self, config: dict) -> None:
        # Bypasses feat_overlay — appearance config is always pushed
        if not self.ws_clients:
            return
        text = json.dumps({"type": "config", **config}, ensure_ascii=False)
        for ws in list(self.ws_clients):
            try:
                await ws.send_str(text)
            except Exception:
                self.ws_clients.discard(ws)

    # TTS queue

    async def enqueue_speak(
        self,
        text:     str,
        voice:    str | None = None,
        pitch:    int | None = None,
        duration: int | None = None,
    ) -> None:
        if not self.feat_speak():
            return

        if voice is not None and self.feat_voice():
            from core.constants import VOICES
            if voice in VOICES:
                dur = duration if duration is not None else self.temp_duration
                asyncio.ensure_future(self.apply_temp("voice_var", voice, dur))

        if pitch is not None and self.feat_pitch():
            dur = duration if duration is not None else self.temp_duration
            asyncio.ensure_future(self.apply_temp("pitch_var", int(pitch), dur))

        self.app.after(0, lambda t=text: self.app._on_speak_text(t))

    # Temporary overrides

    async def apply_temp(self, var_name: str, new_val: Any, duration: int) -> None:
        if var_name == "voice_var" and not self.feat_voice():
            return
        if var_name == "pitch_var" and not self.feat_pitch():
            return

        old_task = self._temp_tasks.pop(var_name, None)
        if old_task and not old_task.done():
            old_task.cancel()

        var     = getattr(self.app, var_name)
        old_val = var.get()
        self.app.after(0, lambda v=new_val: var.set(v))

        async def _restore():
            await asyncio.sleep(duration)
            self.app.after(0, lambda v=old_val: var.set(v))
            self._temp_tasks.pop(var_name, None)

        self._temp_tasks[var_name] = asyncio.ensure_future(_restore())

    # Bot

    def _start_bot(self, settings: dict) -> None:
        try:
            from twitch.bot import TwitchBot
        except ImportError:
            return

        token   = settings.get("twitch_oauth_token", "")
        channel = settings.get("twitch_channel", "")
        if not token or not channel:
            return

        bot_loop       = asyncio.new_event_loop()
        self._bot_loop = bot_loop

        def _run_bot():
            asyncio.set_event_loop(bot_loop)
            bot = TwitchBot(token=token, channel=channel, manager=self)
            try:
                bot_loop.run_until_complete(bot.start())
            except Exception as exc:
                print(f"[Twitch bot] {exc}")
            finally:
                bot_loop.close()

        self._bot_thread = threading.Thread(
            target=_run_bot, daemon=True, name="twitch-bot")
        self._bot_thread.start()
