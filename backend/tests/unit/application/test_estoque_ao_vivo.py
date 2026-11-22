"""Decorator `EstoqueConferidoAoVivo`: confere o SKU no ERP antes de entregar o item ao agente.

A conferencia e uma porta (`ConferenciaItemErp`) trocada por fakes; o timeout real e pequeno
(0.05 s) e o fake dorme de verdade, como em `test_estoque_resiliente.py`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from app.adapters.outbound.estoque.memoria import FonteEstoqueEmMemoria
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application import estoque_ao_vivo
from app.application.config.memoria import MemoriaEstoqueLocal
from app.application.config.modelos import LinhaEstoqueLocal
from app.application.estoque import EstoqueIndisponivel
from app.application.estoque_ao_vivo import (
    ConferenciaAoVivo,
    EstoqueConferidoAoVivo,
    linha_de_item,
)
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.estoque import ItemEstoque
from app.domain.valores import Dinheiro
from tests.contract.estoque_contrato import LOJA_A, item


class ConferenciaFalsa:
    def __init__(self, comportamento: Callable[[ItemEstoque], ConferenciaAoVivo]) -> None:
        self._comportamento = comportamento
        self.chamadas: list[tuple[UUID, str]] = []

    async def conferir(self, loja_id: UUID, item: ItemEstoque) -> ConferenciaAoVivo:
        self.chamadas.append((loja_id, item.sku))
        return self._comportamento(item)


class ErroNoUpdate(Exception):
    pass


async def montar(
    itens: list[ItemEstoque],
    conferencia: ConferenciaFalsa,
    **kwargs: object,
) -> tuple[EstoqueConferidoAoVivo, MemoriaEstoqueLocal, EstoqueResiliente]:
    local = MemoriaEstoqueLocal()
    await local.substituir(LOJA_A, [linha_de_item(i) for i in itens])
    base = EstoqueResiliente(
        PlanilhaAdapter(FonteEstoqueEmMemoria({LOJA_A: itens})), RelogioFalso()
    )
    return EstoqueConferidoAoVivo(base, conferencia, local, **kwargs), local, base  # type: ignore[arg-type]


def com_preco(i: ItemEstoque, preco: str) -> ItemEstoque:
    return replace(i, preco_pix=Dinheiro.de(Decimal(preco)))


async def test_item_vendido_no_erp_volta_esgotado_e_sai_do_estoque_local() -> None:
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.indisponivel())
    estoque, local, _ = await montar([item("A"), item("B")], conferencia)

    resultado = await estoque.obter(LOJA_A, "A")

    assert resultado is not None and not resultado.disponivel
    assert resultado.sku == "A"
    assert [x.sku for x in await local.listar(LOJA_A)] == ["B"]


async def test_preco_novo_do_erp_e_o_devolvido_e_atualiza_a_linha_local() -> None:
    novo = com_preco(item("A"), "6500")
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.disponivel(linha_de_item(novo)))
    estoque, local, _ = await montar([item("A")], conferencia)

    resultado = await estoque.obter(LOJA_A, "A")

    assert resultado is not None
    assert resultado.preco_pix.valor == Decimal("6500.00")
    assert not resultado.desatualizado
    assert [x.preco_pix.valor for x in await local.listar(LOJA_A)] == [Decimal("6500.00")]


async def test_sem_mudanca_devolve_o_item_sem_gravar() -> None:
    original = item("A")
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.disponivel(linha_de_item(original)))
    estoque, local, _ = await montar([original], conferencia)
    gravacoes: list[str] = []
    atualizar = local.atualizar_linha

    async def espiar(loja_id: UUID, sku: str, linha: LinhaEstoqueLocal | None) -> None:
        gravacoes.append(sku)
        await atualizar(loja_id, sku, linha)

    local.atualizar_linha = espiar  # type: ignore[method-assign]

    assert await estoque.obter(LOJA_A, "A") == original
    assert gravacoes == []


async def test_quantidade_menor_no_erp_atualiza_a_linha() -> None:
    novo = replace(item("A", quantidade=2), quantidade=1)
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.disponivel(linha_de_item(novo)))
    estoque, local, _ = await montar([item("A", quantidade=2)], conferencia)

    resultado = await estoque.obter(LOJA_A, "A")

    assert resultado is not None and resultado.quantidade == 1
    assert [x.quantidade for x in await local.listar(LOJA_A)] == [1]


async def test_sem_conexao_ativa_o_comportamento_atual_fica_intacto() -> None:
    original = item("A")
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.nao_conferido())
    estoque, local, _ = await montar([original], conferencia)

    assert await estoque.obter(LOJA_A, "A") == original
    assert [x.sku for x in await local.listar(LOJA_A)] == ["A"]


async def test_sku_que_nao_existe_localmente_nao_chama_o_erp() -> None:
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.indisponivel())
    estoque, _, _ = await montar([item("A")], conferencia)

    assert await estoque.obter(LOJA_A, "NAO-EXISTE") is None
    assert conferencia.chamadas == []


async def test_erp_fora_segue_com_o_dado_local_desatualizado() -> None:
    def falhar(i: ItemEstoque) -> ConferenciaAoVivo:
        raise EstoqueIndisponivel("erp fora")

    estoque, local, _ = await montar([item("A")], ConferenciaFalsa(falhar))

    resultado = await estoque.obter(LOJA_A, "A")

    assert resultado is not None and resultado.disponivel and resultado.desatualizado
    assert [x.sku for x in await local.listar(LOJA_A)] == ["A"]


async def test_erro_inesperado_do_erp_tambem_nao_trava() -> None:
    def falhar(i: ItemEstoque) -> ConferenciaAoVivo:
        raise RuntimeError("bug no adaptador")

    estoque, _, _ = await montar([item("A")], ConferenciaFalsa(falhar))

    resultado = await estoque.obter(LOJA_A, "A")

    assert resultado is not None and resultado.desatualizado


async def test_erp_lento_estoura_o_timeout_e_segue_com_o_local() -> None:
    class Lenta:
        async def conferir(self, loja_id: UUID, item: ItemEstoque) -> ConferenciaAoVivo:
            await asyncio.sleep(5)
            return ConferenciaAoVivo.indisponivel()

    local = MemoriaEstoqueLocal()
    itens = [item("A")]
    base = EstoqueResiliente(
        PlanilhaAdapter(FonteEstoqueEmMemoria({LOJA_A: itens})), RelogioFalso()
    )
    estoque = EstoqueConferidoAoVivo(base, Lenta(), local, timeout_s=0.05)

    resultado = await asyncio.wait_for(estoque.obter(LOJA_A, "A"), 1.0)

    assert resultado is not None and resultado.disponivel and resultado.desatualizado


async def test_credencial_invalida_cai_no_local_e_avisa_uma_vez(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(estoque_ao_vivo, "_ja_avisou", set())

    class Recusada(EstoqueIndisponivel):
        retentavel = False

    def falhar(i: ItemEstoque) -> ConferenciaAoVivo:
        raise Recusada("chave recusada")

    estoque, _, _ = await montar([item("A")], ConferenciaFalsa(falhar))

    with caplog.at_level(logging.WARNING, logger=estoque_ao_vivo.__name__):
        for _ in range(3):
            resultado = await estoque.obter(LOJA_A, "A")
            assert resultado is not None and resultado.desatualizado

    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 1


async def test_cache_de_60s_da_resiliencia_nao_esconde_a_conferencia() -> None:
    """O decorator fica POR FORA da resiliencia: o 2o `obter` dentro dos 60 s ve a venda."""
    vendido = False

    def conferir(i: ItemEstoque) -> ConferenciaAoVivo:
        if vendido:
            return ConferenciaAoVivo.indisponivel()
        return ConferenciaAoVivo.disponivel(linha_de_item(i))

    conferencia = ConferenciaFalsa(conferir)
    estoque, _, base = await montar([item("A")], conferencia)

    primeiro = await estoque.obter(LOJA_A, "A")
    assert primeiro is not None and primeiro.disponivel

    vendido = True
    segundo = await estoque.obter(LOJA_A, "A")

    assert segundo is not None and not segundo.disponivel
    assert len(conferencia.chamadas) == 2
    assert base.metricas.acertos_cache == 1  # o local veio do cache; a conferencia nao


async def test_buscar_nao_confere_no_erp() -> None:
    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.indisponivel())
    estoque, _, _ = await montar([item("A")], conferencia)

    achados = await estoque.buscar(LOJA_A, "iPhone 15 Pro")

    assert [i.sku for i in achados] == ["A"]
    assert conferencia.chamadas == []


async def test_capacidades_vem_do_adaptador_de_baixo() -> None:
    estoque, _, base = await montar(
        [], ConferenciaFalsa(lambda i: ConferenciaAoVivo.nao_conferido())
    )
    assert estoque.capacidades == base.capacidades


async def test_confirma_a_transacao_depois_de_gravar() -> None:
    eventos: list[str] = []

    async def commit() -> None:
        eventos.append("commit")

    conferencia = ConferenciaFalsa(lambda i: ConferenciaAoVivo.indisponivel())
    estoque, local, _ = await montar([item("A")], conferencia, commit=commit)

    await estoque.obter(LOJA_A, "A")

    assert eventos == ["commit"]
    assert await local.listar(LOJA_A) == []
