"""Cria lojas direto no banco dos testes (a API nao tem mais `POST /lojas`)."""

from app.adapters.outbound.db.config import RepositorioLojasSql
from app.infra.dependencias import get_session
from app.main import app


async def criar_loja_no_banco(nome: str = "Loja") -> str:
    """Usa o override de `get_session` do teste (mesmo banco isolado da API)."""
    gerador = app.dependency_overrides[get_session]()
    sessao = await anext(gerador)
    try:
        loja_id = await RepositorioLojasSql(sessao).criar(nome)
        await sessao.commit()
    finally:
        await gerador.aclose()
    return str(loja_id)
