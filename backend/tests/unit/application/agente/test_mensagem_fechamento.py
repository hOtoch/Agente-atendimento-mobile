"""Mensagem de fechamento: montada pelo codigo, em paragrafos, com poucos emojis."""

from __future__ import annotations

from typing import Any

from app.application.agente.acordo import conteudo_para_ia, horarios_legiveis, mensagem_fechamento
from app.domain.ficha import TipoPagamento

ENDERECO = "Rua das Palmeiras, 123, Centro, Cidade Exemplo - UF, CEP 00000-000"
HORARIOS = (
    "seg: 09:00-18:00; ter: 09:00-18:00; qua: 09:00-18:00; qui: 09:00-18:00; "
    "sex: 09:00-18:00; sab: 09:00-14:00"
)
PIX = {"tipo": "email", "chave": "pix@lojademo.exemplo", "favorecido": "Loja Demo Celulares"}
OBS = "Obs.: esta é uma pré-avaliação; o valor final é confirmado na loja com o aparelho em mãos."


def _acordo(
    *,
    forma: dict[str, Any] | None = None,
    troca: dict[str, Any] | None = None,
    pix: dict[str, str] | None = PIX,
    endereco: str | None = ENDERECO,
    horarios: str | None = HORARIOS,
    pagamento: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "aparelho": {
            "sku": "IP15-256-ROSA",
            "modelo": "iPhone 15",
            "capacidade": "256GB",
            "cor": "Rosa",
            "condicao": "novo",
        },
        "troca": troca or {"status": "sem_troca", "aparelho_usado": "Sem aparelho na troca"},
        "forma_escolhida": forma
        or {"rotulo": "Pix ou dinheiro à vista", "valor_a_vista": "R$ 3.100,00"},
        "pagamento": pagamento
        or {"tipo": "pix", "parcelas": None, "bandeira": None, "entrada": None},
        "data_prevista": None,
        "informado": {"endereco": endereco, "horarios": horarios, "chave_pix": pix},
    }


def _emojis(texto: str) -> int:
    return sum(1 for ch in texto if ord(ch) >= 0x1F300)


def test_pix_sem_troca_em_paragrafos_com_poucos_emojis() -> None:
    texto = mensagem_fechamento(_acordo(), TipoPagamento.PIX)
    assert texto == (
        "Fechado! 🎉 Resumo do seu pedido: iPhone 15 novo de 256GB, cor rosa.\n"
        "\n"
        "Valor final: R$ 3.100,00 à vista no Pix\n"
        "\n"
        "Para pagar no Pix:\n"
        "Chave: pix@lojademo.exemplo\n"
        "Favorecido: Loja Demo Celulares\n"
        "\n"
        f"📍 {ENDERECO}\n"
        "🕘 Segunda a sexta, das 9h às 18h; sábado, das 9h às 14h\n"
        "\n"
        "Obrigado pela preferência! Um vendedor vai continuar o atendimento com você na loja.\n"
        "\n"
        f"{OBS}"
    )
    assert _emojis(texto) <= 3
    assert "?" not in texto  # nada de pergunta no fechamento


def test_com_troca_mostra_primeiro_o_usado_e_depois_o_valor_final_descontado() -> None:
    texto = mensagem_fechamento(
        _acordo(
            forma={"rotulo": "Pix ou dinheiro à vista", "valor_a_vista": "R$ 1.350,00"},
            troca={
                "status": "avaliada",
                "valor": "R$ 2.950,00",
                "aparelho_usado": "iPhone 15 256GB",
            },
        ),
        TipoPagamento.PIX,
    )
    assert (
        "\n\nSeu iPhone 15 256GB na troca: R$ 2.950,00\n"
        "Valor final, já descontada a troca: R$ 1.350,00 à vista no Pix\n\n"
    ) in texto
    assert texto.endswith(OBS)


def test_credito_com_troca_avaliada_diz_parcelas_e_o_usado() -> None:
    texto = mensagem_fechamento(
        _acordo(
            forma={
                "rotulo": "Cartão de crédito em 12x Mastercard",
                "parcelas": 12,
                "valor_parcela": "R$ 250,00",
                "total_pago": "R$ 3.000,00",
                "taxa": "8,00%",
            },
            troca={"status": "avaliada", "valor": "R$ 900,00", "aparelho_usado": "iPhone 13 128GB"},
            pix=None,
            pagamento={
                "tipo": "credito",
                "parcelas": 12,
                "bandeira": "mastercard",
                "entrada": None,
            },
        ),
        TipoPagamento.CREDITO,
    )
    assert (
        "Seu iPhone 13 128GB na troca: R$ 900,00\n"
        "Valor final, já descontada a troca: 12x de R$ 250,00 no cartão Mastercard "
        "(total R$ 3.000,00)"
    ) in texto
    assert "Pix" not in texto


def test_entrada_via_pix_mostra_a_chave_da_entrada() -> None:
    texto = mensagem_fechamento(
        _acordo(
            forma={
                "rotulo": "Entrada de R$ 1.000,00 + cartão em 10x Visa",
                "parcelas": 10,
                "valor_parcela": "R$ 220,00",
                "total_pago": "R$ 3.200,00",
                "taxa": "6,00%",
                "entrada": "R$ 1.000,00",
            },
            pagamento={
                "tipo": "entrada_mais_credito",
                "parcelas": 10,
                "bandeira": "visa",
                "entrada": "1000.00",
            },
        ),
        TipoPagamento.ENTRADA_MAIS_CREDITO,
    )
    assert "entrada de R$ 1.000,00 + 10x de R$ 220,00 no cartão Visa" in texto
    assert "Para pagar a entrada no Pix:\nChave: pix@lojademo.exemplo" in texto


def test_debito() -> None:
    texto = mensagem_fechamento(
        _acordo(
            forma={
                "rotulo": "Débito Visa",
                "parcelas": 1,
                "valor_parcela": "R$ 3.150,00",
                "total_pago": "R$ 3.150,00",
                "taxa": "1,50%",
            },
            pix=None,
            pagamento={"tipo": "debito", "parcelas": None, "bandeira": "visa", "entrada": None},
        ),
        TipoPagamento.DEBITO,
    )
    assert "Valor final: R$ 3.150,00 no débito Visa\n" in texto


def test_troca_avaliada_na_loja_avisa_que_o_valor_nao_inclui_a_troca() -> None:
    texto = mensagem_fechamento(
        _acordo(troca={"status": "avaliacao_na_loja", "aparelho_usado": "Galaxy S21"}),
        TipoPagamento.PIX,
    )
    assert (
        "Seu Galaxy S21 será avaliado na loja; o valor abaixo não inclui a troca.\n"
        "Valor final: R$ 3.100,00 à vista no Pix"
    ) in texto


def test_sem_chave_sem_endereco_e_sem_horario_nao_inventa() -> None:
    texto = mensagem_fechamento(_acordo(pix=None, endereco=None, horarios=""), TipoPagamento.PIX)
    assert "O vendedor passa os dados do Pix na loja." in texto
    assert "O vendedor te passa o endereço da loja em seguida." in texto
    assert "📍" not in texto and "🕘" not in texto


def test_horarios_legiveis_agrupa_dias_seguidos_e_respeita_o_que_nao_entende() -> None:
    assert horarios_legiveis(HORARIOS) == "Segunda a sexta, das 9h às 18h; sábado, das 9h às 14h"
    assert horarios_legiveis("seg: 09:30-18:00; ter: 09:30-18:00") == (
        "Segunda e terça, das 9h30 às 18h"
    )
    assert horarios_legiveis("sab: 9 às 13") == "Sábado, 9 às 13"
    assert horarios_legiveis("") is None and horarios_legiveis(None) is None


def test_horarios_fora_de_ordem_saem_na_ordem_da_semana() -> None:
    """O banco devolve os dias fora de ordem (o jsonb reordena as chaves)."""
    fora_de_ordem = (
        "qua: 09:00-18:00; qui: 09:00-18:00; sab: 09:00-14:00; seg: 09:00-18:00; "
        "sex: 09:00-18:00; ter: 09:00-18:00"
    )
    assert horarios_legiveis(fora_de_ordem) == (
        "Segunda a sexta, das 9h às 18h; sábado, das 9h às 14h"
    )


def test_conteudo_para_ia_traz_a_mensagem_pronta_para_o_cliente() -> None:
    conteudo = conteudo_para_ia(_acordo(), TipoPagamento.PIX)
    assert conteudo["mensagem_ao_cliente"] == mensagem_fechamento(_acordo(), TipoPagamento.PIX)
    assert "chamar_vendedor" in conteudo["mensagem"]
