"""Atendente de agendamento de consultas por telefone (Twilio), usando o SDK da Ermis.

O agente marca, remarca ou cancela uma consulta. As intenções do negócio vão na sessão
(``custom_intents``) e cada ``Decision`` já traz a escolhida; os horários livres viram as intenções
da etapa com ``set_custom_intents()``. O nome sai de ``extract_slot()`` e o telefone de
``expect_slot()``, lido também pelo reconhecimento de maior precisão. Tudo é confirmado antes de gravar.

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    uvicorn agendamento:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
Troque ``horarios_livres`` e ``gravar_agendamento`` pela sua agenda de verdade.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import FastAPI, Form, Response

from ermis import (
    Call,
    CustomIntent,
    Decision,
    Ermis,
    SessionEnded,
    SessionStarted,
    SpeakDone,
    Transcript,
    WaitingOptions,
)

log = logging.getLogger("agendamento")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

CLINICA = "Clínica Exemplo"
SAUDACAO = f"Olá! Você ligou para a {CLINICA}. Você quer marcar, remarcar ou cancelar uma consulta?"
DESPEDIDA = "Obrigada pela ligação. Até logo!"

PEDIDOS = [
    CustomIntent("marcar", "Marcar consulta", "Agendar uma consulta nova"),
    CustomIntent("remarcar", "Remarcar consulta", "Mudar o dia ou o horário de uma consulta já marcada"),
    CustomIntent("cancelar", "Cancelar consulta", "Desmarcar uma consulta"),
]


# ── Sua agenda (troque pelo seu sistema) ────────────────────────────────────
async def horarios_livres(dia: str) -> list[CustomIntent]:
    """Horários livres no dia pedido, como opções que o cliente pode escolher falando."""
    return [
        CustomIntent("09:00", "nove da manhã", "9h, nove horas, de manhã cedo"),
        CustomIntent("14:00", "duas da tarde", "14h, duas horas, depois do almoço"),
        CustomIntent("16:30", "quatro e meia da tarde", "16h30, quatro e meia, fim da tarde"),
    ]


async def gravar_agendamento(pedido: Pedido) -> None:
    log.info("Agendamento gravado: %s", pedido)


# ── A conversa ─────────────────────────────────────────────────────────────
@dataclass
class Pedido:
    tipo: str = ""  # marcar | remarcar | cancelar
    dia: str = ""
    hora: str = ""
    hora_falada: str = ""
    nome: str = ""
    telefone: str = ""
    opcoes: list[CustomIntent] = field(default_factory=list)


def resumo(p: Pedido) -> str:
    if p.tipo == "cancelar":
        return f"Vou cancelar a consulta de {p.nome}, telefone {p.telefone}. Está certo?"
    acao = "remarcar a consulta" if p.tipo == "remarcar" else "marcar uma consulta"
    return f"Vou {acao} para {p.nome}, {p.dia}, às {p.hora_falada}. O telefone é {p.telefone}. Está certo?"


async def conduzir(call: Call) -> None:
    pedido = Pedido()
    etapa = "pedido"  # pedido -> dia -> hora -> nome -> telefone -> confirmar
    falas: dict[str, str] = {}
    encerrando = False
    telefone_esperado = None  # o valor pedido com expect_slot

    async def falar(texto: str, **opcoes) -> None:
        await call.speak(texto, **opcoes)

    async def despedir(texto: str = DESPEDIDA) -> None:
        nonlocal encerrando
        encerrando = True
        await falar(texto, allow_barge_in=False)

    async for event in call:
        if isinstance(event, SessionStarted):
            await falar(SAUDACAO, calibrate=True)

        elif isinstance(event, Transcript):
            if event.assessment.ignore:
                await call.done_processing()
            elif not event.assessment.usable:
                await falar("Desculpe, não entendi. Pode repetir, por favor?")
            else:
                falas[event.utterance_id] = event.text

        elif isinstance(event, Decision) and not encerrando:
            texto = falas.get(event.utterance_id or "", "")
            if event.is_escape:
                if event.intent == "request_human":
                    await despedir("Vou transferir você para a recepção. Um momento.")
                else:
                    await despedir()
                continue

            if event.unclear:  # fala confusa: pede para repetir em vez de agir num palpite
                await falar("Desculpe, não entendi. Pode repetir?")
                continue

            if etapa == "pedido":
                escolha = event.business_intent()  # as intenções da sessão já vêm decididas
                if escolha in ("marcar", "remarcar", "cancelar"):
                    pedido.tipo = escolha
                    if pedido.tipo == "cancelar":
                        etapa = "nome"
                        await falar("Certo. Qual é o nome do paciente?")
                    else:
                        etapa = "dia"
                        await falar("Claro! Para qual dia você prefere?")
                else:
                    await falar("Aqui eu posso marcar, remarcar ou cancelar consultas. O que você prefere?")

            elif etapa == "dia":
                dia = await call.extract_slot(texto, "dia", "date")
                if not dia.found:
                    await falar("Não peguei o dia. Pode dizer de novo? Por exemplo: amanhã, ou sexta-feira.")
                    continue
                pedido.dia = dia.value
                await call.thinking("Vou ver a agenda, só um instante.")
                pedido.opcoes = await horarios_livres(pedido.dia)
                nomes = ", ".join(o.label for o in pedido.opcoes[:-1]) + f" ou {pedido.opcoes[-1].label}"
                etapa = "hora"
                await call.set_custom_intents(pedido.opcoes)  # a próxima Decision escolhe entre os horários
                await falar(f"Para {pedido.dia} eu tenho {nomes}. Qual prefere?")

            elif etapa == "hora":
                opcao = next((o for o in pedido.opcoes if o.key == event.business_intent()), None)
                if opcao is None:
                    await falar("Desculpe, qual desses horários você prefere?")
                    continue
                pedido.hora, pedido.hora_falada = opcao.key, opcao.label
                await call.set_custom_intents(PEDIDOS)
                etapa = "nome"
                await falar("Perfeito. Qual é o nome do paciente?")

            elif etapa == "nome":
                nome = await call.extract_slot(texto, "nome", "name")
                if not nome.found:
                    await falar("Pode repetir o nome, por favor?")
                    continue
                pedido.nome = nome.value
                etapa = "telefone"
                await falar(f"Obrigada, {pedido.nome}. E um telefone para contato?")
                telefone_esperado = await call.expect_slot("telefone", "phone")

            elif etapa == "telefone":
                telefone = (
                    await telefone_esperado
                    if telefone_esperado
                    else await call.extract_slot(texto, "telefone", "phone")
                )
                telefone_esperado = None
                if not telefone.found:
                    await falar("Não entendi o número. Pode dizer devagar, com o DDD?")
                    continue
                pedido.telefone = telefone.value
                etapa = "confirmar"
                await falar(resumo(pedido))

            elif etapa == "confirmar":
                if event.intent == "confirm_yes":
                    await gravar_agendamento(pedido)
                    feito = {"cancelar": "Consulta cancelada.", "remarcar": "Consulta remarcada!"}.get(
                        pedido.tipo, "Consulta marcada!"
                    )
                    await despedir(f"{feito} {DESPEDIDA}")
                elif event.intent == "confirm_no":
                    pedido = Pedido(tipo=pedido.tipo)
                    etapa = "nome" if pedido.tipo == "cancelar" else "dia"
                    pergunta = "Qual é o nome do paciente?" if etapa == "nome" else "Para qual dia você prefere?"
                    await falar(f"Sem problemas, vamos de novo. {pergunta}")
                else:
                    await falar("É só dizer sim ou não: está certo?")

        elif isinstance(event, SpeakDone) and encerrando:
            await call.end()

        elif isinstance(event, SessionEnded):
            log.info("Ligação encerrada (%s), %s s", event.reason, event.billed_seconds)


async def _rodar(session) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call)


@app.post("/twilio/voz")
async def ligacao_recebida(CallSid: str = Form(...)) -> Response:  # noqa: N803 (nome do campo do Twilio)
    session = await ermis.sessions.create(
        transport="twilio",
        voice="Sarah",
        custom_intents=PEDIDOS,  # cada Decision já traz marcar, remarcar ou cancelar em custom_intent
        # Datas e telefones ditados têm pausas: um pouco mais de silêncio antes de fechar o turno
        vad={"min_silence_ms": 600},
        waiting=WaitingOptions(filler_after_ms=900),
        metadata={"call_sid": CallSid, "fluxo": "agendamento"},
    )
    tarefa = asyncio.create_task(_rodar(session))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    return Response(content=session.twiml(), media_type="application/xml")
