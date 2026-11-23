"""Modelos e erros tipados da autenticacao."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

SENHA_MIN_CARACTERES = 10


@dataclass(frozen=True)
class Usuario:
    id: UUID
    loja_id: UUID
    loja_nome: str
    email: str
    senha_hash: str
    senha_provisoria: bool
    ativo: bool
    ultimo_login_em: datetime | None = None


@dataclass(frozen=True)
class Identidade:
    """O que o painel pode saber de quem esta logado (sem segredos)."""

    loja_id: UUID
    loja_nome: str
    email: str
    senha_provisoria: bool


@dataclass(frozen=True)
class DadosSessao:
    usuario_id: UUID
    loja_id: UUID


@dataclass(frozen=True)
class SessaoAtual:
    """Sessao autenticada da requisicao (`token` serve para logout e troca de senha)."""

    usuario_id: UUID
    loja_id: UUID
    token: str


@dataclass(frozen=True)
class ResultadoEntrar:
    token: str
    identidade: Identidade


class CredenciaisInvalidas(Exception):
    """E-mail inexistente, senha errada ou usuario inativo: sempre a mesma resposta."""

    def __init__(self) -> None:
        super().__init__("E-mail ou senha inválidos.")


class SessaoInvalida(Exception):
    """Sem sessao, sessao expirada ou usuario que deixou de existir/ficou inativo."""

    def __init__(self) -> None:
        super().__init__("Sessão inválida ou expirada.")


class MotivoTrocaSenha(StrEnum):
    SENHA_ATUAL_INCORRETA = "senha_atual_incorreta"
    SENHA_NOVA_CURTA = "senha_nova_curta"
    SENHA_NOVA_IGUAL = "senha_nova_igual"


MENSAGENS_TROCA_SENHA: dict[MotivoTrocaSenha, str] = {
    MotivoTrocaSenha.SENHA_ATUAL_INCORRETA: "A senha atual está incorreta.",
    MotivoTrocaSenha.SENHA_NOVA_CURTA: (
        f"A nova senha precisa ter pelo menos {SENHA_MIN_CARACTERES} caracteres."
    ),
    MotivoTrocaSenha.SENHA_NOVA_IGUAL: "A nova senha precisa ser diferente da atual.",
}


class TrocaSenhaInvalida(Exception):
    def __init__(self, motivo: MotivoTrocaSenha) -> None:
        super().__init__(MENSAGENS_TROCA_SENHA[motivo])
        self.motivo = motivo


def normalizar_email(email: str) -> str:
    return email.strip().lower()
