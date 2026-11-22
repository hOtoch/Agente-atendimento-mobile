"""Handoff com Postgres real: distribui, avisa o vendedor E exporta cliente/orcamento ao ERP.

O ERP e um `PedidoPort` falso (nenhuma chamada ao Mercado Phone real).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.outbound.db.atendimento import RepositorioAtendimentoSql
from app.adapters.outbound.db.conexao_erp import RepositorioConexaoErpSql
from app.adapters.outbound.db.config import RepositorioEstoqueLocalSql, RepositorioVendedoresSql
from app.adapters.outbound.db.models import Evento, Lead, Loja
from app.adapters.outbound.db.vinculo_erp import VinculosErpLeadSql
from app.application.agente.estado import EstadoAtendimento
from app.application.config.entradas import EntradaVendedor
from app.application.painel.memoria import PublicadorEmMemoria
from app.application.pedido_erp import FalhaPedidoErp, VinculoErp
from app.domain.conexao_erp import ConexaoErp
from app.domain.ficha import Ficha, TipoPagamento
from app.domain.valores import Bandeira
from app.infra.composicao import montar_casos_handoff, montar_gancho_handoff
from app.infra.settings import Settings
from tests.integration.test_notificar_vendedor_sql import GatewayFalso, RegistroFalso
from tests.unit.application.test_exportar_handoff_erp import (
    SKU,
    PedidoFalso,
    _linha,
    proposta_credito,
)

pytestmark = pytest.mark.integration

D = Decimal


async def _cenario(session: AsyncSession, *, exportar: bool = True) -> tuple[UUID, UUID]:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    vendedores = RepositorioVendedoresSql(session)
    await vendedores.substituir(
        loja.id, [EntradaVendedor(None, "Carla", "(11) 98888-1111", D("100"), True)]
    )
    v = (await vendedores.listar(loja.id))[0]
    await session.execute(
        text("update vendedores set codigo_erp = '9' where id = :i"),
        {"i": v.id},
    )
    await RepositorioConexaoErpSql(session).salvar(
        ConexaoErp(loja.id, 12, ativo=True, exportar_handoff=exportar)
    )
    await RepositorioEstoqueLocalSql(session).substituir(loja.id, [_linha(777)])
    lead = Lead(loja_id=loja.id, telefone="5511912345678", canal="whatsapp", nome="Marcos")
    session.add(lead)
    await session.flush()
    ficha = Ficha.vazia().com_interesse(sku_estoque_confirmado=SKU)
    ficha = ficha.com_pagamento(tipo=TipoPagamento.CREDITO, parcelas=12, bandeira=Bandeira.VISA)
    await RepositorioAtendimentoSql(session).salvar(
        loja.id, lead.id, EstadoAtendimento(ficha=ficha, ultima_proposta=proposta_credito())
    )
    await session.commit()
    return loja.id, lead.id


def _montar(session: AsyncSession, pedido: Any, gateway: GatewayFalso) -> Any:
    assert session.bind is not None
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    publicador = PublicadorEmMemoria()
    gancho = montar_gancho_handoff(
        factory,
        gateway=gateway,
        registro=RegistroFalso(),
        publicador=publicador,
        pedido=pedido,
        settings=Settings(_env_file=None, painel_url="https://painel.exemplo"),
    )
    return montar_casos_handoff(session, publicador=publicador, aviso=gancho)


async def test_handoff_avisa_o_vendedor_e_grava_cliente_e_orcamento_no_lead(
    session: AsyncSession,
) -> None:
    loja, lead = await _cenario(session)
    pedido, gateway = PedidoFalso(), GatewayFalso()
    await _montar(session, pedido, gateway).chamar_vendedor(loja, lead, "cliente pediu")

    session.expire_all()
    row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
    assert (row.erp_cliente_id, row.erp_orcamento_id) == (501, 701)
    assert len(gateway.enviados) == 1  # o aviso do vendedor continua saindo
    (dados,) = pedido.chamadas
    assert dados.orcamento is not None and dados.orcamento.vendedor_id_erp == 9
    assert dados.orcamento.itens[0].produto_id == 777
    eventos = (
        (
            await session.execute(
                select(Evento).where(Evento.lead_id == lead, Evento.tipo == "erp_handoff")
            )
        )
        .scalars()
        .all()
    )
    assert len(eventos) == 1 and eventos[0].payload["ok"] is True


async def test_segundo_handoff_edita_o_mesmo_orcamento(session: AsyncSession) -> None:
    loja, lead = await _cenario(session)
    pedido = PedidoFalso()
    casos = _montar(session, pedido, GatewayFalso())
    await casos.chamar_vendedor(loja, lead, "primeiro")
    await casos.devolver(loja, lead)
    await casos.chamar_vendedor(loja, lead, "segundo")

    assert [(d.cliente_id, d.orcamento_id) for d in pedido.chamadas] == [(None, None), (501, 701)]


async def test_falha_do_erp_nao_impede_o_aviso_nem_o_handoff(session: AsyncSession) -> None:
    loja, lead = await _cenario(session)
    pedido, gateway = PedidoFalso(falha=FalhaPedidoErp("fora do ar")), GatewayFalso()
    await _montar(session, pedido, gateway).chamar_vendedor(loja, lead, "cliente pediu")

    session.expire_all()
    row = (await session.execute(select(Lead).where(Lead.id == lead))).scalar_one()
    assert row.dono == "vendedor" and row.vendedor_id is not None
    assert row.erp_cliente_id is None and row.erp_orcamento_id is None
    assert len(gateway.enviados) == 1


async def test_exportar_handoff_desligado_nao_chama_o_erp(session: AsyncSession) -> None:
    loja, lead = await _cenario(session, exportar=False)
    pedido, gateway = PedidoFalso(), GatewayFalso()
    await _montar(session, pedido, gateway).chamar_vendedor(loja, lead, "cliente pediu")
    assert pedido.chamadas == [] and len(gateway.enviados) == 1


async def test_vinculos_sql_ida_e_volta_e_gravacao_parcial(session: AsyncSession) -> None:
    loja, lead = await _cenario(session)
    repo = VinculosErpLeadSql(session)
    assert await repo.obter(loja, lead) == VinculoErp()
    await repo.gravar(loja, lead, cliente_id=9_000_000_001)
    await repo.gravar(loja, lead, orcamento_id=5)
    await session.commit()
    assert await repo.obter(loja, lead) == VinculoErp(9_000_000_001, 5)
    # lead de outra loja: nada acontece
    await repo.gravar(loja, lead, cliente_id=1)
    outro = (await _cenario(session))[0]
    await repo.gravar(outro, lead, cliente_id=2)
    await session.commit()
    assert (await repo.obter(loja, lead)).cliente_id == 1
