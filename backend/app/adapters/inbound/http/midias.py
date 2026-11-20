"""Entrega das midias enviadas pelo cliente do chat web."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.application.midia import ArmazenamentoMidia, MidiaNaoEncontrada
from app.infra.dependencias import get_armazenamento_midia

router = APIRouter(tags=["webchat"])


@router.get(
    "/midias/{nome}",
    summary="Baixa uma midia enviada",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        404: {"description": "Nao existe."},
    },
)
async def obter_midia(
    nome: str, armazenamento: Annotated[ArmazenamentoMidia, Depends(get_armazenamento_midia)]
) -> Response:
    conteudo = await armazenamento.ler(nome)
    if conteudo is None:
        raise MidiaNaoEncontrada(nome)
    return Response(
        content=conteudo.dados,
        media_type=conteudo.tipo_mime,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=31536000"},
    )
