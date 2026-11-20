"""Vendedores ficticios da loja demo, com IDs fixos para o seed ser idempotente."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DadosVendedor:
    id: UUID
    nome: str
    telefone: str
    peso_percentual: Decimal
    ativo: bool = True


VENDEDORES: tuple[DadosVendedor, ...] = (
    DadosVendedor(
        UUID("00000000-0000-4000-8000-00000000de31"), "Ana Souza", "+55 11 90000-0001", Decimal(50)
    ),
    DadosVendedor(
        UUID("00000000-0000-4000-8000-00000000de32"), "Bruno Lima", "+55 11 90000-0002", Decimal(30)
    ),
    DadosVendedor(
        UUID("00000000-0000-4000-8000-00000000de33"), "Carla Dias", "+55 11 90000-0003", Decimal(20)
    ),
)
