"""Testes do SDK contra uma Ermis Voice API simulada.

O REST é simulado com ``httpx.MockTransport`` e o canal de controle com um
servidor WebSocket local que fala o protocolo público.
"""

from __future__ import annotations

import asyncio
import json
from xml.etree import ElementTree

import httpx
import pytest
from websockets.asyncio.server import serve

from ermis import (
    AuthenticationError,
    BargeIn,
    ChannelLimitError,
    CustomIntent,
    Decision,
    Ermis,
    InsufficientCreditsError,
    InvalidRequestError,
    RateLimitError,
    SessionEnded,
    SessionStarted,
    Transcript,
    UnknownEvent,
    Voice,
    WaitingOptions,
    parse_event,
)

SESSION = {
    "session_id": "vs_1",
    "audio_url": "wss://api.ermis.ai/v1/voice/twilio",
    "control_url": "wss://api.ermis.ai/v1/voice/sessions/vs_1/control",
    "session_token": 'st_a"<&',
}


def _client(handler) -> Ermis:
    http = httpx.AsyncClient(base_url="https://api.ermis.ai", transport=httpx.MockTransport(handler))
    return Ermis("ek_test_123", http_client=http)


# REST


async def test_create_session_sends_only_given_fields():
    seen: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=SESSION)

    ermis = _client(api)
    session = await ermis.sessions.create(
        transport="twilio",
        voice="woman",
        waiting=WaitingOptions(timeout_ms=25000, filler_after_ms=None),
        metadata={"call_sid": "CA1"},
    )

    assert session.session_id == "vs_1"
    assert seen[0].headers["authorization"] == "Bearer ek_test_123"
    assert seen[0].url.path == "/v1/voice/sessions"
    assert json.loads(seen[0].content) == {
        "transport": "twilio",
        "voice": "woman",
        "waiting": {"filler_after_ms": None, "timeout_ms": 25000},
        "metadata": {"call_sid": "CA1"},
    }
    assert ermis.sandbox


async def test_session_turn_options_and_custom_intents():
    seen: list[dict] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(201, json=SESSION)

    ermis = _client(api)
    await ermis.sessions.create(
        transcription_priority="local_first",
        turn_detection="smart_turn",
        early_turn={"speculate": True, "close_on_complete_text": True},
        custom_intents=[CustomIntent("pedir_pizza", "Pede pizza", "tamanho e sabor"), {"key": "outro_assunto"}],
        vocabulary=["margherita", "calabresa"],
    )
    assert seen[0] == {
        "transcription_priority": "local_first",
        "turn_detection": "smart_turn",
        "early_turn": {"speculate": True, "close_on_complete_text": True},
        "custom_intents": [
            {"key": "pedir_pizza", "label": "Pede pizza", "description": "tamanho e sabor"},
            {"key": "outro_assunto"},
        ],
        "vocabulary": ["margherita", "calabresa"],
    }


async def test_twiml_is_valid_xml_with_escaped_token():
    ermis = _client(lambda r: httpx.Response(201, json=SESSION))
    session = await ermis.sessions.create(transport="twilio")
    stream = ElementTree.fromstring(session.twiml()).find("./Connect/Stream")
    assert stream.get("url") == SESSION["audio_url"]
    assert stream.find("Parameter").attrib == {"name": "session_token", "value": 'st_a"<&'}
    assert set(session.browser_credentials()) == {"audio_url", "session_token"}


@pytest.mark.parametrize(
    ("status", "exc"),
    [(401, AuthenticationError), (402, InsufficientCreditsError), (429, ChannelLimitError), (400, InvalidRequestError)],
)
async def test_http_errors_map_to_exceptions(status, exc):
    ermis = _client(lambda r: httpx.Response(status, json={"message": "nope"}))
    with pytest.raises(exc) as info:
        await ermis.sessions.create()
    assert info.value.status == status and info.value.message == "nope"


async def test_usage_and_balance():
    def api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/usage":
            assert dict(request.url.params) == {"limit": "25", "before": "123"}
            return httpx.Response(200, json={"account_id": 42, "unit": "credit", "entries": [], "next_cursor": None})
        return httpx.Response(
            200,
            json={
                "account_id": 42,
                "unit": "credit",
                "balance": 1000,
                "reserved_credits": 100,
                "available_credits": 900,
            },
        )

    ermis = _client(api)
    assert (await ermis.usage(limit=25, before=123))["entries"] == []
    assert (await ermis.balance())["available_credits"] == 900


async def test_list_voices_and_use_one():
    sent = []

    def api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/voice/voices":
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {"id": "man", "name": "Masculina", "gender": "male", "production": True, "default": True},
                        {"id": "demo", "name": "Demo", "production": False},
                    ],
                    "default": "man",
                },
            )
        sent.append(json.loads(request.content))
        return httpx.Response(201, json=SESSION)

    ermis = _client(api)
    voices = await ermis.voices.list()
    assert voices[0] == Voice(id="man", name="Masculina", gender="male", default=True)
    assert [v.id for v in voices if v.production] == ["man"]
    await ermis.sessions.create(voice=voices[1].id)
    assert sent == [{"voice": "demo"}]


async def test_usage_default_pagination():
    def api(request):
        assert dict(request.url.params) == {"limit": "50"}
        return httpx.Response(200, json={"entries": [], "next_cursor": None})

    assert (await _client(api).usage())["next_cursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"before": 0}, {"before": "1"}])
async def test_usage_rejects_invalid_pagination(params):
    def api(request):
        raise AssertionError("invalid pagination must not make a request")

    with pytest.raises(InvalidRequestError):
        await _client(api).usage(**params)


async def test_rate_limit_and_gateway_trace_are_exposed():
    ermis = _client(
        lambda req: httpx.Response(
            429, headers={"X-Request-Id": "trace-123"}, json={"error": "rate_limited", "message": "Tente novamente"}
        )
    )
    with pytest.raises(RateLimitError) as failure:
        await ermis.sessions.create()
    assert failure.value.code == "rate_limited" and failure.value.request_id == "trace-123"


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("ERMIS_API_KEY", raising=False)
    with pytest.raises(AuthenticationError):
        Ermis()


# Eventos


def test_parse_events():
    usage = parse_event({"type": "usage", "billed_seconds": 10, "credits": 1.25, "balance": 9.75})
    assert usage.credits == 1.25 and usage.balance == 9.75
    pending = parse_event({"type": "usage", "billed_seconds": 10, "credits": None})
    assert pending.credits is None
    t = parse_event(
        {"type": "transcript", "utterance_id": "u1", "text": "oi", "assessment": {"confirm": True}, "latency_ms": 90}
    )
    assert isinstance(t, Transcript) and t.assessment.confirm and t.assessment.usable
    d = parse_event({"type": "decision", "utterance_id": "u1", "intent": "greeting", "action": "respond"})
    assert isinstance(d, Decision) and d.intent == "greeting" and d.complexity == 0
    u = parse_event({"type": "novidade", "x": 1})
    assert isinstance(u, UnknownEvent) and u.raw["x"] == 1


# Canal de controle


async def _with_server(handler, body):
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ermis = Ermis("ek_test_123", base_url="http://unused")
        url = f"ws://127.0.0.1:{port}/v1/voice/sessions/vs_1/control"
        return await asyncio.wait_for(body(ermis, url), timeout=5)


async def test_conversation_with_decide_and_slot():
    received: list[dict] = []
    headers: dict[str, str] = {}

    async def handler(ws):
        headers.update(dict(ws.request.headers))
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        received.append(json.loads(await ws.recv()))  # speak (saudação)
        await ws.send(json.dumps({"type": "transcript", "utterance_id": "u1", "text": "segunda via", "assessment": {}}))

        decide = json.loads(await ws.recv())
        received.append(decide)
        await ws.send(json.dumps({"type": "speech.started"}))  # evento comum no meio da resposta
        await ws.send(
            json.dumps(
                {
                    "type": "decision",
                    "id": decide["id"],
                    "intent": "question_service",
                    "action": "escalate",
                    "custom_intent": "segunda_via",
                }
            )
        )
        slot = json.loads(await ws.recv())
        received.append(slot)
        await ws.send(json.dumps({"type": "slot", "id": slot["id"], "value": "ana@gmail.com", "status": "found"}))

        received.append(json.loads(await ws.recv()))  # end
        await ws.send(json.dumps({"type": "session.ended", "reason": "ended_by_client", "billed_seconds": 30}))

    async def body(ermis, url):
        seen = []
        async with ermis.connect(url) as call:
            async for event in call:
                seen.append(event)
                if isinstance(event, SessionStarted):
                    await call.speak("Olá!", calibrate=True, allow_barge_in=False)
                elif isinstance(event, Transcript):
                    decision = await call.decide(
                        event.text, custom_intents=[CustomIntent("segunda_via", "Segunda via", "Boleto")]
                    )
                    assert decision.custom_intent == "segunda_via"
                    slot = await call.extract_slot("ana arroba gmail ponto com", "email", "email")
                    assert slot.found and slot.value == "ana@gmail.com"
                    await call.end()
            assert call.session_id == "vs_1"
            assert isinstance(call.ended, SessionEnded) and call.ended.billed_seconds == 30
        return seen

    seen = await _with_server(handler, body)

    assert headers["authorization"] == "Bearer ek_test_123"
    speak, decide, slot, end = received
    assert speak["type"] == "speak" and speak["calibrate"] is True and speak["allow_barge_in"] is False
    assert decide["type"] == "decide" and decide["custom_intents"][0]["key"] == "segunda_via"
    assert slot["slot"] == {"name": "email", "type": "email"}
    assert end == {"type": "end"}
    # respostas de decide/extract_slot não aparecem na iteração
    assert [e.type for e in seen] == ["session.started", "transcript", "speech.started", "session.ended"]


async def test_say_reports_barge_in():
    async def handler(ws):
        first = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "speak.done", "id": first["id"], "chars": 5}))
        second = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "barge_in", "id": second["id"]}))
        await ws.send(json.dumps({"type": "session.ended", "reason": "x"}))

    async def body(ermis, url):
        async with ermis.connect(url) as call:
            completed = await call.say("Olá!")
            interrupted = await call.say("Uma frase longa…")
            events = [e async for e in call]
        return completed, interrupted, events

    completed, interrupted, events = await _with_server(handler, body)
    assert completed is True and interrupted is False
    assert isinstance(events[1], BargeIn) and events[-1].type == "session.ended"


async def test_close_code_raises_mapped_error():
    async def handler(ws):
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        await ws.close(code=4002, reason="sem créditos")

    async def body(ermis, url):
        async with ermis.connect(url) as call:
            with pytest.raises(InsufficientCreditsError) as info:
                async for _ in call:
                    pass
        return info.value

    err = await _with_server(handler, body)
    assert err.code == 4002 and "créditos" in err.message


async def test_handshake_rejected():
    async def handler(ws):
        pass

    def reject(connection, request):
        return connection.respond(401, "invalid key\n")

    async with serve(handler, "127.0.0.1", 0, process_request=reject) as server:
        port = server.sockets[0].getsockname()[1]
        ermis = Ermis("ek_test_bad", base_url="http://unused")
        with pytest.raises(AuthenticationError):
            async with ermis.connect(f"ws://127.0.0.1:{port}/x"):
                pass


def test_transcription_priority_option():
    from ermis.options import session_body

    assert session_body(transcription_priority="latency") == {"transcription_priority": "latency"}
    assert "transcription_priority" not in session_body()


def test_waiting_options_new_fields():
    from ermis import WaitingOptions

    opts = WaitingOptions(filler_by_intent={"complaint": ["Sinto muito."]}, gap_after_ms=None)
    assert opts.to_dict() == {"filler_by_intent": {"complaint": ["Sinto muito."]}, "gap_after_ms": None}


async def test_set_custom_intents_command():
    received: list[dict] = []

    async def handler(ws):
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        received.append(json.loads(await ws.recv()))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "session.ended", "reason": "client", "billed_seconds": 1}))

    async def body(ermis, url):
        async with ermis.connect(url) as call:
            async for event in call:
                if isinstance(event, SessionStarted):
                    await call.set_custom_intents([CustomIntent("financeiro", "Financeiro")])
                    await call.set_custom_intents([])

    await _with_server(handler, body)
    assert received == [
        {
            "type": "set_custom_intents",
            "custom_intents": [{"key": "financeiro", "label": "Financeiro", "description": ""}],
        },
        {"type": "set_custom_intents", "custom_intents": []},
    ]


async def test_speech_is_normalized_unless_turned_off():
    received: list[dict] = []

    async def handler(ws):
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        for _ in range(4):
            received.append(json.loads(await ws.recv()))
        await ws.send(
            json.dumps(
                {
                    "type": "transcript",
                    "utterance_id": "u1",
                    "text": "uma margherita",
                    "assessment": {},
                    "corrections": [{"heard": "marquerita", "term": "margherita", "score": 0.89}],
                }
            )
        )
        await ws.send(json.dumps({"type": "session.ended", "reason": "client", "billed_seconds": 1}))

    async def body(ermis, url):
        seen = []
        async with ermis.connect(url) as call:
            async for event in call:
                seen.append(event)
                if isinstance(event, SessionStarted):
                    await call.speak("**Fica R$ 49,90** 🍕")
                    await call.speak("R$ 49,90", normalize=False)
                    await call.set_vocabulary(["margherita"])
                    call.normalize_text = False
                    await call.speak("2 pizzas")
        return seen

    seen = await _with_server(handler, body)
    assert received[0]["text"] == "Fica quarenta e nove reais e noventa centavos"
    assert received[1]["text"] == "R$ 49,90"
    assert received[2] == {"type": "set_vocabulary", "vocabulary": ["margherita"]}
    assert received[3]["text"] == "2 pizzas"
    transcript = next(e for e in seen if isinstance(e, Transcript))
    assert transcript.corrections == [{"heard": "marquerita", "term": "margherita", "score": 0.89}]
