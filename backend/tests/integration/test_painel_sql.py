"""Repositorio SQL do painel e a coluna `mensagens.autor` (migration 0003)."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import Conversa, Lead, Loja, Mensagem
from app.adapters.outbound.db.processamento import RepositorioProcessamentoSql
from app.adapters.outbound.db.repositorios import MensagemRepositorio
from app.application.canal import Canal, MensagemSaida, TipoMensagem
from tests.integration.conftest import aplicar_migrations

pytestmark = pytest.mark.integration


async def _conversa(session: AsyncSession) -> tuple[UUID, UUID]:
    loja = Loja(nome="L")
    session.add(loja)
    await session.flush()
    lead = Lead(loja_id=loja.id, telefone="s1", canal="webchat")
    session.add(lead)
    await session.flush()
    conversa = Conversa(loja_id=loja.id, lead_id=lead.id, canal="webchat")
    session.add(conversa)
    await session.commit()
    return loja.id, conversa.id


async def test_autor_padrao_segue_a_direcao(session: AsyncSession) -> None:
    loja, conversa = await _conversa(session)
    repo = MensagemRepositorio(session)
    base = {"loja_id": loja, "conversa_id": conversa, "canal": "webchat"}
    await repo.inserir_se_nova(
        id=uuid.uuid4(), direcao="entrada", conteudo="a", id_externo="1", **base
    )
    await repo.inserir_se_nova(id=uuid.uuid4(), direcao="saida", conteudo="b", **base)
    await repo.inserir_se_nova(
        id=uuid.uuid4(), direcao="saida", conteudo="c", autor="vendedor", **base
    )
    await session.commit()
    autores = (
        await session.execute(select(Mensagem.conteudo, Mensagem.autor).order_by(Mensagem.conteudo))
    ).all()
    assert [tuple(a) for a in autores] == [("a", "cliente"), ("b", "ia"), ("c", "vendedor")]


async def test_registrar_saida_do_agente_grava_autor_ia(session: AsyncSession) -> None:
    loja, conversa = await _conversa(session)
    await RepositorioProcessamentoSql(session).registrar_saida(
        conversa,
        MensagemSaida(loja, Canal.WEBCHAT, "s1", TipoMensagem.TEXTO, "oi", None),
    )
    assert (await session.execute(select(Mensagem.autor))).scalar_one() == "ia"


async def test_autor_invalido_viola_o_check(session: AsyncSession) -> None:
    loja, conversa = await _conversa(session)
    session.add(
        Mensagem(loja_id=loja, conversa_id=conversa, canal="webchat", direcao="saida", autor="robo")
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_migration_0003_preenche_autor_das_mensagens_existentes(db_url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    await aplicar_migrations(db_url, "0002")
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            loja = uuid.uuid4()
            lead = uuid.uuid4()
            conversa = uuid.uuid4()
            await conn.execute(text("INSERT INTO lojas (id, nome) VALUES (:i, 'L')"), {"i": loja})
            await conn.execute(
                text(
                    "INSERT INTO leads (id, loja_id, telefone, canal) "
                    "VALUES (:i, :l, 's', 'webchat')"
                ),
                {"i": lead, "l": loja},
            )
            await conn.execute(
                text(
                    "INSERT INTO conversas (id, loja_id, lead_id, canal) "
                    "VALUES (:i, :l, :d, 'webchat')"
                ),
                {"i": conversa, "l": loja, "d": lead},
            )
            for direcao in ("entrada", "saida"):
                await conn.execute(
                    text(
                        "INSERT INTO mensagens (id, loja_id, conversa_id, canal, direcao) "
                        "VALUES (:i, :l, :c, 'webchat', :d)"
                    ),
                    {"i": uuid.uuid4(), "l": loja, "c": conversa, "d": direcao},
                )
    finally:
        await engine.dispose()

    await aplicar_migrations(db_url, "head")
    engine = create_async_engine(db_url)
    try:
        async with async_sessionmaker(engine)() as s:
            linhas = (
                await s.execute(select(Mensagem.direcao, Mensagem.autor).order_by(Mensagem.direcao))
            ).all()
    finally:
        await engine.dispose()
    assert [tuple(x) for x in linhas] == [("entrada", "cliente"), ("saida", "ia")]
