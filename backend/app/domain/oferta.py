"""Regra de oferta: quando um item de estoque vindo de um sistema externo pode ir ao agente.

Funcao pura, sem IO e sem conhecer nomes de campo de nenhum ERP: o adaptador traduz o item
cru para estes tipos primitivos e esta regra decide se ele e ofertavel.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Final

from app.domain.estoque import Condicao
from app.domain.valores import Capacidade, Dinheiro

PRECO_MINIMO_OFERTAVEL: Final = Dinheiro.de(Decimal("0.01"))
"""Preco que ja conta como 'sem preco': ERPs usam R$ 0,01 para 'ainda nao precificado'."""


class MotivoDescarte(StrEnum):
    """Por que um item nao pode ser ofertado (ordem = prioridade de avaliacao)."""

    ITEM_MALFORMADO = "item_malformado"
    NAO_E_CELULAR = "nao_e_celular"
    INDISPONIVEL = "indisponivel"
    SEM_QUANTIDADE = "sem_quantidade"
    SEM_MODELO = "sem_modelo"
    MARCA_NAO_IDENTIFICADA = "marca_nao_identificada"
    SEM_CAPACIDADE = "sem_capacidade"
    ESTADO_NAO_INFORMADO = "estado_nao_informado"
    SEM_PRECO = "sem_preco"
    SKU_DUPLICADO = "sku_duplicado"
    """O mesmo SKU apareceu mais de uma vez na leitura: vale o primeiro (nao e regra de oferta)."""


def motivo_nao_ofertavel(
    *,
    e_celular: bool,
    disponivel: bool,
    quantidade: int,
    modelo: str | None,
    marca: str | None,
    capacidade: Capacidade | None,
    condicao: Condicao | None,
    preco: Dinheiro | None,
) -> MotivoDescarte | None:
    """Primeiro motivo que impede a oferta do item, ou None se for ofertavel."""
    if not e_celular:
        return MotivoDescarte.NAO_E_CELULAR
    if not disponivel:
        return MotivoDescarte.INDISPONIVEL
    if quantidade <= 0:
        return MotivoDescarte.SEM_QUANTIDADE
    if modelo is None or not modelo.strip():
        return MotivoDescarte.SEM_MODELO
    if marca is None or not marca.strip():
        return MotivoDescarte.MARCA_NAO_IDENTIFICADA
    if capacidade is None:
        return MotivoDescarte.SEM_CAPACIDADE
    if condicao is None:
        return MotivoDescarte.ESTADO_NAO_INFORMADO
    if preco is None or preco <= PRECO_MINIMO_OFERTAVEL:
        return MotivoDescarte.SEM_PRECO
    return None
