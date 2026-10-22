"""Ligação ativa: o agente liga para o paciente e confirma a consulta de amanhã.

Passo a passo em docs/tutoriais/ligacao-ativa.md. O seu sistema chama ``POST /lembretes`` com a consulta;
o servidor cria a sessão e pede ao Twilio para discar com o TwiML da sessão. Quando o paciente atende, o
agente confirma com quem fala, lembra a consulta e registra a resposta: confirmada, cancelada, remarcar
(a recepção liga de volta), engano ou sem resposta.

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart twilio
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    export TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=... TWILIO_NUMERO=+55...
    uvicorn confirmacao:app --port 8000

    curl -X POST localhost:8000/lembretes -H 'Content-Type: application/json' \\
      -d '{"id": "c1", "paciente": "Maria", "telefone": "+5511999990000", "quando": "amanhã às 14h30",
           "especialidade": "dermatologia"}'
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from ermis import (
    Call,
    CustomIntent,
    Decision,
    Ermis,
    NoReply,
    SessionEnded,
    SessionStarted,
    SpeakDone,
)

log = logging.getLogger("confirmacao")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

NOME_AGENTE = "Lia"
EMPRESA = "Clínica Bem Estar"
RECEPCAO = "(11) 3000-0000"

RESPOSTAS = [  # o que o paciente pode responder ao lembrete
    CustomIntent("confirmar", "Confirma", "vai comparecer, está confirmado, pode deixar"),
    CustomIntent("cancelar", "Cancela", "não vai, quer desmarcar, não precisa mais"),
    CustomIntent("remarcar", "Remarca", "não pode nesse dia ou horário, quer outro dia"),
]
FINAIS = {  # resultado -> o que o agente fala antes de desligar
    "confirmada": "Perfeito, consulta confirmada! Até amanhã.",
    "cancelada": f"Tudo bem, consulta cancelada. Quando quiser marcar de novo, ligue para {RECEPCAO}. Até logo!",
    "remarcar": "Sem problemas! A recepção vai te ligar hoje para combinar um novo horário. Até logo!",
    "engano": "Desculpe o incômodo. Tenha um bom dia!",
}


class Consulta(BaseModel):
    id: str
    paciente: str
    telefone: str
    quando: str  # como o agente fala: "amanhã às 14h30"
    especialidade: str


# ── Seu sistema (troque pelas chamadas de verdade) ──────────────────────────
async def registrar(consulta: Consulta, resultado: str) -> None:
    """Grava o resultado da ligação: confirmada, cancelada, remarcar, engano ou sem_resposta."""
    log.info("Consulta %s: %s", consulta.id, resultado)


async def discar(telefone: str, twiml: str) -> None:
    """Pede ao Twilio para ligar para o paciente e, quando ele atender, mandar o áudio para a Ermis.

    Com o SDK do Twilio (``pip install twilio``)::

        import os
        from twilio.rest import Client
        await asyncio.to_thread(
            Client().calls.create, to=telefone, from_=os.environ["TWILIO_NUMERO"], twiml=twiml, timeout=30
        )

    ``timeout``: segundos chamando antes de desistir. A sessão espera o áudio por até 60 s.
    """
    log.info("Discar para %s", telefone)


# ── A conversa ─────────────────────────────────────────────────────────────
async def conduzir(call: Call, consulta: Consulta) -> None:
    etapa = "identidade"  # identidade -> lembrete -> motivo (não vai: cancelar ou remarcar?)
    resultado: str | None = None

    async def finalizar(chave: str) -> None:
        nonlocal resultado
        resultado = chave
        await registrar(consulta, chave)
        await call.speak(FINAIS[chave], allow_barge_in=False)

    async for event in call:
        if isinstance(event, SessionStarted):
            # Quem atende fala primeiro ("alô?"): uma saudação curta, que pergunta com quem fala
            await call.ask(f"Olá! Falo com {consulta.paciente}?", calibrate=True)

        elif isinstance(event, Decision) and resultado is None:
            if event.handled:  # fala confusa: a Ermis já pediu para repetir
                continue
            escolha = event.business_intent()

            if etapa == "identidade":
                if event.answer == "no" or event.is_escape:
                    await finalizar("engano")
                elif event.answer == "yes" or event.intent == "name_provide":  # "sim, sou eu", "é a Maria"
                    etapa = "lembrete"
                    await call.ask(
                        f"Aqui é a {NOME_AGENTE}, da {EMPRESA}. Estou ligando para lembrar da sua consulta de "
                        f"{consulta.especialidade}, {consulta.quando}. Você confirma a sua presença?"
                    )
                else:
                    await call.ask(f"Desculpe, eu falo com {consulta.paciente}?")

            elif etapa == "lembrete":
                if escolha in ("cancelar", "remarcar"):
                    await finalizar("cancelada" if escolha == "cancelar" else "remarcar")
                elif escolha == "confirmar" or event.answer == "yes":
                    await finalizar("confirmada")
                elif event.answer == "no":
                    etapa = "motivo"
                    await call.ask("Tudo bem. Você prefere cancelar ou remarcar para outro dia?")
                else:
                    await call.ask(f"Só para eu anotar: você vai à consulta {consulta.quando}?")

            elif etapa == "motivo":
                if escolha == "cancelar":
                    await finalizar("cancelada")
                elif escolha == "remarcar" or event.answer == "yes":
                    await finalizar("remarcar")
                else:
                    await call.ask("Desculpe, você quer cancelar ou remarcar?")

        elif isinstance(event, NoReply) and not event.handled and resultado is None:
            # "on_no_reply": "notify": o último silêncio chega para você decidir
            resultado = "sem_resposta"
            await registrar(consulta, resultado)
            await call.speak(f"Não consegui te ouvir. Se precisar, ligue para {RECEPCAO}. Até logo!")

        elif isinstance(event, SpeakDone) and resultado is not None:
            await call.end()

        elif isinstance(event, SessionEnded):
            if resultado is None:  # desligou antes de responder, ou ninguém atendeu
                await registrar(consulta, "sem_resposta")
            log.info("Ligação para %s encerrada (%s)", consulta.telefone, event.reason)


async def _rodar(session, consulta: Consulta) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call, consulta)


@app.post("/lembretes")
async def lembrar(consulta: Consulta) -> dict[str, str]:
    """O seu sistema chama este endpoint para cada consulta de amanhã."""
    session = await ermis.sessions.create(
        transport="twilio",
        voice="Sarah",
        custom_intents=RESPOSTAS,  # cada Decision já traz confirmar, cancelar ou remarcar
        turn_detection="smart_turn",
        guard={
            "enabled": True,
            "repeat": "Desculpe, não entendi. Pode repetir?",
            "steer": "Só para eu anotar:",
            "drift": "Entendi!",
            "off_topic": f"Isso a recepção pode te ajudar, no {RECEPCAO}.",
            "give_up": f"Estou com dificuldade para te ouvir. Se precisar, ligue para {RECEPCAO}. Até logo!",
            "no_reply": "Alô? Você está me ouvindo?",
            "on_no_reply": "notify",  # no último silêncio, o código registra "sem_resposta"
        },
        max_duration_s=180,  # um lembrete é curto
        metadata={"consulta": consulta.id, "fluxo": "confirmacao"},
    )
    tarefa = asyncio.create_task(_rodar(session, consulta))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    await discar(consulta.telefone, session.twiml())  # o áudio chega quando o paciente atender
    return {"session_id": session.session_id}
