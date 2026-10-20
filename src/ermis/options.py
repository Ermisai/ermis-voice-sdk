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


def session_body(
    *,
    transport: Transport | Any = UNSET,
    audio_format: AudioFormat | Any = UNSET,
    language: str = UNSET,
    voice: str = UNSET,
    auto_decide: bool = UNSET,
    transcription_priority: Literal["balanced", "latency", "accuracy", "local_first", "local_only"] = UNSET,
    turn_detection: Literal["smart_turn", "silence"] = UNSET,
    early_turn: dict[str, Any] = UNSET,
    custom_intents: list[Any] = UNSET,
    vad: VadOptions | dict[str, Any] = UNSET,
    barge_in: BargeInOptions | dict[str, Any] = UNSET,
    waiting: WaitingOptions | dict[str, Any] = UNSET,
    max_duration_s: int = UNSET,
    metadata: dict[str, Any] = UNSET,
) -> dict[str, Any]:
    """Monta o corpo JSON de criação de sessão, sem os campos não informados."""
    raw = {
        "transport": transport,
        "audio_format": audio_format,
        "language": language,
        "voice": voice,
        "auto_decide": auto_decide,
        "transcription_priority": transcription_priority,
        "turn_detection": turn_detection,
        "early_turn": early_turn,
        "custom_intents": custom_intents
        if custom_intents is UNSET
        else [i if isinstance(i, dict) else asdict(i) for i in custom_intents],
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
