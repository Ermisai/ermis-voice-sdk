"""Texto para a voz: o que o agente fala, escrito do jeito que se fala em português do Brasil.

O ``Call`` aplica :func:`normalize_for_speech` em toda fala (``speak`` e ``say``), a não ser que você
desligue com ``ermis.connect(session, normalize_text=False)`` ou ``speak(..., normalize=False)``.

- Números por extenso, com gênero quando há um substantivo depois: ``2 pizzas`` -> "duas pizzas",
  ``1.500`` -> "mil e quinhentos", ``2,5`` -> "dois vírgula cinco".
- Dinheiro, datas, horas, porcentagens e ordinais: ``R$ 1.234,56``, ``05/01/2026``, ``14h30``, ``15%``, ``3º``.
- Códigos lidos em grupos de dígitos: CPF, CEP, telefone, protocolo (``123.456.789-00``, ``74000-000``).
- E-mails e sites: ``ana@gmail.com`` -> "ana arroba gmail ponto com".
- Abreviações comuns (``Sr.``, ``Dra.``, ``nº``) e símbolos (``&``, ``+``).
- Sem markdown nem emojis: ``**Claro!**`` -> "Claro!".

Baseado no ``text-normalizer`` da Ermis (github.com/Ermisai/text-normalizer), sem dependências.
"""

from __future__ import annotations

import re

__all__ = ["normalize_for_speech", "number_to_words"]

_UNITS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
          "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]  # fmt: skip
_TENS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_HUNDREDS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos"]  # fmt: skip
_SCALES = [(10**9, "bilhão", "bilhões"), (10**6, "milhão", "milhões"), (1000, "mil", "mil")]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"]  # fmt: skip
_DIGITS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]
# Substantivos femininos comuns depois de números: "2 pizzas" se lê "duas pizzas"
_FEMININE = re.compile(
    r"\s+(?:horas?|pizzas?|pessoas?|vezes|semanas?|fatias?|unidades?|parcelas?|consultas?|opç(?:ão|ões)|"
    r"mesas?|noites?|caixas?|garrafas?|porç(?:ão|ões)|latas?|pizzas?|camisetas?|entregas?|ligaç(?:ão|ões)|"
    r"faturas?|contas?|linhas?|vagas?|crianças?|libras?|toneladas?|gramas?)\b",
    re.IGNORECASE,
)
_ABBREVIATIONS = {
    "sr.": "senhor", "sra.": "senhora", "srta.": "senhorita", "dr.": "doutor", "dra.": "doutora",
    "prof.": "professor", "profa.": "professora", "av.": "avenida", "tel.": "telefone", "nº": "número",
    "n°": "número", "obs.": "observação", "aprox.": "aproximadamente", "etc.": "etcétera",
}  # fmt: skip


def number_to_words(n: int, *, feminine: bool = False) -> str:
    """``1534`` -> "mil quinhentos e trinta e quatro"; ``feminine=True`` -> "duas", "duzentas"."""
    if n < 0:
        return "menos " + number_to_words(-n, feminine=feminine)
    if n == 0:
        return "zero"
    parts: list[str] = []
    rest = n
    for value, singular, plural in _SCALES:
        count, rest = divmod(rest, value)
        if count:
            if value == 1000:
                # "mil", "duas mil"; a escala mil concorda com o substantivo
                parts.append("mil" if count == 1 else f"{_below_thousand(count, feminine)} mil")
            else:
                parts.append(f"{_below_thousand(count, False)} {singular if count == 1 else plural}")
    if rest:
        parts.append(_below_thousand(rest, feminine))
    if len(parts) > 1 and (rest < 100 or rest % 100 == 0) and rest:
        # "mil e duzentos", "dois mil e cinquenta", mas "mil duzentos e trinta"
        return " ".join(parts[:-1]) + " e " + parts[-1]
    return " ".join(parts)


def _below_thousand(n: int, feminine: bool) -> str:
    words: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        if hundreds == 1 and rest == 0:
            words.append("cem")
        else:
            word = _HUNDREDS[hundreds]
            words.append(word[:-2] + "as" if feminine and hundreds > 1 else word)
    if rest:
        if rest < 20:
            word = _UNITS[rest]
        else:
            tens, unit = divmod(rest, 10)
            word = _TENS[tens] + (f" e {_UNITS[unit]}" if unit else "")
        if feminine:
            word = re.sub(r"\bum$", "uma", word)
            word = re.sub(r"\bdois$", "duas", word)
        words.append(word)
    return " e ".join(words)


def _digits(text: str) -> str:
    return " ".join(_DIGITS[int(d)] for d in text if d.isdigit())


def _plain_number(text: str, feminine: bool = False) -> str:
    """Um número escrito ("1.500", "2,5", "0800"), por extenso; códigos longos dígito a dígito."""
    if "," in text:
        whole, decimals = text.split(",", 1)
        whole_words = _plain_number(whole, feminine)
        decimals = decimals.rstrip("0") or "0"
        decimal_words = _digits(decimals) if decimals.startswith("0") else number_to_words(int(decimals))
        return f"{whole_words} vírgula {decimal_words}"
    digits = text.replace(".", "")
    if not digits.isdigit():
        return text
    if (len(digits) > 1 and digits.startswith("0")) or len(digits) > 9:
        return _digits(digits)  # códigos, protocolos: "zero oitocentos" soaria errado
    return number_to_words(int(digits), feminine=feminine)


def _money(match: re.Match[str]) -> str:
    whole = int(match.group(1).replace(".", ""))
    cents = int((match.group(2) or "0").ljust(2, "0"))
    parts = []
    if whole:
        mil = whole % 1_000_000 == 0
        parts.append(f"{number_to_words(whole)}{' de' if mil else ''} {'real' if whole == 1 else 'reais'}")
    if cents:
        parts.append(f"{number_to_words(cents)} {'centavo' if cents == 1 else 'centavos'}")
    return " e ".join(parts) or "zero reais"


def _date(match: re.Match[str]) -> str:
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)
    spoken = f"{'primeiro' if day == 1 else number_to_words(day)} de {_MONTHS[month - 1]}"
    if year:
        y = int(year)
        y += 2000 if y < 50 and len(year) == 2 else 1900 if len(year) == 2 else 0
        spoken += f" de {number_to_words(y)}"
    return spoken


def _time(match: re.Match[str]) -> str:
    hours, minutes = int(match.group(1)), int(match.group(2) or 0)
    if hours > 23 or minutes > 59:
        return match.group(0)
    spoken = (
        "uma hora"
        if hours == 1
        else "meia-noite"
        if hours == 0 and not minutes
        else (f"{number_to_words(hours, feminine=True)} horas")
    )
    if minutes:
        spoken += f" e {number_to_words(minutes)}"
    return spoken


def _code(match: re.Match[str]) -> str:
    """CPF, CEP, telefone, cartão: grupos de dígitos com uma pausa entre eles."""
    groups = re.findall(r"\d+", match.group(0))
    return ", ".join(_digits(group) for group in groups)


_TLDS = {"br": "bê erre", "com": "com", "org": "órg", "net": "net", "gov": "gov", "io": "i ó", "ai": "a i"}


def _address(text: str) -> str:
    def part(word: str) -> str:
        return _TLDS.get(word.lower(), word.replace("-", " hífen ").replace("_", " sublinhado "))

    return " ponto ".join(part(word) for word in text.split("."))


def _email(match: re.Match[str]) -> str:
    local, domain = match.group(0).split("@", 1)
    return f"{_address(local)} arroba {_address(domain)}"


def _url(match: re.Match[str]) -> str:
    host = re.sub(r"^https?://", "", match.group(0), flags=re.IGNORECASE).rstrip("/.")
    host, _, path = host.partition("/")
    spoken = _address(host.removeprefix("www.").removeprefix("WWW."))
    if host.lower().startswith("www."):
        spoken = "dáblio dáblio dáblio ponto " + spoken
    if path:
        spoken += " barra " + " barra ".join(_address(p) for p in path.split("/") if p)
    return spoken


_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\U00002190-\U000021ff"
    "\U00002300-\U000023ff\U00002b00-\U00002bff️‍]+"
)


def normalize_for_speech(text: str) -> str:
    """``text`` pronto para a voz: números, valores, datas, códigos e endereços por extenso, sem símbolos."""
    if not text or not text.strip():
        return text
    t = text
    # Markdown, listas e emojis: a voz leria os símbolos
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)  # [texto](link)
    t = re.sub(r"(\*\*|__|\*|`|~~)", "", t)
    t = re.sub(r"^\s*(?:#{1,6}|[-*•>]|\d+[.)])\s+", "", t, flags=re.M)
    t = _EMOJI.sub("", t)
    # Cada linha (item de lista, título) vira uma frase: a voz faz a pausa
    t = (
        " ".join(
            line if re.search(r"[.!?:;,]$", line) else line + "."
            for line in (x.strip() for x in t.splitlines())
            if line
        )
        if "\n" in t
        else t
    )

    # Endereços antes dos números (têm pontos e dígitos)
    t = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", _email, t)
    t = re.sub(r"\b(?:https?://|www\.)[^\s,;!?)]+", _url, t, flags=re.IGNORECASE)

    # Abreviações
    for short, long in _ABBREVIATIONS.items():
        t = re.sub(rf"(?<!\w){re.escape(short)}(?=\s|$)", long, t, flags=re.IGNORECASE)

    # Dinheiro, porcentagem, datas, horas, ordinais
    t = re.sub(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?", _money, t)
    t = re.sub(r"(\d+(?:,\d+)?)\s*%", lambda m: f"{_plain_number(m.group(1))} por cento", t)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b", _date, t)
    t = re.sub(r"\b(\d{1,2})(?:h|:)(\d{2})?(?:min)?\b", _time, t)
    t = re.sub(r"\b(\d{1,2})\s*horas?\b", lambda m: _time(re.match(r"(\d+)()", m.group(1))), t)
    t = re.sub(
        r"\b(\d+)\s*([ºª°])",
        lambda m: _ordinal(int(m.group(1)), feminine=m.group(2) == "ª"),
        t,
    )

    # Códigos: CPF 123.456.789-00, CNPJ, CEP 74000-000, telefone (62) 99999-1234, cartão 1234 5678
    t = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", _code, t)
    t = re.sub(r"\(?\b\d{2}\)?\s*\d{4,5}-\d{4}\b|\b\d{5}-\d{3}\b|\b\d{4}(?:\s\d{4}){2,3}\b", _code, t)
    t = re.sub(r"\b0[358]00[\s-]?\d{3}[\s-]?\d{4}\b", _code, t)  # 0800 123 4567

    # Unidades depois de números: "2 kg" -> "2 quilos"
    for unit, spoken in (("kg", "quilos"), ("km", "quilômetros"), ("ml", "mililitros"), ("cm", "centímetros")):
        t = re.sub(rf"(\d)\s*{unit}\b", rf"\1 {spoken}", t)

    # Números que sobraram: "1.500", "2,5", "3 pizzas"
    def number(match: re.Match[str]) -> str:
        feminine = bool(_FEMININE.match(t, match.end()))
        return _plain_number(match.group(0), feminine)

    t = re.sub(r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b|\b\d+(?:,\d+)?\b", number, t)

    # Símbolos que sobraram
    t = re.sub(r"\s*&\s*", " e ", t)
    t = re.sub(r"(?<=\w)\s*\+\s*(?=\w)", " mais ", t)
    t = re.sub(r"[#*_~^|<>{}\[\]\\=$@]", " ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"\bàs meia-noite\b", "à meia-noite", t)
    t = re.sub(r"\b(um|uma) quilos\b", r"\1 quilo", t)
    return re.sub(r"\s+", " ", t).strip()


_ORDINAL_UNITS = ["", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto", "sétimo", "oitavo", "nono"]
_ORDINAL_TENS = ["", "décimo", "vigésimo", "trigésimo", "quadragésimo", "quinquagésimo", "sexagésimo",
                 "septuagésimo", "octogésimo", "nonagésimo"]  # fmt: skip


def _ordinal(n: int, feminine: bool = False) -> str:
    if not 1 <= n < 100:
        return number_to_words(n, feminine=feminine)
    tens, unit = divmod(n, 10)
    words = " ".join(w for w in (_ORDINAL_TENS[tens], _ORDINAL_UNITS[unit]) if w)
    return re.sub(r"o\b", "a", words) if feminine else words
