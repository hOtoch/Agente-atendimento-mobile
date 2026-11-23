"""Rotas de importacao de planilhas xlsx e download dos modelos."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.application.importacao.importar import (
    ImportarPlanilha,
    ModoImportacao,
    RelatorioImportacao,
    TipoImportacao,
)
from app.application.importacao.portas import GeradorModelo
from app.infra.dependencias import get_gerador_modelo, get_importador, loja_autorizada

router = APIRouter(tags=["importacao"])
"""Publico: o modelo de planilha em branco."""
router_loja = APIRouter(tags=["importacao"], dependencies=[Depends(loja_autorizada)])
"""Importacao em nome de uma loja: exige a sessao dela."""

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TAMANHO_MAXIMO = 10 * 1024 * 1024

Importador = Annotated[ImportarPlanilha, Depends(get_importador)]
Gerador = Annotated[GeradorModelo, Depends(get_gerador_modelo)]


class ErroSchema(BaseModel):
    caminho: str
    mensagem: str


class RelatorioSchema(BaseModel):
    ok: bool
    erros: list[ErroSchema]
    resumo: dict[str, object]


def _schema(r: RelatorioImportacao) -> RelatorioSchema:
    return RelatorioSchema(
        ok=r.ok,
        erros=[ErroSchema(caminho=e.caminho, mensagem=e.mensagem) for e in r.erros],
        resumo=r.resumo,
    )


@router_loja.post(
    "/lojas/{loja_id}/importar/{tipo}",
    response_model=RelatorioSchema,
    responses={422: {"model": RelatorioSchema}},
)
async def importar(
    loja_id: UUID,
    tipo: TipoImportacao,
    importador: Importador,
    arquivo: Annotated[UploadFile, File()],
    modo: ModoImportacao = "validar",
) -> JSONResponse:
    """200 com o relatorio quando a planilha e valida; 422 com o relatorio quando nao e."""
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        relatorio = RelatorioSchema(
            ok=False,
            erros=[ErroSchema(caminho="arquivo", mensagem="Arquivo maior que 10 MB.")],
            resumo={},
        )
        return JSONResponse(relatorio.model_dump(mode="json"), status_code=422)
    resultado = await importador.executar(loja_id, tipo, conteudo, modo)
    return JSONResponse(
        _schema(resultado).model_dump(mode="json"), status_code=200 if resultado.ok else 422
    )


@router.get("/modelos/{tipo}", response_class=Response, responses={200: {"content": {XLSX: {}}}})
async def baixar_modelo(tipo: TipoImportacao, gerador: Gerador) -> Response:
    return Response(
        gerador.gerar(tipo),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="modelo-{tipo}.xlsx"'},
    )
