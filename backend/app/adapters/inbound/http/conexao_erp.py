"""Rotas REST da conexao da loja com o ERP (tela Configuracoes do painel)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.inbound.http.schemas_conexao_erp import ConexaoErpEntrada, ConexaoErpSaida
from app.application.config.conexao_erp import ConfigurarConexaoErp, EntradaConexaoErp
from app.domain.conexao_erp import INTERVALO_MIN_PADRAO, PROVEDOR_MERCADOPHONE, ConexaoErp
from app.infra.dependencias import get_configurar_conexao_erp, get_session

router = APIRouter(tags=["config"])

Casos = Annotated[ConfigurarConexaoErp, Depends(get_configurar_conexao_erp)]
Sessao = Annotated[AsyncSession, Depends(get_session)]


def _out(c: ConexaoErp | None) -> ConexaoErpSaida:
    if c is None:
        return ConexaoErpSaida(
            configurada=False,
            provedor=PROVEDOR_MERCADOPHONE,
            system_unit_id=None,
            filtro_loja=None,
            ativo=False,
            intervalo_min=INTERVALO_MIN_PADRAO,
            exportar_handoff=False,
            ultima_sincronizacao_em=None,
            ultimo_status=None,
            ultimo_relatorio=None,
        )
    return ConexaoErpSaida(
        configurada=True,
        provedor=c.provedor,
        system_unit_id=c.system_unit_id,
        filtro_loja=c.filtro_loja,
        ativo=c.ativo,
        intervalo_min=c.intervalo_min,
        exportar_handoff=c.exportar_handoff,
        ultima_sincronizacao_em=c.ultima_sincronizacao_em,
        ultimo_status=c.ultimo_status,
        ultimo_relatorio=None if c.ultimo_relatorio is None else dict(c.ultimo_relatorio),
    )


@router.get("/lojas/{loja_id}/config/erp", response_model=ConexaoErpSaida)
async def obter_conexao_erp(loja_id: UUID, casos: Casos) -> ConexaoErpSaida:
    return _out(await casos.obter(loja_id))


@router.put("/lojas/{loja_id}/config/erp", response_model=ConexaoErpSaida)
async def atualizar_conexao_erp(
    loja_id: UUID, corpo: ConexaoErpEntrada, casos: Casos, sessao: Sessao
) -> ConexaoErpSaida:
    conexao = await casos.atualizar(
        loja_id,
        EntradaConexaoErp(
            system_unit_id=corpo.system_unit_id,
            filtro_loja=corpo.filtro_loja,
            ativo=corpo.ativo,
            intervalo_min=corpo.intervalo_min,
            exportar_handoff=corpo.exportar_handoff,
        ),
    )
    await sessao.commit()
    return _out(conexao)
