"""RepositorioConversasSql contra Postgres real."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.config import RepositorioLojasSql
from app.adapters.outbound.db.conversas import RepositorioConversasSql
from app.adapters.outbound.db.models import Conversa, Lead, Mensagem
from app.application.canal import Canal, MensagemEntrada, TipoMensagem

pytestmark = pytest.mark.integration


async def _loja(session: AsyncSession) -> UUID:
    loja_id = await RepositorioLojasSql(session).criar("Loja")
    await session.commit()
    return loja_id


def _msg(loja_id: UUID, id_externo: str, remetente: str = "sessao-1") -> MensagemEntrada:
    return MensagemEntrada(
        loja_id=loja_id,
        canal=Canal.WEBCHAT,
        id_externo=id_externo,
        remetente=remetente,
        tipo=TipoMensagem.TEXTO,
        texto="oi",
        midia_url=None,
        recebida_em=datetime.now(UTC),
    )


async def _contar(session: AsyncSession, modelo: type) -> int:
    return (await session.execute(select(func.count()).select_from(modelo))).scalar_one()


async def test_cria_lead_novo_com_defaults(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConversasSql(session)
    lead_id, conversa_id = await repo.obter_ou_criar(loja_id, Canal.WEBCHAT, "sessao-1")
    lead = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
    assert (lead.etapa, lead.dono, lead.canal, lead.telefone) == (
        "novo_contato",
        "ia",
        "webchat",
        "sessao-1",
    )
    conversa = (
        await session.execute(select(Conversa).where(Conversa.id == conversa_id))
    ).scalar_one()
    assert conversa.lead_id == lead_id
    assert conversa.canal == "webchat"


async def test_reaproveita_lead_e_conversa_na_segunda_vez(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConversasSql(session)
    primeiro = await repo.obter_ou_criar(loja_id, Canal.WEBCHAT, "sessao-1")
    segundo = await repo.obter_ou_criar(loja_id, Canal.WEBCHAT, "sessao-1")
    outro = await repo.obter_ou_criar(loja_id, Canal.WEBCHAT, "sessao-2")
    assert primeiro == segundo
    assert outro[0] != primeiro[0]
    assert await _contar(session, Lead) == 2
    assert await _contar(session, Conversa) == 2


async def test_registrar_entrada_e_idempotente(session: AsyncSession) -> None:
    loja_id = await _loja(session)
    repo = RepositorioConversasSql(session)
    _, conversa_id = await repo.obter_ou_criar(loja_id, Canal.WEBCHAT, "sessao-1")
    assert await repo.registrar_entrada(conversa_id, _msg(loja_id, "m1")) is True
    assert await repo.registrar_entrada(conversa_id, _msg(loja_id, "m1")) is False
    assert await repo.registrar_entrada(conversa_id, _msg(loja_id, "m2")) is True
    linhas = (await session.execute(select(Mensagem).order_by(Mensagem.id_externo))).scalars().all()
    assert [m.id_externo for m in linhas] == ["m1", "m2"]
    assert all(m.direcao == "entrada" and m.tipo == "texto" for m in linhas)
