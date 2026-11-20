"""PausarIAProvisorio: dono = vendedor + evento DonoMudou, idempotente."""

from __future__ import annotations

from uuid import uuid4

from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.memoria import PublicadorEmMemoria, RepositorioPainelEmMemoria
from app.application.painel.pausar_ia import PausarIAProvisorio
from app.application.whatsapp import PausarIA


def _montar() -> tuple[PausarIAProvisorio, RepositorioPainelEmMemoria, PublicadorEmMemoria]:
    repo, publicador = RepositorioPainelEmMemoria(), PublicadorEmMemoria()
    return PausarIAProvisorio(repo, publicador), repo, publicador


async def test_pausa_a_ia_e_publica_o_dono() -> None:
    caso, repo, publicador = _montar()
    loja = uuid4()
    lead = repo.adicionar_lead(loja, telefone="5511987654321")
    pausar: PausarIA = caso
    await pausar.pausar_por_vendedor(loja, lead)
    assert repo.leads[lead].dono == "vendedor"
    assert repo.leads[lead].vendedor_id is None
    ((loja_pub, evento),) = publicador.publicados
    assert loja_pub == loja
    assert isinstance(evento, EventoDonoMudou)
    assert (evento.lead_id, evento.dono, evento.vendedor_id) == (lead, "vendedor", None)
    (auditoria,) = repo.eventos_de(lead)
    assert auditoria.tipo == "dono_mudou"
    assert auditoria.payload["origem"] == "celular_da_loja"


async def test_preserva_o_vendedor_ja_atribuido() -> None:
    caso, repo, publicador = _montar()
    loja, vendedor = uuid4(), uuid4()
    repo.adicionar_vendedor(loja, vendedor, "Ana")
    lead = repo.adicionar_lead(loja, telefone="1", vendedor_id=vendedor)
    await caso.pausar_por_vendedor(loja, lead)
    assert repo.leads[lead].vendedor_id == vendedor
    assert publicador.publicados[0][1].dono == f"vendedor:{vendedor}"  # type: ignore[union-attr]


async def test_ja_pausada_nao_repete_nada() -> None:
    caso, repo, publicador = _montar()
    loja = uuid4()
    lead = repo.adicionar_lead(loja, telefone="1", dono="vendedor")
    await caso.pausar_por_vendedor(loja, lead)
    assert publicador.publicados == []
    assert repo.eventos_de(lead) == []


async def test_lead_inexistente_e_ignorado() -> None:
    caso, _, publicador = _montar()
    await caso.pausar_por_vendedor(uuid4(), uuid4())
    assert publicador.publicados == []


async def test_falha_no_tempo_real_nao_desfaz_a_pausa() -> None:
    caso, repo, publicador = _montar()
    publicador.falhar = True
    loja = uuid4()
    lead = repo.adicionar_lead(loja, telefone="1")
    await caso.pausar_por_vendedor(loja, lead)
    assert repo.leads[lead].dono == "vendedor"
