"""Eventos que a Ermis envia pelo canal de controle.

Cada mensagem JSON vira uma dataclass. Campos novos que a API passar a enviar
continuam acessíveis em ``event.raw``, e tipos desconhecidos chegam como
``UnknownEvent``, então uma versão antiga do SDK não quebra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    raw: dict[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class SessionStarted(Event):
    """O áudio conectou. Bom momento para a saudação."""

    session_id: str
    limits: dict[str, Any]


@dataclass(frozen=True)
class SpeechStarted(Event):
    """O cliente final começou a falar."""


@dataclass(frozen=True)
class SpeechEnded(Event):
    """O cliente final parou de falar."""

    duration_ms: int | None


@dataclass(frozen=True)
class Assessment:
    """Se vale a pena agir sobre a fala transcrita."""

    ignore: bool = False
    """Foi ruído. Não responda; chame ``call.done_processing()``."""
    ask_to_repeat: bool = False
    """Houve fala, mas não deu para entender."""
    unproductive: bool = False
    """"alô alô", "teste", palavra repetida."""
    confirm: bool = False
    """A transcrição é incerta: confirme antes de agir."""

    @property
    def usable(self) -> bool:
        """``True`` quando a fala pode ser respondida normalmente (talvez com confirmação)."""
        return not (self.ignore or self.ask_to_repeat or self.unproductive)


@dataclass(frozen=True)
class Transcript(Event):
    """O que o cliente final falou."""

    utterance_id: str
    text: str
    uncertain: bool
    assessment: Assessment
    latency_ms: int | None


@dataclass(frozen=True)
class Decision(Event):
    """O que o cliente final quer.

    Chega sozinho com ``auto_decide`` (``utterance_id`` preenchido) ou como
    resposta de ``call.decide()`` (``id`` preenchido).
    """

    intent: str
    action: str
    """``respond`` (frase pronta resolve), ``escalate`` (sua IA ou um humano) ou ``clarify``."""
    is_escape: bool
    complexity: int
    custom_intent: str | None
    extracted: dict[str, Any]
    utterance_id: str | None = None
    id: str | None = None


@dataclass(frozen=True)
class SlotResult(Event):
    """Resposta de ``call.extract_slot()``."""

    id: str
    value: Any
    status: str
    """``found``, ``not_found`` ou ``rejected`` (a fala não responde ao que foi pedido)."""

    @property
    def found(self) -> bool:
        return self.status == "found"


@dataclass(frozen=True)
class SpeakStarted(Event):
    id: str
    chars: int | None


@dataclass(frozen=True)
class SpeakDone(Event):
    """O agente terminou de falar ``id``."""

    id: str
    chars: int | None


@dataclass(frozen=True)
class BargeIn(Event):
    """O cliente final interrompeu a fala ``id``."""

    id: str | None


@dataclass(frozen=True)
class WaitingSpoken(Event):
    """A Ermis falou uma mensagem de espera enquanto a sua IA pensava."""

    utterance_id: str | None
    kind: str
    """``filler``, ``patience`` ou ``timeout``."""
    text: str


@dataclass(frozen=True)
class ReplyTimeout(Event):
    """A sua resposta não chegou a tempo. Um ``speak`` atrasado será descartado."""

    utterance_id: str | None
    action: str


@dataclass(frozen=True)
class Usage(Event):
    """Uso acumulado, a cada 60 s."""

    billed_seconds: int
    credits: int
    balance: int | None


@dataclass(frozen=True)
class WarningEvent(Event):
    """``credits_low``, ``noisy_environment``, ``max_duration_soon`` ou ``late_reply``."""

    code: str
    message: str | None


@dataclass(frozen=True)
class ErrorEvent(Event):
    """Erro que não encerrou a sessão (por exemplo, um comando inválido)."""

    code: str | int | None
    message: str | None


@dataclass(frozen=True)
class SessionEnded(Event):
    """Fim da sessão. É o último evento; a iteração termina depois dele."""

    reason: str | None
    billed_seconds: int | None
    credits: int | None


@dataclass(frozen=True)
class Audio(Event):
    """Quadro de áudio do agente (só no transporte ``websocket``)."""

    data: bytes


@dataclass(frozen=True)
class UnknownEvent(Event):
    """Evento que esta versão do SDK ainda não conhece. Veja ``raw``."""


def parse_event(msg: dict[str, Any]) -> Event:
    """Converte uma mensagem JSON do canal de controle no evento correspondente."""
    t = str(msg.get("type", ""))
    g = msg.get
    if t == "session.started":
        return SessionStarted(t, msg, session_id=g("session_id", ""), limits=g("limits") or {})
    if t == "speech.started":
        return SpeechStarted(t, msg)
    if t == "speech.ended":
        return SpeechEnded(t, msg, duration_ms=g("duration_ms"))
    if t == "transcript":
        a = g("assessment") or {}
        assessment = Assessment(
            ignore=bool(a.get("ignore")),
            ask_to_repeat=bool(a.get("ask_to_repeat")),
            unproductive=bool(a.get("unproductive")),
            confirm=bool(a.get("confirm")),
        )
        return Transcript(
            t,
            msg,
            utterance_id=g("utterance_id", ""),
            text=g("text") or "",
            uncertain=bool(g("uncertain")),
            assessment=assessment,
            latency_ms=g("latency_ms"),
        )
    if t == "decision":
        return Decision(
            t,
            msg,
            intent=g("intent", "unclear"),
            action=g("action", "escalate"),
            is_escape=bool(g("is_escape")),
            complexity=int(g("complexity") or 0),
            custom_intent=g("custom_intent"),
            extracted=g("extracted") or {},
            utterance_id=g("utterance_id"),
            id=g("id"),
        )
    if t == "slot":
        return SlotResult(t, msg, id=g("id", ""), value=g("value"), status=g("status", "not_found"))
    if t == "speak.started":
        return SpeakStarted(t, msg, id=g("id", ""), chars=g("chars"))
    if t == "speak.done":
        return SpeakDone(t, msg, id=g("id", ""), chars=g("chars"))
    if t == "barge_in":
        return BargeIn(t, msg, id=g("id"))
    if t == "waiting":
        return WaitingSpoken(t, msg, utterance_id=g("utterance_id"), kind=g("kind", ""), text=g("text") or "")
    if t == "reply_timeout":
        return ReplyTimeout(t, msg, utterance_id=g("utterance_id"), action=g("action", ""))
    if t == "usage":
        return Usage(
            t, msg, billed_seconds=int(g("billed_seconds") or 0), credits=int(g("credits") or 0), balance=g("balance")
        )
    if t == "warning":
        return WarningEvent(t, msg, code=g("code", ""), message=g("message"))
    if t == "error":
        return ErrorEvent(t, msg, code=g("code"), message=g("message"))
    if t == "session.ended":
        return SessionEnded(t, msg, reason=g("reason"), billed_seconds=g("billed_seconds"), credits=g("credits"))
    return UnknownEvent(t, msg)
