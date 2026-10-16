"""Atendente por telefone com Twilio, usando o SDK da Ermis.

Passo a passo completo em docs/primeiros-passos.md (seção "Ligação de verdade pelo Twilio").

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    uvicorn atendente_twilio:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Form, Response

from ermis import (
    Call,
    Decision,
    Ermis,
    ReplyTimeout,
    SessionEnded,
    SessionStarted,
    SpeakDone,
    Transcript,
    WaitingOptions,
    WarningEvent,
)

log = logging.getLogger("atendente")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY
_conversas: set[asyncio.Task] = set()

SAUDACAO = "Olá! Você ligou para a Loja Exemplo. Como posso ajudar?"
DESPEDIDA = "Obrigado pela ligação. Até logo!"
RESPOSTAS_RAPIDAS = {
    "greeting": "Oi! Em que posso ajudar?",
    "thanks": "Por nada! Posso ajudar em mais alguma coisa?",
    "wait": "Claro, fico aguardando.",
    "repeat": "Claro. Como posso ajudar?",
}
MAX_TENTATIVAS = 3

ESPERA = WaitingOptions(
    filler_after_ms=1000,
    filler_messages=["Um momento, por favor.", "Só um instante."],
    timeout_ms=25000,
    timeout_action="apologize",
)


async def responder_com_ia(historico: list[tuple[str, str]], texto: str) -> str:
    """Sua IA: recebe o histórico e a última fala do cliente e devolve a resposta."""
    return "Entendi. Vou verificar isso para você e já te respondo."


async def conduzir(call: Call) -> None:
    """Toda a lógica da conversa: o que o agente fala em resposta a cada evento."""
    historico: list[tuple[str, str]] = []
    tentativas = 0
    encerrando = False
    confirmar: set[str] = set()

    async def falar(texto: str, **opcoes) -> None:
        historico.append(("agente", texto))
        await call.speak(texto, **opcoes)

    async for event in call:
        if isinstance(event, SessionStarted):
            await falar(SAUDACAO, calibrate=True, allow_barge_in=False)

        elif isinstance(event, Transcript):
            a = event.assessment
            if a.ignore:
                await call.done_processing()
            elif not a.usable:
                tentativas += 1
                if tentativas >= MAX_TENTATIVAS:
                    encerrando = True
                    await falar("Não estou conseguindo te ouvir bem. Por favor, ligue novamente.", allow_barge_in=False)
                else:
                    await falar("Desculpe, não entendi. Pode repetir, por favor?")
            else:
                tentativas = 0
                historico.append(("cliente", event.text))
                if a.confirm:
                    confirmar.add(event.utterance_id)
                    await falar(f"Só para confirmar: você disse {event.text}?")

        elif isinstance(event, Decision):
            if encerrando or event.utterance_id in confirmar:
                continue
            if event.is_escape:
                encerrando = True
                texto = "Vou transferir você para um atendente." if event.intent == "request_human" else DESPEDIDA
                await falar(texto, allow_barge_in=False)
            elif event.action == "clarify":
                await falar("Pode repetir, por favor?")
            elif event.action == "respond" and event.intent in RESPOSTAS_RAPIDAS:
                await falar(RESPOSTAS_RAPIDAS[event.intent])
            else:
                if event.complexity >= 2:
                    await call.thinking("Vou consultar isso para você, só um instante.", timeout_ms=45000)
                ultima = historico[-1][1] if historico else ""
                await falar(await responder_com_ia(historico, ultima))

        elif isinstance(event, SpeakDone) and encerrando:
            await call.end()

        elif isinstance(event, ReplyTimeout):
            log.warning("A IA não respondeu a tempo (fala %s)", event.utterance_id)

        elif isinstance(event, WarningEvent):
            log.warning("Aviso da Ermis: %s", event.code)

        elif isinstance(event, SessionEnded):
            log.info("Sessão encerrada (%s): %s s, %s créditos", event.reason, event.billed_seconds, event.credits)


async def _rodar(session) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call)


@app.post("/twilio/voz")
async def ligacao_recebida(CallSid: str = Form(...)) -> Response:  # noqa: N803 (nome do campo do Twilio)
    session = await ermis.sessions.create(
        transport="twilio",
        voice="woman",
        auto_decide=True,
        max_duration_s=900,
        waiting=ESPERA,
        metadata={"call_sid": CallSid},
    )
    tarefa = asyncio.create_task(_rodar(session))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    return Response(content=session.twiml(), media_type="application/xml")
