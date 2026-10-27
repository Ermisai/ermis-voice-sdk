# Ermis Voice API — documentação (prévia)

> **Prévia.** Esta API ainda está em desenvolvimento. Endpoints, nomes de campos e preços podem mudar até o lançamento.

A Ermis Voice API coloca um agente de voz em tempo real na sua ligação. Você conecta o áudio (Twilio, navegador ou seu próprio servidor) e recebe, a cada fala do seu cliente, **o que ele disse** e **o que ele quer**. Você decide a resposta e a Ermis fala por você, com voz natural em streaming, parando na hora se o cliente interromper.

Tudo roda na Ermis: detecção de fala, transcrição, decisões e voz. Você paga por minuto de sessão, com tudo incluído.

## Sumário

- [Início rápido](#início-rápido)
- [Autenticação](#autenticação)
- [Sessões (REST)](#sessões-rest)
- [Canal de controle (WebSocket)](#canal-de-controle-websocket)
- [Decisões e extração de dados](#decisões-e-extração-de-dados)
- [Enquanto a sua IA pensa](#enquanto-a-sua-ia-pensa)
- [Conectando a sua IA](#conectando-a-sua-ia)
- [Conectando o áudio](#conectando-o-áudio)
- [Erros e limites](#erros-e-limites)
- [Boas práticas](#boas-práticas)
- [Perguntas frequentes: qualidade e latência](#perguntas-frequentes-qualidade-e-latência)
- [Exemplo completo](#exemplo-completo)

## Início rápido

Um atendente por telefone com o Twilio, em quatro passos.

**1. Gere uma chave de API** na plataforma da Ermis (página Tokens API), com acesso ao Ermis Voice. Use a chave só no seu servidor. Para conferir a chave e os créditos: `GET /v1/account/balance`.

**2. Quando a ligação chegar, crie uma sessão:**

```bash
curl https://voice-api.live.ermis.ai/v1/voice/v0.4.6/sessions \
  -H "Authorization: Bearer $ERMIS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"transport": "twilio", "voice": "Sarah", "auto_decide": true}'
```

```json
{
  "session_id": "vs_8f2c1a",
  "audio_url": "wss://voice-api.live.ermis.ai/v1/voice/v0.4.6/twilio",
  "control_url": "wss://voice-api.live.ermis.ai/v1/voice/v0.4.6/sessions/vs_8f2c1a/control",
  "session_token": "st_…"
}
```

**3. Responda ao Twilio com o TwiML** que manda o áudio da ligação para a Ermis:

```xml
<Response>
  <Connect>
    <Stream url="wss://voice-api.live.ermis.ai/v1/voice/v0.4.6/twilio">
      <Parameter name="session_token" value="st_…" />
    </Stream>
  </Connect>
</Response>
```

**4. Conduza a conversa pelo canal de controle.** Conecte em `control_url` com a sua chave e responda aos eventos:

```python
async with connect(control_url, additional_headers={"Authorization": f"Bearer {API_KEY}"}) as ws:
    async for message in ws:
        event = json.loads(message)
        if event["type"] == "session.started":
            await ws.send(json.dumps({"type": "speak", "id": "r1", "text": "Olá! Como posso ajudar?"}))
        elif event["type"] == "decision":
            reply = await sua_ia(event)            # seu roteiro ou sua IA
            await ws.send(json.dumps({"type": "speak", "id": "r2", "text": reply}))
        elif event["type"] == "session.ended":
            break
```

Pronto: o seu cliente liga, ouve a saudação, fala, e a sua aplicação responde.

### Com o SDK Python

O SDK `ermis` faz os mesmos passos sem JSON à mão: cria a sessão, gera o TwiML e entrega os eventos como objetos.

```python
from ermis import Ermis, SessionStarted, Decision

ermis = Ermis()  # lê ERMIS_API_KEY
session = await ermis.sessions.create(transport="twilio", auto_decide=True)
twiml = session.twiml()

async with ermis.connect(session) as call:
    async for event in call:
        if isinstance(event, SessionStarted):
            await call.speak("Olá! Como posso ajudar?", calibrate=True)
        elif isinstance(event, Decision):
            await call.speak(await sua_ia(event))
```

O SDK não processa áudio nem decide nada: quem conduz a ligação é a Voice API. Referência completa no [README do SDK](../README.md).

## Autenticação

| Credencial | Onde usar | Validade |
|---|---|---|
| **Chave de API** (criada na plataforma) | Só no seu servidor: REST e canal de controle, no header `Authorization: Bearer <chave>` | Até você revogar no painel |
| **Token de sessão** (`st_…`) | Onde o áudio nasce (Twilio ou navegador), para conectar o áudio de **uma** sessão | Uso único; expira se não for usado em 5 minutos |

Nunca coloque a chave de API no navegador ou no aplicativo do usuário. Use o token de sessão.

## Sessões (REST)

Base: `https://voice-api.live.ermis.ai`. As rotas de voz levam a versão do motor depois de `/v1/voice`: `/v1/voice/v0.4.6/sessions` é a 0.4.6 (`v1` é a versão da API HTTP; `v0.4.6`, a do motor de voz), e o SDK de mesmo número usa a dele. Sem versão (`/v1/voice/sessions`), é a mais nova. `GET /health` lista as versões disponíveis (`versions`); uma versão que não existe responde `404 version_not_available`. Nas tabelas abaixo, `/v1/voice/...` vale também com a versão.

| Método e caminho | O que faz |
|---|---|
| `POST /v1/voice/sessions` | Cria uma sessão |
| `GET /v1/voice/voices` | Vozes disponíveis para o campo `voice` ([ver abaixo](#vozes)) |
| `GET /v1/voice/sessions/{session_id}` | Estado da sessão e segundos cobrados até agora |
| `DELETE /v1/voice/sessions/{session_id}` | Encerra a sessão |
| `GET /v1/usage?limit=50&before=123` | Lançamentos de crédito em `entries`; use `next_cursor` como o próximo `before` |
| `GET /v1/account/balance` | `balance`, `reserved_credits` e `available_credits` |

### Criar sessão

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `transport` | string | `websocket` | Como o áudio chega: `twilio`, `browser` ou `websocket` ([detalhes](#conectando-o-áudio)) |
| `audio_format` | string | `mulaw_8k` | Formato do áudio que a Ermis devolve: `mulaw_8k` (telefonia) ou `pcm16_48k` (navegador) |
| `language` | string | `pt-BR` | Idioma da conversa |
| `voice` | string | a voz padrão da conta | Voz do agente: um `id` de `GET /v1/voice/voices`. Uma voz desconhecida devolve `400` |
| `auto_decide` | bool | `true` | Cada fala do cliente já vem com o evento `decision` |
| `partial_transcripts` | bool | `false` | Envia `transcript.partial` com o texto parcial enquanto o cliente ainda fala |
| `transcription_priority` | string | `balanced` | `balanced`, `latency` (transcrição mais rápida, menos precisa), `accuracy` (confere falas duvidosas), `local_first` (a leitura de maior qualidade só nas falas em que o reconhecimento rápido ficou em dúvida) ou `local_only` (só o reconhecimento rápido). Ver [perguntas frequentes](#perguntas-frequentes-qualidade-e-latência) |
| `precise_wait_ms` | inteiro | `0` | Com `latency` e `local_first`: quanto uma resposta marcada como importante (`precise`, `slot`) espera a leitura de maior qualidade, em ms (0 a 3000). `0` (padrão): não espera; a leitura precisa chega depois, como revisão. As outras prioridades sempre esperam |
| `turn_detection` | string | `smart_turn` | `smart_turn`: um modelo ouve como a fala termina e fecha o turno antes do silêncio completo quando a pessoa terminou; `silence`: só o silêncio de `vad.min_silence_ms` |
| `vad.min_silence_ms` | int | `400` | Silêncio que encerra a fala do cliente |
| `early_turn.speculate` | bool | `false` | Começa a transcrever (e a decidir) já na pausa do cliente, antes de o turno fechar. Se o cliente voltar a falar, esse trabalho é descartado |
| `early_turn.pause_ms` | int | `160` | Pausa que inicia esse trabalho adiantado (60 a 1000) |
| `early_turn.close_on_complete_text` | bool | `false` | Fecha o turno assim que o texto já é um pedido completo, sem esperar todo o silêncio. Frases que terminam abertas ("o meu e-mail é", números sendo ditados) continuam esperando |
| `barge_in.enabled` | bool | `true` | Permite que o cliente interrompa o agente |
| `barge_in.min_speech_ms` | int | `150` | Fala contínua necessária para interromper |
| `max_duration_s` | int | `1800` | Duração máxima da sessão |
| `vocabulary` | lista | `[]` | Palavras do seu negócio (sabores, serviços, produtos; até 200). Quando o cliente fala uma delas e a transcrição sai parecida ("marquerita"), o texto já chega corrigido ("margherita"), antes das decisões ([ver abaixo](#vocabulário-do-seu-negócio)) |
| `guard` | objeto | desligado | A Ermis responde sozinha a fala confusa, à divagação e ao assunto fora do tema, com as frases do seu negócio, e volta à pergunta atual ([ver abaixo](#fluxo-da-conversa-decidido-pela-ermis)) |
| `custom_intents` | lista | `[]` | Intenções do seu negócio (`key`, `label`, `description`; até 20). Cada decisão automática já traz `custom_intent` com a escolhida, sem pedido extra ([ver abaixo](#intenções-customizadas)) |
| `waiting` | objeto | [ver abaixo](#enquanto-a-sua-ia-pensa) | Mensagens de espera e tempo limite enquanto a sua IA prepara a resposta |
| `metadata` | objeto | `{}` | Seus dados (id da ligação, do cliente…). Voltam nos eventos e no relatório de uso |

Resposta `201`: `session_id`, `audio_url`, `control_url`, `session_token`.

### Vozes

`GET /v1/voice/voices` lista as vozes que a sua conta pode usar, pelo nome. Use o `id` no campo `voice` ao criar a sessão. No SDK: `await ermis.voices.list()`.

```json
{
  "voices": [
    {"id": "Alex", "name": "Alex", "gender": "male", "language": "pt-BR", "description": "Voz padrão, brasileira natural", "production": true, "default": true},
    {"id": "Sarah", "name": "Sarah", "gender": "female", "language": "pt-BR", "description": "…", "production": true, "default": false}
  ],
  "default": "Alex"
}
```

A mesma voz fala em dois níveis, escolhidos pela prioridade da sessão: com `transcription_priority` igual a `latency`, o mais rápido (primeiro áudio em ~50–85 ms); nas demais, o de mais qualidade (~120–210 ms). `man` e `woman`, os nomes de antes (até a API 0.3), continuam aceitos como Alex e Sarah.

Vozes com `production: false` servem só para testes e não devem ser usadas com clientes reais. Sem `voice`, a sessão usa a voz `default`.

## Canal de controle (WebSocket)

Conecte em `control_url` com a chave de API. Todas as mensagens são JSON.

### O que você envia

| Mensagem | Efeito |
|---|---|
| `{"type": "speak", "id": "r1", "text": "…"}` | O agente fala. Campos opcionais: `voice`, `allow_barge_in` (padrão `true`), `calibrate` (use `true` na primeira fala) |
| `{"type": "ask", "id": "q1", "text": "De qual sabor?", "choices": […], "precise": true}` | Uma pergunta: fala como `speak` e vira a **pergunta atual** (o `guard` a repete depois de um desvio). Opcionais: `choices` (as respostas esperadas, `key`/`label`/`description`: a `decision` traz `choice`), `precise` (como `expect_precise`) e `slot` (como `expect_slot`, com o `id` da pergunta) ([ver abaixo](#fluxo-da-conversa-decidido-pela-ermis)) |
| `{"type": "interrupt"}` | Para a fala atual do agente |
| `{"type": "decide", "id": "d1", "text": "…", "custom_intents": […]}` | Pede uma decisão, com intenções suas ([ver abaixo](#intenções-customizadas)) |
| `{"type": "extract_slot", "id": "s1", "text": "…", "slot": {"name": "email", "type": "email"}}` | Extrai um dado da fala |
| `{"type": "expect_slot", "id": "e1", "slot": {"name": "endereco", "type": "address"}}` | A próxima resposta do cliente traz esse dado. A Ermis lê essa fala também com o reconhecimento de maior precisão, em segundo plano, e manda o `slot` com o valor (ver [Dados importantes](#dados-importantes-endereço-e-mail-documentos)) |
| `{"type": "expect_precise"}` | A próxima resposta precisa ser exata (um item do cardápio, um tamanho, uma quantidade): a `transcript` e a `decision` dela saem do reconhecimento de maior precisão. Leva um pouco mais (a espera por essa leitura), só nessa fala ([ver abaixo](#dados-importantes-endereço-e-mail-documentos)) |
| `{"type": "set_custom_intents", "custom_intents": […]}` | Troca as intenções suas avaliadas nas próximas decisões automáticas (por exemplo, a cada etapa da conversa); `[]` desliga |
| `{"type": "set_vocabulary", "vocabulary": […]}` | Troca o vocabulário das próximas falas; `[]` desliga |
| `{"type": "thinking", "message": "…", "timeout_ms": 45000}` | A resposta vai demorar: o agente fala `message` agora e espera até `timeout_ms` neste turno ([ver abaixo](#avisar-que-vai-demorar-thinking)) |
| `{"type": "done_processing"}` | Você decidiu não responder esta fala (por exemplo, era ruído). O agente volta a ouvir |
| `{"type": "end"}` | Encerra a sessão |

`speak.text` aceita até 5.000 caracteres. Textos longos começam a tocar antes de terminar de ser gerados.

### O que você recebe

| Evento | Quando | Campos principais |
|---|---|---|
| `session.started` | Áudio conectado | `session_id`, `limits` |
| `speech.started` | O cliente começou a falar | — |
| `speech.ended` | O cliente parou de falar | `duration_ms` |
| `transcript` | Fala transcrita | `utterance_id`, `text`, `uncertain`, `assessment`, `latency_ms`; `corrections` quando palavras foram ajustadas ao seu `vocabulary` |
| `decision` | Decisão sobre a fala (com `auto_decide` ou após `decide`) | `utterance_id` ou `id`, `intent`, `action`, `is_escape`, `complexity`, `custom_intent`, `extracted` |
| `slot` | Resposta a `extract_slot` ou a `expect_slot` (com `utterance_id`) | `id`, `value`, `status` (`found`, `not_found` ou `rejected`: a fala não responde ao que foi pedido) |
| `transcript.partial` | O texto até agora, enquanto o cliente fala (com `partial_transcripts`) | `utterance_id`, `text`. No SDK: `TranscriptPartial` |
| `transcript.revised` | A leitura de maior precisão de uma fala ficou diferente: com `expect_slot`, ou com prioridade de latência (a conversa não esperou por ela) | `utterance_id`, `text`, `previous` |
| `speak.started` / `speak.done` | Início e fim de uma fala do agente | `id`, `chars` |
| `barge_in` | O cliente interrompeu o agente | `id` da fala interrompida |
| `waiting` | O agente falou uma mensagem de espera | `utterance_id`, `kind` (`filler`, `patience`, `timeout`), `text` |
| `reply_timeout` | A sua resposta não chegou a tempo | `utterance_id`, `action` (`apologize` ou `end`) |
| `usage` | A cada 60 s | `billed_seconds`, `credits`, `balance` |
| `no_reply` | O cliente ficou calado depois da fala do agente (`guard`) | `count` (silêncios seguidos), `handled` (`true`: a Ermis já falou `guided_text`; não responda), `guided_text`. No SDK: `NoReply` |
| `noise.calibrated` | Terminou a medição do ruído de fundo (fala com `calibrate`) | `noise_level`, `noise_floor`, `samples`, `noisy` (com o `guard` `too_noisy`, a Ermis avisa e encerra). No SDK: `NoiseCalibrated` |
| `warning` | Algo pede atenção | `code`: `credits_low`, `noisy_environment`, `max_duration_soon`, `late_reply` (um `speak` chegou depois do tempo limite e foi descartado) |
| `error` | Mensagem inválida ou falha | `code`, `message` |
| `session.ended` | Fim da sessão | `reason`, `billed_seconds`, `credits` |

### A avaliação da transcrição (`assessment`)

Cada `transcript` diz se vale a pena agir sobre a fala:

| Campo | Significa | O que fazer |
|---|---|---|
| `ignore` | Foi ruído, não uma fala | Não responda; envie `done_processing` |
| `ask_to_repeat` | Houve fala, mas não deu para entender | "Desculpe, não entendi. Pode repetir?" |
| `unproductive` | "alô alô alô", "teste", uma palavra repetida | Peça para repetir; encerre depois de algumas vezes |
| `confirm` | A transcrição é incerta | Confirme: "Você disse …?" |

Com `auto_decide`, o evento `decision` só vem para falas aproveitáveis (sem `ignore`, `ask_to_repeat` ou `unproductive`).

## Decisões e extração de dados

A Ermis classifica cada fala em milissegundos. Você usa a decisão para escolher a resposta sem esperar a sua IA quando não precisa.

### Campos da decisão

| Campo | Valores |
|---|---|
| `intent` | `greeting`, `name_provide`, `name_correction`, `confirm_yes`, `confirm_no`, `farewell`, `thanks`, `wait`, `repeat`, `unclear`, `question_product`, `question_service`, `complaint`, `request_human`, `complex` |
| `action` | `respond`: dá para responder na hora com uma frase pronta · `escalate`: precisa da sua IA ou de um humano · `clarify`: peça para repetir |
| `is_escape` | `true` quando o cliente quer desligar ou falar com uma pessoa |
| `complexity` | De 0 (cumprimento, confirmação) a 2 (problema, reclamação, pedido de ação). Com `action`, diz quando vale chamar a sua IA: veja [Quando chamar a sua IA](#quando-chamar-a-sua-ia) |
| `custom_intent` | A chave escolhida entre as suas intenções, ou `other` |
| `custom_intent_confidence` | De 0 a 1: quanto a escolha de `custom_intent` é segura. Frases truncadas ou fora do assunto que ainda caem numa intenção sua vêm baixas (abaixo de 0,8): trate como `other` |
| `answer` | `yes`, `no` ou `null`: o sim/não da fala como resposta à última pergunta do agente ("já reiniciei e nada" para "já tentou reiniciar o modem?" é `yes`; "eu não quero calabresa, quero quatro queijos" é mudança de pedido, não um "não") |
| `guidance` | `unclear` (fala confusa), `drifting` (divagação), `off_topic` (pergunta fora do seu negócio) ou `null` (uma resposta para o seu roteiro) |
| `handled` / `guided_text` | Com o `guard`: `true` quando a Ermis já respondeu a fala (o que ela disse vem em `guided_text`); o seu agente não responde |
| `choice` / `choice_confidence` | Com `ask` e `choices`: a resposta esperada que o cliente quis dizer (ou `none`) e o quanto a escolha é segura (use a partir de 0,8) |
| `extracted.name` | Nome do cliente, quando ele se apresenta ou corrige o nome |



**`expect_slot` ou `expect_precise`?** Use `expect_slot` quando o que você precisa é o dado (endereço, e-mail, CPF): a conversa não espera e o valor chega depois. Use `expect_precise` quando a resposta inteira precisa estar certa para você decidir o que fazer, como um sabor ou um tamanho ditos em uma ou duas palavras ("chocolate", "uma pequena"): a `transcript` e a `decision` dessa fala já saem da leitura de maior precisão, ao custo de alguns décimos de segundo nessa fala. Envie logo depois da pergunta; vale só para a próxima resposta. No SDK: `await call.expect_precise()`.

No SDK: `valor = await call.expect_slot("endereco", "address")` devolve um `Future`; dê `await valor` na `Decision` da resposta. `TranscriptRevised` traz a frase corrigida.



No SDK: `valor = await call.expect_slot("endereco", "address")` devolve um `Future`; dê `await valor` na `Decision` da resposta. `TranscriptRevised` traz a frase corrigida.

### Fluxo da conversa decidido pela Ermis

O seu roteiro guarda as respostas e as perguntas do negócio; o que acontece entre elas fica com a Ermis:

1. **Pergunte com `ask`**, não com `speak`. A pergunta vira a pergunta atual e pode levar as respostas esperadas:
   ```json
   {"type": "ask", "id": "q3", "text": "De qual sabor?", "precise": true,
    "choices": [{"key": "calabresa", "label": "calabresa"}, {"key": "chocolate", "label": "chocolate", "description": "a pizza doce"}]}
   ```
   A `decision` da resposta traz `choice` (aqui, `chocolate`) e `choice_confidence`. A Ermis entende respostas mal transcritas ou ditas de outro jeito ("pit sapequena dissocolate", "aquela doce") e, quando não tem certeza, devolve confiança baixa em vez de chutar. Medido: nenhuma escolha errada com confiança de 0,8 ou mais, e a mesma latência sem `choices`.
2. **Ligue o `guard`** com as frases do seu negócio:
   ```json
   "guard": {"enabled": true, "repeat": "Desculpa, não entendi direito. Pode repetir?",
             "steer": "Vamos voltar ao seu pedido?", "drift": "Tá bom! Voltando ao seu pedido:",
             "off_topic": "Isso eu não sei te dizer, aqui eu cuido dos pedidos.",
             "give_up": "Tô com dificuldade pra te entender. Tenta ligar de novo, por favor.", "max_unclear": 3}
   ```
   Fala confusa: a Ermis pede para repetir; na segunda seguida, volta à pergunta atual ("Vamos voltar ao seu pedido? De qual sabor?"); na terceira (`max_unclear`), diz `give_up` e encerra (ou só avisa, com `"on_give_up": "notify"`, para você transferir). Divagação e assunto fora do tema: a frase do negócio e a pergunta atual. `"drift": ""` deixa a divagação com o seu agente (útil para uma IA de conversa aberta). **Cliente calado:** se ninguém fala por `no_reply_ms` (padrão 8000; `0` desliga) depois que o agente termina de falar, a Ermis pergunta `no_reply` ("Você ainda está aí?") e repete a pergunta atual; no `max_no_reply`º silêncio seguido (padrão 2) diz `no_reply_give_up` e encerra (`reason: "no_reply"`), ou só avisa com `"on_no_reply": "notify"`. O agente falando ou pensando não conta. **Ruído:** com `"too_noisy": "…"`, se a medição da saudação (`calibrate`) acusar ambiente alto demais, a Ermis diz a frase e encerra (`reason: "too_noisy"`). A expectativa da pergunta (`precise`, `slot`, `choices`) vale de novo para a próxima resposta. Nessas falas a `decision` chega com `handled: true`: não responda.
3. **Use `answer`** para sim/não, não o `intent` (`confirm_yes`/`confirm_no` vem também em frases que são outra coisa).

No SDK: `question = await call.ask(texto, choices=[...], precise=True, slot=(...))`; na `Decision`: `handled`, `guided_text`, `answer`, `chosen()` e `guidance`.

### Vocabulário do seu negócio

O reconhecimento de fala conhece o português do dia a dia, mas não o seu cardápio, os seus serviços ou os nomes dos seus produtos. Liste essas palavras em `vocabulary` ao criar a sessão: quando a transcrição sair parecida com uma delas pelo som ("marquerito", "carabeço"), a Ermis troca pela palavra certa ("margherita", "calabresa") antes das decisões. Assim as intenções, a extração de dados e o seu código recebem o texto já certo.

```json
{"transport": "twilio", "vocabulary": ["margherita", "calabresa", "quatro queijos", "frango com catupiry"]}
```

O `transcript` traz em `corrections` o que foi ajustado (`heard`, `term`, `score`). Palavras comuns, números e nomes de pessoas não são trocados. Use termos que o cliente fala, não códigos internos.

No SDK: `sessions.create(vocabulary=[...])` e `call.set_vocabulary([...])`; `Transcript.corrections` traz o que foi ajustado.

### Fala confusa ou fora do assunto

- **Fala confusa** (transcrição ruim, frase sem sentido): a `decision` vem com `action` igual a `clarify`. Peça para repetir quando, além disso, a fala não trouxer nenhuma intenção sua com segurança (`custom_intent` `other` ou `custom_intent_confidence` abaixo de 0,8). Respostas curtas e válidas ("grande", "não, só isso") também podem vir com `clarify`, por isso olhe as duas coisas.
- **Fora do assunto** ("vocês vendem celular?", "vai chover amanhã?"): `custom_intent` vem `other` com confiança alta e `action` diferente de `clarify`. Diga educadamente o que o agente faz e volte à pergunta em que estava.

- **Divagação** (o cliente fala bastante sobre outra coisa, sem nada do seu negócio): reconheça em poucas palavras e volte à pergunta em que estava ("Tá bom! Voltando ao seu pedido: …").

No SDK, a `Decision` já faz essa leitura: `decision.unclear`, `decision.off_topic`, `decision.drifting` (divagação) e `decision.business_intent()`; `decision.text` traz o que o cliente disse.

### Dados importantes: endereço, e-mail, documentos

Endereços, e-mails e números ditados são onde a transcrição rápida mais erra ("rodas flores" no lugar de "Rua das Flores"). Quando fizer a pergunta, avise que a próxima resposta traz o dado:

```json
{"type": "speak", "id": "r7", "text": "Pra qual endereço eu mando?"}
{"type": "expect_slot", "id": "e1", "slot": {"name": "endereco", "type": "address", "description": "rua, número e bairro"}}
```

Quando o cliente responde, a conversa segue no ritmo normal (`transcript` e `decision` chegam como sempre) e, em segundo plano, a Ermis lê a mesma fala com o reconhecimento de maior precisão. Em seguida chega o `slot` com `id` `e1` e o valor extraído desse texto; se a leitura mudou, antes chega `transcript.revised` com a frase corrigida. Use o `slot` para o dado e ignore a `decision` dessa fala, a não ser que seja uma despedida ou uma pergunta. Vale só para a próxima resposta. Com prioridade de latência (`latency`, `local_first`, `local_only`), o `slot` sai na hora, do texto rápido; se a leitura de maior precisão achar outro valor, chega um segundo `slot` com `revised: true` (no SDK, `SlotResult.revised`). Com `precise_wait_ms`, a Ermis espera essa leitura por até esse tempo antes de responder (`local_only` nunca espera). Ao receber um `slot` revisado, corrija o dado; se o agente já o repetiu para o cliente, diga a correção.

No SDK: `valor = await call.expect_slot("endereco", "address")` devolve um `Future`; dê `await valor` na `Decision` da resposta. `TranscriptRevised` traz a frase corrigida.

### Intenções customizadas

Defina as intenções do seu negócio ao criar a sessão (`custom_intents`) e cada `decision` automática já traz em `custom_intent` a que se aplica, ou `other`. É a forma mais rápida: a escolha sai na mesma decisão, que começa ainda na pausa do cliente.

```json
{"transport": "twilio", "custom_intents": [
  {"key": "pedir_pizza", "label": "Pede pizza", "description": "tamanho, sabor ou quantidade"},
  {"key": "perguntar_cardapio", "label": "Pergunta sobre o cardápio", "description": "sabores, tamanhos, opções sem carne"}
]}
```

Para trocar as intenções no meio da ligação, envie `set_custom_intents`. Também é possível pedir uma decisão avulsa sobre qualquer texto:

```json
{"type": "decide", "id": "d1", "text": "quero a segunda via do boleto",
 "custom_intents": [
   {"key": "segunda_via", "label": "Segunda via", "description": "Boleto, fatura ou comprovante"},
   {"key": "cancelamento", "label": "Cancelamento", "description": "Cancelar plano ou pedido"}
 ]}
```

```json
{"type": "decision", "id": "d1", "intent": "question_service", "action": "escalate", "custom_intent": "segunda_via", "is_escape": false}
```

### Extrair um dado

```json
{"type": "extract_slot", "id": "s1", "text": "é lucas arroba gmail ponto com", "slot": {"name": "email", "type": "email"}}
```

```json
{"type": "slot", "id": "s1", "value": "lucas@gmail.com", "status": "found"}
```

| `slot.type` | Exemplo de fala | Valor |
|---|---|---|
| `email` | "ana arroba gmail ponto com" | `ana@gmail.com` |
| `phone`, `number`, `cpf`, `cnpj` | "um um nove oito sete…" | `(11) 98765-4321` |
| `date`, `datetime`, `time` | "pode ser amanhã às duas da tarde, tá?" | `amanhã às duas da tarde` (o trecho com a data, sem o resto da frase) |
| `boolean` | "pode ser, sim" | `sim` / `não` |
| `name` | "é João, não, peraí, é José" | `José` |
| qualquer outro, com `description` | "minha internet caiu" (motivo do contato) | O texto, se de fato responde ao que foi pedido; senão `null` |

## Enquanto a sua IA pensa

Se a sua IA demora para responder, o cliente final não fica no silêncio: o agente fala mensagens de espera sozinho. Você só configura o que ele diz e quanto tempo espera, no campo `waiting` ao criar a sessão.

```json
"waiting": {
  "filler_after_ms": 800,
  "filler_messages": ["Certo, um momento.", "Hum, deixa eu ver.", "Entendi, só um instante.", "Aham, certo."],
  "filler_by_intent": {
    "complaint": ["Entendo, sinto muito por isso.", "Entendi. Deixa eu verificar isso pra você."],
    "question_service": ["Deixa eu verificar isso pra você.", "Hum, deixa eu ver.", "Claro, vou verificar."]
  },
  "gap_after_ms": 600,
  "patience_after_ms": 3500,
  "patience_every_ms": 8000,
  "patience_messages": ["Ainda estou verificando, espera um pouquinho, tá bom?", "Só mais um instante, já te respondo."],
  "timeout_ms": 20000,
  "timeout_message": "Desculpe, não consegui essa informação agora. Pode repetir, por favor?",
  "timeout_action": "apologize"
}
```

Os valores acima são o padrão (o `filler_by_intent` padrão tem mais intenções; veja a tabela). Envie só o que quiser mudar.

| Campo | Padrão | O que faz |
|---|---|---|
| `filler_after_ms` | `800` | Depois de quanto tempo sem resposta o agente fala uma frase de espera. `null` desliga |
| `filler_messages` | 4 frases curtas | Frases de espera, usadas em rodízio quando a intenção da fala não tem frases próprias |
| `filler_by_intent` | frases para `complaint`, `question_product`, `question_service`, `confirm_yes`, `confirm_no`, `name_provide`, `name_correction`, `request_human` | Frases de espera escolhidas pela intenção da fala (a mesma do evento `decision`): reclamação ouve "Entendo, sinto muito por isso.", confirmação ouve "Aham, certo.". Se você enviar `filler_messages` sem `filler_by_intent`, só as suas frases são usadas. `{}` desliga. Até 30 intenções |
| `gap_after_ms` | `600` | Silêncio entre uma mensagem de espera e a sua resposta, para a resposta não emendar na frase de espera. `null` desliga |
| `patience_after_ms` | `3500` | Quando começam as frases de paciência. `null` desliga |
| `patience_every_ms` | `8000` | Intervalo entre frases de paciência. Nos 2 s antes do tempo limite, nenhuma é falada |
| `patience_messages` | 4 frases | Frases de paciência, usadas em rodízio |
| `timeout_ms` | `20000` | Tempo máximo de espera pela sua resposta. `null`: espera sem limite |
| `timeout_message` | "Desculpe, não consegui…" | O que o agente fala no tempo limite |
| `timeout_action` | `apologize` | `apologize`: fala a mensagem e volta a ouvir. `end`: fala a mensagem e encerra a sessão |

**Como funciona um turno:**

```
cliente fala ─► decision ─► 0,8 s: "Um momento, por favor."
                            3,5 s: "Ainda estou verificando…"
                           11,5 s: "Só mais um instante…"
                             20 s: "Desculpe, não consegui…"  + evento reply_timeout
```

- O relógio começa quando você recebe a fala (o `decision`, ou o `transcript` sem `auto_decide`). Falas que eram ruído ou que precisam ser repetidas não disparam espera.
- A espera acaba quando você envia `speak`, `done_processing` ou `end`, ou quando o cliente final volta a falar. Se a sua resposta chega em menos de 0,8 s, ninguém ouve mensagem de espera.
- Se o `speak` chega depois do tempo limite, ele é descartado e você recebe `warning` com `late_reply`. A conversa já seguiu.
- As mensagens de espera obedecem ao barge-in e aparecem no evento `waiting`. Não há cobrança à parte: tudo entra no minuto de sessão.
- Limites: até 10 frases por lista, 300 caracteres cada; `timeout_ms` até 120.000.

### Avisar que vai demorar (`thinking`)

Quando você sabe que um passo é lento (consulta a um sistema, geração de documento), avise:

```json
{"type": "thinking", "message": "Vou consultar o seu pedido, só um instante.", "timeout_ms": 45000}
```

O agente fala `message` na hora, no lugar da frase de espera padrão, e espera até `timeout_ms` neste turno. As frases de paciência continuam. Os dois campos são opcionais, e você pode enviar `thinking` mais de uma vez no mesmo turno.

## Conectando a sua IA

A Ermis não escreve as falas do agente: ela ouve, transcreve, classifica e fala. O texto vem sempre do seu código, de um roteiro, da sua IA ou dos dois. Qualquer IA serve (um modelo de linguagem em nuvem, um modelo seu, regras): o SDK só precisa do texto pronto.

Há dois jeitos comuns de ligar a sua IA a um roteiro (para um agente conduzido inteiramente pela IA, com ferramentas que consultam o seu sistema, veja o [tutorial do assistente com IA](tutoriais/assistente-ia.md)).

**1. O roteiro conduz, a IA responde o que sai dele.** O roteiro faz as perguntas e guarda os dados; a IA responde só perguntas fora do roteiro e divagações. Crie a sessão com `off_topic` e `drift` vazios no `guard`: essas falas chegam ao seu código em vez de a Ermis responder com a frase pronta. Responda com a sua IA e repita a pergunta atual com `ask`.

**2. O roteiro decide, a IA escreve.** O roteiro continua decidindo o que precisa ser dito (o próximo passo, os valores, a confirmação) e a sua IA transforma isso numa fala natural, respondendo antes ao que o cliente disse. O roteiro garante o fluxo e os dados; a IA cuida do jeito de falar. Na instrução da IA, peça para manter exatamente os valores do roteiro (preços, horários, nomes, e-mails) e para terminar com a pergunta do roteiro, quando houver.

```python
from ermis import Decision

guard = {"enabled": True, "off_topic": "", "drift": ""}  # perguntas e divagações chegam ao seu código
session = await ermis.sessions.create(transport="twilio", guard=guard)

async def falar(call, fala_do_roteiro: str, pergunta: bool, historico: list[str]) -> None:
    await call.thinking(timeout_ms=6000)  # a Ermis não encerra o turno enquanto a IA escreve
    try:
        texto = await asyncio.wait_for(sua_ia(historico, fala_do_roteiro), timeout=4)
    except Exception:
        texto = fala_do_roteiro  # a IA falhou ou demorou: a fala do roteiro
    historico.append(f"Atendente: {texto}")
    if pergunta:
        await call.ask(texto)  # vira a pergunta atual: a Ermis a repete depois de um desvio
    else:
        await call.say(texto)

# Na Decision:
#   decision.off_topic ou decision.drifting  -> falar(call, pergunta_atual, True, historico)
#   o resto                                  -> o roteiro decide a fala_do_roteiro e chama falar(...)
```

### Quando chamar a sua IA

A IA deixa a conversa mais esperta, mas custa tempo (em geral 0,5 a 1,5 s por fala). Chame só quando precisa. Cada `decision` traz a avaliação da Ermis sobre a fala:

- `action`: `respond` (uma frase pronta resolve), `escalate` (precisa da sua IA ou de um humano) ou `clarify` (peça para repetir);
- `complexity`: de 0 (cumprimento, confirmação) a 2 (problema, reclamação, pedido com vários detalhes).

No SDK, `decision.complex()` junta os dois: `True` quando a Ermis escalou a fala ou a complexidade passa de 0,8 (ajuste com `decision.complex(threshold=...)`). Despedidas e pedidos de atendente nunca contam.

Use esse sinal **junto** com o que o seu roteiro entendeu, não sozinho: uma fala clara também pode vir como complexa (em testes com um agente de pizzaria, cerca de 1 em cada 5 falas veio com `escalate`, inclusive "eu queria uma pizza grande de calabresa"). A regra que funciona bem:

```python
def precisa_da_ia(decision, entendido_pelo_roteiro) -> bool:
    if decision.is_escape or decision.unclear:
        return False                    # despedida, atendente ou fala confusa: o roteiro e o guard resolvem
    if decision.off_topic or decision.drifting:
        return True                     # pergunta ou comentário fora do roteiro: a IA responde e volta à pergunta
    return decision.complex() and not entendido_pelo_roteiro   # complexa e o roteiro não deu conta
```

Assim as falas simples ("calabresa", "sim", o nome) saem na hora, pelo roteiro, e a IA entra nas que pedem: pedidos com vários itens, correções ("na verdade, troca a calabresa"), palavras que o roteiro não reconhece e perguntas fora do script. Enquanto a IA pensa, envie `thinking` para a Ermis segurar a vez.

Cuidados:

- **Latência:** cada fala passa pela sua IA. Prefira modelos rápidos e respostas curtas; as frases de espera (`waiting`) cobrem a demora, e `thinking` evita o tempo limite do turno.
- **Dados:** use a IA para o texto, não para os dados. Endereço, e-mail e CPF continuam vindo do `slot`; preços e horários, do seu sistema.
- **Fallback:** sem resposta da IA no tempo, use a fala do roteiro. A ligação nunca fica parada esperando a IA.
- **Fim da ligação:** despedidas e pedidos de atendente (`is_escape`) não precisam da IA: responda com a frase pronta e encerre.

## Conectando o áudio

### Twilio (`transport: "twilio"`)

Responda à ligação com o TwiML do [início rápido](#início-rápido). A Ermis recebe o áudio direto do Twilio e cuida de tudo: marcas de fim de áudio e limpeza do buffer quando o cliente interrompe. Seu servidor só usa o canal de controle.

O Twilio não aceita parâmetros na URL do `<Stream>`: envie o token em `<Parameter name="session_token">`.

### Navegador (`transport: "browser"`)

Seu servidor cria a sessão e entrega ao navegador **só** o `audio_url` e o `session_token`. O navegador:

1. abre `audio_url?session_token=…`;
2. envia o microfone como quadros binários de μ-law 8 kHz, 20 ms cada (160 bytes);
3. toca o áudio recebido (`audio_format: "pcm16_48k"` recomendado);
4. descarta a fila de áudio ao receber `{"type": "clear"}` (o cliente interrompeu).

Seu servidor conduz a conversa pelo `control_url`, como no Twilio.

### Seu próprio WebSocket (`transport: "websocket"`)

Um único socket (`control_url`) leva áudio e controle. Você envia quadros binários de μ-law 8 kHz e recebe os quadros de áudio do agente. Como é você quem toca o áudio, avise quando cada fala terminou: `{"type": "playback_finished", "id": "r1"}`.

## Erros e limites

| Código (fechamento do WebSocket / HTTP) | Quando | O que fazer |
|---|---|---|
| `4001` / `401` | Chave ou token inválido ou expirado | Verifique a chave; gere uma nova sessão |
| `4002` / `402` | Créditos insuficientes | Recarregue ou ative a recarga automática |
| `4029` / `429` | Todos os canais do plano estão em uso | Espere uma sessão terminar ou mude de plano |
| `4008` | 60 s sem áudio | Crie uma nova sessão quando precisar |
| `4013` | `max_duration_s` atingido | Aumente o limite ou encerre antes |
| `4400` / `400` | Mensagem inválida | Veja `message` |
| `1011` / `500` | Erro interno | Tente de novo; se persistir, fale com o suporte |

Até 20 comandos por segundo por sessão. Ao atingir o limite de créditos durante uma ligação, você recebe `warning: credits_low` e tem 60 s para o agente se despedir.

## Boas práticas

- **Saudação:** envie a primeira fala com `"calibrate": true`. A Ermis mede o ruído do ambiente enquanto o cliente escuta.
- **Avisos obrigatórios** ("esta ligação é gravada"): use `"allow_barge_in": false`.
- **Transcrição incerta** (`assessment.confirm`): confirme antes de agir em dados importantes (e-mail, valor, data).
- **Espera pela sua IA:** deixe o `waiting` cuidar das frases de espera e use `thinking` nos passos que você sabe que são lentos. Frases de espera curtas soam mais naturais; evite prometer prazos ("em 5 segundos").
- **Encerramento:** depois da despedida, espere `speak.done` e envie `end`. O minuto é cobrado enquanto a sessão estiver aberta.
- **Decisões rápidas:** para `action: "respond"` com intenções simples (`greeting`, `thanks`, `wait`), responda com frases prontas. É mais rápido do que chamar a sua IA.

## Perguntas frequentes: qualidade e latência

Os ajustes abaixo são campos da criação da sessão (`POST /v1/voice/sessions`) ou atitudes da sua aplicação. Teste com ligações reais do seu público: o melhor ajuste depende de como seus clientes falam e de onde ligam.

### Quero a menor latência possível. O que ajustar?

| Ajuste | Efeito | Custo |
|---|---|---|
| `"transcription_priority": "latency"` | A transcrição sai assim que o reconhecimento rápido tem texto, sem esperar a leitura de maior qualidade (cerca de 150 ms a menos por fala). Com `precise_wait_ms`, as respostas que você marcou como importantes (`precise`, `slot`) esperam essa leitura por até esse tempo | Mais erros em nomes, números e frases longas |
| `vad.min_silence_ms` entre `300` e `350` | O turno fecha mais cedo depois que o cliente para de falar | Clientes que fazem pausas no meio da frase são cortados |
| Respostas prontas para `action: "respond"` | Cumprimentos, agradecimentos e despedidas sem passar pela sua IA | — |
| Respostas curtas | Menos texto para sintetizar e para o cliente ouvir antes de poder responder | — |

A maior parte da espera numa conversa costuma ser a sua IA. Se ela leva mais de um segundo, mantenha o `waiting` ligado: o cliente ouve "Um momento" em vez de silêncio.

### Quero a melhor transcrição possível. O que ajustar?

| Ajuste | Efeito | Custo |
|---|---|---|
| `"transcription_priority": "accuracy"` | Quando a transcrição é incerta, a Ermis confere se o texto faz sentido como resposta ao que o agente perguntou, antes de pedir confirmação | Uma verificação extra nas falas duvidosas (~0,3 s) |
| `vad.min_silence_ms` entre `600` e `800` | Não corta quem fala devagar ou faz pausas (idosos, ditado de números) | O turno demora mais para fechar |
| `extract_slot` para e-mail, telefone, CPF, data e nome | A Ermis interpreta o dado ditado ("ana arroba gmail ponto com") em vez de você tratar o texto | — |
| Confirmar quando `assessment.confirm` vier `true` | Evita gravar um dado errado | Uma pergunta a mais |
| `"calibrate": true` na primeira fala | A Ermis mede o ruído de fundo enquanto o cliente ouve a saudação | — |

O padrão, `"balanced"`, espera as duas leituras do áudio e escolhe a melhor; é o recomendado para a maioria dos casos.

### O cliente fala "tchau" e a ligação não termina

Encerre pela decisão, não pelo texto: quando o `decision` vier com `is_escape: true` e `intent: "farewell"`, fale a despedida e mande `end` depois do `speak.done`. Não compare o texto com "tchau": a transcrição pode vir como "Tchau.", "Valeu, tchau!" ou "tchau tchau". Despedidas e pedidos de atendente nunca vêm com `confirm`, para que você não precise perguntar "você disse tchau?".

### O agente interrompe a própria fala, ou para por qualquer barulho

É barge-in disparado por eco ou ruído. Aumente `barge_in.min_speech_ms` (por exemplo, `300`). No navegador, use cancelamento de eco do microfone (`echoCancellation: true`) e, em testes, fone de ouvido. Para avisos que não podem ser cortados, use `"allow_barge_in": false` no `speak`.

### O cliente é cortado no meio da frase

Aumente `vad.min_silence_ms`. O padrão (400 ms) é bom para conversa rápida; para ditado de números, endereços ou clientes que pensam enquanto falam, use 600 a 800 ms.

### A transcrição erra em ambiente barulhento

Você recebe `warning` com `noisy_environment` uma vez por ligação. Peça ao cliente para ir a um lugar mais silencioso ou trocar o viva-voz pelo telefone no ouvido. Para dados importantes, confirme antes de agir.

## Exemplo completo

[`examples/atendente_twilio.py`](../examples/atendente_twilio.py): atendente por telefone com Twilio, em FastAPI. Cria a sessão quando a ligação chega, responde o TwiML e conduz a conversa: saudação, respostas rápidas, sua IA para o resto, confirmação de transcrições incertas, desistência após falhas repetidas e despedida.
