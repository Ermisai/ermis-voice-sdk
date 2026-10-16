"""Primeira ligação: fale com o agente da Ermis sem telefone nem navegador.

O script abre uma sessão no transporte ``websocket``, onde o próprio script faz o
papel do telefone: envia uma fala gravada (um WAV qualquer) como se fosse o cliente
falando, conduz a conversa pelo canal de controle e salva tudo o que o agente
falou em ``resposta.wav``.

    pip install ermis-voice
    export ERMIS_API_KEY=...            # chave do Ermis Voice
    export ERMIS_API_URL=...            # URL do Ermis Voice
    python primeira_ligacao.py minha_fala.wav

Grave ``minha_fala.wav`` no celular ou no computador com uma frase curta, por exemplo
"quero a segunda via do boleto". Qualquer taxa de amostragem serve; o script converte.
"""

from __future__ import annotations

import asyncio
import sys
import wave
from array import array

from ermis import Audio, Decision, Ermis, SessionEnded, SessionStarted, SpeakDone, Transcript, UnknownEvent

FRAME = 160  # 20 ms de μ-law 8 kHz
SILENCE = b"\xff" * FRAME  # μ-law do silêncio
SAUDACAO = "Olá! Aqui é a assistente da Ermis. Como posso ajudar?"


# ── 1. Sua lógica: o que o agente responde ──────────────────────────────────
def responder(texto: str, decisao: Decision) -> str:
    """Troque por um roteiro ou pela sua IA. ``decisao`` já diz o que o cliente quer."""
    if decisao.is_escape:
        return "Tudo bem. Obrigada pela ligação, até logo!"
    if decisao.intent == "greeting":
        return "Oi! Em que posso ajudar?"
    return f"Entendi: {texto}. Vou verificar isso para você. Até logo!"


# ── 2. Áudio: WAV -> μ-law 8 kHz e de volta (só biblioteca padrão) ─────────
def _linear_to_ulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    sample = min(abs(sample), 32635) + 0x84
    exponent, mask = 7, 0x4000
    while exponent > 0 and not sample & mask:
        exponent, mask = exponent - 1, mask >> 1
    return ~(sign | (exponent << 4) | ((sample >> (exponent + 3)) & 0x0F)) & 0xFF


def _ulaw_to_linear(byte: int) -> int:
    byte = ~byte & 0xFF
    sample = (((byte & 0x0F) << 3) + 0x84) << ((byte & 0x70) >> 4)
    return 0x84 - sample if byte & 0x80 else sample - 0x84


def ler_wav_como_ulaw(caminho: str) -> bytes:
    with wave.open(caminho, "rb") as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit("Use um WAV PCM de 16 bits (o padrão da maioria dos gravadores).")
        canais, taxa = wav.getnchannels(), wav.getframerate()
        amostras = array("h", wav.readframes(wav.getnframes()))
    if sys.byteorder == "big":
        amostras.byteswap()
    mono = [sum(amostras[i : i + canais]) // canais for i in range(0, len(amostras), canais)]
    passo = taxa / 8000  # reamostragem simples para 8 kHz, suficiente para voz
    em_8k = [mono[int(i * passo)] for i in range(int(len(mono) / passo))]
    return bytes(_linear_to_ulaw(s) for s in em_8k)


def salvar_ulaw_como_wav(ulaw: bytes, caminho: str) -> None:
    pcm = array("h", (_ulaw_to_linear(b) for b in ulaw))
    if sys.byteorder == "big":
        pcm.byteswap()
    with wave.open(caminho, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(pcm.tobytes())


# ── 3. A ligação ────────────────────────────────────────────────────────────
async def main(arquivo: str) -> None:
    fala = SILENCE * 25 + ler_wav_como_ulaw(arquivo) + SILENCE * 50  # 0,5 s antes e 1 s depois
    resposta = bytearray()
    vez_do_cliente = asyncio.Event()  # o "cliente" fala depois que a saudação termina
    despedida: str | None = None
    ultima_fala = ""

    async with Ermis() as ermis:
        session = await ermis.sessions.create(transport="websocket", metadata={"exemplo": "primeira_ligacao"})
        print("sessão", session.session_id)

        async with ermis.connect(session) as call:

            async def telefone() -> None:
                """Microfone aberto: silêncio o tempo todo, e a fala gravada quando for a vez do cliente."""
                falou = False
                while True:
                    if vez_do_cliente.is_set() and not falou:
                        falou = True
                        for i in range(0, len(fala), FRAME):
                            await call.send_audio(fala[i : i + FRAME].ljust(FRAME, b"\xff"))
                            await asyncio.sleep(0.02)
                    await call.send_audio(SILENCE)
                    await asyncio.sleep(0.02)

            microfone = asyncio.create_task(telefone())
            try:
                async for event in call:
                    if isinstance(event, SessionStarted):
                        await call.speak(SAUDACAO, calibrate=True)
                    elif isinstance(event, Audio):
                        resposta += event.data  # voz do agente, μ-law 8 kHz
                    elif isinstance(event, UnknownEvent) and event.type == "audio.end":
                        # Quem toca o áudio é você: avise quando a fala do agente terminou
                        await call.playback_finished(event.raw["id"])
                    elif isinstance(event, SpeakDone):
                        if event.id == despedida:
                            await call.end()
                        else:
                            vez_do_cliente.set()
                    elif isinstance(event, Transcript):
                        print(f"cliente: {event.text!r}  ({event.latency_ms} ms)")
                        ultima_fala = event.text
                        if not event.assessment.usable:
                            await call.speak("Desculpe, não entendi. Pode repetir?")
                    elif isinstance(event, Decision):
                        print(f"decisão: intent={event.intent} action={event.action} encerrar={event.is_escape}")
                        texto = responder(ultima_fala, event)
                        print(f"agente: {texto!r}")
                        despedida = await call.speak(texto)
                    elif isinstance(event, SessionEnded):
                        print(f"fim: {event.reason}, {event.billed_seconds} s cobrados")
            finally:
                microfone.cancel()

    salvar_ulaw_como_wav(bytes(resposta), "resposta.wav")
    print(f"resposta.wav: {len(resposta) / 8000:.1f} s com tudo o que o agente falou")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1]))
