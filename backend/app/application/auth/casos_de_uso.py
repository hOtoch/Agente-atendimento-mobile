"""Casos de uso da autenticacao."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from app.application.auth.modelos import (
    SENHA_MIN_CARACTERES,
    CredenciaisInvalidas,
    Identidade,
    MotivoTrocaSenha,
    ResultadoEntrar,
    SessaoInvalida,
    TrocaSenhaInvalida,
    Usuario,
    normalizar_email,
)
from app.application.auth.portas import HasherSenha, RepositorioUsuarios, Sessoes


def identidade_de(usuario: Usuario) -> Identidade:
    return Identidade(
        loja_id=usuario.loja_id,
        loja_nome=usuario.loja_nome,
        email=usuario.email,
        senha_provisoria=usuario.senha_provisoria,
    )


class Entrar:
    # Um `Entrar` nasce a cada request: o hash falso fica no nivel da classe (um por tipo de
    # hasher), senao todo e-mail inexistente pagaria gerar + conferir e seria mais lento.
    _hashes_falsos: ClassVar[dict[type, str]] = {}

    def __init__(
        self,
        usuarios: RepositorioUsuarios,
        hasher: HasherSenha,
        sessoes: Sessoes,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._usuarios = usuarios
        self._hasher = hasher
        self._sessoes = sessoes
        self._agora = agora

    async def _hash_falso(self) -> str:
        tipo = type(self._hasher)
        if tipo not in Entrar._hashes_falsos:
            Entrar._hashes_falsos[tipo] = await self._hasher.gerar("senha-que-ninguem-tem")
        return Entrar._hashes_falsos[tipo]

    async def __call__(self, email: str, senha: str) -> ResultadoEntrar:
        usuario = await self._usuarios.obter_por_email(normalizar_email(email))
        if usuario is None:
            # gasta o mesmo tempo de uma conferencia real: nao revela se o e-mail existe
            await self._hasher.conferir(senha, await self._hash_falso())
            raise CredenciaisInvalidas
        if not await self._hasher.conferir(senha, usuario.senha_hash) or not usuario.ativo:
            raise CredenciaisInvalidas
        token = await self._sessoes.criar(usuario.id, usuario.loja_id)
        await self._usuarios.registrar_login(usuario.id, self._agora())
        return ResultadoEntrar(token=token, identidade=identidade_de(usuario))


class Sair:
    def __init__(self, sessoes: Sessoes) -> None:
        self._sessoes = sessoes

    async def __call__(self, token: str) -> None:
        await self._sessoes.encerrar(token)


class QuemSouEu:
    def __init__(self, usuarios: RepositorioUsuarios) -> None:
        self._usuarios = usuarios

    async def __call__(self, usuario_id: UUID) -> Identidade:
        usuario = await self._usuarios.obter_por_id(usuario_id)
        if usuario is None or not usuario.ativo:
            raise SessaoInvalida
        return identidade_de(usuario)


class TrocarSenha:
    def __init__(
        self, usuarios: RepositorioUsuarios, hasher: HasherSenha, sessoes: Sessoes
    ) -> None:
        self._usuarios = usuarios
        self._hasher = hasher
        self._sessoes = sessoes

    async def __call__(
        self, usuario_id: UUID, token_atual: str, senha_atual: str, senha_nova: str
    ) -> None:
        usuario = await self._usuarios.obter_por_id(usuario_id)
        if usuario is None or not usuario.ativo:
            raise SessaoInvalida
        if not await self._hasher.conferir(senha_atual, usuario.senha_hash):
            raise TrocaSenhaInvalida(MotivoTrocaSenha.SENHA_ATUAL_INCORRETA)
        if len(senha_nova) < SENHA_MIN_CARACTERES:
            raise TrocaSenhaInvalida(MotivoTrocaSenha.SENHA_NOVA_CURTA)
        if senha_nova == senha_atual:
            raise TrocaSenhaInvalida(MotivoTrocaSenha.SENHA_NOVA_IGUAL)
        await self._usuarios.atualizar_senha(
            usuario_id, await self._hasher.gerar(senha_nova), senha_provisoria=False
        )
        await self._sessoes.encerrar_do_usuario(usuario_id, manter=token_atual)
