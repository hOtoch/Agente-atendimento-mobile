"""Adaptador do handoff no Mercado Phone sobre o MCP falso (httpx.MockTransport, dados sinteticos).

O adaptador so traduz: acha ou cria o cliente, mapeia as formas de pagamento por nome e envia o
orcamento com os valores que recebeu. Nada e recalculado. Nenhuma chamada ao servico real.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.adapters.outbound.mercadophone.cliente import ClienteMercadoPhone
from app.adapters.outbound.mercadophone.pedido import PedidoMercadoPhone, normalizar_nome
from app.application.pedido_erp import (
    DadosHandoff,
    DadosOrcamento,
    FalhaPedidoErp,
    FormaPedido,
    ItemPedido,
    PagamentoPedido,
)
from app.domain.conexao_erp import ConexaoErp
from tests.mercadophone_falso import CHAVE, FORMAS_PADRAO, URL, McpFalso, cliente_erp

D = Decimal
UNIDADE = 12
CONEXAO = ConexaoErp(uuid4(), UNIDADE, ativo=True, exportar_handoff=True)


def pedido_com(falso: McpFalso) -> PedidoMercadoPhone:
    return PedidoMercadoPhone(ClienteMercadoPhone(falso.cliente_http(), URL, CHAVE))


def orcamento(**campos: Any) -> DadosOrcamento:
    base: dict[str, Any] = {
        "vendedor_id_erp": 9,
        "itens": (ItemPedido(777, 1, D("4200.00"), D("100.00")),),
        "pagamentos": (
            PagamentoPedido(FormaPedido.CREDITO, D("3333.24"), 12),
            PagamentoPedido(FormaPedido.APARELHO, D("1200.00"), 1),
        ),
        "observacao": "Handoff da IA. Pré-avaliação, valor final confirmado na loja.",
        "previsao": date(2026, 11, 30),
    }
    base.update(campos)
    return DadosOrcamento(**base)


def dados(**campos: Any) -> DadosHandoff:
    base: dict[str, Any] = {
        "nome_cliente": "Marcos",
        "telefone": "5511912345678",
        "cliente_id": None,
        "orcamento_id": None,
        "orcamento": orcamento(),
    }
    base.update(campos)
    return DadosHandoff(**base)


# --- cliente -------------------------------------------------------------------------------------


async def test_cria_o_cliente_quando_o_telefone_nao_existe() -> None:
    falso = McpFalso({UNIDADE: []})
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())

    (busca,) = falso.chamadas_de("list_customers")
    assert busca["telefone"] == "12345678"  # so os ultimos 8 digitos: o ERP guarda formatado
    assert busca["system_unit_id"] == UNIDADE
    (criacao,) = falso.chamadas_de("create_customer")
    assert criacao == {"nome": "Marcos", "telefone": "5511912345678", "system_unit_id": UNIDADE}
    assert registro.cliente_id == falso.clientes[0]["id"]


async def test_reaproveita_o_cliente_do_erp_pelo_telefone_formatado() -> None:
    falso = McpFalso({UNIDADE: []}, clientes=[cliente_erp(321, "(11) 91234-5678")])
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())

    assert registro.cliente_id == 321
    assert falso.chamadas_de("create_customer") == []
    assert falso.orcamentos[0]["clienteId"] == 321


async def test_reaproveita_cliente_cadastrado_sem_ddi_nem_ddd() -> None:
    falso = McpFalso({UNIDADE: []}, clientes=[cliente_erp(322, "91234-5678")])
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert registro.cliente_id == 322


async def test_busca_parcial_que_nao_confere_nao_reaproveita_o_cliente_errado() -> None:
    # mesmo trecho no meio do numero, mas o fim e outro: nao e a mesma pessoa
    outro = cliente_erp(400, "(21) 12345-6789")
    falso = McpFalso({UNIDADE: []}, clientes=[outro])
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())

    assert registro.cliente_id != 400
    assert len(falso.chamadas_de("create_customer")) == 1


async def test_cliente_ja_vinculado_ao_lead_nao_busca_nem_cria() -> None:
    falso = McpFalso({UNIDADE: []})
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados(cliente_id=55))

    assert registro.cliente_id == 55
    assert falso.chamadas_de("list_customers") == []
    assert falso.chamadas_de("create_customer") == []
    assert falso.orcamentos[0]["clienteId"] == 55


async def test_sem_telefone_cria_o_cliente_so_com_o_nome() -> None:
    falso = McpFalso({UNIDADE: []})
    await pedido_com(falso).registrar_handoff(CONEXAO, dados(telefone=None))

    assert falso.chamadas_de("list_customers") == []
    (criacao,) = falso.chamadas_de("create_customer")
    assert "telefone" not in criacao


async def test_sem_orcamento_so_o_cliente_e_nada_de_forma_de_pagamento() -> None:
    falso = McpFalso({UNIDADE: []})
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados(orcamento=None))

    assert registro.orcamento_id is None
    assert falso.chamadas_de("create_estimate") == []
    assert falso.chamadas_de("list_payment_methods") == []


# --- orcamento -----------------------------------------------------------------------------------


async def test_orcamento_leva_os_valores_recebidos_sem_recalcular() -> None:
    falso = McpFalso({UNIDADE: []})
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())

    (envio,) = falso.chamadas_de("create_estimate")
    assert envio["system_unit_id"] == UNIDADE
    assert envio["vendedorId"] == 9 and envio["clienteId"] == registro.cliente_id
    assert envio["itens"] == [
        {"produtoId": 777, "quantidade": 1, "valorUnitario": 4200.0, "desconto": 100.0}
    ]
    assert envio["pagamentos"] == [
        {"formaPagamentoId": 35, "valor": 3333.24, "parcelas": 12},
        {"formaPagamentoId": 40, "valor": 1200.0, "parcelas": 1},
    ]
    assert envio["previsaoOrcamento"] == "2026-11-30"
    assert "valor final confirmado na loja" in envio["observacao"]
    assert "id" not in envio
    assert registro.orcamento_id == falso.orcamentos[0]["id"]


async def test_orcamento_ja_vinculado_e_editado_com_o_id() -> None:
    falso = McpFalso({UNIDADE: []}, clientes=[cliente_erp(55, "(11) 91234-5678")])
    falso.orcamentos.append({"id": 700, "clienteId": 55})
    registro = await pedido_com(falso).registrar_handoff(
        CONEXAO, dados(cliente_id=55, orcamento_id=700)
    )

    (envio,) = falso.chamadas_de("create_estimate")
    assert envio["id"] == 700
    assert registro.orcamento_id == 700
    assert len(falso.orcamentos) == 1  # editou, nao criou outro


async def test_sem_previsao_nao_envia_a_data() -> None:
    falso = McpFalso({UNIDADE: []})
    await pedido_com(falso).registrar_handoff(CONEXAO, dados(orcamento=orcamento(previsao=None)))
    assert "previsaoOrcamento" not in falso.chamadas_de("create_estimate")[0]


# --- formas de pagamento -----------------------------------------------------------------------


def _forma_enviada(falso: McpFalso, indice: int = 0) -> int:
    return falso.chamadas_de("create_estimate")[0]["pagamentos"][indice]["formaPagamentoId"]


@pytest.mark.parametrize(
    ("forma", "esperado"),
    [
        (FormaPedido.PIX, 30),  # dois "PIX" ativos: vale o menor id
        (FormaPedido.CREDITO, 35),  # "Cartão de Crédito" (acento e caixa)
        (FormaPedido.DEBITO, 36),  # "CARTAO DEBITO" nao e confundido com credito
        (FormaPedido.APARELHO, 40),
    ],
)
async def test_mapeia_a_forma_por_nome_normalizado(forma: FormaPedido, esperado: int) -> None:
    falso = McpFalso({UNIDADE: []})
    pagamentos = (PagamentoPedido(forma, D("10"), 1),)
    await pedido_com(falso).registrar_handoff(
        CONEXAO, dados(orcamento=orcamento(pagamentos=pagamentos))
    )
    assert _forma_enviada(falso) == esperado


async def test_ignora_forma_inativa() -> None:
    formas = [
        {"id": 1, "name": "PIX", "snAtivo": 0, "taxas": []},
        {"id": 2, "name": "PIX", "snAtivo": 1, "taxas": []},
    ]
    falso = McpFalso({UNIDADE: []}, formas_pagamento=formas)
    pagamentos = (PagamentoPedido(FormaPedido.PIX, D("10"), 1),)
    await pedido_com(falso).registrar_handoff(
        CONEXAO, dados(orcamento=orcamento(pagamentos=pagamentos))
    )
    assert _forma_enviada(falso) == 2


async def test_forma_nao_encontrada_sai_do_orcamento_com_aviso() -> None:
    formas = [f for f in FORMAS_PADRAO if f["name"] != "APARELHO"]
    falso = McpFalso({UNIDADE: []}, formas_pagamento=formas)
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())

    enviados = falso.chamadas_de("create_estimate")[0]["pagamentos"]
    assert [p["formaPagamentoId"] for p in enviados] == [35]
    assert len(registro.avisos) == 1 and "aparelho" in registro.avisos[0].lower()


async def test_consulta_as_formas_na_unidade_da_conexao() -> None:
    falso = McpFalso({UNIDADE: []})
    await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert falso.chamadas_de("list_payment_methods") == [{"system_unit_id": UNIDADE}]


def test_normalizar_nome_tira_acento_caixa_e_espacos() -> None:
    assert normalizar_nome("  Cartão  de Crédito ") == "CARTAO DE CREDITO"


# --- formato da resposta de escrita (tolerante) e falhas ---------------------------------------


@pytest.mark.parametrize("formato", ["topo", "data", "item"])
async def test_extrai_o_id_criado_em_formatos_diferentes(formato: str) -> None:
    falso = McpFalso({UNIDADE: []}, formato_escrita=formato)
    registro = await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert registro.cliente_id == falso.clientes[0]["id"]
    assert registro.orcamento_id == falso.orcamentos[0]["id"]


async def test_resposta_de_criacao_sem_id_e_erro_tipado() -> None:
    falso = McpFalso({UNIDADE: []}, formato_escrita="sem_id")
    with pytest.raises(FalhaPedidoErp) as erro:
        await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert erro.value.cliente_id is None


async def test_falha_no_orcamento_leva_o_cliente_ja_criado_na_excecao() -> None:
    falso = McpFalso(
        {UNIDADE: []}, falha_ferramentas={"create_estimate": httpx.Response(500, text="boom")}
    )
    with pytest.raises(FalhaPedidoErp) as erro:
        await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert erro.value.cliente_id == falso.clientes[0]["id"]
    assert "500" in str(erro.value)


async def test_chave_nunca_aparece_na_mensagem_de_erro() -> None:
    falso = McpFalso({UNIDADE: []}, falha_ferramentas={"list_customers": httpx.Response(401)})
    with pytest.raises(FalhaPedidoErp) as erro:
        await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    assert CHAVE not in str(erro.value)


async def test_so_usa_ferramentas_da_allowlist_de_escrita_do_handoff() -> None:
    falso = McpFalso({UNIDADE: []})
    await pedido_com(falso).registrar_handoff(CONEXAO, dados())
    usadas = {nome for nome, _ in falso.chamadas}
    assert usadas <= {
        "list_customers",
        "create_customer",
        "list_payment_methods",
        "create_estimate",
    }
