"""Porta do pedido no ERP (cliente + orcamento do handoff) e a montagem dos dados a enviar.

`montar_dados_pedido` e uma funcao PURA: so le o estado do atendimento (a ultima proposta que o
dominio calculou e a ficha) e reorganiza os valores no formato do pedido. Nenhum preco, troca,
parcela ou desconto e calculado aqui: o que a proposta trouxe e o que vai para o ERP.

Quando falta algo para o orcamento (sem proposta, sem vendedor com codigo do ERP, SKU que nao
veio do ERP), os dados saem so com o cliente e o motivo vira aviso.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal
from app.application.handoff import ResumoHandoff
from app.domain.conexao_erp import ConexaoErp
from app.domain.ficha import TipoPagamento

FRASE_PRE_AVALIACAO = "Pré-avaliação, valor final confirmado na loja."


class FormaPedido(StrEnum):
    """Forma de pagamento do orcamento; o adaptador do ERP mapeia para o cadastro do cliente."""

    PIX = "pix"
    CREDITO = "credito"
    DEBITO = "debito"
    APARELHO = "aparelho"


@dataclass(frozen=True, slots=True)
class ItemPedido:
    produto_id: int
    quantidade: int
    valor_unitario: Decimal
    desconto: Decimal


@dataclass(frozen=True, slots=True)
class PagamentoPedido:
    forma: FormaPedido
    valor: Decimal
    parcelas: int = 1


@dataclass(frozen=True, slots=True)
class DadosOrcamento:
    vendedor_id_erp: int
    itens: tuple[ItemPedido, ...]
    pagamentos: tuple[PagamentoPedido, ...]
    observacao: str
    previsao: date | None = None


@dataclass(frozen=True, slots=True)
class DadosHandoff:
    """Tudo o que o ERP recebe. `orcamento` None = so o cliente."""

    nome_cliente: str
    telefone: str | None
    """So digitos com DDI; None quando o canal nao tem telefone real (ex.: webchat)."""
    cliente_id: int | None
    """Cliente ja vinculado ao lead (nao busca nem cria de novo)."""
    orcamento_id: int | None
    """Orcamento ja vinculado ao lead (edita em vez de criar outro)."""
    orcamento: DadosOrcamento | None = None


@dataclass(frozen=True, slots=True)
class RegistroErp:
    cliente_id: int
    orcamento_id: int | None
    avisos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VinculoErp:
    """Ids do lead no ERP (`leads.erp_cliente_id`, `leads.erp_orcamento_id`)."""

    cliente_id: int | None = None
    orcamento_id: int | None = None


class FalhaPedidoErp(Exception):
    """O ERP nao concluiu o pedido. `cliente_id` = cliente que chegou a existir antes da falha."""

    def __init__(self, mensagem: str, *, cliente_id: int | None = None) -> None:
        super().__init__(mensagem)
        self.cliente_id = cliente_id


class PedidoPort(Protocol):
    async def registrar_handoff(self, conexao: ConexaoErp, dados: DadosHandoff) -> RegistroErp:
        """Acha ou cria o cliente e cria (ou edita, com `orcamento_id`) o orcamento.

        Levanta `FalhaPedidoErp`; nunca recalcula valores.
        """
        ...


class VinculosErpLead(Protocol):
    async def obter(self, loja_id: UUID, lead_id: UUID) -> VinculoErp: ...

    async def gravar(
        self,
        loja_id: UUID,
        lead_id: UUID,
        *,
        cliente_id: int | None = None,
        orcamento_id: int | None = None,
    ) -> None:
        """Grava so o que vier diferente de None. Lead de outra loja: nada."""
        ...


# --- montagem (pura) ----------------------------------------------------------------------------

_ROTULO_CANAL = {Canal.WHATSAPP: "WhatsApp", Canal.WEBCHAT: "Webchat", Canal.INSTAGRAM: "Instagram"}


def _digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _dec(valor: object) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return None


def nome_do_cliente(nome: str | None, canal: Canal, telefone: str) -> str:
    if nome and nome.strip():
        return nome.strip()
    ultimos = _digitos(telefone)[-4:]
    return " ".join(p for p in ("Cliente", _ROTULO_CANAL.get(canal, canal.value), ultimos) if p)


def _telefone_do_erp(canal: Canal, telefone: str) -> str | None:
    digitos = _digitos(telefone)
    return digitos if canal is Canal.WHATSAPP and digitos else None


def _pagamentos(
    estado: EstadoAtendimento, proposta: Mapping[str, Any]
) -> tuple[PagamentoPedido, ...]:
    forma: Mapping[str, Any] = proposta.get("forma_escolhida") or {}
    tipo = estado.ficha.pagamento.tipo
    if tipo is None:  # ficha sem tipo (nao deveria ocorrer): deduz pelo formato da proposta
        if "valor_a_vista" in forma:
            tipo = TipoPagamento.PIX
        elif forma.get("entrada") is not None:
            tipo = TipoPagamento.ENTRADA_MAIS_CREDITO
        else:
            tipo = TipoPagamento.CREDITO
    pagamentos: list[PagamentoPedido] = []
    total = _dec(forma.get("total_pago"))
    parcelas = int(forma.get("parcelas") or 1)
    match tipo:
        case TipoPagamento.PIX:
            valor = _dec(forma.get("valor_a_vista"))
            if valor is not None:
                pagamentos.append(PagamentoPedido(FormaPedido.PIX, valor))
        case TipoPagamento.DEBITO:
            if total is not None:
                pagamentos.append(PagamentoPedido(FormaPedido.DEBITO, total))
        case TipoPagamento.CREDITO:
            if total is not None:
                pagamentos.append(PagamentoPedido(FormaPedido.CREDITO, total, parcelas))
        case TipoPagamento.ENTRADA_MAIS_CREDITO:
            entrada = _dec(forma.get("entrada")) or Decimal(0)
            if entrada > 0:
                pagamentos.append(PagamentoPedido(FormaPedido.PIX, entrada))
            if total is not None:
                pagamentos.append(PagamentoPedido(FormaPedido.CREDITO, total - entrada, parcelas))
    troca: Mapping[str, Any] = proposta.get("troca") or {}
    valor_troca = _dec(troca.get("valor")) if troca.get("status") == "avaliada" else None
    if valor_troca is not None and valor_troca > 0:
        pagamentos.append(PagamentoPedido(FormaPedido.APARELHO, valor_troca))
    return tuple(pagamentos)


def _observacao(resumo: ResumoHandoff) -> str:
    linhas = [f"Handoff da IA: {resumo.motivo}"]
    for rotulo, valor in (
        ("Aparelho", resumo.aparelho_desejado),
        ("Troca", resumo.troca),
        ("Proposta", resumo.proposta),
        ("Pagamento", resumo.forma_pagamento),
        ("Observações", resumo.observacoes),
    ):
        if valor:
            linhas.append(f"{rotulo}: {valor}")
    if resumo.pendencias:
        linhas.append("Pendências: " + ", ".join(resumo.pendencias))
    linhas.append(FRASE_PRE_AVALIACAO)
    return "\n".join(linhas)


def _orcamento(
    estado: EstadoAtendimento,
    resumo: ResumoHandoff,
    codigo_erp_vendedor: str | None,
    produtos: Mapping[str, int],
) -> DadosOrcamento | str:
    """Os dados do orcamento ou, se faltar algo, o motivo (texto para o aviso)."""
    proposta = estado.ultima_proposta
    if not proposta or not proposta.get("forma_escolhida"):
        return "orçamento não criado: nenhuma proposta foi apresentada ao cliente"
    if not codigo_erp_vendedor:
        return "orçamento não criado: o vendedor atribuído não tem código do ERP"
    try:
        vendedor_erp = int(codigo_erp_vendedor)
    except ValueError:
        return "orçamento não criado: o código do ERP do vendedor atribuído não é numérico"
    sku = (proposta.get("aparelho") or {}).get(
        "sku"
    ) or estado.ficha.interesse.sku_estoque_confirmado
    produto_id = produtos.get(sku) if sku else None
    if produto_id is None:
        return f"orçamento não criado: o SKU {sku} não tem produto do ERP (estoque sem sincronizar)"
    preco = _dec(proposta.get("preco_aparelho"))
    desconto = _dec((proposta.get("desconto") or {}).get("total")) or Decimal(0)
    pagamentos = _pagamentos(estado, proposta)
    if preco is None or not pagamentos:
        return "orçamento não criado: a proposta não trouxe os valores esperados"
    return DadosOrcamento(
        vendedor_id_erp=vendedor_erp,
        itens=(ItemPedido(produto_id, 1, preco, desconto),),
        pagamentos=pagamentos,
        observacao=_observacao(resumo),
        previsao=resumo.data_prevista,
    )


def montar_dados_pedido(
    *,
    nome: str | None,
    telefone: str,
    canal: Canal,
    estado: EstadoAtendimento,
    vinculo: VinculoErp,
    resumo: ResumoHandoff,
    codigo_erp_vendedor: str | None,
    produtos: Mapping[str, int],
) -> tuple[DadosHandoff, tuple[str, ...]]:
    """`(dados, avisos)`: `produtos` mapeia SKU do estoque local para o id do produto no ERP."""
    orcamento = _orcamento(estado, resumo, codigo_erp_vendedor, produtos)
    avisos = (orcamento,) if isinstance(orcamento, str) else ()
    dados = DadosHandoff(
        nome_cliente=nome_do_cliente(nome, canal, telefone),
        telefone=_telefone_do_erp(canal, telefone),
        cliente_id=vinculo.cliente_id,
        orcamento_id=vinculo.orcamento_id,
        orcamento=None if isinstance(orcamento, str) else orcamento,
    )
    return dados, avisos
