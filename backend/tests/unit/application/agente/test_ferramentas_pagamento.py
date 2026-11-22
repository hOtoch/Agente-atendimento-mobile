"""registrar_compra respeita as formas de pagamento que a loja aceita."""

from __future__ import annotations

from app.application.agente.estado import EstadoAtendimento
from app.application.config.entradas import EntradaPagamento
from app.domain.ficha import Pendencia, TipoPagamento, pendencias

from .apoio_ferramentas import (
    COMPRA_HOJE_12X,
    HOJE,
    INTERESSE_16,
    USADO_EXEMPLO,
    Ambiente,
    criar_ambiente,
)

VAZIO = EstadoAtendimento()


def _compra(**campos: object) -> dict[str, object]:
    base: dict[str, object] = dict.fromkeys(COMPRA_HOJE_12X)
    return base | campos


async def _formas(amb: Ambiente, **sobre: bool) -> None:
    atual = await amb.casos.obter_pagamento(amb.loja_id)
    entrada = EntradaPagamento(
        aceita_pix=sobre.get("aceita_pix", atual.formas.pix),
        aceita_debito=sobre.get("aceita_debito", atual.formas.debito),
        aceita_credito=sobre.get("aceita_credito", atual.formas.credito),
        chave_pix_tipo=atual.chave_pix.tipo.value if atual.chave_pix else None,
        chave_pix=atual.chave_pix.chave if atual.chave_pix else None,
        chave_pix_favorecido=atual.chave_pix.favorecido if atual.chave_pix else None,
    )
    await amb.casos.atualizar_pagamento(amb.loja_id, entrada)


async def _qualificado_sem_pagamento(amb: Ambiente) -> EstadoAtendimento:
    estado, _ = await amb.seq(
        VAZIO,
        ("registrar_interesse", INTERESSE_16),
        ("consultar_estoque", INTERESSE_16),
        ("registrar_usado", USADO_EXEMPLO),
        ("registrar_compra", _compra(data_prevista=HOJE.isoformat())),
    )
    assert pendencias(estado.ficha) == [Pendencia.PAGAMENTO_TIPO]
    return estado


async def test_forma_desligada_e_recusada_e_lista_as_aceitas() -> None:
    amb = await criar_ambiente()
    await _formas(amb, aceita_debito=False)
    r = await amb.rodar("registrar_compra", _compra(tipo_pagamento="debito"), VAZIO)
    assert r.erro
    assert r.estado == VAZIO  # nada gravado
    assert "débito" in r.conteudo["erro"]
    assert r.conteudo["formas_aceitas"] == ["pix", "credito", "entrada_mais_credito"]
    for aceita in ("Pix", "crédito", "entrada mais cartão"):
        assert aceita in r.conteudo["erro"]


async def test_forma_ligada_continua_aceita() -> None:
    amb = await criar_ambiente()
    await _formas(amb, aceita_debito=False)
    r = await amb.rodar("registrar_compra", _compra(tipo_pagamento="pix"), VAZIO)
    assert not r.erro
    assert r.estado.ficha.pagamento.tipo is TipoPagamento.PIX


async def test_credito_desligado_recusa_credito_e_entrada_mais_cartao() -> None:
    amb = await criar_ambiente()
    await _formas(amb, aceita_credito=False)
    for compra in (
        COMPRA_HOJE_12X,
        _compra(tipo_pagamento="entrada_mais_credito", parcelas=10, bandeira="Visa", entrada="500"),
    ):
        r = await amb.rodar("registrar_compra", compra, VAZIO)
        assert r.erro, compra
        assert r.conteudo["formas_aceitas"] == ["pix", "debito"]


async def test_mudar_so_a_data_nao_e_barrado_por_forma_ja_na_ficha() -> None:
    amb = await criar_ambiente()
    estado, _ = await amb.seq(
        VAZIO, ("registrar_compra", _compra(tipo_pagamento="debito", bandeira="Visa"))
    )
    await _formas(amb, aceita_debito=False)
    r = await amb.rodar("registrar_compra", _compra(data_prevista=HOJE.isoformat()), estado)
    assert not r.erro


async def test_proxima_pergunta_de_pagamento_lista_so_as_aceitas() -> None:
    amb = await criar_ambiente()
    await _formas(amb, aceita_debito=False, aceita_credito=False)
    estado = await _qualificado_sem_pagamento(amb)
    r = await amb.rodar("registrar_compra", _compra(), estado)
    pergunta = r.conteudo["proxima_pergunta"]
    assert "Pix" in pergunta
    assert "débito" not in pergunta
    assert "crédito" not in pergunta


async def test_proxima_pergunta_com_todas_as_formas_mantem_o_texto() -> None:
    amb = await criar_ambiente()
    estado = await _qualificado_sem_pagamento(amb)
    r = await amb.rodar("registrar_compra", _compra(), estado)
    assert r.conteudo["proxima_pergunta"] == (
        "Como você prefere pagar: Pix, débito, cartão de crédito ou entrada mais cartão?"
    )


async def test_calcular_proposta_bloqueada_tambem_usa_as_formas_aceitas() -> None:
    amb = await criar_ambiente()
    await _formas(amb, aceita_credito=False)
    estado = await _qualificado_sem_pagamento(amb)
    r = await amb.rodar("calcular_proposta", {}, estado)
    assert r.conteudo["bloqueado"] is True
    assert "crédito" not in r.conteudo["proxima_pergunta"]
