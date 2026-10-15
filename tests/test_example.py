"""Roda examples/atendente_twilio.py contra a Voice API simulada."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

pytest.importorskip("fastapi")
pytest.importorskip("multipart")


def _load_example(monkeypatch):
    monkeypatch.setenv("ERMIS_API_KEY", "ek_test_123")
    path = Path(__file__).parents[1] / "examples" / "atendente_twilio.py"
    spec = importlib.util.spec_from_file_location("atendente_twilio_sdk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _t(uid, text, **assessment):
    return {"type": "transcript", "utterance_id": uid, "text": text, "assessment": assessment}


def _d(uid, intent, action, **extra):
    return {"type": "decision", "utterance_id": uid, "intent": intent, "action": action, **extra}


async def test_example_conversation(monkeypatch):
    exemplo = _load_example(monkeypatch)
    script = [
        ({"type": "session.started", "session_id": "vs_1"}, 1),
        (_t("u1", "bom dia"), 0),
        (_d("u1", "greeting", "respond"), 1),
        (_t("u2", "", ignore=True), 1),
        (_t("u3", "meu pedido não chegou"), 0),
        (_d("u3", "complaint", "escalate", complexity=2), 2),
        (_t("u4", "tchau"), 0),
        (_d("u4", "farewell", "respond", is_escape=True), 1),
        ({"type": "speak.done", "id": "x"}, 1),
        ({"type": "session.ended", "reason": "ended_by_client"}, 0),
    ]
    received: list[dict] = []

    async def handler(ws):
        for event, expected in script:
            await ws.send(json.dumps(event))
            for _ in range(expected):
                received.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=2)))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with exemplo.ermis.connect(f"ws://127.0.0.1:{port}/control") as call:
            await asyncio.wait_for(exemplo.conduzir(call), timeout=5)

    types = [m["type"] for m in received]
    assert types == ["speak", "speak", "done_processing", "thinking", "speak", "speak", "end"]
    assert received[0]["text"] == exemplo.SAUDACAO and received[0]["calibrate"] is True
    assert received[1]["text"] == exemplo.RESPOSTAS_RAPIDAS["greeting"]
    assert received[3]["timeout_ms"] == 45000
    assert received[5]["text"] == exemplo.DESPEDIDA
