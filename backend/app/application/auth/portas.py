"""Portas da autenticacao."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.auth.modelos import ChaveLimite, DadosSessao, Usuario


class RepositorioUsuarios(Protocol):
    async def obter_por_email(self, email: str) -> Usuario | None: ...

    async def obter_por_id(self, usuario_id: UUID) -> Usuario | None: ...

    async def criar(
        self, loja_id: UUID, email: str, senha_hash: str, *, senha_provisoria: bool
    ) -> Usuario: ...

    async def atualizar_senha(
        self, usuario_id: UUID, senha_hash: str, *, senha_provisoria: bool
    ) -> None: ...

    async def registrar_login(self, usuario_id: UUID, quando: datetime) -> None: ...


class HasherSenha(Protocol):
    """Async porque o hash custa CPU de proposito: o adaptador real roda fora do event loop."""

    async def gerar(self, senha: str) -> str: ...

    async def conferir(self, senha: str, hash_: str) -> bool: ...


class Sessoes(Protocol):
    async def criar(self, usuario_id: UUID, loja_id: UUID) -> str:
        """Cria a sessao e devolve o token (so o cliente o conhece em texto)."""
        ...

    async def obter(self, token: str) -> DadosSessao | None: ...

    async def renovar(self, token: str) -> bool:
        """Reinicia o TTL; False se a sessao ja nao existe."""
        ...

    async def encerrar(self, token: str) -> None: ...

    async def encerrar_do_usuario(self, usuario_id: UUID, *, manter: str | None = None) -> None:
        """Encerra todas as sessoes do usuario, exceto a do token `manter`."""
        ...


class LimiteTentativas(Protocol):
    """Contador de falhas de login por chave, com janela fixa a partir da primeira falha."""

    async def bloqueado(self, chaves: Sequence[ChaveLimite]) -> int | None:
        """Segundos ate a janela expirar se alguma chave atingiu o maximo; senao None."""
        ...

    async def registrar_falha(self, chaves: Sequence[ChaveLimite]) -> None: ...

    async def limpar(self, chaves: Sequence[ChaveLimite]) -> None: ...
