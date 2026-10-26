"""SDK Python da Ermis Voice API.

A Ermis conduz a ligação (ouve, transcreve, decide, fala, espera, cobra).
Este SDK é a ponte do seu backend até ela: cria sessões e entrega os eventos
da ligação como objetos Python, com métodos para mandar o agente agir.
"""

from .call import Call, CustomIntent, Question
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
    NoiseCalibrated,
    NoReply,
    ReplyTimeout,
    SessionEnded,
    SessionStarted,
    SlotResult,
    SpeakDone,
    SpeakStarted,
    SpeechEnded,
    SpeechStarted,
    Transcript,
    TranscriptPartial,
    TranscriptRevised,
    UnknownEvent,
    Usage,
    WaitingSpoken,
    WarningEvent,
    parse_event,
)
from .options import BargeInOptions, VadOptions, WaitingOptions
from .speech_text import normalize_for_speech, number_to_words

__version__ = "0.4.1a1"

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
    "Question",
    "RateLimitError",
    "ReplyTimeout",
    "Session",
    "NoiseCalibrated",
    "NoReply",
    "SessionEnded",
    "SessionStarted",
    "SessionTimeoutError",
    "SlotResult",
    "SpeakDone",
    "SpeakStarted",
    "SpeechEnded",
    "SpeechStarted",
    "Transcript",
    "TranscriptPartial",
    "TranscriptRevised",
    "UnknownEvent",
    "Voice",
    "Usage",
    "VadOptions",
    "WaitingOptions",
    "WaitingSpoken",
    "WarningEvent",
    "normalize_for_speech",
    "number_to_words",
    "parse_event",
]
