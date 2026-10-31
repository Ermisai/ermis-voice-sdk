"""Opções de criação de sessão (corpo de ``POST /v1/voice/sessions``).

Todos os campos são opcionais: o que ficar ``UNSET`` não é enviado e a Ermis
usa o padrão documentado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Literal


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Any = _Unset()
"""Marca um campo não informado (diferente de ``None``, que desliga o recurso)."""


def _compact(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(obj):
        value = getattr(obj, f.name)
        if value is UNSET:
            continue
        out[f.name] = list(value) if isinstance(value, tuple) else value
    return out


@dataclass(frozen=True)
class WaitingOptions:
    """O que o cliente final ouve enquanto a sua IA prepara a resposta.

    A Ermis fala essas frases sozinha. ``None`` em ``filler_after_ms``,
    ``patience_after_ms`` ou ``timeout_ms`` desliga aquela etapa.
    """

    filler_after_ms: int | None = UNSET
    filler_messages: list[str] | tuple[str, ...] = UNSET
    filler_by_intent: dict[str, list[str]] = UNSET
    """Frases de espera por intenção (``complaint``, ``question_service``…); ``{}`` desliga."""
    gap_after_ms: int | None = UNSET
    """Silêncio entre a frase de espera e a sua resposta (padrão 600 ms); ``None`` desliga."""
    patience_after_ms: int | None = UNSET
    patience_every_ms: int = UNSET
    patience_messages: list[str] | tuple[str, ...] = UNSET
    timeout_ms: int | None = UNSET
    timeout_message: str = UNSET
    timeout_action: Literal["apologize", "end"] = UNSET

    def to_dict(self) -> dict[str, Any]:
        return _compact(self)


@dataclass(frozen=True)
class BargeInOptions:
    """Interrupção do agente pelo cliente final."""

    enabled: bool = UNSET
    min_speech_ms: int = UNSET

    def to_dict(self) -> dict[str, Any]:
        return _compact(self)


@dataclass(frozen=True)
class VadOptions:
    """Detecção de fim de fala."""

    min_silence_ms: int = UNSET

    def to_dict(self) -> dict[str, Any]:
        return _compact(self)


Transport = Literal["twilio", "browser", "websocket"]
AudioFormat = Literal["mulaw_8k", "pcm16_48k"]
EndOfTurn = Literal["fast", "balanced", "patient"]
"""Quanto a Ermis espera depois que o cliente para de falar, antes de responder (``end_of_turn``).

Troca latência por acurácia; medido em fala humana ao telefone (português, 8 kHz):

- ``"fast"`` (padrão): 0,43 s em média até o fim do turno; 42% das pausas de quem ia continuar viram fim de turno.
- ``"balanced"``: **+0,16 s em todo turno** (0,60 s); 23% das pausas.
- ``"patient"``: **+0,37 s em todo turno** (0,80 s); 9% das pausas.

Os campos ``vad`` e ``early_turn`` que você mandar ganham do perfil.
"""


def session_body(
    *,
    transport: Transport | Any = UNSET,
    audio_format: AudioFormat | Any = UNSET,
    language: str = UNSET,
    voice: str = UNSET,
    auto_decide: bool = UNSET,
    partial_transcripts: bool = UNSET,
    transcription_priority: Literal["balanced", "latency", "accuracy", "local_first", "local_only"] = UNSET,
    precise_wait_ms: int = UNSET,
    turn_detection: Literal["smart_turn", "silence"] = UNSET,
    end_of_turn: EndOfTurn = UNSET,
    ask_again_on_ambiguous_stt: bool | None = UNSET,
    early_turn: dict[str, Any] = UNSET,
    custom_intents: list[Any] = UNSET,
    vocabulary: list[str] = UNSET,
    guard: dict[str, Any] = UNSET,
    vad: VadOptions | dict[str, Any] = UNSET,
    barge_in: BargeInOptions | dict[str, Any] = UNSET,
    waiting: WaitingOptions | dict[str, Any] = UNSET,
    max_duration_s: int = UNSET,
    metadata: dict[str, Any] = UNSET,
) -> dict[str, Any]:
    """Monta o corpo JSON de criação de sessão, sem os campos não informados.

    ``end_of_turn``: ver :data:`EndOfTurn` (**adiciona latência** fora de ``"fast"``: +0,16 s ou +0,37 s por turno).
    ``ask_again_on_ambiguous_stt``: ver ``Sessions.create`` (**adiciona latência**: +5 a +30 ms por turno, às vezes
    uma decisão a mais, ~0,2 s, e perguntas a mais).
    """
    raw = {
        "transport": transport,
        "audio_format": audio_format,
        "language": language,
        "voice": voice,
        "auto_decide": auto_decide,
        "partial_transcripts": partial_transcripts,
        "transcription_priority": transcription_priority,
        "precise_wait_ms": precise_wait_ms,
        "turn_detection": turn_detection,
        "end_of_turn": end_of_turn,
        "ask_again_on_ambiguous_stt": ask_again_on_ambiguous_stt,
        "early_turn": early_turn,
        "custom_intents": custom_intents
        if custom_intents is UNSET
        else [i if isinstance(i, dict) else asdict(i) for i in custom_intents],
        "vocabulary": vocabulary,
        "guard": guard,
        "vad": vad,
        "barge_in": barge_in,
        "waiting": waiting,
        "max_duration_s": max_duration_s,
        "metadata": metadata,
    }
    body: dict[str, Any] = {}
    for key, value in raw.items():
        if value is UNSET:
            continue
        body[key] = value.to_dict() if hasattr(value, "to_dict") else value
    return body
