"""Handlers de erro: corpo `{"erros": [{"caminho", "mensagem"}]}` para 422 e 404."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.config.modelos import ErroCampo, ErrosDeValidacao, LojaNaoEncontrada
from app.application.estoque_erp import ConexaoErpNaoConfigurada, ErpNaoConfigurado
from app.application.handoff import ConflitoDono, LeadNaoEncontrado, VendedorNaoEncontrado
from app.application.midia import MidiaGrandeDemais, MidiaNaoEncontrada, TipoMidiaNaoSuportado
from app.application.painel.casos_de_uso import MovimentoEtapaInvalido
from app.application.whatsapp import ErroGateway


def _caminho(loc: Sequence[str | int]) -> str:
    partes = [p for p in loc if p not in ("body", "path", "query")]
    texto = ""
    for p in partes:
        texto += f"[{p}]" if isinstance(p, int) else (f".{p}" if texto else str(p))
    return texto


def _mensagem(erro: dict[str, Any]) -> str:
    tipo = str(erro.get("type", ""))
    if tipo == "missing":
        return "Campo obrigatório."
    if tipo.endswith(("_type", "_parsing", "_from_float")) or tipo in ("bool_parsing", "int_type"):
        return "Valor inválido."
    return str(erro.get("msg", "Valor inválido."))


def _corpo(erros: Sequence[ErroCampo], **extra: Any) -> dict[str, Any]:
    return {"erros": [{"caminho": e.caminho, "mensagem": e.mensagem} for e in erros], **extra}


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErrosDeValidacao)
    async def _validacao(_: Request, exc: ErrosDeValidacao) -> JSONResponse:
        return JSONResponse(_corpo(exc.erros), status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _requisicao(_: Request, exc: RequestValidationError) -> JSONResponse:
        erros = [ErroCampo(_caminho(e["loc"]), _mensagem(e)) for e in exc.errors()]
        # sem o `input` de cada erro: a resposta nunca devolve o valor enviado (pode ser segredo)
        detalhes = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
        return JSONResponse(
            _corpo(erros, detail=jsonable_encoder(detalhes, custom_encoder={Exception: str})),
            status_code=422,
        )

    @app.exception_handler(LojaNaoEncontrada)
    async def _loja(_: Request, exc: LojaNaoEncontrada) -> JSONResponse:
        return JSONResponse(_corpo([ErroCampo("loja_id", "Loja não encontrada.")]), status_code=404)

    @app.exception_handler(LeadNaoEncontrado)
    async def _lead(_: Request, exc: LeadNaoEncontrado) -> JSONResponse:
        return JSONResponse(_corpo([ErroCampo("lead_id", "Lead não encontrado.")]), status_code=404)

    @app.exception_handler(VendedorNaoEncontrado)
    async def _vendedor(_: Request, exc: VendedorNaoEncontrado) -> JSONResponse:
        erro = ErroCampo("vendedor_id", "Vendedor não encontrado.")
        return JSONResponse(_corpo([erro]), status_code=404)

    @app.exception_handler(MovimentoEtapaInvalido)
    async def _movimento(_: Request, exc: MovimentoEtapaInvalido) -> JSONResponse:
        return JSONResponse(_corpo([ErroCampo("etapa", exc.motivo)]), status_code=409)

    @app.exception_handler(ConflitoDono)
    async def _dono(_: Request, exc: ConflitoDono) -> JSONResponse:
        return JSONResponse(_corpo([ErroCampo("dono", exc.motivo)]), status_code=409)

    @app.exception_handler(TipoMidiaNaoSuportado)
    async def _tipo_midia(_: Request, exc: TipoMidiaNaoSuportado) -> JSONResponse:
        erro = ErroCampo("arquivo", "Tipo de arquivo não suportado.")
        return JSONResponse(_corpo([erro]), status_code=415)

    @app.exception_handler(MidiaGrandeDemais)
    async def _midia_grande(_: Request, exc: MidiaGrandeDemais) -> JSONResponse:
        mb = exc.limite_bytes / (1024 * 1024)
        erro = ErroCampo("arquivo", f"Arquivo acima do limite de {mb:g} MB.")
        return JSONResponse(_corpo([erro]), status_code=413)

    @app.exception_handler(MidiaNaoEncontrada)
    async def _midia(_: Request, exc: MidiaNaoEncontrada) -> JSONResponse:
        return JSONResponse(_corpo([ErroCampo("nome", "Mídia não encontrada.")]), status_code=404)

    @app.exception_handler(ErroGateway)
    async def _gateway(_: Request, exc: ErroGateway) -> JSONResponse:
        erro = ErroCampo("whatsapp", "Não foi possível falar com o WhatsApp (Evolution API).")
        return JSONResponse(_corpo([erro]), status_code=502)

    @app.exception_handler(ErpNaoConfigurado)
    async def _erp_sem_chave(_: Request, exc: ErpNaoConfigurado) -> JSONResponse:
        erro = ErroCampo("erp", "Integração com o ERP não configurada no servidor.")
        return JSONResponse(_corpo([erro]), status_code=409)

    @app.exception_handler(ConexaoErpNaoConfigurada)
    async def _conexao_erp(_: Request, exc: ConexaoErpNaoConfigurada) -> JSONResponse:
        erro = ErroCampo("conexao", "Configure e salve a conexão com o ERP antes de usar.")
        return JSONResponse(_corpo([erro]), status_code=409)
