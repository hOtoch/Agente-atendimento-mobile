"""Rotas REST da conexao da loja com o ERP (tela Configuracoes do painel)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.inbound.http.schemas_conexao_erp import (
    ConexaoErpEntrada,
    ConexaoErpSaida,
    TesteConexaoErpSaida,
)
from app.application.config.conexao_erp import ConfigurarConexaoErp, EntradaConexaoErp
from app.application.estoque_erp import ConexaoErpNaoConfigurada, SincronizarEstoqueErp
from app.domain.conexao_erp import INTERVALO_MIN_PADRAO, PROVEDOR_MERCADOPHONE, ConexaoErp
from app.infra.dependencias import (
    get_configurar_conexao_erp,
    get_session,
    get_sincronizar_estoque_erp,
)

router = APIRouter(tags=["config"])

Casos = Annotated[ConfigurarConexaoErp, Depends(get_configurar_conexao_erp)]
Sessao = Annotated[AsyncSession, Depends(get_session)]
Sincronizador = Annotated[SincronizarEstoqueErp, Depends(get_sincronizar_estoque_erp)]


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


async def _conexao_configurada(casos: ConfigurarConexaoErp, loja_id: UUID) -> ConexaoErp:
    conexao = await casos.obter(loja_id)  # 404 se a loja nao existe
    if conexao is None:
        raise ConexaoErpNaoConfigurada(loja_id)
    return conexao


@router.post("/lojas/{loja_id}/config/erp/testar", response_model=TesteConexaoErpSaida)
async def testar_conexao_erp(
    loja_id: UUID, casos: Casos, sincronizador: Sincronizador
) -> TesteConexaoErpSaida:
    """A unidade configurada existe entre as da chave do servidor? Nao grava nada."""
    teste = await sincronizador.testar(await _conexao_configurada(casos, loja_id))
    return TesteConexaoErpSaida(ok=teste.ok, mensagem=teste.mensagem)


@router.post("/lojas/{loja_id}/config/erp/sincronizar", response_model=ConexaoErpSaida)
async def sincronizar_estoque_erp(
    loja_id: UUID, casos: Casos, sincronizador: Sincronizador
) -> ConexaoErpSaida:
    """Sincroniza o estoque agora (mesmo com a conexao inativa) e devolve a conexao atualizada.

    Falha do ERP nao e erro HTTP: o estoque anterior fica, e `ultimo_status` = `erro` com o motivo.
    """
    await sincronizador.sincronizar(await _conexao_configurada(casos, loja_id))
    return _out(await casos.obter(loja_id))
