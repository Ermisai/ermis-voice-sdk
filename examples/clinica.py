"""Clínica Bem Estar: atendente com URA por voz, respostas prontas e IA, montado no tutorial.

Passo a passo completo em docs/tutoriais/atendente.md. As três camadas de resposta:

1. A Ermis cuida sozinha (``guard``): ruído, fala confusa, divagação, assunto fora do tema e cliente calado.
2. Respostas pré-definidas: as frases da clínica (horário, endereço, convênios) e a URA (agendamento,
   financeiro), escolhidas pelas intenções da sessão (``custom_intents``).
3. A sua IA: o que sobra (dúvidas abertas) vai para o modelo, com o nome do agente e as regras da clínica.

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart anthropic
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    export ANTHROPIC_API_KEY=...        # chave da sua IA (camada 3); sem ela, o agente transfere as dúvidas abertas
    export PERFIL=equilibrado           # rapido, equilibrado ou preciso (qualidade x latência)
    uvicorn clinica:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
No navegador, o seu site chama ``POST /ligar`` e recebe as credenciais do áudio.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI, Form, Response

from ermis import (
    Call,
    CustomIntent,
    Decision,
    Ermis,
    NoiseCalibrated,
    SessionEnded,
    SessionStarted,
    SpeakDone,
    Transcript,
    WaitingOptions,
    WarningEvent,
)

log = logging.getLogger("clinica")
app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

# ── Passo 3: identidade do agente ───────────────────────────────────────────
NOME_AGENTE = "Lia"
EMPRESA = "Clínica Bem Estar"
VOZ = "woman"  # um id de `await ermis.voices.list()` com production=True
SAUDACAO = f"Olá! Você ligou para a {EMPRESA}, aqui é a {NOME_AGENTE}. Como posso ajudar?"
DESPEDIDA = "Obrigada pela ligação. Até logo!"
MAIS_ALGO = "Posso ajudar em mais alguma coisa?"

# ── Passo 5: qualidade x latência ───────────────────────────────────────────
PERFIS = {
    # URA e respostas curtas: o turno fecha cedo e a transcrição não espera a leitura de maior qualidade
    "rapido": {
        "transcription_priority": "latency",
        "turn_detection": "smart_turn",
        "early_turn": {"speculate": True, "close_on_complete_text": True},
        "vad": {"min_silence_ms": 350},
    },
    # O padrão recomendado: as duas leituras do áudio, a melhor escolhida
    "equilibrado": {
        "transcription_priority": "balanced",
        "turn_detection": "smart_turn",
        "early_turn": {"speculate": True},
    },
    # Público que fala devagar, dita números ou liga de lugares barulhentos
    "preciso": {
        "transcription_priority": "accuracy",
        "turn_detection": "smart_turn",
        "vad": {"min_silence_ms": 700},
        "barge_in": {"min_speech_ms": 300},
    },
}
PERFIL = PERFIS[os.environ.get("PERFIL", "equilibrado")]

# Palavras da clínica que o reconhecimento de fala pode não conhecer
VOCABULARIO = ["Bem Estar", "dermatologia", "ortopedia", "Unimed", "Bradesco Saúde", "SulAmérica", "Amil"]

ESPERA = WaitingOptions(
    filler_after_ms=900,
    filler_messages=["Um momento, por favor.", "Só um instante."],
    timeout_ms=20000,
    timeout_message="Desculpe, não consegui essa informação agora. Vou te passar para a recepção.",
    timeout_action="apologize",
)

# ── Camada 1: a Ermis cuida sozinha, com as frases da clínica ───────────────
GUARD = {
    "enabled": True,
    "repeat": "Desculpe, não entendi direito. Pode repetir?",
    "steer": "Vamos voltar ao seu atendimento?",
    "drift": "Entendi! Voltando ao seu atendimento:",
    "off_topic": "",  # vazio: perguntas fora do tema chegam ao código (a camada 3 responde ou transfere)
    "give_up": "Estou com dificuldade para te entender. Por favor, ligue de novo. Até logo!",
    "no_reply": "Você ainda está aí?",
    "no_reply_give_up": "Como não ouvi resposta, vou encerrar. Ligue de novo quando quiser!",
}

# ── Camada 2: respostas pré-definidas ───────────────────────────────────────
INTENCOES = [
    CustomIntent("horario", "Horário de funcionamento", "que horas abre ou fecha, se abre sábado ou feriado"),
    CustomIntent("endereco", "Endereço", "onde fica a clínica, como chegar, estacionamento"),
    CustomIntent("convenios", "Convênios", "quais planos de saúde aceita, se atende particular"),
    CustomIntent("agendar", "Agendamento", "marcar, remarcar ou cancelar consulta ou exame"),
    CustomIntent("financeiro", "Financeiro", "boleto, nota fiscal, reembolso, pagamento, cobrança"),
]
RESPOSTAS_PRONTAS = {  # intenção da clínica -> resposta fixa
    "horario": "Atendemos de segunda a sexta, das 7h às 19h, e aos sábados das 8h às 12h.",
    "endereco": "Ficamos na Avenida Paulista, 1000, sexto andar, com estacionamento no prédio.",
    "convenios": "Atendemos Unimed, Bradesco Saúde, SulAmérica e Amil, e também particular.",
}
SETORES = {  # URA: intenção da clínica -> (aviso, número para transferir)
    "agendar": ("Certo, vou te transferir para o agendamento.", "+5511900000001"),
    "financeiro": ("Certo, vou te transferir para o financeiro.", "+5511900000002"),
    "recepcao": ("Vou te transferir para a recepção.", "+5511900000000"),
}
RESPOSTAS_RAPIDAS = {  # intenção geral da Ermis (com action == "respond") -> frase pronta
    "greeting": "Oi! Em que posso ajudar?",
    "thanks": f"Por nada! {MAIS_ALGO}",
    "wait": "Claro, fico aguardando.",
    "repeat": "Claro. Como posso ajudar?",
}

# ── Camada 3: a sua IA ──────────────────────────────────────────────────────
PROMPT_IA = f"""Você é {NOME_AGENTE}, atendente virtual da {EMPRESA}, numa ligação telefônica.
Fatos da clínica: {" ".join(RESPOSTAS_PRONTAS.values())}
Especialidades: clínica geral, dermatologia e ortopedia.
Regras:
- Responda em português do Brasil, em uma ou duas frases curtas: o cliente ouve, não lê.
- Sem listas, markdown ou emojis.
- Não invente preços, horários de médicos nem resultados de exame. Se não souber, diga que vai transferir
  para a recepção e termine a resposta com [TRANSFERIR].
- Não dê orientação médica; em caso de urgência, oriente a procurar um pronto-socorro ou ligar 192."""
MARCA_TRANSFERIR = "[TRANSFERIR]"


async def responder_com_ia(historico: list[tuple[str, str]]) -> str:
    """Camada 3: recebe a conversa até aqui e devolve a próxima fala do agente."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return f"Essa eu prefiro confirmar com a recepção. {MARCA_TRANSFERIR}"
    import anthropic  # pip install anthropic

    mensagens = [{"role": "user" if quem == "cliente" else "assistant", "content": texto} for quem, texto in historico]
    while mensagens and mensagens[0]["role"] != "user":  # a conversa da IA começa pela fala do cliente
        mensagens.pop(0)
    resposta = await anthropic.AsyncAnthropic().beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=1024,
        output_config={"effort": "low"},  # respostas curtas de atendimento: menos espera
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # se o modelo recusar, outro modelo responde na mesma chamada
        system=PROMPT_IA,
        messages=mensagens,
    )
    if resposta.stop_reason == "refusal":
        return f"Essa eu prefiro confirmar com a recepção. {MARCA_TRANSFERIR}"
    return next((b.text for b in resposta.content if b.type == "text"), "").strip()


async def transferir(call_sid: str, numero: str) -> None:
    """Encaminha a ligação no Twilio. Ao trocar o TwiML, a sessão da Ermis termina sozinha.

    Com o SDK do Twilio (``pip install twilio``)::

        from twilio.rest import Client
        Client().calls(call_sid).update(twiml=f"<Response><Dial>{numero}</Dial></Response>")
    """
    log.info("Transferir %s para %s", call_sid, numero)


async def conduzir(call: Call, call_sid: str = "") -> None:
    historico: list[tuple[str, str]] = []
    destino: str | None = None  # setor da transferência, ou "fim" para só desligar

    async def falar(texto: str, **opcoes) -> None:
        historico.append(("agente", texto))
        await call.speak(texto, **opcoes)

    async def encaminhar(setor: str) -> None:
        nonlocal destino
        destino = setor
        await falar(SETORES[setor][0], allow_barge_in=False)

    async for event in call:
        if isinstance(event, SessionStarted):
            # Passo 4: a Ermis mede o ruído de fundo enquanto o cliente ouve a saudação
            historico.append(("agente", SAUDACAO))
            await call.ask(SAUDACAO, calibrate=True)

        elif isinstance(event, NoiseCalibrated):
            log.info("Ruído de fundo: %s (barulhento: %s)", event.noise_level, event.noisy)
            if event.noisy:
                await falar("Estou ouvindo bastante barulho aí. Se puder, fale mais perto do telefone.")

        elif isinstance(event, Transcript):
            if not event.handled and event.assessment.usable:  # ruído e fala ilegível: a Ermis já cuidou
                historico.append(("cliente", event.text))

        elif isinstance(event, Decision) and destino is None:
            if event.handled:  # camada 1: fala confusa ou divagação, a Ermis já respondeu
                continue
            if event.is_escape:
                if event.intent == "request_human":
                    await encaminhar("recepcao")
                else:
                    destino = "fim"
                    await falar(DESPEDIDA, allow_barge_in=False)
                continue

            # Camada 2: respostas pré-definidas e URA
            intencao = event.business_intent()
            if intencao in RESPOSTAS_PRONTAS:
                await falar(f"{RESPOSTAS_PRONTAS[intencao]} {MAIS_ALGO}")
            elif intencao in SETORES:
                await encaminhar(intencao)
            elif event.action == "respond" and event.intent in RESPOSTAS_RAPIDAS:
                await falar(RESPOSTAS_RAPIDAS[event.intent])
            else:
                # Camada 3: a sua IA
                if event.complexity >= 2:
                    await call.thinking("Deixa eu verificar isso pra você.")
                resposta = await responder_com_ia(historico)
                if MARCA_TRANSFERIR in resposta:
                    await falar(resposta.replace(MARCA_TRANSFERIR, "").strip())
                    destino = "recepcao"
                else:
                    await falar(resposta)

        elif isinstance(event, SpeakDone) and destino is not None:
            if destino != "fim":
                await transferir(call_sid, SETORES[destino][1])
            await call.end()

        elif isinstance(event, WarningEvent):
            log.warning("Aviso da Ermis: %s", event.code)

        elif isinstance(event, SessionEnded):
            log.info("Ligação encerrada (%s): %s s cobrados", event.reason, event.billed_seconds)


async def criar_sessao(transporte: str, **extras):
    """Passos 2 a 6: a mesma configuração para telefone e navegador."""
    return await ermis.sessions.create(
        transport=transporte,
        voice=VOZ,
        language="pt-BR",
        custom_intents=INTENCOES,
        vocabulary=VOCABULARIO,
        guard=GUARD,
        waiting=ESPERA,
        max_duration_s=900,
        **PERFIL,
        **extras,
    )


async def _rodar(session, call_sid: str = "") -> None:
    async with ermis.connect(session) as call:
        await conduzir(call, call_sid)


def _em_segundo_plano(session, call_sid: str = "") -> None:
    tarefa = asyncio.create_task(_rodar(session, call_sid))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)


@app.post("/twilio/voz")
async def ligacao_recebida(CallSid: str = Form(...)) -> Response:  # noqa: N803 (nome do campo do Twilio)
    """Passo 2a: o Twilio chama este webhook quando o número toca."""
    session = await criar_sessao("twilio", metadata={"call_sid": CallSid})
    _em_segundo_plano(session, CallSid)
    return Response(content=session.twiml(), media_type="application/xml")


@app.post("/ligar")
async def ligar_pelo_navegador() -> dict[str, str]:
    """Passo 2b: o botão "Ligar" do seu site. O navegador recebe só o endereço do áudio e o token."""
    session = await criar_sessao("browser", audio_format="pcm16_48k")
    _em_segundo_plano(session)
    return session.browser_credentials()
