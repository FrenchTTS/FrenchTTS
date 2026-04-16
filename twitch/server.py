from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from aiohttp import web

from core.constants import VOICES

if TYPE_CHECKING:
    from twitch.manager import TwitchManager

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def build_app(manager: "TwitchManager") -> web.Application:
    app = web.Application()
    app["manager"] = manager
    app.router.add_get("/",           _handle_overlay)
    app.router.add_get("/callback",   _handle_callback)
    app.router.add_get("/ws",         _handle_ws)
    app.router.add_post("/api/speak", _handle_speak)
    app.router.add_post("/api/voice", _handle_voice)
    app.router.add_post("/api/pitch", _handle_pitch)
    app.router.add_get("/api/status", _handle_status)
    return app


async def _handle_overlay(request: web.Request) -> web.Response:
    return _serve_static("overlay.html")


async def _handle_callback(request: web.Request) -> web.Response:
    # OAuth redirect landing page — JS reads access_token from the URL hash
    return _serve_static("callback.html")


def _serve_static(filename: str) -> web.Response:
    path = os.path.join(_STATIC_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    except FileNotFoundError:
        return web.Response(status=404, text=f"{filename} not found")


async def _handle_ws(request: web.Request) -> web.WebSocketResponse:
    manager: TwitchManager = request.app["manager"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    manager.ws_clients.add(ws)
    try:
        # Push appearance config immediately so the overlay is styled before first TTS
        await ws.send_str(json.dumps(manager.get_overlay_config()))
        async for _ in ws:
            pass
    finally:
        manager.ws_clients.discard(ws)
    return ws


async def _handle_speak(request: web.Request) -> web.Response:
    manager: TwitchManager = request.app["manager"]
    if not manager.feat_speak():
        return web.Response(status=403, text="speak feature is disabled")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    text = str(data.get("text", "")).strip()
    if not text:
        return web.Response(status=400, text="'text' is required")

    await manager.enqueue_speak(
        text,
        voice=data.get("voice"),
        pitch=data.get("pitch"),
        duration=data.get("duration"),
    )
    return web.Response(status=200, text="ok")


async def _handle_voice(request: web.Request) -> web.Response:
    manager: TwitchManager = request.app["manager"]
    if not manager.feat_voice():
        return web.Response(status=403, text="voice feature is disabled")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    voice = str(data.get("voice", "")).strip()
    if not voice:
        return web.Response(status=400, text="'voice' is required")

    if voice not in VOICES:
        return web.Response(
            status=400,
            text=f"Unknown voice '{voice}'. Valid: {', '.join(VOICES.keys())}")

    duration = int(data.get("duration", manager.temp_duration))
    await manager.apply_temp("voice_var", voice, duration)
    return web.Response(status=200, text="ok")


async def _handle_pitch(request: web.Request) -> web.Response:
    manager: TwitchManager = request.app["manager"]
    if not manager.feat_pitch():
        return web.Response(status=403, text="pitch feature is disabled")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    try:
        pitch = int(data["pitch"])
    except (KeyError, ValueError, TypeError):
        return web.Response(status=400, text="'pitch' must be an integer")

    pitch    = max(-100, min(100, pitch))
    duration = int(data.get("duration", manager.temp_duration))
    await manager.apply_temp("pitch_var", pitch, duration)
    return web.Response(status=200, text="ok")


async def _handle_status(request: web.Request) -> web.Response:
    manager: TwitchManager = request.app["manager"]
    app = manager.app
    return web.Response(
        text=json.dumps({
            "speaking": app._tts_busy.is_set(),
            "voice":    app.voice_var.get(),
            "pitch":    app.pitch_var.get(),
            "port":     manager.port,
        }),
        content_type="application/json",
    )
