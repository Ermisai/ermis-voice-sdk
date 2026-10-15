"""Canal de controle de uma sessão: eventos chegando, comandos saindo."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from .errors import ConnectionClosedError, ErmisError, InvalidRequestError, from_close_code
from .events import Audio, BargeIn, Decision, ErrorEvent, Event, SessionEnded, SlotResult, SpeakDone, parse_event


@dataclass(frozen=True)
class CustomIntent:
    """Uma intenção do seu negócio para ``Call.decide()``."""

    key: str
    label: str
    description: str = ""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


_END = object()


class Call:
    """Uma ligação em andamento, vista pelo seu backend.

    Itere para receber eventos e use os métodos para mandar o agente agir::

        async with ermis.connect(session) as call:
            async for event in call:
                if isinstance(event, SessionStarted):
                    await call.speak("Olá! Como posso ajudar?", calibrate=True)

    A iteração termina depois de ``SessionEnded``. Se o canal fechar com erro,
    a iteração levanta a exceção correspondente (``InsufficientCreditsError``…).

    Respostas a ``decide()`` e ``extract_slot()`` são entregues como retorno
    desses métodos e não aparecem na iteração.
    """

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._events: asyncio.Queue[Any] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._speaking: dict[str, asyncio.Future[bool]] = {}
        self._reader: asyncio.Task[None] | None = None
        self.session_id: str | None = None
        self.ended: SessionEnded | None = None

    # ciclo de vida

    def _start(self) -> None:
        self._reader = asyncio.create_task(self._read())

    async def close(self) -> None:
        """Fecha o canal de controle. Não encerra a sessão: para isso use ``end()``."""
        await self._ws.close()
        if self._reader:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader

    async def __aenter__(self) -> Call:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # eventos

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        item = await self._events.get()
        if item is _END:
            self._events.put_nowait(_END)  # iterações seguintes também terminam
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            self._events.put_nowait(_END)
            raise item
        return item

    async def _read(self) -> None:
        error: ErmisError | None = None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    self._events.put_nowait(Audio("audio", {}, data=raw))
                    continue
                event = parse_event(json.loads(raw))
                if self._route(event):
                    continue
                self._events.put_nowait(event)
                if isinstance(event, SessionEnded):
                    self.ended = event
                    break
        except ConnectionClosed as exc:
            if self.ended is None:
                rcvd = exc.rcvd
                error = from_close_code(rcvd.code if rcvd else None, rcvd.reason if rcvd else "")
        finally:
            if self.ended is None and error is None:
                error = ConnectionClosedError("canal de controle fechado antes de session.ended")
            self._fail_pending(error or ConnectionClosedError("sessão encerrada"))
            if error is not None and self.ended is None:
                self._events.put_nowait(error)
            self._events.put_nowait(_END)

    def _route(self, event: Event) -> bool:
        """Entrega respostas a quem está esperando. Devolve True se o evento foi consumido."""
        if isinstance(event, Decision | SlotResult) and event.id in self._pending:
            fut = self._pending.pop(event.id)
            if not fut.done():
                fut.set_result(event)
            return True
        if isinstance(event, ErrorEvent):
            req_id = event.raw.get("id")
            if req_id in self._pending:
                fut = self._pending.pop(req_id)
                if not fut.done():
                    fut.set_exception(InvalidRequestError(event.message or "comando inválido", code=event.code))
                return True
        if isinstance(event, SpeakDone | BargeIn) and event.id in self._speaking:
            fut = self._speaking.pop(event.id)
            if not fut.done():
                fut.set_result(isinstance(event, SpeakDone))
        if event.type == "session.started":
            self.session_id = event.raw.get("session_id")
        return False

    def _fail_pending(self, error: ErmisError) -> None:
        for fut in [*self._pending.values(), *self._speaking.values()]:
            if not fut.done():
                fut.set_exception(error)
        self._pending.clear()
        self._speaking.clear()

    # comandos

    async def send(self, message: dict[str, Any]) -> None:
        """Envia uma mensagem crua do protocolo. Prefira os métodos abaixo."""
        await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def speak(
        self,
        text: str,
        *,
        id: str | None = None,
        voice: str | None = None,
        allow_barge_in: bool | None = None,
        calibrate: bool | None = None,
    ) -> str:
        """O agente fala ``text``. Devolve o ``id`` da fala na hora, sem esperar o áudio terminar.

        - ``calibrate=True`` na saudação: a Ermis mede o ruído de fundo enquanto o cliente escuta.
        - ``allow_barge_in=False`` para avisos que não podem ser interrompidos.
        """
        speak_id = id or _new_id("r")
        msg: dict[str, Any] = {"type": "speak", "id": speak_id, "text": text}
        for key, value in (("voice", voice), ("allow_barge_in", allow_barge_in), ("calibrate", calibrate)):
            if value is not None:
                msg[key] = value
        await self.send(msg)
        return speak_id

    async def say(self, text: str, **options: Any) -> bool:
        """Como ``speak()``, mas espera a fala acabar.

        Devolve ``True`` se o agente falou tudo e ``False`` se o cliente interrompeu.
        """
        speak_id = options.pop("id", None) or _new_id("r")
        done: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._speaking[speak_id] = done
        await self.speak(text, id=speak_id, **options)
        return await done

    async def interrupt(self) -> None:
        """Para a fala atual do agente."""
        await self.send({"type": "interrupt"})

    async def decide(
        self,
        text: str,
        *,
        custom_intents: list[CustomIntent | dict[str, Any]] | None = None,
        timeout: float = 10.0,
    ) -> Decision:
        """Pede uma decisão sobre ``text``, opcionalmente com intenções do seu negócio.

        Com ``auto_decide`` ligado você já recebe ``Decision`` para cada fala; use
        este método quando precisar das suas intenções (``custom_intent``).
        """
        msg: dict[str, Any] = {"type": "decide", "text": text}
        if custom_intents:
            msg["custom_intents"] = [asdict(i) if isinstance(i, CustomIntent) else i for i in custom_intents]
        return await self._request("d", msg, timeout)

    async def extract_slot(
        self,
        text: str,
        name: str,
        type: str = "text",
        *,
        description: str | None = None,
        timeout: float = 10.0,
    ) -> SlotResult:
        """Extrai um dado de ``text``: ``email``, ``phone``, ``cpf``, ``date``, ``name``…"""
        slot: dict[str, Any] = {"name": name, "type": type}
        if description:
            slot["description"] = description
        return await self._request("s", {"type": "extract_slot", "text": text, "slot": slot}, timeout)

    async def thinking(self, message: str | None = None, *, timeout_ms: int | None = None) -> None:
        """Avisa que a resposta vai demorar: o agente fala ``message`` agora e espera até ``timeout_ms``."""
        msg: dict[str, Any] = {"type": "thinking"}
        if message is not None:
            msg["message"] = message
        if timeout_ms is not None:
            msg["timeout_ms"] = timeout_ms
        await self.send(msg)

    async def done_processing(self) -> None:
        """Você decidiu não responder esta fala. O agente volta a ouvir."""
        await self.send({"type": "done_processing"})

    async def end(self) -> None:
        """Encerra a sessão. A cobrança para quando ``SessionEnded`` chegar."""
        await self.send({"type": "end"})

    # transporte "websocket": o áudio passa pelo mesmo socket

    async def send_audio(self, frame: bytes) -> None:
        """Envia 20 ms de áudio μ-law 8 kHz (160 bytes). Só no transporte ``websocket``."""
        await self._ws.send(frame)

    async def playback_finished(self, speak_id: str) -> None:
        """Avisa que o áudio de ``speak_id`` terminou de tocar do seu lado. Só no transporte ``websocket``."""
        await self.send({"type": "playback_finished", "id": speak_id})

    async def _request(self, prefix: str, msg: dict[str, Any], timeout: float) -> Any:
        if self.ended is not None:
            raise ConnectionClosedError("a sessão já terminou")
        req_id = _new_id(prefix)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self.send({**msg, "id": req_id})
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(req_id, None)
