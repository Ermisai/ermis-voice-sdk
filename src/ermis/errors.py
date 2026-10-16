"""Erros da Ermis Voice API.

O mesmo erro pode chegar como status HTTP (REST) ou como código de fechamento
do WebSocket (canal de controle). O SDK converte os dois na mesma exceção.
"""

from __future__ import annotations


class ErmisError(Exception):
    """Base de todos os erros do SDK."""

    def __init__(
        self, message: str, *, code: int | str | None = None, status: int | None = None, request_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id


class AuthenticationError(ErmisError):
    """Chave de API ou token de sessão inválido ou expirado (401 / 4001)."""


class InsufficientCreditsError(ErmisError):
    """Créditos insuficientes para abrir ou continuar a sessão (402 / 4002)."""


class ChannelLimitError(ErmisError):
    """Todos os canais simultâneos do plano estão em uso (429 / 4029)."""


class RateLimitError(ErmisError):
    """A API limitou temporariamente a frequência de requisições (429 `rate_limited`)."""


class InvalidRequestError(ErmisError):
    """Mensagem ou corpo inválido (400 / 4400)."""


class SessionTimeoutError(ErmisError):
    """A sessão ficou 60 s sem áudio (4008)."""


class MaxDurationError(ErmisError):
    """A sessão atingiu ``max_duration_s`` (4013)."""


class APIError(ErmisError):
    """Erro interno da Ermis ou resposta inesperada (500 / 1011)."""


class ConnectionClosedError(ErmisError):
    """O canal de controle fechou antes do evento ``session.ended``."""


_BY_HTTP = {
    400: InvalidRequestError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    429: ChannelLimitError,
}

_BY_CLOSE_CODE = {
    4001: AuthenticationError,
    4002: InsufficientCreditsError,
    4029: ChannelLimitError,
    4008: SessionTimeoutError,
    4013: MaxDurationError,
    4400: InvalidRequestError,
    1011: APIError,
}


def from_http(status: int, message: str, *, code: str | None = None, request_id: str | None = None) -> ErmisError:
    cls = RateLimitError if status == 429 and code == "rate_limited" else _BY_HTTP.get(status, APIError)
    return cls(message or f"HTTP {status}", status=status, code=code or status, request_id=request_id)


def from_close_code(code: int | None, reason: str) -> ErmisError:
    cls = _BY_CLOSE_CODE.get(code or 0, ConnectionClosedError)
    return cls(reason or f"canal de controle fechado (código {code})", code=code)
