"""Suporte técnico conduzido pela IA (camada 3), com dados do seu sistema.

Passo a passo em docs/tutoriais/assistente-ia.md. O código identifica o cliente (o CPF, lido pelo
reconhecimento de maior precisão) e passa a conversa para a IA, que consulta o seu sistema por ferramentas
(o cadastro, a conexão, um chamado novo). A Ermis cuida da fala confusa e do silêncio; a divagação e o
assunto fora do tema ficam com a IA (``drift`` e ``off_topic`` vazios).

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart anthropic
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    export ANTHROPIC_API_KEY=...        # chave da sua IA
    uvicorn assistente_ia:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
Troque as funções da seção "Seu sistema" pelas consultas de verdade.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Form, Response

from ermis import Call, Decision, Ermis, SessionEnded, SessionStarted, SpeakDone, Transcript, WaitingOptions

log = logging.getLogger("assistente")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

NOME_AGENTE = "Davi"
EMPRESA = "Conecta Internet"
SAUDACAO = f"Olá! Aqui é o {NOME_AGENTE}, do suporte da {EMPRESA}. Para começar, qual é o CPF do titular?"
DESPEDIDA = "Obrigado por ligar para a Conecta. Até mais!"
TRANSFERIR = "Vou te passar para um técnico. Um momento, por favor."
MARCA_TRANSFERIR = "[TRANSFERIR]"
MARCA_FIM = "[FIM]"


# ── Seu sistema (troque pelas consultas de verdade) ─────────────────────────
async def consultar_cliente(cpf: str) -> dict:
    return {"nome": "Maria", "plano": "Fibra 500 mega", "pagamento": "em dia", "cidade": "Campinas"}


async def verificar_conexao(cpf: str) -> dict:
    return {"modem": "offline desde 14h10", "falha_na_regiao": False}


async def abrir_chamado(cpf: str, descricao: str) -> dict:
    return {"protocolo": "2026102100123", "visita": "amanhã, entre 8h e 12h"}


# ── Camada 3: a IA, com ferramentas para consultar o seu sistema ────────────
PROMPT_IA = f"""Você é {NOME_AGENTE}, atendente de suporte técnico da {EMPRESA}, numa ligação telefônica.
O cliente já foi identificado; os dados dele vêm na primeira mensagem.
Como atender:
- Entenda o problema, consulte a conexão com a ferramenta antes de dar qualquer diagnóstico e oriente um passo
  por vez (por exemplo, desligar o modem da tomada por trinta segundos).
- Se o problema continuar depois das orientações, abra um chamado e informe o protocolo e a visita.
- Responda em português do Brasil, em uma ou duas frases curtas: o cliente ouve, não lê. Sem listas nem markdown.
- Não fale de assuntos fora do suporte: diga com gentileza que aqui você cuida da internet e volte ao problema.
- Se o cliente pedir uma pessoa, ou o problema for de cobrança, termine a resposta com {MARCA_TRANSFERIR}.
- Quando o atendimento terminar e o cliente se despedir, termine a resposta com {MARCA_FIM}."""

FERRAMENTAS = [
    {
        "name": "verificar_conexao",
        "description": "Estado do modem e se há falha na região do cliente. Use antes de qualquer diagnóstico.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "abrir_chamado",
        "description": "Abre um chamado técnico com visita. Use só depois de tentar as orientações por telefone.",
        "input_schema": {
            "type": "object",
            "properties": {"descricao": {"type": "string", "description": "O problema, em uma frase"}},
            "required": ["descricao"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


async def executar_ferramenta(nome: str, entrada: dict, cpf: str) -> dict:
    if nome == "verificar_conexao":
        return await verificar_conexao(cpf)
    if nome == "abrir_chamado":
        return await abrir_chamado(cpf, entrada["descricao"])
    raise ValueError(f"ferramenta desconhecida: {nome}")


async def responder_com_ia(
    historico: list[tuple[str, str]], cliente: dict, cpf: str, avisar: Callable[[str], Awaitable[None]]
) -> str:
    """A próxima fala do agente. ``avisar`` fala uma frase de espera enquanto o seu sistema é consultado."""
    import anthropic  # pip install anthropic

    contexto = f"Dados do cliente: {json.dumps(cliente, ensure_ascii=False)}"
    mensagens: list[dict] = [{"role": "user", "content": contexto}]
    for quem, texto in historico:
        mensagens.append({"role": "user" if quem == "cliente" else "assistant", "content": texto})
    ia = anthropic.AsyncAnthropic()
    for _ in range(4):  # algumas consultas por resposta, no máximo
        resposta = await ia.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=2048,
            output_config={"effort": "low"},  # respostas curtas de atendimento: menos espera
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # se o modelo recusar, outro modelo responde na mesma chamada
            system=PROMPT_IA,
            tools=FERRAMENTAS,
            messages=mensagens,
        )
        if resposta.stop_reason != "tool_use":
            break
        await avisar("Deixa eu verificar aqui no sistema.")
        mensagens.append({"role": "assistant", "content": resposta.content})
        resultados = []
        for bloco in resposta.content:
            if bloco.type == "tool_use":
                try:
                    saida = json.dumps(await executar_ferramenta(bloco.name, bloco.input, cpf), ensure_ascii=False)
                    resultados.append({"type": "tool_result", "tool_use_id": bloco.id, "content": saida})
                except Exception as erro:  # o erro vai para a IA, que explica ou transfere
                    resultados.append(
                        {"type": "tool_result", "tool_use_id": bloco.id, "content": str(erro), "is_error": True}
                    )
        mensagens.append({"role": "user", "content": resultados})
    else:
        return f"Preciso de ajuda de um técnico para isso. {MARCA_TRANSFERIR}"
    if resposta.stop_reason == "refusal":
        return f"Vou te passar para um técnico. {MARCA_TRANSFERIR}"
    return next((b.text for b in resposta.content if b.type == "text"), "").strip()


async def transferir(call_sid: str) -> None:
    """Encaminha a ligação no Twilio (veja ``transferir`` em ura.py)."""
    log.info("Transferir %s para um técnico", call_sid)


# ── A conversa ─────────────────────────────────────────────────────────────
async def conduzir(call: Call, call_sid: str = "") -> None:
    historico: list[tuple[str, str]] = []
    cpf_pedido = None  # o valor da resposta à saudação (ask com slot)
    cpf = ""
    cliente: dict = {}
    destino: str | None = None  # "tecnico" ou "fim"
    tentativas = 0

    async def falar(texto: str, **opcoes) -> None:
        historico.append(("agente", texto))
        await call.speak(texto, **opcoes)

    async def perguntar_cpf(texto: str, **opcoes) -> None:
        nonlocal cpf_pedido
        pergunta = await call.ask(texto, slot=("cpf", "cpf"), **opcoes)
        cpf_pedido = pergunta.value

    async def avisar(texto: str) -> None:
        await call.thinking(texto)

    async for event in call:
        if isinstance(event, SessionStarted):
            await perguntar_cpf(SAUDACAO, calibrate=True)

        elif isinstance(event, Transcript):
            if not event.handled and event.assessment.usable and cpf:  # depois da identificação
                historico.append(("cliente", event.text))

        elif isinstance(event, Decision) and destino is None:
            if event.handled:  # fala confusa ou silêncio: a Ermis já respondeu
                continue
            if event.is_escape:  # despedida ou pedido de uma pessoa: sempre igual, sem a IA
                destino = "tecnico" if event.intent == "request_human" else "fim"
                await falar(TRANSFERIR if destino == "tecnico" else DESPEDIDA, allow_barge_in=False)
                continue

            if not cpf:  # camada 2: identificação, sempre igual
                resultado = await cpf_pedido if cpf_pedido else await call.extract_slot(event.text, "cpf", "cpf")
                cpf_pedido = None
                if not resultado.found:
                    tentativas += 1
                    if tentativas >= 2:
                        destino = "tecnico"
                        await falar(TRANSFERIR, allow_barge_in=False)
                    else:
                        await perguntar_cpf("Não peguei o CPF. Pode dizer os onze números, devagar?")
                    continue
                cpf = resultado.value
                await call.thinking("Só um instante, vou localizar o seu cadastro.")
                cliente = await consultar_cliente(cpf)
                await falar(f"Obrigado, {cliente['nome']}. Me conta: o que está acontecendo com a sua internet?")
                continue

            # Camada 3: a IA conduz o atendimento
            resposta = await responder_com_ia(historico, cliente, cpf, avisar)
            for marca, fim in ((MARCA_TRANSFERIR, "tecnico"), (MARCA_FIM, "fim")):
                if marca in resposta:
                    resposta, destino = resposta.replace(marca, "").strip(), fim
            await falar(resposta, allow_barge_in=destino is None)

        elif isinstance(event, SpeakDone) and destino is not None:
            if destino == "tecnico":
                await transferir(call_sid)
            await call.end()

        elif isinstance(event, SessionEnded):
            log.info("Atendimento encerrado (%s): %s s", event.reason, event.billed_seconds)


async def _rodar(session, call_sid: str) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call, call_sid)


@app.post("/twilio/voz")
async def ligacao_recebida(CallSid: str = Form(...)) -> Response:  # noqa: N803 (nome do campo do Twilio)
    session = await ermis.sessions.create(
        transport="twilio",
        voice="Alex",
        transcription_priority="balanced",
        vocabulary=["modem", "roteador", "wi-fi", "fibra", "Conecta"],
        guard={
            "enabled": True,
            "repeat": "Desculpe, não entendi. Pode repetir?",
            "steer": "Vamos voltar ao seu atendimento?",
            "drift": "",  # vazio: a divagação vai para a IA, que conhece o contexto
            "off_topic": "",  # vazio: o assunto fora do tema também
            "give_up": "Estou com dificuldade para te ouvir. Por favor, ligue de novo.",
            "no_reply": "Você ainda está aí?",
            "no_reply_give_up": "Como não ouvi resposta, vou encerrar. Até mais!",
        },
        # Uma resposta com consulta ao sistema pode levar alguns segundos
        waiting=WaitingOptions(filler_after_ms=1000, timeout_ms=30000),
        metadata={"call_sid": CallSid, "fluxo": "suporte"},
    )
    tarefa = asyncio.create_task(_rodar(session, CallSid))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    return Response(content=session.twiml(), media_type="application/xml")
