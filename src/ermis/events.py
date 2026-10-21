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
    """O cliente final começou a falar. ``utterance_id`` é o mesmo dos parciais e da ``Transcript`` dessa fala."""

    utterance_id: str | None = None


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
    corrections: list[dict[str, Any]] = field(default_factory=list)
    """Palavras ajustadas ao ``vocabulary`` da sessão: ``{"heard", "term", "score"}``."""
    handled: bool = False
    """Com o ``guard`` da sessão: a Ermis já cuidou desta fala (ruído, ou pediu para repetir). Não responda."""


DRIFT_WORDS = 10  # a partir daqui, uma fala sem nada do negócio é divagação
_PLAIN_ANSWERS = ("confirm_yes", "confirm_no", "name_provide", "name_correction", "farewell", "thanks", "greeting")


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
    complexity: float
    custom_intent: str | None
    extracted: dict[str, Any]
    utterance_id: str | None = None
    id: str | None = None
    custom_intent_confidence: float | None = None
    """De 0 a 1: quanto a escolha de ``custom_intent`` é segura. Abaixo de 0,8 é um palpite (frase confusa)."""
    text: str = ""
    """O que o cliente disse (o ``Transcript`` da mesma fala; preenchido pelo ``Call``)."""
    answer: str | None = None
    """``"yes"``, ``"no"`` ou ``None``: o sim/não da fala como resposta à última pergunta do agente."""
    guidance: str | None = None
    """Decidido pela Ermis: ``"unclear"`` (fala confusa), ``"drifting"`` (divagação), ``"off_topic"`` ou ``None``."""
    handled: bool = False
    """Com o ``guard`` da sessão: a Ermis já respondeu esta fala (``guided_text``). Não responda."""
    guided_text: str | None = None
    choice: str | None = None
    """Com ``ask(..., choices=...)``: a resposta esperada que o cliente quis dizer, ou ``"none"``."""
    choice_confidence: float | None = None

    def chosen(self, min_confidence: float = 0.8) -> str | None:
        """A resposta esperada escolhida, quando a escolha é segura; ``None`` quando não é."""
        if not self.choice or self.choice == "none":
            return None
        confidence = 1.0 if self.choice_confidence is None else self.choice_confidence
        return self.choice if confidence >= min_confidence else None

    def business_intent(self, min_confidence: float = 0.8) -> str:
        """A sua intenção (``custom_intent``), ou ``"other"`` quando a escolha não é segura."""
        if not self.custom_intent:
            return "other"
        confidence = 1.0 if self.custom_intent_confidence is None else self.custom_intent_confidence
        return self.custom_intent if confidence >= min_confidence else "other"

    @property
    def _plain_answer(self) -> bool:
        # "sim", "não, só isso", um nome: respostas curtas. Uma frase longa lida como nome é divagação
        if self.intent in ("name_provide", "name_correction"):
            return len(self.text.split()) <= 5 if self.text else True
        # "Bom dia, tudo bem? Nossa, hoje tá um calor..." começa com um cumprimento, mas é divagação
        return self.intent in _PLAIN_ANSWERS and (not self.text or len(self.text.split()) < 10)

    @property
    def unclear(self) -> bool:
        if "guidance" in self.raw:
            return self.guidance == "unclear"
        return self._local_unclear

    @property
    def _local_unclear(self) -> bool:
        """Fala confusa (transcrição ruim, frase sem sentido): peça para repetir em vez de agir num palpite.

        A Ermis pediu esclarecimento (``action == "clarify"``) e nenhuma intenção sua veio segura. Respostas
        curtas válidas ("sim", "não, só isso", um nome) não contam.
        """
        return (
            self.action == "clarify"
            and not self.is_escape
            and self.business_intent() == "other"
            and not self._plain_answer
            and not self._local_drifting
        )

    @property
    def off_topic(self) -> bool:
        if "guidance" in self.raw:
            return self.guidance == "off_topic"
        return self._local_off_topic

    @property
    def _local_off_topic(self) -> bool:
        """Uma pergunta ou pedido claro sobre algo que não é do seu negócio ("vocês vendem celular?").

        Use depois de tentar ler o que a etapa espera: respostas de dados ("sexta-feira", "Rua 7") também
        chegam sem intenção do negócio e podem vir com este valor.
        """
        return (
            self.action != "clarify"
            and not self.is_escape
            and self.business_intent() == "other"
            and not self._plain_answer
            and self.intent in ("question_product", "question_service", "complex", "complaint")
        )

    @property
    def drifting(self) -> bool:
        if "guidance" in self.raw:
            return self.guidance == "drifting"
        return self._local_drifting

    @property
    def _local_drifting(self) -> bool:
        """O cliente está divagando: uma fala longa (10 palavras ou mais) sem nada do seu negócio.

        Reconheça em poucas palavras e volte à pergunta em que estava ("Tá bom! Voltando ao seu pedido: ...").
        Precisa do texto da fala (``text``, que o ``Call`` preenche).
        """
        return (
            not self.is_escape
            and self.business_intent() == "other"
            and not self._plain_answer
            and len(self.text.split()) >= DRIFT_WORDS
            and not (self.action != "clarify" and self.intent in ("question_product", "question_service"))
        )


@dataclass(frozen=True)
class SlotResult(Event):
    """Resposta de ``call.extract_slot()``."""

    id: str
    value: Any
    status: str
    """``found``, ``not_found`` ou ``rejected`` (a fala não responde ao que foi pedido)."""
    revised: bool = False
    """Com prioridade de latência: o valor relido pelo reconhecimento de maior precisão, diferente do primeiro."""

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
    credits: float | None
    balance: float | None


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
    credits: float | None


@dataclass(frozen=True)
class Audio(Event):
    """Quadro de áudio do agente (só no transporte ``websocket``)."""

    data: bytes


@dataclass(frozen=True)
class TranscriptRevised(Event):
    """A leitura de maior precisão de uma fala (pedida com ``expect_slot``) ficou diferente da rápida."""

    utterance_id: str
    text: str
    previous: str


@dataclass(frozen=True)
class TranscriptPartial(Event):
    """O texto até agora, enquanto o cliente ainda fala (sessão com ``partial_transcripts``). Pode mudar."""

    utterance_id: str | None
    text: str


@dataclass(frozen=True)
class NoiseCalibrated(Event):
    """Terminou a medição do ruído de fundo (fala com ``calibrate``, normalmente a saudação).

    ``noisy``: alto demais para entender bem o cliente; com o ``guard`` ``too_noisy``, a Ermis avisa e encerra.
    """

    noise_level: float | None
    noise_floor: float | None
    samples: int
    noisy: bool


@dataclass(frozen=True)
class NoReply(Event):
    """O cliente ficou calado depois da fala do agente (``guard`` da sessão, ``no_reply_ms``).

    ``handled``: a Ermis já perguntou se ele está aí (``guided_text``) ou já se despediu; não responda. Com
    ``"on_no_reply": "notify"``, o último silêncio chega com ``handled=False``: você decide (transferir, encerrar).
    """

    count: int
    handled: bool = False
    guided_text: str | None = None


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
        return SpeechStarted(t, msg, utterance_id=g("utterance_id"))
    if t == "transcript.partial":
        return TranscriptPartial(t, msg, utterance_id=g("utterance_id"), text=g("text") or "")
    if t == "noise.calibrated":
        return NoiseCalibrated(
            t,
            msg,
            noise_level=g("noise_level"),
            noise_floor=g("noise_floor"),
            samples=int(g("samples") or 0),
            noisy=bool(g("noisy")),
        )
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
            corrections=list(g("corrections") or []),
            handled=bool(g("handled")),
        )
    if t == "decision":
        return Decision(
            t,
            msg,
            intent=g("intent", "unclear"),
            action=g("action", "escalate"),
            is_escape=bool(g("is_escape")),
            complexity=float(g("complexity") or 0),
            custom_intent=g("custom_intent"),
            extracted=g("extracted") or {},
            utterance_id=g("utterance_id"),
            id=g("id"),
            custom_intent_confidence=g("custom_intent_confidence"),
            answer=g("answer"),
            guidance=g("guidance"),
            handled=bool(g("handled")),
            guided_text=g("guided_text"),
            choice=g("choice"),
            choice_confidence=g("choice_confidence"),
        )
    if t == "slot":
        return SlotResult(
            t, msg, id=g("id", ""), value=g("value"), status=g("status", "not_found"), revised=bool(g("revised"))
        )
    if t == "no_reply":
        return NoReply(t, msg, count=int(g("count") or 0), handled=bool(g("handled")), guided_text=g("guided_text"))
    if t == "transcript.revised":
        return TranscriptRevised(
            t, msg, utterance_id=g("utterance_id", ""), text=g("text") or "", previous=g("previous") or ""
        )
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
        return Usage(t, msg, billed_seconds=int(g("billed_seconds") or 0), credits=g("credits"), balance=g("balance"))
    if t == "warning":
        return WarningEvent(t, msg, code=g("code", ""), message=g("message"))
    if t == "error":
        return ErrorEvent(t, msg, code=g("code"), message=g("message"))
    if t == "session.ended":
        return SessionEnded(t, msg, reason=g("reason"), billed_seconds=g("billed_seconds"), credits=g("credits"))
    return UnknownEvent(t, msg)
