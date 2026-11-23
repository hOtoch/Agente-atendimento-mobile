"""Importacao de vendedores do ERP (botao "Importar do ERP" da tela de vendedores)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.config.vendedores_erp import ImportarVendedoresErp
from app.infra.dependencias import get_importar_vendedores_erp, get_session, loja_autorizada

router = APIRouter(tags=["config"], dependencies=[Depends(loja_autorizada)])

Importar = Annotated[ImportarVendedoresErp, Depends(get_importar_vendedores_erp)]
Sessao = Annotated[AsyncSession, Depends(get_session)]


class ResumoImportacaoVendedoresSchema(BaseModel):
    criados: int
    atualizados: int
    desativados: int
    sem_alteracao: int


@router.post(
    "/lojas/{loja_id}/vendedores/importar-erp", response_model=ResumoImportacaoVendedoresSchema
)
async def importar_vendedores_erp(
    loja_id: UUID, caso: Importar, sessao: Sessao
) -> ResumoImportacaoVendedoresSchema:
    resumo = await caso.executar(loja_id)
    await sessao.commit()
    return ResumoImportacaoVendedoresSchema(
        criados=resumo.criados,
        atualizados=resumo.atualizados,
        desativados=resumo.desativados,
        sem_alteracao=resumo.sem_alteracao,
    )
