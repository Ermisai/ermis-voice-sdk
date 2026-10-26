"""Checagem de conexão: a chave, o endereço da Voice API e os créditos da conta, antes da primeira ligação.

    pip install ermis-voice
    export ERMIS_API_KEY=...            # chave de API criada na plataforma da Ermis (app.ermis.ai)
    python checa_conexao.py

Se der certo, mostra a versão do SDK, o endereço usado, as vozes da sua conta e o saldo de créditos. Se der
errado, diz o que conferir. ``ERMIS_API_URL`` só é preciso quando a equipe da Ermis indicar outro endereço.
"""

from __future__ import annotations

import asyncio
import sys

import ermis
from ermis import APIError, AuthenticationError, Ermis, ErmisError


async def main() -> int:
    print(f"SDK ermis-voice {ermis.__version__}")
    try:
        async with Ermis() as cliente:  # lê ERMIS_API_KEY e ERMIS_API_URL
            print(f"Voice API: {cliente.base_url}")
            saldo = await cliente.balance()  # primeiro: é aqui que a chave é conferida
            vozes = await cliente.voices.list()
            print(f"Vozes: {', '.join(v.name for v in vozes)}")
    except AuthenticationError as exc:
        print(f"Chave recusada ({exc.status or exc.code}): confira ERMIS_API_KEY (sem espaços sobrando) ou gere outra.")
        return 1
    except APIError as exc:
        if exc.code == "product_not_allowed":
            print(f"Chave sem acesso ao Ermis Voice: {exc.message}")
        else:
            print(f"Falha: {exc.message}")
        return 1
    except ErmisError as exc:
        print(f"Falha: {exc.message}")
        return 1
    disponivel = saldo.get("available_credits", 0)
    print(f"Créditos: {disponivel} disponíveis ({saldo.get('reserved_credits', 0)} reservados em ligações)")
    if not disponivel:
        print("Atenção: a conta está sem créditos; as ligações podem ser recusadas.")
    print("Tudo certo: a conexão funciona. Próximo passo: python primeira_ligacao.py minha_fala.wav")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
