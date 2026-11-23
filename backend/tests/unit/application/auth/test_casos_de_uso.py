"""Casos de uso de autenticacao com fakes em memoria."""

from uuid import uuid4

import pytest

from app.application.auth.casos_de_uso import Entrar, QuemSouEu, Sair, TrocarSenha
from app.application.auth.memoria import MemoriaSessoes, MemoriaUsuarios, SenhaSemHash
from app.application.auth.modelos import (
    CredenciaisInvalidas,
    MotivoTrocaSenha,
    SessaoInvalida,
    TrocaSenhaInvalida,
)

SENHA = "senha-segura-123"


class HasherContado(SenhaSemHash):
    def __init__(self) -> None:
        self.geracoes = 0
        self.conferencias = 0

    async def gerar(self, senha: str) -> str:
        self.geracoes += 1
        return await super().gerar(senha)

    async def conferir(self, senha: str, hash_: str) -> bool:
        self.conferencias += 1
        return await super().conferir(senha, hash_)


class Cenario:
    def __init__(self) -> None:
        self.usuarios = MemoriaUsuarios()
        self.sessoes = MemoriaSessoes()
        self.hasher = HasherContado()
        self.loja_id = uuid4()
        self.usuarios.adicionar_loja(self.loja_id, "Loja Demo")

    async def montar(self) -> "Cenario":
        self.usuario = self.usuarios.adicionar(
            self.loja_id, "dono@loja.com", await self.hasher.gerar(SENHA), senha_provisoria=True
        )
        self.hasher.geracoes = self.hasher.conferencias = 0
        return self

    def entrar(self) -> Entrar:
        return Entrar(self.usuarios, self.hasher, self.sessoes)

    def trocar(self) -> TrocarSenha:
        return TrocarSenha(self.usuarios, self.hasher, self.sessoes)


@pytest.fixture
async def c() -> Cenario:
    return await Cenario().montar()


async def test_email_inexistente_custa_uma_conferencia_como_o_existente(c: Cenario) -> None:
    """Cada request cria um `Entrar`: o hash falso nao pode ser gerado de novo a cada vez,
    senao o e-mail inexistente fica mais lento e revela que nao existe."""
    with pytest.raises(CredenciaisInvalidas):
        await c.entrar()("ninguem@loja.com", SENHA)
    c.hasher.geracoes = c.hasher.conferencias = 0
    for _ in range(3):
        with pytest.raises(CredenciaisInvalidas):
            await c.entrar()("ninguem@loja.com", SENHA)
    assert (c.hasher.geracoes, c.hasher.conferencias) == (0, 3)
    with pytest.raises(CredenciaisInvalidas):
        await c.entrar()("dono@loja.com", "errada-errada")
    assert (c.hasher.geracoes, c.hasher.conferencias) == (0, 4)


async def test_entrar_devolve_token_e_identidade(c: Cenario) -> None:
    resultado = await c.entrar()("Dono@Loja.com ", SENHA)
    assert resultado.identidade.loja_id == c.loja_id
    assert resultado.identidade.loja_nome == "Loja Demo"
    assert resultado.identidade.email == "dono@loja.com"
    assert resultado.identidade.senha_provisoria is True
    dados = await c.sessoes.obter(resultado.token)
    assert dados is not None
    assert (dados.usuario_id, dados.loja_id) == (c.usuario.id, c.loja_id)
    assert c.usuarios.logins == [c.usuario.id]


@pytest.mark.parametrize("caso", ["email_inexistente", "senha_errada", "inativo"])
async def test_credencial_invalida_e_uniforme(c: Cenario, caso: str) -> None:
    email, senha = "dono@loja.com", SENHA
    if caso == "email_inexistente":
        email = "outro@loja.com"
    elif caso == "senha_errada":
        senha = "errada-errada"
    else:
        c.usuarios.desativar(c.usuario.id)
    with pytest.raises(CredenciaisInvalidas) as exc:
        await c.entrar()(email, senha)
    assert str(exc.value) == str(CredenciaisInvalidas())
    assert c.sessoes.ativos() == 0
    assert c.usuarios.logins == []


async def test_sair_invalida_o_token(c: Cenario) -> None:
    token = (await c.entrar()("dono@loja.com", SENHA)).token
    await Sair(c.sessoes)(token)
    assert await c.sessoes.obter(token) is None
    await Sair(c.sessoes)(token)  # idempotente


async def test_quem_sou_eu(c: Cenario) -> None:
    ident = await QuemSouEu(c.usuarios)(c.usuario.id)
    assert ident.email == "dono@loja.com" and ident.loja_nome == "Loja Demo"


async def test_quem_sou_eu_de_usuario_inativo_ou_inexistente(c: Cenario) -> None:
    with pytest.raises(SessaoInvalida):
        await QuemSouEu(c.usuarios)(uuid4())
    c.usuarios.desativar(c.usuario.id)
    with pytest.raises(SessaoInvalida):
        await QuemSouEu(c.usuarios)(c.usuario.id)


async def test_trocar_senha_desliga_provisoria_e_derruba_outras_sessoes(c: Cenario) -> None:
    atual = (await c.entrar()("dono@loja.com", SENHA)).token
    outra = (await c.entrar()("dono@loja.com", SENHA)).token
    await c.trocar()(c.usuario.id, atual, SENHA, "nova-senha-forte")
    assert await c.sessoes.obter(atual) is not None
    assert await c.sessoes.obter(outra) is None
    usuario = await c.usuarios.obter_por_id(c.usuario.id)
    assert usuario is not None and usuario.senha_provisoria is False
    assert await c.hasher.conferir("nova-senha-forte", usuario.senha_hash)
    await c.entrar()("dono@loja.com", "nova-senha-forte")


@pytest.mark.parametrize(
    ("atual", "nova", "motivo"),
    [
        ("errada-errada", "nova-senha-forte", MotivoTrocaSenha.SENHA_ATUAL_INCORRETA),
        (SENHA, "curta", MotivoTrocaSenha.SENHA_NOVA_CURTA),
        (SENHA, SENHA, MotivoTrocaSenha.SENHA_NOVA_IGUAL),
    ],
)
async def test_trocar_senha_recusa(
    c: Cenario, atual: str, nova: str, motivo: MotivoTrocaSenha
) -> None:
    token = (await c.entrar()("dono@loja.com", SENHA)).token
    with pytest.raises(TrocaSenhaInvalida) as exc:
        await c.trocar()(c.usuario.id, token, atual, nova)
    assert exc.value.motivo is motivo
    usuario = await c.usuarios.obter_por_id(c.usuario.id)
    assert usuario is not None and usuario.senha_provisoria is True
    assert await c.hasher.conferir(SENHA, usuario.senha_hash)


async def test_senha_de_exatamente_10_caracteres_passa(c: Cenario) -> None:
    token = (await c.entrar()("dono@loja.com", SENHA)).token
    await c.trocar()(c.usuario.id, token, SENHA, "1234567890")
