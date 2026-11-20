"""Publicador do painel sobre o barramento: topico por loja e payload serializavel."""

import json
from datetime import UTC, datetime
from uuid import UUID

from app.adapters.outbound.barramento.memoria import BarramentoEmMemoria
from app.adapters.outbound.barramento.painel import PublicadorPainelBarramento, topico_painel
from app.application.painel.eventos import EventoDonoMudou, EventoEtapaMudou, EventoMensagemNova
from app.domain.kanban import Etapa

LOJA = UUID(int=1)
LEAD = UUID(int=2)
EM = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def test_topico_por_loja() -> None:
    assert topico_painel(LOJA) == f"painel:{LOJA}"


async def test_publica_cada_evento_no_topico_da_loja_como_json() -> None:
    barramento = BarramentoEmMemoria()
    stream = barramento.assinar(topico_painel(LOJA))
    pub = PublicadorPainelBarramento(barramento)

    await pub.publicar(
        LOJA,
        EventoEtapaMudou(
            lead_id=LEAD,
            de=Etapa.NOVO_CONTATO,
            para=Etapa.COM_O_VENDEDOR,
            ator="vendedor",
            motivo="m",
            em=EM,
        ),
    )
    await pub.publicar(
        LOJA,
        EventoMensagemNova(
            lead_id=LEAD,
            conversa_id=UUID(int=3),
            autor="ia",
            direcao="saida",
            tipo="texto",
            texto="oi",
            midia_url=None,
            em=EM,
        ),
    )
    await pub.publicar(LOJA, EventoDonoMudou(lead_id=LEAD, dono="ia", vendedor_id=None, em=EM))

    recebidos = [await anext(stream) for _ in range(3)]
    json.dumps(recebidos)  # tudo serializavel
    assert [r["evento"] for r in recebidos] == ["EtapaMudou", "MensagemNova", "DonoMudou"]
    assert recebidos[0] == {
        "evento": "EtapaMudou",
        "lead_id": str(LEAD),
        "de": "novo_contato",
        "para": "com_o_vendedor",
        "ator": "vendedor",
        "motivo": "m",
        "em": EM.isoformat(),
    }
    assert recebidos[1]["texto"] == "oi"
    assert recebidos[2]["dono"] == "ia" and recebidos[2]["vendedor_id"] is None
    await stream.aclose()  # type: ignore[attr-defined]


async def test_nao_vaza_para_outra_loja() -> None:
    barramento = BarramentoEmMemoria()
    outra = barramento.assinar(topico_painel(UUID(int=99)))
    await PublicadorPainelBarramento(barramento).publicar(
        LOJA, EventoDonoMudou(lead_id=LEAD, dono="ia", vendedor_id=None, em=EM)
    )
    barramento.fechar(topico_painel(UUID(int=99)))
    assert [x async for x in outra] == []
