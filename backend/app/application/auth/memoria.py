"""Implementacoes em memoria das portas de autenticacao (testes unitarios; sem IO)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.application.auth.modelos import DadosSessao, Usuario, normalizar_email


class SenhaSemHash:
    """Hasher de mentira (`hash:<senha>`): so para testes."""

    async def gerar(self, senha: str) -> str:
        return f"hash:{senha}"

    async def conferir(self, senha: str, hash_: str) -> bool:
        return hash_ == f"hash:{senha}"


class MemoriaUsuarios:
    def __init__(self) -> None:
        self.por_id: dict[UUID, Usuario] = {}
        self.lojas: dict[UUID, str] = {}
        self.logins: list[UUID] = []

    def adicionar_loja(self, loja_id: UUID, nome: str) -> None:
        self.lojas[loja_id] = nome

    def adicionar(
        self, loja_id: UUID, email: str, senha_hash: str, *, senha_provisoria: bool = False
    ) -> Usuario:
        usuario = Usuario(
            id=uuid4(),
            loja_id=loja_id,
            loja_nome=self.lojas.get(loja_id, "Loja"),
            email=normalizar_email(email),
            senha_hash=senha_hash,
            senha_provisoria=senha_provisoria,
            ativo=True,
        )
        self.por_id[usuario.id] = usuario
        return usuario

    def desativar(self, usuario_id: UUID) -> None:
        self.por_id[usuario_id] = replace(self.por_id[usuario_id], ativo=False)

    async def obter_por_email(self, email: str) -> Usuario | None:
        return next((u for u in self.por_id.values() if u.email == email), None)

    async def obter_por_id(self, usuario_id: UUID) -> Usuario | None:
        return self.por_id.get(usuario_id)

    async def criar(
        self, loja_id: UUID, email: str, senha_hash: str, *, senha_provisoria: bool
    ) -> Usuario:
        return self.adicionar(loja_id, email, senha_hash, senha_provisoria=senha_provisoria)

    async def atualizar_senha(
        self, usuario_id: UUID, senha_hash: str, *, senha_provisoria: bool
    ) -> None:
        self.por_id[usuario_id] = replace(
            self.por_id[usuario_id], senha_hash=senha_hash, senha_provisoria=senha_provisoria
        )

    async def registrar_login(self, usuario_id: UUID, quando: datetime) -> None:
        self.logins.append(usuario_id)
        self.por_id[usuario_id] = replace(self.por_id[usuario_id], ultimo_login_em=quando)


class MemoriaSessoes:
    def __init__(self) -> None:
        self._dados: dict[str, DadosSessao] = {}
        self.renovacoes: list[str] = []

    def ativos(self) -> int:
        return len(self._dados)

    async def criar(self, usuario_id: UUID, loja_id: UUID) -> str:
        token = f"token-{uuid4().hex}"
        self._dados[token] = DadosSessao(usuario_id, loja_id)
        return token

    async def obter(self, token: str) -> DadosSessao | None:
        return self._dados.get(token)

    async def renovar(self, token: str) -> bool:
        self.renovacoes.append(token)
        return token in self._dados

    async def encerrar(self, token: str) -> None:
        self._dados.pop(token, None)

    async def encerrar_do_usuario(self, usuario_id: UUID, *, manter: str | None = None) -> None:
        for token in [t for t, d in self._dados.items() if d.usuario_id == usuario_id]:
            if token != manter:
                del self._dados[token]
