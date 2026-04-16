from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands, pubsub

if TYPE_CHECKING:
    from twitch.manager import TwitchManager

_SPEAK_TITLES = {"tts", "lire tts", "dire", "text to speech", "parler"}
_VOICE_TITLES = {"voix tts", "changer voix", "voice tts"}
_PITCH_TITLES = {"pitch tts", "changer pitch"}

# Maximum TTS text length accepted from channel-point redemptions
_MAX_TEXT_LEN = 300


class TwitchBot(commands.Bot):

    def __init__(self, token: str, channel: str, manager: "TwitchManager") -> None:
        super().__init__(
            token=token.removeprefix("oauth:"),
            prefix="!",
            initial_channels=[channel],
        )
        self._channel = channel
        self._manager = manager
        self._pubsub  = pubsub.PubSubPool(self)

    async def event_ready(self) -> None:
        print(f"[Twitch bot] Connected as {self.nick} — #{self._channel}")
        try:
            users = await self.fetch_users(names=[self._channel])
            if users:
                topics = [pubsub.channel_points(self._http.token)[users[0].id]]
                await self._pubsub.subscribe_topics(topics)
        except Exception as exc:
            print(f"[Twitch bot] PubSub subscribe error: {exc}")

    async def event_pubsub_channel_points(
        self, event: pubsub.PubSubChannelPointsMessage
    ) -> None:
        title = event.reward.title.strip().lower()
        text  = (event.input or "").strip()[:_MAX_TEXT_LEN]

        if title in _SPEAK_TITLES:
            if text:
                await self._manager.enqueue_speak(text)

        elif title in _VOICE_TITLES:
            if text:
                # Empty TTS text — voice change only, no speech
                await self._manager.enqueue_speak(
                    text="",
                    voice=text,
                    duration=self._manager.temp_duration,
                )

        elif title in _PITCH_TITLES:
            try:
                await self._manager.apply_temp(
                    "pitch_var", int(text), self._manager.temp_duration)
            except (ValueError, TypeError):
                print(f"[Twitch bot] Invalid pitch value: {text!r}")

    async def event_error(self, error: Exception, data: str = None) -> None:
        print(f"[Twitch bot] Error: {error}")
