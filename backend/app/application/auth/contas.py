"""Contas administradas por comando (sem cadastro publico): criar loja + login e redefinir senha."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.application.auth.modelos import SENHA_MIN_CARACTERES, Usuario, normalizar_email
from app.application.auth.portas import HasherSenha, RepositorioUsuarios, Sessoes

# Sem caracteres ambiguos (0/O, 1/l/I): a senha provisoria e lida e digitada por uma pessoa.
ALFABETO_SENHA = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TAMANHO_SENHA_GERADA = 20


class EmailJaCadastrado(Exception):
    def __init__(self, email: str) -> None:
        super().__init__(f"Ja existe um usuario com o e-mail {email}.")
        self.email = email


class UsuarioNaoEncontrado(Exception):
    def __init__(self, email: str) -> None:
        super().__init__(f"Nenhum usuario com o e-mail {email}.")
        self.email = email


def gerar_senha_aleatoria(tamanho: int = TAMANHO_SENHA_GERADA) -> str:
    return "".join(secrets.choice(ALFABETO_SENHA) for _ in range(max(tamanho, 16)))


@dataclass(frozen=True)
class ContaCriada:
    loja_id: UUID
    usuario: Usuario
    senha: str
    """Senha provisoria em texto: existe so para ser mostrada uma vez ao operador."""


class CriarLojaComLogin:
    """Cria a loja e o usuario dono (senha provisoria); o chamador faz o commit (transacao so)."""

    def __init__(
        self,
        criar_loja: Callable[[str], Awaitable[UUID]],
        usuarios: RepositorioUsuarios,
        hasher: HasherSenha,
    ) -> None:
        self._criar_loja = criar_loja
        self._usuarios = usuarios
        self._hasher = hasher

    async def __call__(
        self, nome: str, email: str, senha_provisoria: str | None = None
    ) -> ContaCriada:
        senha = senha_provisoria if senha_provisoria is not None else gerar_senha_aleatoria()
        if len(senha) < SENHA_MIN_CARACTERES:
            raise ValueError(f"A senha deve ter ao menos {SENHA_MIN_CARACTERES} caracteres.")
        email = normalizar_email(email)
        if await self._usuarios.obter_por_email(email) is not None:
            raise EmailJaCadastrado(email)
        loja_id = await self._criar_loja(nome)
        usuario = await self._usuarios.criar(
            loja_id, email, await self._hasher.gerar(senha), senha_provisoria=True
        )
        return ContaCriada(loja_id=loja_id, usuario=usuario, senha=senha)


class RedefinirSenha:
    """Nova senha provisoria + encerra as sessoes do usuario. O chamador faz o commit."""

    def __init__(
        self, usuarios: RepositorioUsuarios, hasher: HasherSenha, sessoes: Sessoes
    ) -> None:
        self._usuarios = usuarios
        self._hasher = hasher
        self._sessoes = sessoes

    async def __call__(self, email: str) -> str:
        email = normalizar_email(email)
        usuario = await self._usuarios.obter_por_email(email)
        if usuario is None:
            raise UsuarioNaoEncontrado(email)
        senha = gerar_senha_aleatoria()
        await self._usuarios.atualizar_senha(
            usuario.id, await self._hasher.gerar(senha), senha_provisoria=True
        )
        await self._sessoes.encerrar_do_usuario(usuario.id)
        return senha
