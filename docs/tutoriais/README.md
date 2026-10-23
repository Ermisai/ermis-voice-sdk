# Tutoriais

Cada tutorial monta um agente de voz completo para um cenário, passo a passo, a partir de um exemplo do repositório que roda e tem testes. Escolha o mais parecido com o seu caso e adapte.

Se você nunca ouviu o agente, comece por [Primeiros passos](../primeiros-passos.md): em 10 minutos ele já fala com você, sem telefone.

| Tutorial | Cenário | O que você aprende | Exemplo |
|---|---|---|---|
| [Atendente com URA e IA](atendente.md) | Atendimento geral de uma clínica | **A configuração inteira, ajuste por ajuste:** canal (Twilio ou navegador), nome e voz do agente, calibragem de ruído, qualidade e latência, mensagens de espera e as três camadas de resposta | [`clinica.py`](../../examples/clinica.py) |
| [URA por voz](ura.md) | O cliente diz o motivo da ligação e é transferido para o setor certo | Setores como intenções, perfil de baixa latência, dados pedidos antes de transferir, horário de funcionamento e submenus | [`ura.py`](../../examples/ura.py) |
| [Agendamento](agendamento.md) | Marcar, remarcar e cancelar consultas | Conversa em etapas, horários livres como opções faladas, dados ditados (data, nome, telefone) e confirmação antes de gravar | [`agendamento.py`](../../examples/agendamento.py) |
| [Pedidos por telefone](pedidos.md) | Pizzaria que recebe pedidos | Conversa por objetivos, vocabulário do cardápio, respostas esperadas, endereço lido com precisão, dúvidas e mudanças no meio do pedido | [`pizzaria.py`](../../examples/pizzaria.py) |
| [Assistente com IA](assistente-ia.md) | Suporte técnico em que a IA conduz a conversa | Identificação feita pelo código, a IA com ferramentas que consultam o seu sistema e o `guard` dividindo o trabalho com a IA | [`assistente_ia.py`](../../examples/assistente_ia.py) |
| [Ligação ativa](ligacao-ativa.md) | O agente liga para confirmar uma consulta | Discar pelo Twilio, confirmar a identidade, registrar o resultado e disparar várias ligações | [`confirmacao.py`](../../examples/confirmacao.py) |

## As três camadas de resposta

Todos os tutoriais organizam as respostas do agente do mesmo jeito, da camada mais rápida e barata para a mais cara:

| Camada | Quem responde | Para quê | Como configurar |
|---|---|---|---|
| **1. A Ermis, sozinha** | A Voice API, sem passar pelo seu código | Ruído, fala confusa, divagação, assunto fora do tema, cliente calado | `guard` na sessão, com as frases do seu negócio |
| **2. Respostas pré-definidas** | O seu código, com frases prontas | Perguntas frequentes, escolhas de um menu, transferências, confirmações | `custom_intents`, `ask(..., choices=...)`, `Decision.business_intent()` |
| **3. A sua IA externa** | O modelo que você escolhe, chamado do seu servidor | Dúvidas abertas, conversas que não cabem num roteiro | A sua função de IA, com o prompt do agente e o histórico |

Os cenários usam as camadas em proporções diferentes. Uma [URA](ura.md) vive da camada 2 e não precisa de IA. Num [assistente](assistente-ia.md), a camada 3 conduz quase tudo. Um [atendente](atendente.md) usa as três.

## O que todos têm em comum

- **A chave fica no servidor.** O áudio vai do telefone (ou do navegador) direto para a Ermis; pelo seu servidor passam só os eventos e os comandos.
- **O mesmo laço de eventos:** `SessionStarted` → saudação com `calibrate=True`; `Transcript` e `Decision` a cada fala do cliente; `SpeakDone` depois da despedida → `end()`.
- **Toda ligação termina:** com uma despedida seguida de `end()`, com uma transferência ou com o limite de `max_duration_s`.
- **Testes sem telefone:** [`tests/test_example_flows.py`](../../tests/test_example_flows.py) roda cada exemplo contra uma Voice API simulada, que faz o papel do cliente. Use o mesmo formato para testar o seu agente.

Antes de ir para produção, passe pela [lista de conferência](../primeiros-passos.md#8-antes-de-ir-para-produção).
