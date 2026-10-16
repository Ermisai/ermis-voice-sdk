# Changelog

## Não lançado

- Guia [Primeiros passos](docs/primeiros-passos.md), da instalação a um número de telefone atendido pelo agente.
- Exemplos novos: `primeira_ligacao.py` (sem telefone, com um WAV gravado), `agendamento.py` (consultas) e `ura.py` (URA por voz com transferência).
- Diagramas do fluxo no README.

## 0.2.0a1 (prévia)

- `usage(limit=50, before=None)`: lançamentos de crédito paginados (`entries`, `next_cursor`). Os parâmetros `from_`, `to` e `group_by` foram removidos.
- `balance()` devolve `balance`, `reserved_credits` e `available_credits`.
- `RateLimitError` para limitação temporária de requisições (429 `rate_limited`), separado de `ChannelLimitError`.
- Erros REST guardam o código da API em `.code` e o identificador da requisição em `.request_id`.
- Eventos `Usage` e `SessionEnded`: `credits` e `balance` podem ser fracionários ou `None` enquanto o valor não foi apurado.

## 0.1.0a1 (prévia)

- Primeira versão pública do SDK Python da Ermis Voice API: sessões (`twilio`, `browser`, `websocket`), canal de controle com eventos tipados, `decide`, `extract_slot`, mensagens de espera (`WaitingOptions`, com frases por intenção e pausa antes da resposta), `transcription_priority`, TwiML pronto e exceções por código de erro.
