"""SDK Python da Ermis Voice API.

A Ermis conduz a ligação (ouve, transcreve, decide, fala, espera, cobra).
Este SDK é a ponte do seu backend até ela: cria sessões e entrega os eventos
da ligação como objetos Python, com métodos para mandar o agente agir.
"""

from .call import Call, CustomIntent
from .client import Ermis, Session, Voice
from .errors import (
    APIError,
    AuthenticationError,
    ChannelLimitError,
    ConnectionClosedError,
    ErmisError,
    InsufficientCreditsError,
    InvalidRequestError,
    MaxDurationError,
    RateLimitError,
    SessionTimeoutError,
)
from .events import (
    Assessment,
    Audio,
    BargeIn,
    Decision,
    ErrorEvent,
    Event,
    ReplyTimeout,
    SessionEnded,
    SessionStarted,
    SlotResult,
    SpeakDone,
    SpeakStarted,
    SpeechEnded,
    SpeechStarted,
    Transcript,
    UnknownEvent,
    Usage,
    WaitingSpoken,
    WarningEvent,
    parse_event,
)
from .options import BargeInOptions, VadOptions, WaitingOptions

__version__ = "0.2.0a1"

__all__ = [
    "APIError",
    "Assessment",
    "Audio",
    "AuthenticationError",
    "BargeIn",
    "BargeInOptions",
    "Call",
    "ChannelLimitError",
    "ConnectionClosedError",
    "CustomIntent",
    "Decision",
    "Ermis",
    "ErmisError",
    "ErrorEvent",
    "Event",
    "InsufficientCreditsError",
    "InvalidRequestError",
    "MaxDurationError",
    "RateLimitError",
    "ReplyTimeout",
    "Session",
    "SessionEnded",
    "SessionStarted",
    "SessionTimeoutError",
    "SlotResult",
    "SpeakDone",
    "SpeakStarted",
    "SpeechEnded",
    "SpeechStarted",
    "Transcript",
    "UnknownEvent",
    "Voice",
    "Usage",
    "VadOptions",
    "WaitingOptions",
    "WaitingSpoken",
    "WarningEvent",
    "parse_event",
]
