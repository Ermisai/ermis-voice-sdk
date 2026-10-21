# Changelog

## 0.3.0a1 (prévia)

Requer a Ermis Voice API 0.3.0 (0.3.1 para a espera curta pela leitura de maior precisão).

- Documentação: [Conectando a sua IA](docs/api.md#conectando-a-sua-ia), com os dois jeitos de ligar a sua IA (o roteiro conduz e a IA responde os desvios; o roteiro decide e a IA escreve as falas), fallback para a fala do roteiro e `thinking` enquanto a IA escreve.
- Com prioridade de latência, as respostas marcadas como importantes (`precise`, `slot`) esperam a leitura de maior precisão por até cerca de meio segundo (Ermis Voice API 0.3.1); o `slot` revisado (`SlotResult.revised`) fica para quando ela chega depois disso. `sessions.create(precise_wait_ms=...)` escolhe essa espera (`0`: nunca espera, como na 0.3.0).

- [Tutoriais](docs/tutoriais/README.md), um por cenário: [atendente](docs/tutoriais/atendente.md) (a configuração inteira: canal, identidade do agente, calibragem de ruído, qualidade e latência, mensagens de espera, as três camadas de resposta, encerramento e transferência), [URA](docs/tutoriais/ura.md), [agendamento](docs/tutoriais/agendamento.md), [pedidos](docs/tutoriais/pedidos.md), [assistente com IA](docs/tutoriais/assistente-ia.md) e [ligação ativa](docs/tutoriais/ligacao-ativa.md). Exemplos novos: `clinica.py`, `assistente_ia.py` (a IA conduz, com ferramentas) e `confirmacao.py` (o agente liga para o cliente).

- O fluxo da conversa fica com a Ermis: `call.ask(texto, choices=..., precise=..., slot=...)` faz a pergunta atual (com as respostas esperadas); com `guard` na sessão, a Ermis responde sozinha a fala confusa, a divagação e o assunto fora do tema (`Decision.handled`, `guided_text`). Na `Decision`: `answer` (sim/não com a sua intenção em primeiro lugar), `guidance`, `choice`/`chosen()`.
- `call.expect_precise()`: a próxima resposta sai do reconhecimento de maior precisão, com a `Decision` já sobre esse texto (para itens do cardápio, tamanhos, quantidades).
- `Decision.text` (o que o cliente disse, preenchido pelo `Call`) e `Decision.drifting` (divagação: fala longa sem nada do seu negócio). Uma frase longa lida como nome não conta mais como resposta curta.
- Exemplos atualizados (`agendamento.py`, `ura.py`) e novo `pizzaria.py`; prompt para IA e `llms.txt` com os recursos novos.
- `Decision.unclear` (fala confusa: peça para repetir), `Decision.off_topic` (assunto fora do seu negócio) e `Decision.business_intent()` (a sua intenção, ou `"other"` quando a escolha não é segura).
- `Decision.custom_intent_confidence`: quanto a escolha de `custom_intent` é segura (abaixo de 0,8, trate como `other`); veja "Fala confusa ou fora do assunto" na documentação. `Decision.complexity` agora é decimal, como na API.
- `call.expect_slot(nome, tipo)`: avisa que a próxima resposta traz um dado (endereço, e-mail, CPF); a Ermis lê essa fala também com o reconhecimento de maior precisão, em segundo plano, e o valor chega no `Future` devolvido. Novo evento `TranscriptRevised` com a frase corrigida.
- Voz natural automática: toda fala passa por `normalize_for_speech()` antes de ir para a voz (números e valores por extenso, com gênero, datas, horas, porcentagens, CPF, CEP e telefone em grupos, e-mails e sites lidos, sem markdown nem emojis). Desligue com `ermis.connect(session, normalize_text=False)` ou `speak(..., normalize=False)`. `normalize_for_speech()` e `number_to_words()` também podem ser usados direto.
- `sessions.create(vocabulary=[...])` e `call.set_vocabulary()`: palavras do seu negócio; a transcrição chega corrigida na direção delas ("marquerita" -> "margherita"). `Transcript.corrections` lista os ajustes.
- `sessions.create(custom_intents=[CustomIntent(...)])`: as intenções do seu negócio vêm em cada `Decision` automática (`custom_intent`), sem chamar `call.decide()`; `call.set_custom_intents()` troca as intenções no meio da ligação.
- Opções `turn_detection` (`smart_turn` ou `silence`) e `early_turn`, e `transcription_priority` aceita `local_first` e `local_only`.
- `ermis.voices.list()`: vozes disponíveis para a conta (`Voice`: `id`, `name`, `gender`, `language`, `production`, `default`); use o `id` em `sessions.create(voice=...)`.
- Guia [Primeiros passos](docs/primeiros-passos.md), da instalação a um número de telefone atendido pelo agente.
- Exemplos novos: `primeira_ligacao.py` (sem telefone, com um WAV gravado), `agendamento.py` (consultas) e `ura.py` (URA por voz com transferência).
- Diagramas do fluxo no README.
- [Prompt para assistentes de IA](docs/prompt-para-ia.md) e `llms.txt`.

## 0.2.0a1 (prévia)

- `usage(limit=50, before=None)`: lançamentos de crédito paginados (`entries`, `next_cursor`). Os parâmetros `from_`, `to` e `group_by` foram removidos.
- `balance()` devolve `balance`, `reserved_credits` e `available_credits`.
- `RateLimitError` para limitação temporária de requisições (429 `rate_limited`), separado de `ChannelLimitError`.
- Erros REST guardam o código da API em `.code` e o identificador da requisição em `.request_id`.
- Eventos `Usage` e `SessionEnded`: `credits` e `balance` podem ser fracionários ou `None` enquanto o valor não foi apurado.

## 0.1.0a1 (prévia)

- Primeira versão pública do SDK Python da Ermis Voice API: sessões (`twilio`, `browser`, `websocket`), canal de controle com eventos tipados, `decide`, `extract_slot`, mensagens de espera (`WaitingOptions`, com frases por intenção e pausa antes da resposta), `transcription_priority`, TwiML pronto e exceções por código de erro.
