# Prompt para assistentes de IA

Cole o prompt abaixo no seu assistente de código (Claude, ChatGPT, Cursor, Copilot...) para criar um agente de voz com o SDK da Ermis. **Antes de enviar, troque o texto entre `<<<` e `>>>` pela descrição do seu negócio.**

O prompt traz tudo o que o assistente precisa: como a Ermis funciona, a lista exata de classes e métodos do SDK, as regras de uma boa ligação, um exemplo completo e uma API simulada para testar o código sem telefone. Ele vale para o SDK **0.3.0a1**; se você usa outra versão, pegue o prompt da mesma versão no histórico deste repositório.

Ao receber o código, rode os testes que o assistente escreveu (`pytest`) e depois siga o passo 6 de [Primeiros passos](primeiros-passos.md#6-ligação-de-verdade-pelo-twilio) para ligar de verdade.

---

````text
Você vai criar um agente de voz para atendimento por telefone usando o SDK Python da Ermis Voice
(pacote `ermis-voice` 0.3.0a1, importado como `ermis`). Leia tudo antes de escrever código.

# 1. O meu negócio

<<<
Descreva aqui, em linguagem natural:
- o que a empresa faz e o que o agente resolve na ligação;
- os dados que ele precisa coletar (nome, CPF, e-mail, data...);
- as regras do negócio (horários, preços, políticas) que ele pode informar;
- horário de funcionamento e o que o agente faz fora dele;
- quando ele deve transferir para uma pessoa, e para qual número;
- se as respostas livres vêm de uma IA (qual) ou só de um roteiro.
>>>

# 2. Como a Ermis funciona

- O áudio da ligação vai do Twilio direto para a Ermis. A Ermis detecta a fala, transcreve, classifica a
  intenção, fala com voz natural, para de falar se o cliente interromper e fala frases de espera sozinha.
- O meu servidor só conduz a conversa: recebe eventos ("o cliente disse X e quer Y") e envia comandos
  ("fale Z"). O SDK é a ponte. Ele não processa áudio e não decide nada.
- A chave fica só no servidor, em `ERMIS_API_KEY`; a URL da API em `ERMIS_API_URL`. `Ermis()` lê as duas
  (sem `ERMIS_API_URL`, usa `https://api.ermis.ai`; sem chave, levanta `AuthenticationError`).
- Fluxo de uma ligação: o Twilio chama meu webhook → crio a sessão → respondo com o TwiML da sessão →
  abro o canal de controle → recebo `SessionStarted` → falo a saudação → a cada fala do cliente recebo
  `Transcript` e logo depois `Decision` → respondo com `speak()` → na despedida chamo `end()` →
  recebo `SessionEnded`.

# 3. API do SDK: use SOMENTE o que está aqui

Não invente classes, métodos, parâmetros ou eventos. Se algo de que você precisa não estiver nesta lista,
diga isso em vez de inventar.

Importações disponíveis: `from ermis import Ermis, Session, Call, CustomIntent, WaitingOptions, VadOptions,
BargeInOptions, SessionStarted, SpeechStarted, SpeechEnded, Transcript, TranscriptRevised, Assessment, Decision, SlotResult,
SpeakStarted, SpeakDone, BargeIn, WaitingSpoken, ReplyTimeout, Usage, WarningEvent, ErrorEvent,
SessionEnded, UnknownEvent, ErmisError, AuthenticationError, InsufficientCreditsError, ChannelLimitError,
RateLimitError, InvalidRequestError, SessionTimeoutError, MaxDurationError, APIError, ConnectionClosedError,
normalize_for_speech`

Cliente:
- `Ermis(api_key=None, *, base_url=None, timeout=10.0)`; feche com `await ermis.aclose()`.
- `await ermis.sessions.create(*, transport="twilio", voice=..., auto_decide=True,
  custom_intents=[CustomIntent(key, label, description), ...], vocabulary=["palavra", ...],
  transcription_priority="balanced" | "latency" | "accuracy" | "local_first" | "local_only",
  turn_detection="smart_turn" | "silence", early_turn={"speculate": True, "close_on_complete_text": True},
  vad=VadOptions(min_silence_ms=...), barge_in=BargeInOptions(enabled=..., min_speech_ms=...),
  waiting=WaitingOptions(...), max_duration_s=..., metadata={...}) -> Session`. Todos os argumentos são
  opcionais. `custom_intents`: as intenções do meu negócio; cada `Decision` já traz em `custom_intent` a
  escolhida, sem chamada extra. `vocabulary`: palavras do meu negócio (produtos, sabores, serviços); a
  transcrição chega corrigida na direção delas. `voice`: um `id` de `await ermis.voices.list()`.
- `Session`: `session_id`, `audio_url`, `control_url`, `session_token`; `session.twiml() -> str` (o TwiML
  pronto para responder ao Twilio).
- `ermis.connect(session_ou_control_url, normalize_text=True)` é um gerenciador assíncrono:
  `async with ermis.connect(session) as call:`. Com `normalize_text` (padrão), toda fala é escrita do jeito
  que se fala antes da voz: números e valores por extenso, datas, horas, CPF e telefone em grupos, e-mails
  ("arroba", "ponto"), sem markdown nem emojis.
  Aceita a `Session` ou a URL do canal de controle (texto), como a API simulada da seção 6 faz.
- `WaitingOptions(filler_after_ms=800, filler_messages=[...], filler_by_intent={intent: [...]},
  gap_after_ms=600, patience_after_ms=3500, patience_every_ms=8000, patience_messages=[...],
  timeout_ms=20000, timeout_message="...", timeout_action="apologize" | "end")`: frases que a Ermis fala
  sozinha enquanto a minha resposta não chega. Os padrões já são frases em português; mude só o necessário.

Ligação (`Call`):
- `async for event in call:` entrega os eventos até `SessionEnded`. Os comandos abaixo podem ser chamados
  de dentro do laço. As respostas de `decide` e `extract_slot` voltam como resultado da chamada e não
  aparecem no laço.
- `await call.speak(text, *, allow_barge_in=None, calibrate=None) -> str` fala e devolve o id da fala na
  hora, sem esperar o áudio. Use `calibrate=True` na saudação e `allow_barge_in=False` em avisos que não
  podem ser interrompidos (despedida, transferência).
- `await call.say(text, ...) -> bool` fala e espera terminar; `False` se o cliente interrompeu.
- `await call.expect_slot(name, type="text", *, description=None) -> asyncio.Future[SlotResult]` avisa que a
  próxima resposta do cliente traz um dado importante (endereço, e-mail, CPF, telefone). A Ermis lê essa
  resposta também com o reconhecimento de maior precisão, em segundo plano. Chame logo depois do `speak`
  da pergunta; na `Decision` da resposta, `resultado = await futuro` (`.found`, `.value`).
- `await call.set_custom_intents([...])` troca as intenções das próximas decisões (por exemplo, as opções de
  horário de uma etapa); `await call.set_vocabulary([...])` troca o vocabulário.
- `await call.decide(text, *, custom_intents=[CustomIntent(key, label, description), ...]) -> Decision`
  decide um texto avulso. Prefira `custom_intents` na sessão: a `Decision` de cada fala já vem com a escolha.
- `await call.extract_slot(text, name, type="text", *, description=None) -> SlotResult` extrai um dado
  ditado. `type`: `email`, `phone`, `number`, `cpf`, `cnpj`, `date`, `datetime`, `time`, `boolean`,
  `name`, ou `text` com `description`. Resultado: `.found` (bool), `.value` (sempre texto,
  ou `None`; números também vêm como texto, por exemplo `"2"`), `.status` (`found`, `not_found`, `rejected`). Exemplo: "ana arroba gmail ponto com" → `ana@gmail.com`.
- `await call.thinking(message=None, *, timeout_ms=None)` avisa que a resposta vai demorar: a Ermis fala
  `message` na hora (sem `message`, uma frase de espera padrão em português) e espera até `timeout_ms`.
- `await call.done_processing()` diz que não vou responder esta fala (era ruído).
- `await call.interrupt()` para a fala atual. `await call.end()` encerra a ligação.

Eventos (todos têm `.type` e `.raw`, o JSON original):
- `SessionStarted(session_id, limits)`: o áudio conectou.
- `Transcript(utterance_id, text, uncertain, assessment, latency_ms, corrections)`: o que o cliente disse
  (`corrections`: palavras ajustadas ao `vocabulary`).
  `assessment` tem `ignore` (ruído), `ask_to_repeat` (não deu para entender), `unproductive`
  ("alô alô", "teste"), `confirm` (transcrição incerta) e o atalho `usable` (verdadeiro quando nenhum de
  `ignore`, `ask_to_repeat` e `unproductive` está ligado).
- `Decision(intent, action, is_escape, complexity, custom_intent, extracted, utterance_id, id,
  custom_intent_confidence)`: o que o cliente quer. Use `decision.business_intent()` (a minha intenção, ou
  `"other"` quando a escolha não é segura), `decision.unclear` (fala confusa: peça para repetir) e
  `decision.off_topic` (assunto fora do meu negócio). Chega logo depois do `Transcript` da mesma `utterance_id` e só para falas aproveitáveis.
  `intent`: `greeting`, `name_provide`, `name_correction`, `confirm_yes`, `confirm_no`, `farewell`,
  `thanks`, `wait`, `repeat`, `unclear`, `question_product`, `question_service`, `complaint`,
  `request_human`, `complex`. `action`: `respond` (frase pronta resolve), `escalate` (precisa de IA ou de
  pessoa), `clarify` (peça para repetir). `is_escape`: o cliente quer desligar ou falar com uma pessoa.
  `Decision` NÃO tem o texto da fala: guarde `Transcript.text` por `utterance_id`.
- `TranscriptRevised(utterance_id, text, previous)`: a leitura precisa de uma resposta pedida com
  `expect_slot` mudou o texto (só informativo; o valor vem no `SlotResult`).
- `SpeakStarted(id, chars)`, `SpeakDone(id, chars)`: início e fim de uma fala do agente.
- `BargeIn(id)`: o cliente interrompeu (a Ermis já parou de falar; não faça nada).
- `WaitingSpoken(utterance_id, kind, text)`, `ReplyTimeout(utterance_id, action)`, `Usage(...)`,
  `WarningEvent(code, message)`, `ErrorEvent(code, message)`: avisos; registre em log.
- `SessionEnded(reason, billed_seconds, credits)`: fim da ligação.
- `UnknownEvent`: qualquer outro tipo; ignore.

Comandos que o SDK envia pelo canal de controle (JSON; útil para os testes): `speak` → `{"type": "speak", "id",
"text", "allow_barge_in"?, "calibrate"?}`; `thinking` → `{"type": "thinking", "message"?, "timeout_ms"?}`;
`decide` → `{"type": "decide", "id", "text", "custom_intents"?}`; `extract_slot` → `{"type": "extract_slot",
"id", "text", "slot": {"name", "type", "description"?}}`; `expect_slot` → `{"type": "expect_slot", "id", "slot":
{"name", "type", "description"?}}` (a resposta é um `slot` com o mesmo `id`); `set_custom_intents` e
`set_vocabulary`; `done_processing`, `interrupt` e `end` → `{"type": ...}`.

Erros: todas as exceções herdam de `ErmisError` (`message`, `code`, `status`, `request_id`).
`InsufficientCreditsError` (sem créditos), `ChannelLimitError` (canais do plano em uso), `RateLimitError`
(muitas requisições), `AuthenticationError`, `InvalidRequestError`, `ConnectionClosedError`.

# 4. Regras de uma boa ligação

As regras do meu negócio (seção 1) têm prioridade sobre as regras abaixo.

1. Saudação no `SessionStarted`, com `calibrate=True`, curta e dizendo o que o agente resolve.
2. Em todo `Transcript`: se `assessment.ignore`, chame `done_processing()`; se não for `usable`, peça para
   repetir. Conte como falha também `Decision` com `decision.unclear` (fala confusa: peça para repetir e não
   aja sobre ela); zere o contador quando a conversa avançar. Depois de 3 falhas
   seguidas, despeça-se e encerre (ou transfira, se o negócio pedir).
3. Decida a resposta no `Decision`, nunca comparando o texto com palavras. Passe os assuntos do meu negócio
   em `custom_intents` na sessão e use `decision.business_intent()` em vez de `intent`: "minha internet caiu"
   pode chegar como `intent == "complaint"` e ainda assim ser algo que o agente resolve. Use
   `decision.off_topic` só depois de tentar ler o que a etapa precisa (uma resposta como "sexta-feira" também
   chega sem intenção do negócio): aí diga em uma frase o que o agente resolve e repita a pergunta. Passe
   em `vocabulary` as palavras do negócio que o reconhecimento pode errar (nomes de produtos, sabores,
   serviços). Para dados ditados importantes (endereço, e-mail, CPF, telefone), `expect_slot` logo depois
   da pergunta; para os outros, `extract_slot`.
4. `intent == "request_human"` (com ou sem `is_escape`): avise e transfira para uma pessoa (veja a regra 9). Com
   `intent == "farewell"` (despedida), ou outro `intent` com `is_escape`: despeça-se, com
   `allow_barge_in=False`, e chame `end()` no `SpeakDone` dessa fala. Transfira também nas situações que a
   seção 1 pedir (por exemplo, reclamação, que chega como `intent == "complaint"`).
5. Confirme dados importantes antes de gravar ("Vou agendar para sexta às 14h. Está certo?") e trate
   `confirm_yes` e `confirm_no`.
6. Uma fala por turno: junte confirmação e pergunta num só `speak()` ("Certo, anotei. Qual é o endereço?").
   Respostas curtas e faladas: no máximo duas frases, sem listas. Números, valores e e-mails podem ir
   escritos normalmente ("R$ 49,90"): o SDK escreve do jeito que se fala antes da voz. Nunca invente informação do negócio que não esteja na seção 1.
7. Se a resposta depende de algo lento (sistema externo, IA), chame `thinking(...)` antes.
8. Uma tarefa por ligação: crie a sessão no webhook, rode a conversa em `asyncio.create_task` e guarde a
   referência da tarefa até ela terminar.
9. Transferência no Twilio: fale o aviso com `allow_barge_in=False`; no `SpeakDone` dele, chame
   `transferir(call_sid, numero)`, uma função que eu possa trocar, com
   `twilio.rest.Client().calls(call_sid).update(twiml="<Response><Dial>NUMERO</Dial></Response>")`
   (importe `twilio` dentro dela, assim os testes não precisam do pacote). **Depois de transferir, não chame
   `end()`; saia do laço (`return`).** Sair do laço só fecha o canal de controle e é seguro: a sessão da Ermis
   termina sozinha quando o Twilio troca o TwiML e fecha o áudio. No Twilio, `end()` desliga a ligação,
   então chamar `end()` antes de transferir derruba o cliente. O `call_sid` vem do webhook (`CallSid`):
   passe para `conduzir(call, call_sid=...)`.

# 5. Exemplo de referência

```python
import asyncio
from fastapi import FastAPI, Form, Response
from ermis import Call, CustomIntent, Decision, Ermis, SessionStarted, SpeakDone, Transcript

app = FastAPI()
ermis = Ermis()
_tarefas: set[asyncio.Task] = set()
PEDIDOS = [CustomIntent("marcar", "Marcar consulta", "Agendar uma consulta nova"),
           CustomIntent("cancelar", "Cancelar consulta", "Desmarcar uma consulta")]

async def conduzir(call: Call) -> None:
    falas: dict[str, str] = {}
    etapa, encerrando, falhas = "pedido", False, 0
    telefone = None  # o valor pedido com expect_slot
    async for event in call:
        if isinstance(event, SessionStarted):
            await call.speak("Olá! Você ligou para a Clínica Exemplo. Quer marcar ou cancelar?", calibrate=True)
        elif isinstance(event, Transcript):
            if event.assessment.ignore:
                await call.done_processing()
            elif not event.assessment.usable:
                falhas += 1
                if falhas >= 3:
                    encerrando = True
                    await call.speak("Não estou conseguindo ouvir. Ligue de novo, por favor.", allow_barge_in=False)
                else:
                    await call.speak("Desculpe, não entendi. Pode repetir?")
            else:
                falhas = 0
                falas[event.utterance_id] = event.text
        elif isinstance(event, Decision) and not encerrando:
            texto = falas.get(event.utterance_id or "", "")
            if event.is_escape:
                encerrando = True
                await call.speak("Obrigada pela ligação. Até logo!", allow_barge_in=False)
            elif event.unclear:
                await call.speak("Desculpe, não entendi. Pode repetir?")
            elif etapa == "pedido":
                if event.business_intent() == "marcar":
                    etapa = "dia"
                    await call.speak("Claro! Para qual dia?")
                elif event.off_topic:  # só depois de tentar ler o que a etapa precisa
                    await call.speak("Aqui eu marco e cancelo consultas. Quer marcar ou cancelar?")
                else:
                    await call.speak("Posso marcar ou cancelar consultas. O que você prefere?")
            elif etapa == "dia":
                dia = await call.extract_slot(texto, "dia", "date")
                if dia.found:
                    etapa = "telefone"
                    await call.speak(f"Anotado: {dia.value}. Qual é o seu telefone?")
                    telefone = await call.expect_slot("telefone", "phone")
                elif event.off_topic:
                    await call.speak("Aqui eu marco consultas. Para qual dia você prefere?")
                else:
                    await call.speak("Qual dia você prefere?")
            elif etapa == "telefone":
                numero = await telefone
                await call.speak(f"Obrigada! Vou confirmar pelo {numero.value}." if numero.found else "Pode repetir o telefone?")
        elif isinstance(event, SpeakDone) and encerrando:
            await call.end()

async def _rodar(session) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call)

@app.post("/twilio/voz")
async def ligacao(CallSid: str = Form(...)) -> Response:
    session = await ermis.sessions.create(
        transport="twilio", custom_intents=PEDIDOS, vocabulary=["consulta", "retorno"], metadata={"call_sid": CallSid}
    )
    tarefa = asyncio.create_task(_rodar(session))
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)
    return Response(content=session.twiml(), media_type="application/xml")
```

# 6. API simulada para testes

Use esta API simulada nos testes (pytest com `pytest-asyncio` em `asyncio_mode = "auto"` e o pacote
`websockets`). Ela faz o papel do cliente: a cada fala do agente, envia a próxima fala do roteiro
(`Transcript` + `Decision`, já com o `custom_intent` de `decisoes`) e responde a `decide`, `extract_slot` e
`expect_slot`. Por isso o agente deve falar uma vez
por turno (regra 6); falas com `allow_barge_in=False` (despedida, aviso de transferência) não puxam uma
nova fala. Ela não envia `session.ended` depois de uma transferência: o agente sai do laço sozinho.

```python
import asyncio, json
from websockets.asyncio.server import serve

async def simular(modulo, falas, decisoes, slots, **kwargs):
    """falas: [(texto, intent, is_escape)] ou [(texto, intent, is_escape, assessment)], com assessment como
    {"ask_to_repeat": True} para uma fala não entendida (aí não vem Decision). decisoes: {texto: custom_intent};
    slots: {nome: valor ou None}. Devolve os comandos que o agente enviou (dicts com "type")."""
    recebidos, pendentes = [], list(falas)

    async def api(ws):
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        n = 0
        async for raw in ws:
            msg = json.loads(raw)
            recebidos.append(msg)
            if msg["type"] == "decide":
                await ws.send(json.dumps({"type": "decision", "id": msg["id"], "intent": "complex",
                    "action": "escalate", "custom_intent": decisoes.get(msg["text"], "other")}))
            elif msg["type"] in ("extract_slot", "expect_slot"):
                valor = slots.get(msg["slot"]["name"])
                await ws.send(json.dumps({"type": "slot", "id": msg["id"], "value": valor,
                    "status": "found" if valor else "not_found"}))
            elif msg["type"] == "speak":
                await ws.send(json.dumps({"type": "speak.done", "id": msg["id"], "chars": len(msg["text"])}))
                if msg.get("allow_barge_in") is False or not pendentes:
                    continue
                texto, intent, escape, *resto = pendentes.pop(0)
                avaliacao = resto[0] if resto else {}
                n += 1
                await ws.send(json.dumps({"type": "transcript", "utterance_id": f"u{n}", "text": texto,
                    "assessment": avaliacao}))
                if not any(avaliacao.get(k) for k in ("ignore", "ask_to_repeat", "unproductive")):
                    await ws.send(json.dumps({"type": "decision", "utterance_id": f"u{n}",
                        "intent": intent, "action": "escalate", "is_escape": escape,
                        "custom_intent": decisoes.get(texto, "other"), "custom_intent_confidence": 1.0}))
            elif msg["type"] == "end":
                await ws.send(json.dumps({"type": "session.ended", "reason": "client"}))
                return

    async with serve(api, "127.0.0.1", 0) as server:
        porta = server.sockets[0].getsockname()[1]
        async with modulo.ermis.connect(f"ws://127.0.0.1:{porta}/control") as call:
            await asyncio.wait_for(modulo.conduzir(call, **kwargs), timeout=5)
    return recebidos
```

Outros comandos (`thinking`, `done_processing`...) são registrados e ignorados. Nos testes, defina
`ERMIS_API_KEY` (qualquer valor) antes de importar o módulo do agente, e troque por funções falsas
(monkeypatch) tudo o que acessa sistemas externos: IA, banco, agenda, transferência.

# 7. O que entregar

1. `agente.py`: o agente completo, no formato do exemplo da seção 5 (FastAPI, webhook `POST /twilio/voz`,
   função `conduzir(call)`), com o fluxo do meu negócio. Deixe as integrações externas (IA, banco,
   transferência) em funções pequenas e fáceis de trocar, com dados de exemplo.
2. `test_agente.py`: testes com a API simulada da seção 6 cobrindo o caminho feliz, uma fala não entendida
   (com `{"ask_to_repeat": True}`), a despedida no meio da conversa e o pedido de atendente (transferência
   sem `end()`).
3. `pytest.ini` com `[pytest]` e `asyncio_mode = auto`.
4. As instruções para rodar: `pip install ermis-voice fastapi uvicorn python-multipart pytest
   pytest-asyncio twilio` (o `websockets` usado nos testes já vem com o `ermis-voice`), as variáveis `ERMIS_API_KEY` e `ERMIS_API_URL` (e `TWILIO_ACCOUNT_SID` e
   `TWILIO_AUTH_TOKEN` para transferir), `pytest`, `uvicorn agente:app --port 8000`, e como apontar o
   webhook de voz do número do Twilio para `https://<host>/twilio/voz`.

Antes de responder, confira se o código usa só o que está na seção 3.
````
