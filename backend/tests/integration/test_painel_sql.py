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


async def test_transcricao_do_audio_e_salva_lida_pelo_agente_e_pelo_painel(
    session: AsyncSession,
) -> None:
    from sqlalchemy import select as _select

    from app.adapters.outbound.db.painel import RepositorioPainelSql

    loja, conversa = await _conversa(session)
    msg_id = uuid.uuid4()
    await MensagemRepositorio(session).inserir_se_nova(
        id=msg_id,
        loja_id=loja,
        conversa_id=conversa,
        canal="webchat",
        direcao="entrada",
        tipo="audio",
        conteudo=None,
        midia_url="http://api.local/midias/a.ogg",
        id_externo="a1",
    )
    await session.commit()
    repo = RepositorioProcessamentoSql(session)
    (antes,) = await repo.entradas_novas(conversa, None)
    assert antes.transcricao is None

    await repo.salvar_transcricao(msg_id, "tem iphone 16?")

    (depois,) = await repo.entradas_novas(conversa, None)
    assert depois.transcricao == "tem iphone 16?"
    assert depois.texto is None  # `conteudo` continua sendo so o que o cliente digitou
    lead_id = (await session.execute(_select(Lead.id))).scalar_one()
    mensagens = await RepositorioPainelSql(session).listar_mensagens(loja, lead_id)
    assert [m.transcricao for m in mensagens] == ["tem iphone 16?"]


async def test_apagar_lead_leva_conversa_mensagens_e_memoria_e_desvincula_eventos(
    session: AsyncSession,
) -> None:
    from sqlalchemy import func

    from app.adapters.outbound.db.models import Evento, Ficha
    from app.adapters.outbound.db.painel import RepositorioPainelSql

    loja, conversa = await _conversa(session)
    lead = (await session.execute(select(Conversa.lead_id))).scalar_one()
    session.add_all(
        [
            Mensagem(loja_id=loja, conversa_id=conversa, canal="webchat", direcao="entrada"),
            Ficha(loja_id=loja, lead_id=lead, versao=1, dados={"ficha": {}}),
            Evento(loja_id=loja, lead_id=lead, tipo="llm_uso", payload={}),
        ]
    )
    outra = Loja(nome="Outra")
    session.add(outra)
    await session.flush()
    alheio = Lead(loja_id=outra.id, telefone="s9", canal="webchat")
    session.add(alheio)
    await session.commit()

    repo = RepositorioPainelSql(session)
    assert await repo.apagar_lead(outra.id, lead) is False  # lead de outra loja: nada muda
    assert await repo.apagar_lead(loja, lead) is True
    assert await repo.apagar_lead(loja, lead) is False  # ja apagado

    async def contar(modelo: type) -> int:
        return (await session.execute(select(func.count()).select_from(modelo))).scalar_one()

    assert await contar(Lead) == 1  # sobrou so o da outra loja
    assert await contar(Conversa) == 0
    assert await contar(Mensagem) == 0
    assert await contar(Ficha) == 0
    evento_lead = (await session.execute(select(Evento.lead_id))).scalar_one()
    assert evento_lead is None  # metrica fica, sem o lead
