"""URA por voz (Twilio): o cliente diz o motivo da ligação e é encaminhado para o setor certo.

Em vez de "digite 1 para financeiro", o cliente fala do jeito dele ("quero a segunda via",
"minha internet caiu") e ``decide()`` escolhe o setor entre as intenções do seu negócio.
Para o financeiro, o agente pede o CPF antes de transferir.

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    uvicorn ura:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
A transferência de verdade é feita pelo Twilio (veja ``transferir``).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Form, Response

from ermis import Call, CustomIntent, Decision, Ermis, SessionEnded, SessionStarted, SpeakDone, Transcript

log = logging.getLogger("ura")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

SAUDACAO = (
    "Olá, você ligou para a Empresa Exemplo. Em poucas palavras, diga o motivo da sua ligação. "
    "Por exemplo: segunda via, suporte técnico ou falar com vendas."
)
MAX_TENTATIVAS = 2

SETORES = [
    CustomIntent("financeiro", "Financeiro", "Boleto, segunda via, fatura, pagamento, cobrança, reembolso"),
    CustomIntent("suporte", "Suporte técnico", "Algo não funciona: internet, aplicativo, aparelho, acesso, senha"),
    CustomIntent("vendas", "Vendas", "Contratar, comprar, conhecer planos e preços, mudar de plano"),
]
NUMEROS = {  # para onde cada setor transfere (troque pelos seus)
    "financeiro": "+5511900000001",
    "suporte": "+5511900000002",
    "vendas": "+5511900000003",
    "atendente": "+5511900000000",
}
AVISOS = {
    "financeiro": "Certo, vou transferir você para o financeiro.",
    "suporte": "Entendi, vou transferir você para o suporte técnico.",
    "vendas": "Ótimo! Vou transferir você para o time de vendas.",
    "atendente": "Vou transferir você para um atendente.",
}


async def transferir(call_sid: str, setor: str, dados: dict[str, str]) -> None:
    """Encaminha a ligação no Twilio. Ao trocar o TwiML, a sessão da Ermis termina sozinha.

    Exemplo com o SDK do Twilio (``pip install twilio``)::

        from twilio.rest import Client
        Client().calls(call_sid).update(twiml=f"<Response><Dial>{NUMEROS[setor]}</Dial></Response>")

    ``dados`` (por exemplo, o CPF) pode ir para o seu CRM antes da transferência.
    """
    log.info("Transferir %s para %s (%s) com %s", call_sid, setor, NUMEROS[setor], dados)


async def conduzir(call: Call, call_sid: str = "") -> None:
    falas: dict[str, str] = {}
    tentativas = 0
    etapa = "motivo"  # motivo -> cpf (só financeiro)
    destino: str | None = None
    dados: dict[str, str] = {}

    async def encaminhar(setor: str) -> None:
        nonlocal destino
        destino = setor
        await call.speak(AVISOS[setor], allow_barge_in=False)

    async for event in call:
        if isinstance(event, SessionStarted):
            await call.speak(SAUDACAO, calibrate=True)

        elif isinstance(event, Transcript):
            if event.assessment.ignore:
                await call.done_processing()
            elif not event.assessment.usable:
                await call.speak("Desculpe, não entendi. Pode repetir o motivo da ligação?")
            else:
                falas[event.utterance_id] = event.text

        elif isinstance(event, Decision) and destino is None:
            texto = falas.get(event.utterance_id or "", "")
            if event.is_escape:
                if event.intent == "request_human":
                    await encaminhar("atendente")
                else:
                    destino = "fim"
                    await call.speak("Tudo bem. Obrigado pela ligação!", allow_barge_in=False)
                continue

            if etapa == "cpf":
                cpf = await call.extract_slot(texto, "cpf", "cpf")
                if cpf.found:
                    dados["cpf"] = cpf.value
                await encaminhar("financeiro")  # com ou sem CPF: o financeiro confirma
                continue

            setor = (await call.decide(texto, custom_intents=SETORES)).custom_intent
            if setor == "financeiro":
                etapa = "cpf"
                await call.speak("Para agilizar, qual é o CPF do titular?")
            elif setor in ("suporte", "vendas"):
                await encaminhar(setor)
            else:
                tentativas += 1
                if tentativas > MAX_TENTATIVAS:
                    await encaminhar("atendente")
                else:
                    await call.speak("Não entendi o assunto. É sobre financeiro, suporte técnico ou vendas?")

        elif isinstance(event, SpeakDone) and destino is not None:
            if destino != "fim":
                await transferir(call_sid, destino, dados)
            await call.end()

        elif isinstance(event, SessionEnded):
            log.info("URA encerrada (%s): destino %s", event.reason, destino)


async def _rodar(session, call_sid: str) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call, call_sid)


@app.post("/twilio/voz")
async def ligacao_recebida(CallSid: str = Form(...)) -> Response:  # noqa: N803 (nome do campo do Twilio)
    session = await ermis.sessions.create(
        transport="twilio",
        voice="woman",
        transcription_priority="latency",  # numa URA, responder rápido importa mais que cada palavra
        metadata={"call_sid": CallSid, "fluxo": "ura"},
    )
    tarefa = asyncio.create_task(_rodar(session, CallSid))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    return Response(content=session.twiml(), media_type="application/xml")
