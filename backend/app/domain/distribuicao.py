"""Distribuicao de leads entre vendedores por porcentagem (algoritmo de deficit).

Funcoes puras, sem IO. O proximo lead vai para o elegivel com maior
`peso_alvo - participacao_atual`, onde:

- `peso_alvo` = peso do vendedor / soma dos pesos dos elegiveis (pesos nao precisam somar 100);
- `participacao_atual` = leads ja atribuidos ao vendedor / total atribuido entre os elegiveis.

Elegivel = ativo, disponivel e com peso > 0. Quem nao e elegivel nao recebe e a sua
contagem nao entra no total (a proporcao vale entre quem esta na roda).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Candidato:
    """Vendedor concorrendo ao proximo lead. `peso` em pontos percentuais (Decimal)."""

    id: UUID
    peso: Decimal
    ativo: bool = True
    disponivel: bool = True

    @property
    def elegivel(self) -> bool:
        return self.ativo and self.disponivel and self.peso > 0


class MotivoSemVendedor(StrEnum):
    SEM_CANDIDATOS = "sem_candidatos"
    NENHUM_ATIVO_DISPONIVEL = "nenhum_ativo_disponivel"
    PESOS_ZERADOS = "pesos_zerados"


@dataclass(frozen=True, slots=True)
class SemVendedorDisponivel:
    """Nenhum vendedor pode receber o lead agora."""

    motivo: MotivoSemVendedor


def escolher_vendedor(
    candidatos: Iterable[Candidato], atribuidos: Mapping[UUID, int]
) -> UUID | SemVendedorDisponivel:
    """Escolhe quem recebe o proximo lead.

    `atribuidos` e a contagem de leads ja atribuidos por vendedor na janela que a aplicacao
    definir (ausente = 0). Deterministico: o empate no deficit vai para o maior peso e, depois,
    para o menor id; a ordem dos candidatos nao influencia.
    """
    lista = list(candidatos)
    if not lista:
        return SemVendedorDisponivel(MotivoSemVendedor.SEM_CANDIDATOS)
    com_vez = [c for c in lista if c.ativo and c.disponivel]
    if not com_vez:
        return SemVendedorDisponivel(MotivoSemVendedor.NENHUM_ATIVO_DISPONIVEL)
    elegiveis = [c for c in com_vez if c.peso > 0]
    if not elegiveis:
        return SemVendedorDisponivel(MotivoSemVendedor.PESOS_ZERADOS)

    soma_pesos = sum((c.peso for c in elegiveis), Decimal(0))
    total = sum(max(atribuidos.get(c.id, 0), 0) for c in elegiveis)

    def deficit_escalado(c: Candidato) -> Decimal:
        # peso/soma - n/total, multiplicado por soma*total (> 0) para comparar sem dividir:
        # exato, sem erro de arredondamento
        n = max(atribuidos.get(c.id, 0), 0)
        if total == 0:
            return c.peso
        return c.peso * total - Decimal(n) * soma_pesos

    escolhido = min(elegiveis, key=lambda c: (-deficit_escalado(c), -c.peso, c.id.int))
    return escolhido.id
