"""Transcricoes fixture para testar as checagens (sem LLM, sem IO)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evals.modelos import (
    ExecucaoFerramenta,
    MensagemAgente,
    MensagemCliente,
    Parametros,
    Transcricao,
)

PARAMS = Parametros(teto=Decimal(100), oportunidade_max=Decimal(100))
FRASE = "É uma pré-avaliação, valor final confirmado na loja com o aparelho em mãos."


def cli(texto: str) -> MensagemCliente:
    return MensagemCliente(texto)


def ag(texto: str) -> MensagemAgente:
    return MensagemAgente(texto)


def ferr(
    nome: str, resultado: dict[str, Any], *, erro: bool = False, interno: bool = False
) -> ExecucaoFerramenta:
    return ExecucaoFerramenta(nome, {}, resultado, erro=erro, erro_interno=interno)


def proposta(
    negociado: str = "R$ 0,00", oportunidade: str | None = None, total: str = "R$ 0,00"
) -> dict[str, Any]:
    return {
        "bloqueado": False,
        "preco_aparelho": "R$ 4.830,00",
        "troca": {"status": "avaliada", "valor": "R$ 2.310,00"},
        "desconto": {"negociado": negociado, "oportunidade_unica": oportunidade, "total": total},
        "forma_escolhida": {"parcelas": 12, "valor_parcela": "R$ 250,00"},
    }


BLOQUEIO: dict[str, Any] = {"bloqueado": True, "pendencias": ["bateria"]}


def transcricao(
    *eventos: Any, etapa: str = "interesse_qualificado", handoff: bool = False
) -> Transcricao:
    return Transcricao(tuple(eventos), etapa_final=etapa, handoff=handoff)
