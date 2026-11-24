"""Ambiente de teste das ferramentas: config da loja demo + estoque em memoria."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.adapters.outbound.estoque.memoria import FonteEstoqueEmMemoria
from app.adapters.outbound.estoque.planilha import PlanilhaAdapter
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.ferramentas import (
    CatalogoFerramentas,
    ContextoFerramentas,
    ResultadoFerramenta,
)
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.memoria import criar_casos_em_memoria
from app.application.estoque import CapacidadesEstoque, EstoqueIndisponivel
from app.domain.estoque import Condicao, ItemEstoque
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho
from app.infra.seed import aplicar_dados

HOJE = date(2026, 11, 20)


def item(
    sku: str,
    modelo: str,
    gb: int,
    cor: str,
    preco: int,
    qtd: int = 2,
    condicao: Condicao = Condicao.NOVO,
    bateria: int | None = None,
) -> ItemEstoque:
    return ItemEstoque(
        sku=sku,
        modelo=ModeloAparelho.de(modelo),
        capacidade=Capacidade(gb),
        cor=cor,
        condicao=condicao,
        preco_pix=Dinheiro(Decimal(preco)),
        quantidade=qtd,
        bateria_pct=bateria,
    )


ITENS_PADRAO = [
    item("IP16-128-PRETO", "iPhone 16", 128, "Preto", 4830),
    item("IP16-256-BRANCO", "iPhone 16", 256, "Branco", 5430),
    item("IP15-128-ROSA", "iPhone 15", 128, "Rosa", 4199),
    item("IP15-128-PRETO", "iPhone 15", 128, "Preto", 4199),
    item("IP13-128-AZUL", "iPhone 13", 128, "Azul", 2399, condicao=Condicao.SEMINOVO, bateria=88),
    item("IP14-256-ROXO", "iPhone 14", 256, "Roxo", 3399, qtd=0, condicao=Condicao.SEMINOVO),
    # seminovo disponivel SEM bateria cadastrada (o dado nao veio do estoque)
    item("IP12-128-PRETO", "iPhone 12", 128, "Preto", 1999, qtd=1, condicao=Condicao.SEMINOVO),
]


# iPhone 16 com varias capacidades/cores/condicoes; o 512GB vem primeiro de proposito (a ordem do
# estoque nao pode ditar a ordem das capacidades) e o 256GB Azul esta esgotado.
ITENS_16_VARIOS = [
    item("IP16-512-PRETO", "iPhone 16", 512, "Preto", 7230, qtd=3),
    item("IP16-128-PRETO", "iPhone 16", 128, "Preto", 4830, qtd=2),
    item("IP16-128-BRANCO", "iPhone 16", 128, "Branco", 4830, qtd=1),
    item(
        "IP16-128-PRETO-SEMI",
        "iPhone 16",
        128,
        "Preto",
        4130,
        qtd=1,
        condicao=Condicao.SEMINOVO,
        bateria=91,
    ),
    item("IP16-256-PRETO", "iPhone 16", 256, "Preto", 5430),
    item("IP16-256-AZUL", "iPhone 16", 256, "Azul", 5430, qtd=0),
    item("IP16-256-ROSA", "iPhone 16", 256, "Rosa", 5430),
]


class EstoqueFora:
    """Estoque que sempre falha (ERP fora do ar)."""

    capacidades = CapacidadesEstoque(suporta_reserva=False, suporta_webhook=False)

    async def buscar(self, *args: Any, **kwargs: Any) -> list[ItemEstoque]:
        raise EstoqueIndisponivel("fora do ar")

    async def obter(self, *args: Any, **kwargs: Any) -> ItemEstoque | None:
        raise EstoqueIndisponivel("fora do ar")


@dataclass
class Ambiente:
    loja_id: UUID
    lead_id: UUID
    casos: CasosDeUsoConfig
    catalogo: CatalogoFerramentas
    ctx: ContextoFerramentas

    async def rodar(
        self, nome: str, entrada: dict[str, Any], estado: EstadoAtendimento
    ) -> ResultadoFerramenta:
        return await self.catalogo.executar(nome, entrada, estado, self.ctx)

    async def seq(
        self, estado: EstadoAtendimento, *chamadas: tuple[str, dict[str, Any]]
    ) -> tuple[EstadoAtendimento, list[ResultadoFerramenta]]:
        """Executa as chamadas em ordem, encadeando o estado."""
        resultados = []
        for nome, entrada in chamadas:
            r = await self.rodar(nome, entrada, estado)
            estado = r.estado
            resultados.append(r)
        return estado, resultados


async def criar_ambiente(
    itens: list[ItemEstoque] | None = None, estoque: Any = None, hoje: date = HOJE
) -> Ambiente:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Loja Teste")
    await aplicar_dados(casos, loja_id)
    if estoque is None:
        fonte = FonteEstoqueEmMemoria({loja_id: list(ITENS_PADRAO if itens is None else itens)})
        estoque = PlanilhaAdapter(fonte)
    lead_id = uuid4()
    ctx = ContextoFerramentas(
        loja_id=loja_id, lead_id=lead_id, estoque=estoque, config=casos, hoje=hoje
    )
    return Ambiente(loja_id, lead_id, casos, CatalogoFerramentas(), ctx)


def sem_valores(conteudo: dict[str, Any]) -> None:
    """Afirma que o conteudo nao tem nenhum numero (preco, troca, parcela) nem 'R$'."""
    texto = json.dumps(conteudo, ensure_ascii=False)
    assert "R$" not in texto, texto
    assert not re.search(r"\d", texto), texto


# Entradas prontas -------------------------------------------------------------------------

INTERESSE_16 = {"modelo": "iPhone 16", "capacidade": "128GB", "cor": None}
USADO_EXEMPLO = {
    "tem_troca": True,
    "modelo": "iPhone 16",
    "capacidade": "128GB",
    "tela_danificada": True,
    "traseira_danificada": False,
    "carcaca_marcada": False,
    "bateria_pct": 79,
    "camera_ok": True,
    "outros_defeitos": [],
    "peca_trocada": False,
}
COMPRA_HOJE_12X = {
    "data_prevista": HOJE.isoformat(),
    "tipo_pagamento": "credito",
    "parcelas": 12,
    "bandeira": "Mastercard",
    "entrada": None,
}
