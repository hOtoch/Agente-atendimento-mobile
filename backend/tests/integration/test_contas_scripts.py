"""Scripts criar_loja / redefinir_senha e usuario demo do seed, contra Postgres e Redis reais."""

import importlib.util
import sys
from types import ModuleType

import pytest
from arq.connections import ArqRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2
from app.adapters.outbound.auth.sessoes import SessoesRedis
from app.adapters.outbound.auth.usuarios import RepositorioUsuariosSql
from app.adapters.outbound.db.models import Loja, UsuarioRow
from app.application.auth.contas import EmailJaCadastrado
from app.infra.seed import EMAIL_DEMO, LOJA_DEMO_ID, semear
from tests.unit.scripts.carregar import BACKEND

pytestmark = pytest.mark.integration


def _carregar(nome: str) -> ModuleType:
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(nome, BACKEND / "scripts" / f"{nome}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    spec.loader.exec_module(modulo)
    return modulo


criar_loja = _carregar("criar_loja")
redefinir_senha = _carregar("redefinir_senha")


async def _contar(session: AsyncSession, modelo: type) -> int:
    session.expire_all()
    return (await session.execute(select(func.count()).select_from(modelo))).scalar_one()


async def test_cria_loja_e_usuario_numa_transacao(db_url: str, session: AsyncSession) -> None:
    conta = await criar_loja.criar(db_url, "Loja X", "Dono@Loja.com", None)
    assert await _contar(session, Loja) == 1 and await _contar(session, UsuarioRow) == 1
    usuario = await RepositorioUsuariosSql(session).obter_por_email("dono@loja.com")
    assert usuario is not None and usuario.senha_provisoria and usuario.loja_nome == "Loja X"
    assert await HasherSenhaArgon2().conferir(conta.senha, usuario.senha_hash)


async def test_email_repetido_nao_cria_nada(db_url: str, session: AsyncSession) -> None:
    await criar_loja.criar(db_url, "Loja X", "a@a.com", None)
    with pytest.raises(EmailJaCadastrado):
        await criar_loja.criar(db_url, "Loja Y", "A@a.com", None)
    assert await _contar(session, Loja) == 1 and await _contar(session, UsuarioRow) == 1


async def test_executar_sai_com_erro_se_email_existe(db_url: str, session: AsyncSession) -> None:
    await criar_loja.criar(db_url, "Loja X", "a@a.com", None)
    codigo = await criar_loja.executar(["--nome", "Y", "--email", "a@a.com"], db_url)
    assert codigo != 0
    assert await _contar(session, Loja) == 1


async def test_executar_imprime_a_senha_uma_vez(
    db_url: str, session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await session.connection()  # garante migrations aplicadas pela fixture
    codigo = await criar_loja.executar(["--nome", "Z", "--email", "z@z.com"], db_url)
    saida = capsys.readouterr().out
    assert codigo == 0 and "z@z.com" in saida
    usuario = await RepositorioUsuariosSql(session).obter_por_email("z@z.com")
    assert usuario is not None
    senha = saida.split("Senha provisoria:")[1].split()[0]
    assert saida.count(senha) == 1
    assert await HasherSenhaArgon2().conferir(senha, usuario.senha_hash)


async def test_redefinir_derruba_sessoes_e_marca_provisoria(
    db_url: str, session: AsyncSession, redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    conta = await criar_loja.criar(db_url, "Loja X", "a@a.com", "senha-original-123")
    sessoes = SessoesRedis(redis_pool, ttl_s=60, prefixo=prefixo_redis)
    try:
        token = await sessoes.criar(conta.usuario.id, conta.loja_id)
        repo = RepositorioUsuariosSql(session)
        await repo.atualizar_senha(conta.usuario.id, "x", senha_provisoria=False)
        await session.commit()
        nova = await redefinir_senha.redefinir(db_url, "a@a.com", sessoes)
        assert await sessoes.obter(token) is None
        session.expire_all()
        usuario = await repo.obter_por_email("a@a.com")
        assert usuario is not None and usuario.senha_provisoria
        assert await HasherSenhaArgon2().conferir(nova, usuario.senha_hash)
    finally:
        async for chave in redis_pool.scan_iter(match=f"{prefixo_redis}*"):
            await redis_pool.delete(chave)


async def test_seed_cria_usuario_demo_idempotente(db_url: str, session: AsyncSession) -> None:
    await semear(db_url, senha_demo="senha-demo-123")
    repo = RepositorioUsuariosSql(session)
    primeiro = await repo.obter_por_email(EMAIL_DEMO)
    assert primeiro is not None and primeiro.loja_id == LOJA_DEMO_ID
    assert await HasherSenhaArgon2().conferir("senha-demo-123", primeiro.senha_hash)
    await semear(db_url, senha_demo="outra-senha-456")
    session.expire_all()
    segundo = await repo.obter_por_email(EMAIL_DEMO)
    assert segundo is not None and segundo.id == primeiro.id
    assert segundo.senha_hash == primeiro.senha_hash
    assert await _contar(session, UsuarioRow) == 1


async def test_seed_sem_senha_pula_usuario(db_url: str, session: AsyncSession) -> None:
    await semear(db_url, senha_demo=None)
    assert await _contar(session, UsuarioRow) == 0
