# Changelog

## Não lançado

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
