"""Rotas de autenticacao: login por e-mail e senha, sessao em cookie HttpOnly."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth.casos_de_uso import Entrar, QuemSouEu, Sair, TrocarSenha
from app.application.auth.modelos import Identidade, SessaoAtual
from app.application.auth.portas import HasherSenha, LimiteTentativas, RepositorioUsuarios, Sessoes
from app.infra.dependencias import (
    COOKIE_SESSAO,
    get_hasher_senha,
    get_limite_tentativas,
    get_repositorio_usuarios,
    get_session,
    get_sessoes,
    sessao_atual,
)
from app.infra.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginEntrada(BaseModel):
    email: str = Field(max_length=320)
    senha: str = Field(max_length=1024)


class TrocaSenhaEntrada(BaseModel):
    senha_atual: str = Field(max_length=1024)
    senha_nova: str = Field(max_length=1024)


class IdentidadeSchema(BaseModel):
    loja_id: UUID
    loja_nome: str
    email: str
    senha_provisoria: bool


def _out(i: Identidade) -> IdentidadeSchema:
    return IdentidadeSchema(
        loja_id=i.loja_id, loja_nome=i.loja_nome, email=i.email, senha_provisoria=i.senha_provisoria
    )


def _gravar_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=settings.sessao_ttl_horas * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _apagar_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_SESSAO,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


Usuarios = Annotated[RepositorioUsuarios, Depends(get_repositorio_usuarios)]
Hasher = Annotated[HasherSenha, Depends(get_hasher_senha)]
SessoesDep = Annotated[Sessoes, Depends(get_sessoes)]
Config = Annotated[Settings, Depends(get_settings)]
Sessao = Annotated[AsyncSession, Depends(get_session)]
Limite = Annotated[LimiteTentativas, Depends(get_limite_tentativas)]


def _ip_cliente(request: Request, settings: Settings) -> str | None:
    """IP da conexao; atras de proxy confiavel, o ultimo de `X-Forwarded-For` (o que ele viu)."""
    if settings.confiar_proxy:
        encaminhado = request.headers.get("x-forwarded-for", "")
        ultimo = encaminhado.rsplit(",", 1)[-1].strip()
        if ultimo:
            return ultimo
    return request.client.host if request.client else None


@router.post(
    "/login",
    response_model=IdentidadeSchema,
    responses={429: {"description": "Muitas tentativas; veja o header `Retry-After` (segundos)."}},
)
async def login(
    request: Request,
    corpo: LoginEntrada,
    response: Response,
    usuarios: Usuarios,
    hasher: Hasher,
    sessoes: SessoesDep,
    settings: Config,
    db: Sessao,
    limite: Limite,
) -> IdentidadeSchema:
    entrar = Entrar(
        usuarios,
        hasher,
        sessoes,
        limite=limite,
        max_falhas_email=settings.login_max_falhas_email,
        max_falhas_ip=settings.login_max_falhas_ip,
    )
    resultado = await entrar(corpo.email, corpo.senha, _ip_cliente(request, settings))
    await db.commit()
    _gravar_cookie(response, resultado.token, settings)
    return _out(resultado.identidade)


@router.post("/logout", status_code=204)
async def logout(
    sessoes: SessoesDep,
    settings: Config,
    sessao: Annotated[str | None, Cookie()] = None,
) -> Response:
    if sessao:
        await Sair(sessoes)(sessao)
    resposta = Response(status_code=204)
    _apagar_cookie(resposta, settings)
    return resposta


@router.get("/eu", response_model=IdentidadeSchema)
async def eu(
    response: Response,
    atual: Annotated[SessaoAtual, Depends(sessao_atual)],
    usuarios: Usuarios,
    settings: Config,
) -> IdentidadeSchema:
    identidade = await QuemSouEu(usuarios)(atual.usuario_id)
    _gravar_cookie(response, atual.token, settings)  # a validade do cookie acompanha a sessao
    return _out(identidade)


@router.put("/senha", status_code=204)
async def trocar_senha(
    corpo: TrocaSenhaEntrada,
    atual: Annotated[SessaoAtual, Depends(sessao_atual)],
    usuarios: Usuarios,
    hasher: Hasher,
    sessoes: SessoesDep,
    db: Sessao,
) -> Response:
    await TrocarSenha(usuarios, hasher, sessoes)(
        atual.usuario_id, atual.token, corpo.senha_atual, corpo.senha_nova
    )
    await db.commit()
    return Response(status_code=204)
