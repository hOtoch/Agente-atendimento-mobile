"""LLMSimulado: texto fixo com latencia configuravel, para teste de carga (sem rede)."""

from __future__ import annotations

import random

import pytest

from app.adapters.outbound.llm.simulado import LLMSimulado
from app.application.llm import BlocoTexto, LLMPort, MensagemLLM


class Dorminhoco:
    def __init__(self) -> None:
        self.esperas: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.esperas.append(segundos)


def usuario(texto: str) -> MensagemLLM:
    return MensagemLLM("user", [BlocoTexto(texto)])


async def test_responde_texto_fixo_sem_chamar_ferramentas() -> None:
    llm: LLMPort = LLMSimulado(latencia_ms=0, dormir=Dorminhoco())
    r = await llm.responder(["sys"], [usuario("oi")], [])
    assert r.texto
    assert r.chamadas == []
    assert r.motivo_parada == "end_turn"
    assert r.mensagem_assistente.papel == "assistant"
    assert r.modelo_usado == "simulado"


async def test_dorme_a_latencia_base_quando_nao_ha_jitter() -> None:
    dorme = Dorminhoco()
    llm = LLMSimulado(latencia_ms=2500, dormir=dorme)
    await llm.responder([], [usuario("oi")], [])
    assert dorme.esperas == [2.5]


async def test_jitter_mantem_a_latencia_na_faixa() -> None:
    dorme = Dorminhoco()
    llm = LLMSimulado(latencia_ms=2750, jitter_ms=1250, dormir=dorme, aleatorio=random.Random(1))
    for _ in range(200):
        await llm.responder([], [usuario("oi")], [])
    assert min(dorme.esperas) >= 1.5
    assert max(dorme.esperas) <= 4.0
    assert len(set(dorme.esperas)) > 50  # varia de verdade


async def test_jitter_maior_que_a_base_nunca_gera_espera_negativa() -> None:
    dorme = Dorminhoco()
    llm = LLMSimulado(latencia_ms=100, jitter_ms=5000, dormir=dorme, aleatorio=random.Random(2))
    for _ in range(100):
        await llm.responder([], [usuario("oi")], [])
    assert min(dorme.esperas) >= 0.0


@pytest.mark.parametrize("campo", ["latencia_ms", "jitter_ms"])
def test_rejeita_valor_negativo(campo: str) -> None:
    with pytest.raises(ValueError):
        LLMSimulado(**{campo: -1})  # type: ignore[arg-type]
