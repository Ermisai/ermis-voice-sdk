"""Pizzaria Bella Napoli: agente de pedidos por telefone com o SDK do Ermis Voice.

Quem faz o quê:
- Ermis Voice: atende a ligação, percebe quando o cliente terminou de falar, transcreve, entende o que
  ele quer (as INTENCOES abaixo chegam resolvidas em cada decisão), extrai dados ditados (nome,
  endereço) e fala com voz natural, parando se o cliente interromper.
- Este código: o negócio. Cardápio, preços e o que perguntar a seguir.

As respostas aqui são frases prontas: rápidas e previsíveis. Para respostas mais ricas, conecte a sua
IA em ``responder_com_ia()`` ("Sua IA aqui").

Rodar:
    pip install ermis-voice fastapi uvicorn python-multipart
    export ERMIS_API_KEY=...  # chave do Ermis Voice
    export ERMIS_API_URL=...  # URL do Ermis Voice
    uvicorn pizzaria:app --port 8000

No Twilio, configure o webhook de voz do número para ``https://<seu-host>/twilio/voz``.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field

from fastapi import FastAPI, Response

from ermis import Call, CustomIntent, Decision, Ermis, SessionStarted, SpeakDone, Transcript

app = FastAPI()
ermis = Ermis()  # lê ERMIS_API_KEY e ERMIS_API_URL
_conversas: set[asyncio.Task] = set()

SAUDACAO = "Oi, boa noite! Pizzaria Bella Napoli, aqui é o Rafael. Com quem eu falo?"
DESPEDIDA = "Eu que agradeço! Tenha um ótimo dia."
REPETIR = "Desculpa, não entendi direito. Pode repetir?"
DESISTIR = "Tô com dificuldade pra te ouvir. Tenta ligar de novo, por favor. Até mais!"
TRANSFERIR = "Vou te passar para um atendente. Um momento, por favor."

# ── O que o cliente pode querer (o Ermis Voice entende; você só lista) ──────
INTENCOES = [
    CustomIntent(
        "perguntar_cardapio",
        "Pergunta sobre o cardápio",
        "quais sabores existem, se tem pizza doce, ingredientes",
    ),
    CustomIntent("perguntar_sem_carne", "Pergunta por pizza sem carne", "vegetariana, sem carne, sem frango"),
    CustomIntent("perguntar_tamanho", "Pergunta sobre os tamanhos", "quantas fatias, serve quantas pessoas"),
    CustomIntent("perguntar_preco", "Pergunta de preço", "quanto custa uma pizza, quanto fica o pedido"),
    CustomIntent("perguntar_entrega", "Pergunta sobre a entrega", "tempo de entrega, taxa, área de entrega"),
    CustomIntent("perguntar_pagamento", "Pergunta sobre pagamento", "formas de pagamento, pix, cartão, troco"),
    CustomIntent("perguntar_horario", "Pergunta de horário de funcionamento", "que horas abre ou fecha"),
    CustomIntent("pedir_pizza", "Pede pizza", "diz tamanho, sabor ou quantidade de pizza que quer"),
    CustomIntent("informar_endereco", "Informa endereço", "rua, número, bairro de entrega"),
    CustomIntent("mudar_pedido", "Quer mudar o pedido", "trocar, tirar ou acrescentar pizza, mudar endereço"),
]

# ── Cardápio (troque pelo seu) ──────────────────────────────────────────────
# Palavras do cardápio que o reconhecimento de fala pode não conhecer: o Ermis Voice corrige a transcrição
# na direção delas ("marquerito" -> "margherita") antes de qualquer decisão
VOCABULARIO = [
    "quatro queijos", "frango com catupiry", "frango", "catupiry", "calabresa", "mussarela", "margherita",
    "portuguesa", "pepperoni", "chocolate", "brigadeiro", "pequena", "média", "grande", "família", "broto",
]  # fmt: skip
TAMANHOS = {"pequena": 39, "média": 49, "grande": 59, "família": 69}
FALAS_TAMANHO = {
    "pequena": ("pequena", "broto"),
    "média": ("media", "medio"),
    "grande": ("grande",),
    "família": ("familia", "gigante"),
}
SABORES = {
    "quatro queijos": ("quatro queijos", "4 queijos"),
    "frango com catupiry": ("frango com catupiry", "frango", "catupiry"),
    "calabresa": ("calabresa", "calabreza"),
    "mussarela": ("mussarela", "mucarela", "queijo"),
    "margherita": ("margherita", "marguerita", "margarita"),
    "portuguesa": ("portuguesa",),
    "pepperoni": ("pepperoni", "peperoni"),
    "chocolate": ("chocolate", "brigadeiro"),
}
QUANTIDADES = {"uma": 1, "um": 1, "duas": 2, "dois": 2, "tres": 3}
PRECOS = (
    "A pequena custa trinta e nove reais, a média quarenta e nove, a grande cinquenta e nove "
    "e a família sessenta e nove"
)
RESPOSTAS = {
    "perguntar_cardapio": "Tem quatro queijos, frango com catupiry, calabresa, mussarela, margherita, portuguesa e "
    "pepperoni, e de doce, chocolate. Dá pra fazer meio a meio também.",
    "perguntar_sem_carne": "Sem carne tem mussarela, margherita e quatro queijos.",
    "perguntar_tamanho": "Tem pequena, de quatro fatias, média, de seis, grande, de oito, e família, de doze.",
    "perguntar_preco": PRECOS + ", qualquer sabor.",
    "perguntar_entrega": "Chega em uns quarenta, cinquenta minutos, e a entrega é grátis acima de cinquenta reais.",
    "perguntar_pagamento": "Pode pagar no pix, no cartão ou em dinheiro, na entrega.",
    "perguntar_horario": "A gente abre todo dia, das seis da tarde até meia-noite.",
}


@dataclass
class Pizza:
    quantidade: int = 1
    tamanho: str | None = None
    sabores: list[str] = field(default_factory=list)

    def falada(self) -> str:
        qtd = {1: "uma", 2: "duas"}.get(self.quantidade, str(self.quantidade))
        tamanho = f" {self.tamanho}" if self.tamanho else ""
        if len(self.sabores) == 2:
            return f"{qtd}{tamanho} meio {self.sabores[0]} e meio {self.sabores[1]}"
        return f"{qtd}{tamanho} de {self.sabores[0]}" if self.sabores else f"{qtd}{tamanho}"


@dataclass
class Pedido:
    etapa: str = "nome"  # nome -> pizzas -> mais -> endereco -> confirmar
    nome: str = ""
    pizzas: list[Pizza] = field(default_factory=list)
    endereco: str = ""
    erros: int = 0
    esperado: asyncio.Future | None = None  # valor pedido com expect_slot, lido pelo STT preciso

    def total(self) -> int:
        return sum(p.quantidade * TAMANHOS.get(p.tamanho or "", 0) for p in self.pizzas)


UNIDADES = "zero um dois três quatro cinco seis sete oito nove dez onze doze treze catorze quinze dezesseis dezessete dezoito dezenove".split()  # noqa: E501
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
            "oitocentos", "novecentos"]  # fmt: skip


def por_extenso(n: int) -> str:
    """108 -> "cento e oito" (até 999): a voz lê números por extenso com mais naturalidade."""
    if n < 20:
        return UNIDADES[n]
    if n < 100:
        return DEZENAS[n // 10] + (f" e {UNIDADES[n % 10]}" if n % 10 else "")
    if n == 100:
        return "cem"
    return CENTENAS[n // 100] + (f" e {por_extenso(n % 100)}" if n % 100 else "")


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", sem_acento)).strip()


NAO_NOMES = set("o a e é eu sou aqui meu nome oi olá alô quem fala falando então bem bom boa tudo me chamo".split())


def primeiro_nome(texto: str) -> str:
    """ "então, aqui é o Lucas" -> "Lucas": ignora as palavras ditas em volta do nome."""
    palavras = [p.strip(",.!?") for p in texto.split()]
    nome = next((p for p in palavras if len(p) >= 2 and p.lower() not in NAO_NOMES), "")
    return nome.capitalize()


def sim_ou_nao(texto: str, decisao: Decision) -> str | None:
    """Sim/não pela decisão do Ermis Voice, e pelas respostas curtas ("só isso") em qualquer lugar da frase."""
    if decisao.intent in ("confirm_yes", "confirm_no"):
        return "sim" if decisao.intent == "confirm_yes" else "nao"
    dito = normalizar(texto)
    curta = len(dito.split()) <= 5
    if re.match(r"(nao|negativo|nada)\b", dito) or (curta and re.search(r"\b(so isso|e so|mais nada)\b", dito)):
        return "nao"
    return "sim" if re.match(r"(sim|isso|pode|claro|beleza|certo)\b", dito) else None


def ler_pizzas(texto: str) -> list[Pizza]:
    """ "uma grande de calabresa e uma média meio frango meio portuguesa" -> duas pizzas."""
    partes: list[str] = []
    for trecho in texto.split(","):
        for parte in re.split(r"\s+e\s+|\s+mais\s+", normalizar(trecho)):
            # "meio frango e meio portuguesa" é uma pizza só
            if re.match(r"(metade|meia|meio)\b", parte) and partes and re.search(r"\b(metade|meia|meio)\b", partes[-1]):
                partes[-1] += f" e {parte}"
            else:
                partes.append(parte)
    pizzas = []
    for parte in partes:
        resto, sabores = f" {parte} ", []
        for sabor, falas in SABORES.items():
            for fala in falas:
                if f" {fala} " in resto:
                    resto = resto.replace(f" {fala} ", " ")
                    if sabor not in sabores:
                        sabores.append(sabor)
        tamanho = next(
            (t for t, falas in FALAS_TAMANHO.items() if any(re.search(rf"\b{f}s?\b", resto) for f in falas)), None
        )
        quantidade = next((q for p, q in QUANTIDADES.items() if f" {p} " in resto), 1)
        if tamanho or sabores:
            pizzas.append(Pizza(quantidade, tamanho, sabores[:2]))
    return pizzas


def proximo_objetivo(pedido: Pedido) -> str:
    """A pergunta do próximo objetivo que falta: nome, pizzas (tamanho e sabor), endereço, confirmação."""
    if not pedido.nome:
        pedido.etapa = "nome"
        return "Com quem eu falo, por favor?"
    for pizza in pedido.pizzas:
        if not pizza.tamanho:
            pedido.etapa = "pizzas"
            return f"E a {pizza.falada()}, vai ser de que tamanho? Tem pequena, média, grande e família."
        if not pizza.sabores:
            pedido.etapa = "pizzas"
            return f"Beleza, {pizza.falada()}. De qual sabor?"
    if not pedido.pizzas:
        pedido.etapa = "pizzas"
        return "O que vai ser hoje?"
    if pedido.etapa in ("pizzas", "mais"):
        pedido.etapa = "mais"
        return "Quer mais alguma pizza?"
    if not pedido.endereco:
        pedido.etapa = "endereco"
        return "Pra qual endereço eu mando? Pode falar a rua, o número e o bairro."
    pedido.etapa = "confirmar"
    itens = ", ".join(p.falada() for p in pedido.pizzas)
    total = por_extenso(pedido.total())
    return f"Deixa eu confirmar: {itens}, dá {total} reais, pra entregar na {pedido.endereco}. Tá certinho?"


def nao_entendi(pedido: Pedido) -> str:
    """Não entendeu a pizza: mantém o que já sabe e oferece as opções do que falta."""
    pedido.erros += 1
    incompleta = next((p for p in pedido.pizzas if not p.tamanho or not p.sabores), None)
    sabores = ", ".join(SABORES)
    if incompleta and not incompleta.tamanho:
        return "Desculpa, não peguei o tamanho. Pode ser pequena, média, grande ou família."
    if incompleta:
        return f"Desculpa, esse sabor eu não entendi. Tem {sabores}. Qual vai ser?"
    if pedido.erros == 1:
        return "Desculpa, não entendi a pizza. Me fala o tamanho e o sabor, tipo: uma grande de calabresa."
    return f"Os sabores são {sabores}, nos tamanhos pequena, média, grande e família. Qual vai ser?"


async def responder_com_ia(texto: str, pedido: Pedido) -> str | None:
    """Sua IA aqui: perguntas fora do roteiro ("tem borda recheada?") podem ir para o seu modelo, com o
    cardápio e o pedido como contexto. Se ela demorar, avise o cliente com ``call.thinking()``.
    Sem IA, o agente pede para o cliente reformular."""
    return None


async def responder(call: Call, pedido: Pedido, texto: str, decisao: Decision) -> tuple[str, bool]:
    """O que dizer a esta fala, e se a ligação termina depois dela."""
    intencao = decisao.business_intent()  # "other" quando a escolha não é segura
    resposta = RESPOSTAS.get(intencao, "")  # dúvida: responde e volta ao objetivo
    pizzas = ler_pizzas(texto)
    # "Meu nome é Lucas" mais tarde: o nome foi mal entendido antes; corrige e segue
    nome_corrigido = primeiro_nome(decisao.extracted.get("name") or "")
    if pedido.etapa != "nome" and nome_corrigido and decisao.intent.startswith("name_") and not pizzas:
        pedido.nome = nome_corrigido
        return f"Ah, desculpa, {nome_corrigido}! {proximo_objetivo(pedido)}", False
    if decisao.off_topic and not pizzas and not resposta and pedido.etapa != "mudar":
        return f"Isso eu não sei te dizer, aqui eu cuido dos pedidos da Bella Napoli. {proximo_objetivo(pedido)}", False

    resposta_curta = sim_ou_nao(texto, decisao)

    # "Só isso" encerra as pizzas, seja qual for a intenção lida (um não não é mudança de pedido)
    if pedido.etapa == "mais" and resposta_curta == "nao" and not pizzas and not resposta:
        pedido.etapa = "endereco"
        return proximo_objetivo(pedido), False
    # Mudar o pedido: o endereço recomeça; as pizzas, só depois de perguntar (nada se perde por engano)
    if intencao == "mudar_pedido" and pedido.pizzas and pedido.etapa not in ("pizzas", "mudar"):
        if re.search(r"endereco|rua|numero|bairro", normalizar(texto)):
            pedido.endereco = ""
            return proximo_objetivo(pedido), False
        pedido.etapa = "mudar"
        return "Claro! O que você quer mudar, as pizzas ou o endereço?", False
    if pedido.etapa == "mudar":
        if re.search(r"endereco|rua|numero|bairro", normalizar(texto)):
            pedido.endereco = ""
            return proximo_objetivo(pedido), False
        if resposta_curta and not pizzas:  # "nada, pode confirmar"
            pedido.etapa = "mais"
            return proximo_objetivo(pedido), False
        pedido.pizzas, pedido.etapa = pizzas, "pizzas"
        if pizzas:
            return proximo_objetivo(pedido), False
        return "Tranquilo, vamos refazer. Me fala de novo as pizzas, com tamanho e sabor.", False

    if pedido.etapa == "nome":
        pedido.pizzas += pizzas
        if not resposta:
            # A decisão já traz o nome quando o cliente se apresenta; senão, o Ermis Voice extrai da frase
            nome = primeiro_nome(decisao.extracted.get("name") or "")
            if not nome:
                extraido = await call.extract_slot(texto, "nome", "name")
                nome = primeiro_nome(extraido.value) if extraido.found else ""
            if not nome:
                pedido.erros += 1
                if pedido.erros < 2:
                    return "Desculpa, não peguei seu nome. Pode repetir?", False
                pedido.nome = "você"  # segue sem o nome
            else:
                pedido.nome = nome
            pedido.erros = 0
            if pedido.pizzas:  # pediu a pizza junto com o nome: confirma o que anotou
                pedido.etapa = "pizzas"
            pergunta = proximo_objetivo(pedido)
            anotado = f"Anotado, {' e '.join(p.falada() for p in pedido.pizzas)}. " if pedido.etapa == "mais" else ""
            saudacao = f"Prazer, {pedido.nome}! " if pedido.nome != "você" else ""
            return f"{saudacao}{anotado}{pergunta}", False

    elif pedido.etapa in ("pizzas", "mais"):
        incompleta = next((p for p in pedido.pizzas if not p.tamanho or not p.sabores), None)
        if incompleta and len(pizzas) == 1 and not (pizzas[0].tamanho and pizzas[0].sabores):
            incompleta.tamanho = incompleta.tamanho or pizzas[0].tamanho
            incompleta.sabores = incompleta.sabores or pizzas[0].sabores
            pizzas = [incompleta]
        else:
            pedido.pizzas += pizzas
        if pizzas:
            pergunta = proximo_objetivo(pedido)
            pedido.erros = 0
            anotado = f"Anotado, {' e '.join(p.falada() for p in pizzas)}. " if pedido.etapa == "mais" else ""
            return f"{anotado}{resposta} {pergunta}".replace("  ", " ").strip(), False
        if not resposta and pedido.etapa == "mais" and resposta_curta:
            if resposta_curta == "sim":
                pedido.etapa = "pizzas"
                return "Claro! Qual vai ser?", False
            pedido.etapa = "endereco"
            return proximo_objetivo(pedido), False
        if not resposta:
            return nao_entendi(pedido), False  # guarda o que entendeu e pergunta só o que falta

    elif pedido.etapa == "endereco" and not resposta:
        # O valor pedido com expect_slot: a mesma fala lida pelo reconhecimento preciso, em segundo plano
        esperado, pedido.esperado = pedido.esperado, None
        endereco = await esperado if esperado else await call.extract_slot(texto, "endereco", "address")
        if not endereco.found:
            return "Pode me dizer a rua, o número e o bairro da entrega?", False
        pedido.endereco = endereco.value
        return proximo_objetivo(pedido), False

    elif pedido.etapa == "confirmar":
        if resposta_curta == "sim":
            # Grave o pedido no seu sistema aqui
            obrigado = f"Obrigado, {pedido.nome}!" if pedido.nome != "você" else "Obrigado!"
            return f"Prontinho, pedido feito! Chega aí em uns quarenta e cinco minutos. {obrigado} Bom apetite!", True
        if resposta_curta == "nao":
            pedido.etapa = "mudar"
            return "Claro! O que você quer mudar, as pizzas ou o endereço?", False

    if resposta:
        return f"{resposta} {proximo_objetivo(pedido)}", False
    return await responder_com_ia(texto, pedido) or "Não entendi. Pode dizer de outro jeito?", False


async def conduzir(call: Call) -> None:
    pedido = Pedido()
    falas: dict[str, str] = {}
    encerrando = False
    confusas = 0  # falas confusas seguidas
    async for event in call:
        if isinstance(event, SessionStarted):
            await call.speak(SAUDACAO, calibrate=True)

        elif isinstance(event, Transcript):
            if event.assessment.ignore:
                await call.done_processing()  # ruído: o agente volta a ouvir
            elif not event.assessment.usable:
                await call.speak("Desculpe, não entendi. Pode repetir, por favor?")
            else:
                falas[event.utterance_id or ""] = event.text

        elif isinstance(event, Decision) and not encerrando:
            if event.is_escape:  # despedida ou pedido de atendente: o Ermis Voice já percebeu
                encerrando = True
                await call.speak(TRANSFERIR if event.intent == "request_human" else DESPEDIDA, allow_barge_in=False)
                continue
            if event.unclear:  # fala confusa: pede para repetir em vez de agir num palpite
                confusas += 1
                encerrando = confusas >= 3
                await call.speak(DESISTIR if encerrando else REPETIR, allow_barge_in=not encerrando)
                continue
            confusas = 0
            resposta, fim = await responder(call, pedido, falas.get(event.utterance_id or "", ""), event)
            encerrando = fim
            await call.speak(resposta, allow_barge_in=not fim)
            if pedido.etapa == "endereco" and pedido.esperado is None:
                # A próxima resposta é o endereço: o Ermis Voice lê com o reconhecimento preciso
                pedido.esperado = await call.expect_slot("endereco", "address", description="rua, número e bairro")

        elif isinstance(event, SpeakDone) and encerrando:
            await call.end()


@app.post("/twilio/voz")
async def voz() -> Response:
    """Webhook do Twilio: cria a sessão e manda o áudio da ligação direto para o Ermis Voice."""
    session = await ermis.sessions.create(
        transport="twilio",
        voice="man",
        custom_intents=INTENCOES,  # cada decisão já diz qual delas o cliente quis
        vocabulary=VOCABULARIO,  # o texto já chega com os sabores escritos certo
        turn_detection="smart_turn",
        early_turn={"speculate": True, "close_on_complete_text": True},
    )
    tarefa = asyncio.create_task(_atender(session))
    _conversas.add(tarefa)
    tarefa.add_done_callback(_conversas.discard)
    return Response(session.twiml(), media_type="application/xml")


async def _atender(session) -> None:
    async with ermis.connect(session) as call:
        await conduzir(call)
