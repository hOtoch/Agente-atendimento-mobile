"""Rotas do chat web: sessao, envio de mensagem (202) e stream SSE da saida."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.adapters.inbound.http.sse import SSE_HEADERS, eventos_sse
from app.adapters.outbound.canal.webchat import topico_webchat
from app.application.canal import (
    BarramentoMensagens,
    Canal,
    MensagemEntrada,
    ReceberMensagem,
    TipoMensagem,
)
from app.application.config.modelos import LojaNaoEncontrada
from app.application.config.portas import RepositorioLojas
from app.application.midia import ReceberMidia
from app.infra.dependencias import (
    get_barramento,
    get_lojas,
    get_receber_mensagem,
    get_receber_midia,
)

router = APIRouter(prefix="/webchat/{loja_id}", tags=["webchat"])

# leads.telefone e VARCHAR(32) e a sessao vira o contato: uuid4().hex tem exatos 32 chars.
SessaoPath = Annotated[str, Path(min_length=1, max_length=32)]


class SessaoSchema(BaseModel):
    sessao: str


class MensagemIn(BaseModel):
    id_cliente: str = Field(min_length=1, max_length=200)
    tipo: Literal["texto", "audio", "imagem"]
    texto: str | None = None
    midia_url: str | None = None

    @model_validator(mode="after")
    def _conteudo(self) -> Self:
        if self.tipo == "texto" and not (self.texto and self.texto.strip()):
            raise ValueError("texto obrigatorio para mensagens de texto")
        if self.tipo != "texto" and not self.midia_url:
            raise ValueError("midia_url obrigatoria para audio e imagem")
        return self


class MidiaSchema(BaseModel):
    midia_url: str


class RecebidaSchema(BaseModel):
    conversa_id: UUID
    nova: bool


async def _exigir_loja(lojas: RepositorioLojas, loja_id: UUID) -> None:
    if not await lojas.existe(loja_id):
        raise LojaNaoEncontrada(loja_id)


@router.post("/sessoes", status_code=201, response_model=SessaoSchema)
async def criar_sessao(
    loja_id: UUID, lojas: Annotated[RepositorioLojas, Depends(get_lojas)]
) -> SessaoSchema:
    await _exigir_loja(lojas, loja_id)
    return SessaoSchema(sessao=uuid.uuid4().hex)


@router.post(
    "/midias",
    status_code=201,
    response_model=MidiaSchema,
    summary="Envia uma imagem ou audio do cliente",
    responses={
        404: {"description": "Loja nao encontrada."},
        413: {"description": "Arquivo acima do limite."},
        415: {"description": "Tipo de arquivo nao suportado."},
    },
)
async def enviar_midia(
    request: Request,
    loja_id: UUID,
    arquivo: Annotated[UploadFile, File()],
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
    receber: Annotated[ReceberMidia, Depends(get_receber_midia)],
) -> MidiaSchema:
    await _exigir_loja(lojas, loja_id)
    # Le so ate o limite + 1 byte: um arquivo gigante nao vai inteiro para a memoria.
    dados = await arquivo.read(receber.limite_bytes + 1)
    nome = await receber(dados, arquivo.content_type or "")
    return MidiaSchema(midia_url=str(request.url_for("obter_midia", nome=nome)))


@router.post("/sessoes/{sessao}/mensagens", status_code=202, response_model=RecebidaSchema)
async def enviar_mensagem(
    loja_id: UUID,
    sessao: SessaoPath,
    corpo: MensagemIn,
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
    receber: Annotated[ReceberMensagem, Depends(get_receber_mensagem)],
) -> RecebidaSchema:
    await _exigir_loja(lojas, loja_id)
    conversa_id, nova = await receber(
        MensagemEntrada(
            loja_id=loja_id,
            canal=Canal.WEBCHAT,
            # O id do cliente so e unico dentro da sessao; o banco e unico por canal.
            id_externo=f"{loja_id}:{sessao}:{corpo.id_cliente}",
            remetente=sessao,
            tipo=TipoMensagem(corpo.tipo),
            texto=corpo.texto,
            midia_url=corpo.midia_url,
            recebida_em=datetime.now(UTC),
        )
    )
    return RecebidaSchema(conversa_id=conversa_id, nova=nova)


@router.get("/sessoes/{sessao}/stream")
async def stream(
    loja_id: UUID,
    sessao: SessaoPath,
    lojas: Annotated[RepositorioLojas, Depends(get_lojas)],
    barramento: Annotated[BarramentoMensagens, Depends(get_barramento)],
) -> StreamingResponse:
    await _exigir_loja(lojas, loja_id)
    return StreamingResponse(
        eventos_sse(barramento.assinar(topico_webchat(loja_id, sessao))),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
