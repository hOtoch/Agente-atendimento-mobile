import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.adapters.outbound.db.models import Conversa, Lead, Loja, Mensagem
from app.adapters.outbound.db.repositorios import MensagemRepositorio
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration

TABELAS = {
    "lojas",
    "vendedores",
    "leads",
    "conversas",
    "mensagens",
    "fichas",
    "eventos",
    "perfil_loja",
    "regras_preco",
    "taxas",
    "tabela_troca",
    "estoque_local",
    "mapeamento_sku",
}


async def _tabelas(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            nomes = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    finally:
        await engine.dispose()
    return nomes - {"alembic_version"}


async def test_migrations_sobem_e_descem(db_url: str) -> None:
    await aplicar_migrations(db_url, "head")
    assert await _tabelas(db_url) == TABELAS

    await aplicar_migrations(db_url, "base")
    assert await _tabelas(db_url) == set()

    await aplicar_migrations(db_url, "head")
    assert await _tabelas(db_url) == TABELAS


async def test_crud_basico_lead(session: AsyncSession) -> None:
    loja = Loja(nome="Loja Centro")
    session.add(loja)
    await session.flush()
    lead = Lead(loja_id=loja.id, telefone="5511999990000", canal="whatsapp", nome="Maria")
    session.add(lead)
    await session.flush()
    conversa = Conversa(loja_id=loja.id, lead_id=lead.id, canal="whatsapp")
    session.add(conversa)
    await session.flush()
    session.add(
        Mensagem(
            loja_id=loja.id,
            conversa_id=conversa.id,
            canal="whatsapp",
            direcao="entrada",
            tipo="texto",
            conteudo="Oi, tem iPhone 16?",
            id_externo="abc",
        )
    )
    loja_id, conversa_id = loja.id, conversa.id
    await session.commit()
    session.expire_all()

    lido = (
        await session.execute(select(Lead).where(Lead.telefone == "5511999990000"))
    ).scalar_one()
    assert lido.loja_id == loja_id
    assert lido.etapa == "novo_contato"
    assert lido.dono == "ia"
    assert lido.vendedor_id is None
    assert lido.criado_em.tzinfo is not None
    msg = (await session.execute(select(Mensagem))).scalar_one()
    assert msg.conteudo == "Oi, tem iPhone 16?"
    assert msg.conversa_id == conversa_id


async def test_idempotencia_mensagem(session: AsyncSession) -> None:
    loja = Loja(nome="Loja Centro")
    session.add(loja)
    await session.flush()
    lead = Lead(loja_id=loja.id, telefone="5511999990000", canal="whatsapp")
    session.add(lead)
    await session.flush()
    conversa = Conversa(loja_id=loja.id, lead_id=lead.id, canal="whatsapp")
    session.add(conversa)
    await session.flush()

    repo = MensagemRepositorio(session)
    dados = {
        "loja_id": loja.id,
        "conversa_id": conversa.id,
        "canal": "whatsapp",
        "direcao": "entrada",
        "tipo": "texto",
        "conteudo": "oi",
        "id_externo": "wamid.123",
    }
    primeira = await repo.inserir_se_nova(id=uuid.uuid4(), **dados)
    segunda = await repo.inserir_se_nova(id=uuid.uuid4(), **dados)
    outro_canal = await repo.inserir_se_nova(id=uuid.uuid4(), **{**dados, "canal": "webchat"})
    await session.commit()

    assert primeira is True
    assert segunda is False
    assert outro_canal is True
    total = (await session.execute(select(Mensagem))).scalars().all()
    assert len(total) == 2
