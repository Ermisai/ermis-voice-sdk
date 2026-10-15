"""Cliente da Ermis Voice API: REST para sessões, uso e saldo; WebSocket para o controle."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from xml.sax.saxutils import quoteattr

import httpx
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus

from .call import Call
from .errors import AuthenticationError, from_http
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
        vad: VadOptions | dict[str, Any] = UNSET,
        barge_in: BargeInOptions | dict[str, Any] = UNSET,
        waiting: WaitingOptions | dict[str, Any] = UNSET,
        max_duration_s: int = UNSET,
        metadata: dict[str, Any] = UNSET,
    ) -> Session:
        """Cria uma sessão (``POST /v1/voice/sessions``). Campos omitidos usam o padrão da API."""
        body = session_body(
            transport=transport,
            audio_format=audio_format,
            language=language,
            voice=voice,
            auto_decide=auto_decide,
            transcription_priority=transcription_priority,
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
        session = await ermis.sessions.create(transport="twilio")
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

    @property
    def sandbox(self) -> bool:
        """``True`` com chaves ``ek_test_…``."""
        return self.api_key.startswith("ek_test_")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = await self._http.request(method, path, headers=self._auth(), **kwargs)
        if resp.is_error:
            try:
                message = resp.json().get("message", "")
            except ValueError:
                message = resp.text
            raise from_http(resp.status_code, message)
        return resp.json() if resp.content else None

    async def usage(self, *, from_: date | str, to: date | str, group_by: str = "day") -> dict[str, Any]:
        """Minutos e créditos no período. ``group_by``: ``day`` ou ``session``."""
        params = {"from": str(from_), "to": str(to), "group_by": group_by}
        return await self._request("GET", "/v1/usage", params=params)

    async def balance(self) -> dict[str, Any]:
        """Saldo de créditos e quando cada parte expira."""
        return await self._request("GET", "/v1/account/balance")

    def connect(self, session: Session | str) -> _CallConnector:
        """Abre o canal de controle de ``session`` (ou de uma ``control_url``). Use com ``async with``."""
        url = session.control_url if isinstance(session, Session) else session
        return _CallConnector(url, self._auth())

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Ermis:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class _CallConnector:
    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self._url = url
        self._headers = headers
        self._call: Call | None = None

    async def __aenter__(self) -> Call:
        try:
            ws = await ws_connect(self._url, additional_headers=self._headers, max_size=2**22)
        except InvalidStatus as exc:
            raise from_http(exc.response.status_code, "não foi possível abrir o canal de controle") from exc
        self._call = Call(ws)
        self._call._start()
        return self._call

    async def __aexit__(self, *exc: object) -> None:
        if self._call:
            await self._call.close()
