"""Telemetria da rodada: latencias no `llm_uso`, `erro` na `ferramenta` e o evento `erro_llm`.

Relogios falsos: o monotonico mede duracoes, o de parede mede o tempo de resposta ao cliente
(da mensagem do cliente ate o envio). Nada muda no comportamento do agente; so eventos.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.adapters.outbound.llm.fake import RespostaRoteirizada, Roteiro
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.llm import (
    ErroLLM,
    LLMIndisponivel,
    LLMRecusou,
    MensagemLLM,
    UsoTokens,
)

from .apoio_processar import INTERESSE_16, Cenario, chamada, criar_cenario, texto


def _eventos(c: Cenario, tipo: str) -> list[dict[str, Any]]:
    return [e.payload for e in c.eventos.registrados if e.tipo == tipo]


def _gasta(c: Cenario, ms: int, resposta: RespostaRoteirizada) -> Roteiro:
    """Chamada ao LLM que leva `ms` (nos dois relogios) e devolve `resposta`."""

    def _roteiro(_mensagens: list[MensagemLLM]) -> RespostaRoteirizada:
        c.relogio.avancar(ms / 1000)
        c.parede.avancar(ms / 1000)
        return resposta

    return _roteiro


class _CatalogoLento(CatalogoFerramentas):
    """Ferramentas reais, mas cada execucao leva `ms` (fora do LLM)."""

    def __init__(self, c_getter: Any, ms: int) -> None:
        super().__init__()
        self._c = c_getter
        self._ms = ms

    async def executar(self, *args: Any, **kwargs: Any) -> Any:
        c = self._c()
        c.relogio.avancar(self._ms / 1000)
        c.parede.avancar(self._ms / 1000)
        return await super().executar(*args, **kwargs)


async def test_rodada_grava_as_tres_latencias() -> None:
    caixa: dict[str, Cenario] = {}
    catalogo = _CatalogoLento(lambda: caixa["c"], 200)
    c = await criar_cenario([], catalogo=catalogo)
    caixa["c"] = c
    c.llm._roteiro.extend(  # type: ignore[attr-defined]
        [
            _gasta(
                c,
                1500,
                RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            ),
            _gasta(
                c, 700, RespostaRoteirizada(texto="Tenho sim!", uso=UsoTokens("fake", 1, 1, 0, 0))
            ),
        ]
    )
    entrada = c.conversas.adicionar_entrada(c.conversa_id, "oi, quero um iphone 16")
    c.parede.definir(entrada.criado_em + timedelta(seconds=5))  # o debounce esperou 5 s

    await c.caso(c.conversa_id)

    (uso,) = _eventos(c, "llm_uso")
    assert uso["latencia_llm_ms"] == 2200  # 1500 + 700
    assert uso["latencia_rodada_ms"] == 2400  # + 200 da ferramenta
    assert uso["tempo_resposta_ms"] == 7400  # 5000 do debounce + a rodada
    assert uso["chamadas"] == 2


async def test_tempo_de_resposta_parte_da_primeira_entrada_atendida_na_rodada() -> None:
    c = await criar_cenario([])
    c.llm._roteiro.append(_gasta(c, 1000, texto("Oi!")))  # type: ignore[attr-defined]
    primeira = c.conversas.adicionar_entrada(c.conversa_id, "oi")
    c.conversas.adicionar_entrada(c.conversa_id, "tem iphone?")
    c.parede.definir(primeira.criado_em + timedelta(seconds=10))

    await c.caso(c.conversa_id)

    (uso,) = _eventos(c, "llm_uso")
    assert uso["tempo_resposta_ms"] == 11000  # conta desde a PRIMEIRA mensagem
    assert uso["latencia_rodada_ms"] == 1000


async def test_latencias_nunca_ficam_negativas() -> None:
    c = await criar_cenario([texto("Oi!")])
    entrada = c.conversas.adicionar_entrada(c.conversa_id, "oi")
    c.parede.definir(entrada.criado_em - timedelta(seconds=3))  # relogios dessincronizados
    await c.caso(c.conversa_id)
    (uso,) = _eventos(c, "llm_uso")
    assert uso["tempo_resposta_ms"] == 0


async def test_resposta_descartada_registra_latencia_mas_nao_tempo_de_resposta() -> None:
    c = await criar_cenario([])

    def _com_mensagem_nova(_m: list[MensagemLLM]) -> RespostaRoteirizada:
        c.relogio.avancar(0.9)
        c.cliente_diz("ah, e o 15?")  # chega enquanto o LLM pensa
        return texto("Tenho o 16.")

    c.llm._roteiro.append(_com_mensagem_nova)  # type: ignore[attr-defined]
    c.cliente_diz("oi")
    await c.caso(c.conversa_id)

    assert "resposta_descartada" in c.tipos_de_evento()
    (uso,) = _eventos(c, "llm_uso")
    assert uso["latencia_llm_ms"] == 900 and uso["latencia_rodada_ms"] == 900
    assert "tempo_resposta_ms" not in uso  # nenhuma resposta saiu ao cliente
    assert c.canal.enviadas == []


async def test_limite_de_iteracoes_continua_gravando_evento_e_latencias() -> None:
    laco = [RespostaRoteirizada(chamadas=[chamada(f"t{i}", "calcular_proposta")]) for i in range(3)]
    c = await criar_cenario([], max_iteracoes=3)
    c.llm._roteiro.extend(_gasta(c, 100, r) for r in laco)  # type: ignore[attr-defined]
    await c.turno("preco?")

    assert "limite_iteracoes" in c.tipos_de_evento()
    (uso,) = _eventos(c, "llm_uso")
    assert uso["latencia_llm_ms"] == 300 and uso["latencia_rodada_ms"] == 300


async def test_ferramenta_sem_erro_grava_erro_false() -> None:
    c = await criar_cenario(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            texto("Anotado!"),
        ]
    )
    await c.turno("quero iphone 16")
    (ev,) = _eventos(c, "ferramenta")
    assert ev["erro"] is False
    assert ev["nome"] == "registrar_interesse" and "resultado_resumido" in ev


async def test_ferramenta_com_erro_grava_erro_true() -> None:
    c = await criar_cenario(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "ferramenta_que_nao_existe")]),
            texto("Vou confirmar isso."),
        ]
    )
    await c.turno("oi")
    (ev,) = _eventos(c, "ferramenta")
    assert ev["erro"] is True
    assert ev["nome"] == "ferramenta_que_nao_existe"


async def test_ferramenta_que_levanta_excecao_tambem_conta_como_erro() -> None:
    class Quebrado(CatalogoFerramentas):
        async def executar(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    c = await criar_cenario(
        [
            RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            texto("Tive um probleminha."),
        ],
        catalogo=Quebrado(),
    )
    await c.turno("quero iphone 16")
    (ev,) = _eventos(c, "ferramenta")
    assert ev["erro"] is True and ev["nome"] == "registrar_interesse"
    assert len(_eventos(c, "ferramenta_erro")) == 1  # o diagnostico (traceback) segue gravado


@pytest.mark.parametrize(
    ("erro", "esperado"),
    [
        (LLMIndisponivel("fora"), {"tipo": "LLMIndisponivel"}),
        (LLMRecusou("cyber"), {"tipo": "LLMRecusou"}),
        (
            ErroLLM("bad request", status=400, modelo="claude-x"),
            {"tipo": "ErroLLM", "status": 400, "modelo": "claude-x"},
        ),
    ],
)
async def test_falha_do_llm_grava_erro_llm(erro: ErroLLM, esperado: dict[str, Any]) -> None:
    c = await criar_cenario([RespostaRoteirizada(erro=erro)])
    await c.turno("oi")

    assert _eventos(c, "erro_llm") == [esperado]
    handoff = _eventos(c, "handoff")
    assert handoff and handoff[0]["motivo"] == "falha_llm"  # o comportamento nao mudou
    assert "llm_uso" not in c.tipos_de_evento()  # nenhuma chamada concluiu: sem tokens


async def test_falha_no_meio_da_rodada_mantem_llm_uso_com_a_latencia_gasta() -> None:
    c = await criar_cenario([])
    c.llm._roteiro.extend(  # type: ignore[attr-defined]
        [
            _gasta(
                c,
                400,
                RespostaRoteirizada(chamadas=[chamada("t1", "registrar_interesse", INTERESSE_16)]),
            ),
            _gasta(c, 600, RespostaRoteirizada(erro=LLMIndisponivel("caiu"))),
        ]
    )
    await c.turno("quero iphone 16")

    assert _eventos(c, "erro_llm") == [{"tipo": "LLMIndisponivel"}]
    (uso,) = _eventos(c, "llm_uso")
    assert uso["chamadas"] == 1
    assert uso["latencia_llm_ms"] == 1000  # a chamada que falhou tambem demorou
    assert uso["latencia_rodada_ms"] == 1000


async def test_sem_relogios_injetados_o_agente_funciona_sem_as_latencias() -> None:
    c = await criar_cenario([texto("Oi!")])
    c.caso._relogio = None  # type: ignore[attr-defined]
    c.caso._parede = None  # type: ignore[attr-defined]
    await c.turno("oi")
    (uso,) = _eventos(c, "llm_uso")
    assert "latencia_llm_ms" not in uso and "tempo_resposta_ms" not in uso
