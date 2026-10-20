"""Texto para a voz: o agente fala números, valores, datas e endereços por extenso, sem símbolos."""

import pytest

from ermis import normalize_for_speech, number_to_words


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("**Claro!** Vou verificar 😊", "Claro! Vou verificar"),
        ("O total é R$ 1.234,56", "O total é mil duzentos e trinta e quatro reais e cinquenta e seis centavos"),
        ("Custa R$ 50", "Custa cinquenta reais"),
        ("R$ 1,50", "um real e cinquenta centavos"),
        ("R$ 0,05", "cinco centavos"),
        ("R$1.500", "mil e quinhentos reais"),
        ("São 2 pizzas e 1 refrigerante", "São duas pizzas e um refrigerante"),
        ("1.500 pessoas", "mil e quinhentas pessoas"),
        ("21 fatias", "vinte e uma fatias"),
        ("Fica pronto em 2 horas", "Fica pronto em duas horas"),
        ("Abrimos às 18h e fechamos às 23h30", "Abrimos às dezoito horas e fechamos às vinte e três horas e trinta"),
        ("Te espero às 14:00", "Te espero às catorze horas"),
        ("às 0h", "à meia-noite"),
        ("Consulta dia 05/01/2026", "Consulta dia cinco de janeiro de dois mil e vinte e seis"),
        ("Vence 1/12", "Vence primeiro de dezembro"),
        ("Desconto de 15%", "Desconto de quinze por cento"),
        ("Taxa de 2,5%", "Taxa de dois vírgula cinco por cento"),
        ("Você é o 3º da fila, na 2ª posição", "Você é o terceiro da fila, na segunda posição"),
        ("Seu CPF 123.456.789-00", "Seu CPF um dois três, quatro cinco seis, sete oito nove, zero zero"),
        ("CEP 74000-000", "CEP sete quatro zero zero zero, zero zero zero"),
        ("Ligue (62) 99876-5432", "Ligue seis dois, nove nove oito sete seis, cinco quatro três dois"),
        ("Ligue 0800 123 4567", "Ligue zero oito zero zero, um dois três, quatro cinco seis sete"),
        ("Protocolo 20261020153", "Protocolo dois zero dois seis um zero dois zero um cinco três"),
        ("Mandei para ana.souza@gmail.com", "Mandei para ana ponto souza arroba gmail ponto com"),
        ("veja https://site.com.br", "veja site ponto com ponto bê erre"),
        ("Rua 7, nº 42", "Rua sete, número quarenta e dois"),
        ("Sr. João e Dra. Ana", "senhor João e doutora Ana"),
        ("Pão & leite", "Pão e leite"),
        ("1 kg de queijo", "um quilo de queijo"),
        ("- item um\n- item dois", "item um. item dois."),
        ("#promoção imperdível", "promoção imperdível"),
        ("Olá! Como posso ajudar?", "Olá! Como posso ajudar?"),
    ],
)
def test_normalize_for_speech(written, spoken):
    assert normalize_for_speech(written) == spoken


def test_number_to_words():
    assert number_to_words(1534) == "mil quinhentos e trinta e quatro"
    assert number_to_words(1200) == "mil e duzentos"
    assert number_to_words(2_500_300) == "dois milhões quinhentos mil e trezentos"
    assert number_to_words(100) == "cem" and number_to_words(101) == "cento e um"
    assert number_to_words(201, feminine=True) == "duzentas e uma"


def test_already_spoken_text_is_kept():
    text = "Prontinho, mandei pra joao arroba gmail ponto com. Posso ajudar em mais alguma coisa?"
    assert normalize_for_speech(text) == text
    assert normalize_for_speech(normalize_for_speech("R$ 49,90")) == "quarenta e nove reais e noventa centavos"
