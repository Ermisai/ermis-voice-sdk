"""Roda examples/agendamento.py e examples/ura.py contra uma Voice API simulada.

A API simulada faz o papel do cliente: a cada fala do agente, envia a próxima fala do
roteiro (transcript + decision, já com o ``custom_intent`` das intenções da sessão) e responde a
``decide``, ``extract_slot`` e ``expect_slot`` (o valor da próxima resposta).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

pytest.importorskip("fastapi")
pytest.importorskip("multipart")


def _load(monkeypatch, name: str):
    monkeypatch.setenv("ERMIS_API_KEY", "ek_test_123")
    path = Path(__file__).parents[1] / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"exemplo_{name}", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # dataclasses look up their module
    spec.loader.exec_module(module)
    return module


async def _run(module, falas, decisoes, slots, **kwargs):
    """``falas``: (texto, intent, is_escape) do cliente; ``decisoes``: texto -> custom_intent;
    ``slots``: nome do slot -> valor (None: não encontrado). Devolve os comandos recebidos."""
    received: list[dict] = []
    pendentes = list(falas)
    pendentes_slot: list[tuple[str, str | None]] = []

    async def handler(ws):
        await ws.send(json.dumps({"type": "session.started", "session_id": "vs_1"}))
        n = 0
        async for raw in ws:
            msg = json.loads(raw)
            received.append(msg)
            kind = msg["type"]
            if kind == "decide":
                intent = decisoes.get(msg["text"], "other")
                await ws.send(
                    json.dumps(
                        {
                            "type": "decision",
                            "id": msg["id"],
                            "intent": "complex",
                            "action": "escalate",
                            "custom_intent": intent,
                        }
                    )
                )
            elif kind == "expect_slot":
                # Lida pelo reconhecimento preciso: o valor chega depois da decisão da resposta
                value = slots.get(msg["slot"]["name"])
                status = "found" if value else "not_found"
                await ws.send(json.dumps({"type": "slot", "id": msg["id"], "value": value, "status": status}))
            elif kind == "extract_slot":
                value = slots.get(msg["slot"]["name"])
                status = "found" if value else "not_found"
                await ws.send(json.dumps({"type": "slot", "id": msg["id"], "value": value, "status": status}))
            elif kind == "ask" and msg.get("slot"):
                # The value of the answer comes as a slot with the id of the question, after its decision
                value = slots.get(msg["slot"]["name"])
                pendentes_slot.append((msg["id"], value))
            if kind == "ask":
                kind = "speak"  # a question is spoken like any other line
            if kind == "speak":
                await ws.send(json.dumps({"type": "speak.done", "id": msg["id"], "chars": len(msg["text"])}))
                if msg.get("allow_barge_in") is False or not pendentes:
                    continue
                texto, intent, escape = pendentes.pop(0)
                n += 1
                uid = f"u{n}"
                await ws.send(json.dumps({"type": "transcript", "utterance_id": uid, "text": texto, "assessment": {}}))
                await ws.send(
                    json.dumps(
                        {
                            "type": "decision",
                            "utterance_id": uid,
                            "intent": intent,
                            "action": "escalate",
                            "is_escape": escape,
                            "custom_intent": decisoes.get(texto, "other"),
                            "custom_intent_confidence": 1.0,
                            "answer": {"confirm_yes": "yes", "confirm_no": "no"}.get(intent),
                        }
                    )
                )
                for slot_id, value in pendentes_slot:
                    status = "found" if value else "not_found"
                    await ws.send(json.dumps({"type": "slot", "id": slot_id, "value": value, "status": status}))
                pendentes_slot.clear()
            elif kind == "end":
                await ws.send(json.dumps({"type": "session.ended", "reason": "client"}))
                return

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with module.ermis.connect(f"ws://127.0.0.1:{port}/control") as call:
            await asyncio.wait_for(module.conduzir(call, **kwargs), timeout=5)
    return received


def _said(received):
    return [m["text"] for m in received if m["type"] in ("speak", "ask")]


async def test_scheduling_books_an_appointment(monkeypatch):
    exemplo = _load(monkeypatch, "agendamento")
    gravados = []

    async def gravar(pedido):
        gravados.append(pedido)

    monkeypatch.setattr(exemplo, "gravar_agendamento", gravar)
    falas = [
        ("quero marcar uma consulta", "complex", False),
        ("pode ser amanhã", "complex", False),
        ("às duas da tarde", "complex", False),
        ("é maria souza", "name_provide", False),
        ("onze nove oito sete seis cinco quatro três dois um", "complex", False),
        ("sim, está certo", "confirm_yes", False),
    ]
    decisoes = {"quero marcar uma consulta": "marcar", "às duas da tarde": "14:00"}
    slots = {"dia": "amanhã", "nome": "Maria Souza", "telefone": "(11) 98765-4321"}
    received = await _run(exemplo, falas, decisoes, slots)

    said = _said(received)
    assert said[0] == exemplo.SAUDACAO
    assert "amanhã" in said[2] and "duas da tarde" in said[2]
    assert said[-2].startswith("Vou marcar uma consulta para Maria Souza, amanhã, às duas da tarde")
    assert said[-1].startswith("Consulta marcada!")
    assert received[-1]["type"] == "end"
    assert any(m["type"] == "thinking" for m in received)
    assert gravados[0].hora == "14:00" and gravados[0].telefone == "(11) 98765-4321"


async def test_scheduling_cancel_and_goodbye(monkeypatch):
    exemplo = _load(monkeypatch, "agendamento")
    falas = [("quero desmarcar", "complex", False), ("não precisa, tchau", "farewell", True)]
    received = await _run(exemplo, falas, {"quero desmarcar": "cancelar"}, {})
    said = _said(received)
    assert said[1] == "Certo. Qual é o nome do paciente?"
    assert said[-1] == exemplo.DESPEDIDA
    assert received[-1]["type"] == "end"


async def test_ivr_routes_finance_with_cpf(monkeypatch):
    exemplo = _load(monkeypatch, "ura")
    transferidos = []

    async def transferir(call_sid, setor, dados):
        transferidos.append((call_sid, setor, dados))

    monkeypatch.setattr(exemplo, "transferir", transferir)
    falas = [
        ("quero a segunda via do boleto", "complex", False),
        ("um dois três ponto quatro cinco seis", "complex", False),
    ]
    received = await _run(
        exemplo, falas, {"quero a segunda via do boleto": "financeiro"}, {"cpf": "123.456.789-09"}, call_sid="CA1"
    )
    assert _said(received)[-1] == exemplo.AVISOS["financeiro"]
    assert transferidos == [("CA1", "financeiro", {"cpf": "123.456.789-09"})]
    assert received[-1]["type"] == "end"


async def test_ivr_falls_back_to_an_agent(monkeypatch):
    exemplo = _load(monkeypatch, "ura")
    transferidos = []

    async def transferir(call_sid, setor, dados):
        transferidos.append(setor)

    monkeypatch.setattr(exemplo, "transferir", transferir)
    falas = [("hã", "unclear", False), ("sei lá", "unclear", False), ("não sei", "unclear", False)]
    received = await _run(exemplo, falas, {}, {})
    assert _said(received)[-1] == exemplo.AVISOS["atendente"]
    assert transferidos == ["atendente"]


async def test_pizzeria_takes_an_order_with_the_address_read_by_the_precise_recognizer(monkeypatch):
    exemplo = _load(monkeypatch, "pizzaria")
    falas = [
        ("é o João", "name_provide", False),
        ("uma grande de calabresa", "complex", False),
        ("não, só isso", "confirm_no", False),
        ("rodas flores dez centro", "complex", False),
        ("sim, pode confirmar", "confirm_yes", False),
    ]
    decisoes = {"uma grande de calabresa": "pedir_pizza", "rodas flores dez centro": "informar_endereco"}
    slots = {"nome": "João", "endereco": "Rua das Flores, 10, Centro"}
    received = await _run(exemplo, falas, decisoes, slots)

    said = _said(received)
    assert said[1] == "Prazer, João! O que vai ser hoje?"
    assert said[2] == "Anotado, uma grande de calabresa. Quer mais alguma pizza?"
    expect = next(m for m in received if m["type"] == "ask" and m.get("slot"))
    assert expect["slot"]["name"] == "endereco" and expect["slot"]["type"] == "address"
    assert any(m["type"] == "ask" and m.get("choices") for m in received), "flavors as expected answers"
    # The address came from expect_slot (the precise reading), and the voice reads "10" as "dez"
    assert "pra entregar na Rua das Flores, dez, Centro" in said[4]
    assert said[-1].startswith("Prontinho, pedido feito!")
    session = exemplo.INTENCOES and exemplo.VOCABULARIO
    assert "margherita" in session


def test_examples_only_pass_options_the_sdk_accepts():
    """Every keyword the examples give to ``sessions.create`` exists in it (a typo or a missing option
    would only fail when a customer runs the example)."""
    import ast
    import inspect

    from ermis.client import _Sessions

    accepted = set(inspect.signature(_Sessions.create).parameters) - {"self"}
    used: set[str] = set()
    for path in Path(__file__).resolve().parents[1].glob("examples/*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "create":
                used |= {k.arg for k in node.keywords if k.arg}
    assert used and used <= accepted, used - accepted
