"""Cliente da Ermis Voice API: REST para sessões, uso e saldo; WebSocket para o controle."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import quoteattr

import httpx
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus

from .call import Call
from .errors import AuthenticationError, InvalidRequestError, from_http
from .options import UNSET, AudioFormat, BargeInOptions, Transport, VadOptions, WaitingOptions, session_body

DEFAULT_BASE_URL = "https://api.ermis.ai"


@dataclass(frozen=True)
class Session:
    """Uma sessão de voz recém-criada."""

    session_id: str
    audio_url: str
    """Onde o áudio da ligação se conecta (Twilio, navegador ou o seu WebSocket)."""
    control_url: str
    """Onde o seu backend recebe eventos e manda comandos. Use ``Ermis.connect()``."""
    session_token: str
    """Credencial de uso único para o lado do áudio. Pode ir ao navegador ou ao Twilio; a chave de API não."""
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def twiml(self) -> str:
        """TwiML que manda o áudio da ligação do Twilio direto para a Ermis (transporte ``twilio``)."""
        return (
            "<Response><Connect>"
            f"<Stream url={quoteattr(self.audio_url)}>"
            f'<Parameter name="session_token" value={quoteattr(self.session_token)} />'
            "</Stream></Connect></Response>"
        )

    def browser_credentials(self) -> dict[str, str]:
        """O que entregar ao navegador no transporte ``browser``. Nunca inclua a chave de API."""
        return {"audio_url": self.audio_url, "session_token": self.session_token}


@dataclass(frozen=True)
class Voice:
    """Uma voz do agente. Use o ``id`` em ``sessions.create(voice=...)``."""

    id: str
    name: str
    gender: str | None = None
    language: str = "pt-BR"
    description: str | None = None
    production: bool = True
    """``False`` para vozes só de teste, que não devem ser usadas com clientes reais."""
    default: bool = False
    """A voz usada quando ``voice`` não é informado."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Voice:
        return cls(
            id=data["id"],
            name=data.get("name") or data["id"],
            gender=data.get("gender"),
            language=data.get("language") or "pt-BR",
            description=data.get("description"),
            production=data.get("production", True),
            default=data.get("default", False),
        )


class _Voices:
    def __init__(self, client: Ermis) -> None:
        self._client = client

    async def list(self) -> list[Voice]:
        """Vozes disponíveis para a sua conta (``GET /v1/voice/voices``), a padrão primeiro."""
        data = await self._client._request("GET", "/v1/voice/voices")
        return [Voice.from_dict(item) for item in data.get("voices", [])]


class _Sessions:
    def __init__(self, client: Ermis) -> None:
        self._client = client

    async def create(
        self,
        *,
        transport: Transport = UNSET,
        audio_format: AudioFormat = UNSET,
        language: str = UNSET,
        voice: str = UNSET,
        auto_decide: bool = UNSET,
        transcription_priority: str = UNSET,
        turn_detection: str = UNSET,
        early_turn: dict[str, Any] = UNSET,
        custom_intents: list[Any] = UNSET,
        vocabulary: list[str] = UNSET,
        vad: VadOptions | dict[str, Any] = UNSET,
        barge_in: BargeInOptions | dict[str, Any] = UNSET,
        waiting: WaitingOptions | dict[str, Any] = UNSET,
        max_duration_s: int = UNSET,
        metadata: dict[str, Any] = UNSET,
    ) -> Session:
        """Cria uma sessão (``POST /v1/voice/sessions``). Campos omitidos usam o padrão da API.

        ``custom_intents`` (lista de ``CustomIntent``): as intenções do seu negócio. Cada ``Decision``
        automática já traz em ``custom_intent`` a que se aplica, sem chamar ``call.decide()``.

        ``vocabulary`` (lista de palavras): termos do seu negócio (sabores, serviços, produtos). Quando a
        transcrição sai parecida com um deles pelo som ("marquerita"), o texto já chega corrigido.
        """
        body = session_body(
            transport=transport,
            audio_format=audio_format,
            language=language,
            voice=voice,
            auto_decide=auto_decide,
            transcription_priority=transcription_priority,
            turn_detection=turn_detection,
            early_turn=early_turn,
            custom_intents=custom_intents,
            vocabulary=vocabulary,
            vad=vad,
            barge_in=barge_in,
            waiting=waiting,
            max_duration_s=max_duration_s,
            metadata=metadata,
        )
        data = await self._client._request("POST", "/v1/voice/sessions", json=body)
        return Session(
            session_id=data["session_id"],
            audio_url=data["audio_url"],
            control_url=data["control_url"],
            session_token=data["session_token"],
            raw=data,
        )

    async def get(self, session_id: str) -> dict[str, Any]:
        """Estado da sessão e segundos cobrados até agora."""
        return await self._client._request("GET", f"/v1/voice/sessions/{session_id}")

    async def end(self, session_id: str) -> None:
        """Encerra a sessão pelo REST (o mesmo que ``call.end()`` no canal de controle)."""
        await self._client._request("DELETE", f"/v1/voice/sessions/{session_id}")


class Ermis:
    """Cliente assíncrono da Ermis Voice API.

    Use só no seu servidor: ele carrega a sua chave de API.

    ::

        ermis = Ermis()  # lê ERMIS_API_KEY
        voices = await ermis.voices.list()
        session = await ermis.sessions.create(transport="twilio", voice=voices[0].id)
        async with ermis.connect(session) as call:
            async for event in call:
                ...
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ERMIS_API_KEY", "")
        if not self.api_key:
            raise AuthenticationError("informe api_key ou defina ERMIS_API_KEY")
        self.base_url = (base_url or os.environ.get("ERMIS_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._http = http_client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self.sessions = _Sessions(self)
        self.voices = _Voices(self)

    @property
    def sandbox(self) -> bool:
        """``True`` com chaves ``ek_test_…``."""
        return self.api_key.startswith("ek_test_")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = await self._http.request(method, path, headers=self._auth(), **kwargs)
        if resp.is_error:
            code = None
            try:
                error = resp.json()
                message = error.get("message", "") if isinstance(error, dict) else ""
                code = error.get("error") if isinstance(error, dict) else None
            except ValueError:
                message = resp.text
            raise from_http(resp.status_code, message, code=code, request_id=resp.headers.get("x-request-id"))
        return resp.json() if resp.content else None

    async def usage(self, *, limit: int = 50, before: int | None = None) -> dict[str, Any]:
        """Lançamentos financeiros: ``entries`` e ``next_cursor`` para a próxima página."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidRequestError("limit deve ser um inteiro entre 1 e 100")
        if before is not None and (type(before) is not int or before < 1):
            raise InvalidRequestError("before deve ser um cursor inteiro positivo")
        params = {"limit": str(limit)}
        if before is not None:
            params["before"] = str(before)
        return await self._request("GET", "/v1/usage", params=params)

    async def balance(self) -> dict[str, Any]:
        """Carteira oficial: balance, reserved_credits e available_credits."""
        return await self._request("GET", "/v1/account/balance")

    def connect(self, session: Session | str, *, normalize_text: bool = True) -> _CallConnector:
        """Abre o canal de controle de ``session`` (ou de uma ``control_url``). Use com ``async with``.

        ``normalize_text`` (padrão ``True``): cada fala passa por :func:`ermis.normalize_for_speech` antes de
        ir para a voz (números por extenso, valores, datas, e-mails, sem markdown nem emojis).
        """
        url = session.control_url if isinstance(session, Session) else session
        return _CallConnector(url, self._auth(), normalize_text)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Ermis:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class _CallConnector:
    def __init__(self, url: str, headers: dict[str, str], normalize_text: bool) -> None:
        self._url = url
        self._headers = headers
        self._normalize_text = normalize_text
        self._call: Call | None = None

    async def __aenter__(self) -> Call:
        try:
            ws = await ws_connect(self._url, additional_headers=self._headers, max_size=2**22)
        except InvalidStatus as exc:
            raise from_http(exc.response.status_code, "não foi possível abrir o canal de controle") from exc
        self._call = Call(ws, normalize_text=self._normalize_text)
        self._call._start()
        return self._call

    async def __aexit__(self, *exc: object) -> None:
        if self._call:
            await self._call.close()
