"""Formas de pagamento e chave Pix da loja: casos de uso, validacao e checklist."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.entradas import EntradaPagamento, EntradaPreco
from app.application.config.memoria import criar_casos_em_memoria
from app.application.config.modelos import ErrosDeValidacao, LojaNaoEncontrada
from app.domain.chave_pix import TipoChavePix
from app.domain.ficha import TipoPagamento

CHAVE = "pix@lojademo.exemplo"


def pagamento(**sobre: object) -> EntradaPagamento:
    base: dict[str, object] = {
        "aceita_pix": True,
        "aceita_debito": True,
        "aceita_credito": True,
        "chave_pix_tipo": "email",
        "chave_pix": CHAVE,
        "chave_pix_favorecido": "Loja Demo",
    }
    base.update(sobre)
    return EntradaPagamento(**base)  # type: ignore[arg-type]


def preco(**sobre: object) -> EntradaPreco:
    base: dict[str, object] = {
        "max_parcelas": 12,
        "repassa_taxa": True,
        "desconto_pix_tipo": "nenhum",
        "desconto_pix_valor": None,
        "aceita_entrada_mais_cartao": True,
        "desconto_teto": Decimal(100),
        "desconto_degrau": Decimal(50),
        "oportunidade_ativa": False,
        "oportunidade_dias_minimos": 0,
        "oportunidade_valor": Decimal(0),
        "oportunidade_conta_no_teto": False,
    }
    base.update(sobre)
    return EntradaPreco(**base)  # type: ignore[arg-type]


async def _loja() -> tuple[CasosDeUsoConfig, object]:
    casos = criar_casos_em_memoria()
    return casos, await casos.criar_loja("Loja")


def _item(itens: list, chave: str):  # type: ignore[no-untyped-def,type-arg]
    return next(i for i in itens if i.chave == chave)


async def test_sem_configuracao_aceita_pix_debito_e_credito_sem_chave() -> None:
    casos, loja = await _loja()
    p = await casos.obter_pagamento(loja)  # type: ignore[arg-type]
    assert p.formas.tipos() == (TipoPagamento.PIX, TipoPagamento.DEBITO, TipoPagamento.CREDITO)
    assert p.chave_pix is None


async def test_salvar_e_ler_formas_e_chave() -> None:
    casos, loja = await _loja()
    salvo = await casos.atualizar_pagamento(
        loja,  # type: ignore[arg-type]
        pagamento(aceita_debito=False, chave_pix_tipo="email", chave_pix="  PIX@LojaDemo.exemplo "),
    )
    lido = await casos.obter_pagamento(loja)  # type: ignore[arg-type]
    assert lido == salvo
    assert lido.formas.tipos() == (TipoPagamento.PIX, TipoPagamento.CREDITO)
    assert lido.chave_pix is not None
    assert lido.chave_pix.tipo is TipoChavePix.EMAIL
    assert lido.chave_pix.chave == CHAVE
    assert lido.chave_pix.favorecido == "Loja Demo"


async def test_entrada_mais_cartao_vem_das_regras_de_preco() -> None:
    casos, loja = await _loja()
    await casos.atualizar_preco(loja, preco(aceita_entrada_mais_cartao=True))  # type: ignore[arg-type]
    assert (await casos.obter_pagamento(loja)).formas.aceita(  # type: ignore[arg-type]
        TipoPagamento.ENTRADA_MAIS_CREDITO
    )
    await casos.atualizar_preco(loja, preco(aceita_entrada_mais_cartao=False))  # type: ignore[arg-type]
    assert not (await casos.obter_pagamento(loja)).formas.aceita(  # type: ignore[arg-type]
        TipoPagamento.ENTRADA_MAIS_CREDITO
    )


async def test_entrada_mais_cartao_sem_regras_de_preco_nao_e_aceita() -> None:
    casos, loja = await _loja()
    formas = (await casos.obter_pagamento(loja)).formas  # type: ignore[arg-type]
    assert not formas.aceita(TipoPagamento.ENTRADA_MAIS_CREDITO)


async def test_credito_desligado_derruba_entrada_mais_cartao() -> None:
    casos, loja = await _loja()
    await casos.atualizar_preco(loja, preco())  # type: ignore[arg-type]
    await casos.atualizar_pagamento(loja, pagamento(aceita_credito=False))  # type: ignore[arg-type]
    formas = (await casos.obter_pagamento(loja)).formas  # type: ignore[arg-type]
    assert not formas.aceita(TipoPagamento.ENTRADA_MAIS_CREDITO)


async def test_chave_invalida_para_o_tipo_e_recusada_com_erro_por_campo() -> None:
    casos, loja = await _loja()
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_pagamento(
            loja,  # type: ignore[arg-type]
            pagamento(chave_pix_tipo="cpf", chave_pix="123.456.789-00"),
        )
    assert [e.caminho for e in exc.value.erros] == ["chave_pix"]
    # nada foi gravado
    assert (await casos.obter_pagamento(loja)).chave_pix is None  # type: ignore[arg-type]


async def test_favorecido_obrigatorio_com_chave() -> None:
    casos, loja = await _loja()
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_pagamento(loja, pagamento(chave_pix_favorecido="  "))  # type: ignore[arg-type]
    assert [e.caminho for e in exc.value.erros] == ["chave_pix_favorecido"]


async def test_tipo_de_chave_desconhecido() -> None:
    casos, loja = await _loja()
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_pagamento(loja, pagamento(chave_pix_tipo="bitcoin"))  # type: ignore[arg-type]
    assert [e.caminho for e in exc.value.erros] == ["chave_pix_tipo"]


async def test_chave_em_branco_remove_a_chave() -> None:
    casos, loja = await _loja()
    await casos.atualizar_pagamento(loja, pagamento())  # type: ignore[arg-type]
    await casos.atualizar_pagamento(
        loja,  # type: ignore[arg-type]
        pagamento(chave_pix_tipo=None, chave_pix="", chave_pix_favorecido=None),
    )
    assert (await casos.obter_pagamento(loja)).chave_pix is None  # type: ignore[arg-type]


async def test_loja_inexistente() -> None:
    casos = criar_casos_em_memoria()
    from uuid import uuid4

    with pytest.raises(LojaNaoEncontrada):
        await casos.obter_pagamento(uuid4())
    with pytest.raises(LojaNaoEncontrada):
        await casos.atualizar_pagamento(uuid4(), pagamento())


# --- checklist ----------------------------------------------------------------------------


async def test_checklist_acusa_pix_aceito_sem_chave() -> None:
    casos, loja = await _loja()
    item = _item(await casos.checklist(loja), "pagamento")  # type: ignore[arg-type]
    assert not item.completo
    assert "chave" in item.detalhe.lower()
    assert item.rotulo_ptbr == "Formas de pagamento"


async def test_checklist_completo_com_chave_pix() -> None:
    casos, loja = await _loja()
    await casos.atualizar_pagamento(loja, pagamento())  # type: ignore[arg-type]
    item = _item(await casos.checklist(loja), "pagamento")  # type: ignore[arg-type]
    assert item.completo


async def test_checklist_sem_pix_nao_exige_chave() -> None:
    casos, loja = await _loja()
    await casos.atualizar_pagamento(
        loja,  # type: ignore[arg-type]
        pagamento(aceita_pix=False, chave_pix_tipo=None, chave_pix=None, chave_pix_favorecido=None),
    )
    item = _item(await casos.checklist(loja), "pagamento")  # type: ignore[arg-type]
    assert item.completo


async def test_checklist_sem_nenhuma_forma_esta_pendente() -> None:
    casos, loja = await _loja()
    await casos.atualizar_pagamento(
        loja,  # type: ignore[arg-type]
        pagamento(
            aceita_pix=False,
            aceita_debito=False,
            aceita_credito=False,
            chave_pix_tipo=None,
            chave_pix=None,
            chave_pix_favorecido=None,
        ),
    )
    item = _item(await casos.checklist(loja), "pagamento")  # type: ignore[arg-type]
    assert not item.completo
    assert "nenhuma forma" in item.detalhe.lower()
