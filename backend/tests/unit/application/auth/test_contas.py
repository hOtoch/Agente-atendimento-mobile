"""Criar loja + login e redefinir senha (casos de uso, fakes em memoria)."""

from uuid import UUID, uuid4

import pytest

from app.application.auth.contas import (
    ALFABETO_SENHA,
    CriarLojaComLogin,
    EmailJaCadastrado,
    RedefinirSenha,
    UsuarioNaoEncontrado,
    gerar_senha_aleatoria,
)
from app.application.auth.memoria import MemoriaSessoes, MemoriaUsuarios, SenhaSemHash
from app.application.auth.modelos import SENHA_MIN_CARACTERES


def test_senha_aleatoria_tamanho_e_alfabeto() -> None:
    senha = gerar_senha_aleatoria()
    assert len(senha) >= 16 > SENHA_MIN_CARACTERES
    assert set(senha) <= set(ALFABETO_SENHA)
    assert not set("0O1lI") & set(ALFABETO_SENHA)  # sem caracteres ambiguos


def test_senhas_aleatorias_diferem() -> None:
    assert len({gerar_senha_aleatoria() for _ in range(20)}) == 20


class Cenario:
    def __init__(self) -> None:
        self.usuarios = MemoriaUsuarios()
        self.sessoes = MemoriaSessoes()
        self.hasher = SenhaSemHash()
        self.lojas: list[str] = []

    async def criar_loja(self, nome: str) -> UUID:
        loja_id = uuid4()
        self.lojas.append(nome)
        self.usuarios.adicionar_loja(loja_id, nome)
        return loja_id

    def criar(self) -> CriarLojaComLogin:
        return CriarLojaComLogin(self.criar_loja, self.usuarios, self.hasher)


async def test_cria_loja_e_dono_com_senha_gerada() -> None:
    c = Cenario()
    conta = await c.criar()("Loja X", "  Dono@Loja.com ")
    assert c.lojas == ["Loja X"]
    assert conta.usuario.email == "dono@loja.com" and conta.usuario.senha_provisoria
    assert conta.usuario.loja_id == conta.loja_id
    assert conta.usuario.senha_hash == f"hash:{conta.senha}"
    assert len(conta.senha) >= 16


async def test_usa_a_senha_informada() -> None:
    c = Cenario()
    conta = await c.criar()("Loja X", "a@a.com", senha_provisoria="minha-senha-123")
    assert conta.senha == "minha-senha-123"
    assert conta.usuario.senha_hash == "hash:minha-senha-123"


async def test_senha_informada_curta_e_recusada() -> None:
    c = Cenario()
    with pytest.raises(ValueError, match="senha"):
        await c.criar()("Loja X", "a@a.com", senha_provisoria="curta")
    assert c.lojas == []


async def test_email_repetido_nao_cria_loja() -> None:
    c = Cenario()
    await c.criar()("Loja X", "a@a.com")
    with pytest.raises(EmailJaCadastrado):
        await c.criar()("Loja Y", "A@a.com")
    assert c.lojas == ["Loja X"]


async def test_redefinir_troca_senha_marca_provisoria_e_derruba_sessoes() -> None:
    c = Cenario()
    conta = await c.criar()("Loja X", "a@a.com", senha_provisoria="senha-original-1")
    await c.usuarios.atualizar_senha(conta.usuario.id, "hash:outra", senha_provisoria=False)
    await c.sessoes.criar(conta.usuario.id, conta.loja_id)
    await c.sessoes.criar(conta.usuario.id, conta.loja_id)
    outra = await c.sessoes.criar(uuid4(), uuid4())

    nova = await RedefinirSenha(c.usuarios, c.hasher, c.sessoes)("A@a.com")

    usuario = await c.usuarios.obter_por_id(conta.usuario.id)
    assert usuario is not None and usuario.senha_provisoria
    assert usuario.senha_hash == f"hash:{nova}" and len(nova) >= 16
    assert c.sessoes.ativos() == 1 and await c.sessoes.obter(outra) is not None


async def test_redefinir_usuario_inexistente() -> None:
    c = Cenario()
    with pytest.raises(UsuarioNaoEncontrado):
        await RedefinirSenha(c.usuarios, c.hasher, c.sessoes)("x@x.com")
