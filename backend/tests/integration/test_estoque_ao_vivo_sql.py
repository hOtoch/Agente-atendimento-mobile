"""Confirmacao ao vivo sobre Postgres real e servidor MCP falso (dados SINTETICOS).

Cobre `atualizar_linha` (SQL e memoria, mesmo comportamento) e o caminho do agente:
banco -> planilha -> resiliente -> conferencia ao vivo -> `confirmar_item`/`calcular_proposta`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import RepositorioEstoqueLocalSql, RepositorioLojasSql
from app.adapters.outbound.estoque.banco import FonteEstoqueLocalSql
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.adapters.outbound.mercadophone.conferencia import ConferenciaItemMercadoPhone
from app.application.agente.contexto import ContextoFerramentas
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import CatalogoFerramentas
from app.application.config.memoria import MemoriaEstoqueLocal
from app.application.config.modelos import LinhaEstoqueLocal
from app.application.config.portas import RepositorioEstoqueLocal
from app.application.estoque_ao_vivo import EstoqueConferidoAoVivo
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.conexao_erp import ConexaoErp
from app.domain.estoque import Condicao
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from app.infra.composicao import montar_casos_config
from app.infra.fila import RelogioParede
from tests.mercadophone_falso import CHAVE, URL, McpFalso, item

pytestmark = pytest.mark.integration


def _linha(
    sku: str, preco: str = "4200", erp_id: int | None = None, qtd: int = 1
) -> LinhaEstoqueLocal:
    return LinhaEstoqueLocal(
        sku=sku,
        modelo=ModeloAparelho.de("iPhone 15 Pro", "Apple"),
        capacidade=Capacidade("256gb"),
        cor="Preto",
        condicao=Condicao.SEMINOVO,
        preco_pix=Dinheiro.de(Decimal(preco)),
        quantidade=qtd,
        bateria_pct=88,
        erp_produto_id=erp_id,
    )


async def _contrato_atualizar_linha(repo: RepositorioEstoqueLocal, loja: UUID, outra: UUID) -> None:
    await repo.substituir(loja, [_linha("A", erp_id=1), _linha("B", erp_id=2), _linha("C")])
    await repo.substituir(outra, [_linha("A")])

    # atualiza no lugar (mesma posicao)
    await repo.atualizar_linha(loja, "B", _linha("B", "5000", erp_id=2, qtd=3))
    atual = await repo.listar(loja)
    assert [x.sku for x in atual] == ["A", "B", "C"]
    assert (atual[1].preco_pix.valor, atual[1].quantidade) == (Decimal("5000.00"), 3)

    # remove uma linha so; a de mesmo sku em outra loja fica
    await repo.atualizar_linha(loja, "A", None)
    assert [x.sku for x in await repo.listar(loja)] == ["B", "C"]
    assert [x.sku for x in await repo.listar(outra)] == ["A"]

    # remover o que nao existe nao faz nada; gravar o que nao existe insere no fim
    await repo.atualizar_linha(loja, "ZZ", None)
    await repo.atualizar_linha(loja, "N", _linha("N", erp_id=9))
    assert [x.sku for x in await repo.listar(loja)] == ["B", "C", "N"]


async def test_atualizar_linha_em_memoria() -> None:
    await _contrato_atualizar_linha(MemoriaEstoqueLocal(), uuid4(), uuid4())


async def test_atualizar_linha_em_sql(session: AsyncSession) -> None:
    lojas = RepositorioLojasSql(session)
    loja, outra = await lojas.criar("L1"), await lojas.criar("L2")
    await _contrato_atualizar_linha(RepositorioEstoqueLocalSql(session), loja, outra)
    session.expire_all()
    assert [x.sku for x in await RepositorioEstoqueLocalSql(session).listar(loja)] == [
        "B",
        "C",
        "N",
    ]


async def _montar(
    session: AsyncSession, mcp: McpFalso, *, ativo: bool = True
) -> tuple[UUID, EstoqueConferidoAoVivo, RepositorioEstoqueLocalSql]:
    loja = await RepositorioLojasSql(session).criar("Loja")
    conexoes = RepositorioConexaoErpSql(session)
    await conexoes.salvar(
        ConexaoErp(loja_id=loja, system_unit_id=4, filtro_loja="Loja A", ativo=ativo)
    )
    repo = RepositorioEstoqueLocalSql(session)
    await repo.substituir(loja, [_linha("TESTE-A", erp_id=7), _linha("TESTE-B", erp_id=8)])
    await session.commit()
    cliente = ClienteMercadoPhone(mcp.cliente_http(), URL, CHAVE, relogio=RelogioFalso())
    base = EstoqueResiliente(PlanilhaAdapter(FonteEstoqueLocalSql(repo)), RelogioParede())
    estoque = EstoqueConferidoAoVivo(
        base, ConferenciaItemMercadoPhone(conexoes, lambda: cliente), repo, commit=session.commit
    )
    return loja, estoque, repo


async def test_item_vendido_sai_do_estoque_local_e_volta_esgotado(session: AsyncSession) -> None:
    mcp = McpFalso({4: [item(8, sku="TESTE-B")]})  # TESTE-A foi vendido no balcao
    loja, estoque, repo = await _montar(session, mcp)

    resultado = await estoque.obter(loja, "TESTE-A")

    assert resultado is not None and not resultado.disponivel
    session.expire_all()
    assert [x.sku for x in await repo.listar(loja)] == ["TESTE-B"]
    assert [i.sku for i in await estoque.buscar(loja, "iPhone 15 Pro")] == ["TESTE-B"]


async def test_preco_novo_do_erp_vai_para_a_linha_e_para_o_calculo(session: AsyncSession) -> None:
    mcp = McpFalso({4: [item(7, sku="TESTE-A", preco=4500), item(8, sku="TESTE-B")]})
    loja, estoque, repo = await _montar(session, mcp)

    resultado = await estoque.obter(loja, "TESTE-A")

    assert resultado is not None and resultado.preco_pix.valor == Decimal("4500.00")
    session.expire_all()
    linhas = {x.sku: x for x in await repo.listar(loja)}
    assert linhas["TESTE-A"].preco_pix.valor == Decimal("4500.00")
    assert linhas["TESTE-A"].erp_produto_id == 7
    assert linhas["TESTE-B"].preco_pix.valor == Decimal("4200.00")


async def test_conexao_inativa_nao_chama_o_erp(session: AsyncSession) -> None:
    mcp = McpFalso({4: []})
    loja, estoque, repo = await _montar(session, mcp, ativo=False)

    resultado = await estoque.obter(loja, "TESTE-A")

    assert resultado is not None and resultado.disponivel
    assert mcp.chamadas == []
    assert len(await repo.listar(loja)) == 2


async def test_confirmar_item_vendido_no_erp_nao_chega_a_proposta(session: AsyncSession) -> None:
    mcp = McpFalso({4: [item(8, sku="TESTE-B")]})
    loja, estoque, _ = await _montar(session, mcp)
    ctx = ContextoFerramentas(
        loja_id=loja,
        lead_id=uuid4(),
        estoque=estoque,
        config=montar_casos_config(session),
        hoje=date(2026, 11, 22),
    )

    r = await CatalogoFerramentas().executar(
        "confirmar_item", {"sku": "TESTE-A"}, EstadoAtendimento(), ctx
    )

    assert r.erro is True
    assert r.estado.ficha.interesse.sku_estoque_confirmado is None
    ok = await CatalogoFerramentas().executar(
        "confirmar_item", {"sku": "TESTE-B"}, EstadoAtendimento(), ctx
    )
    assert ok.erro is False
