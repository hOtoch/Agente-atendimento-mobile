"""Conexao da loja com o ERP (Mercado Phone): a que unidade a loja aponta e como sincroniza.

A chave de acesso NAO faz parte do dominio: fica no ambiente do servidor (uma chave pode cobrir
varias unidades). O status da ultima sincronizacao e escrito pelo job de sincronizacao.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

PROVEDOR_MERCADOPHONE = "mercadophone"
INTERVALO_MIN_PADRAO = 15
INTERVALO_MIN_MINIMO = 5
INTERVALO_MIN_MAXIMO = 1440


class ConexaoErpInvalida(ValueError):
    """Conexao que o dominio nao aceita (`campo` = nome no painel/API)."""

    def __init__(self, campo: str, mensagem: str) -> None:
        super().__init__(f"{campo}: {mensagem}")
        self.campo = campo
        self.mensagem = mensagem


@dataclass(frozen=True, slots=True)
class ConexaoErp:
    loja_id: UUID
    system_unit_id: int
    """Unidade do Mercado Phone a que a loja aponta."""
    filtro_loja: str | None = None
    """Filtro de loja, quando duas lojas nossas dividem a mesma unidade."""
    ativo: bool = False
    intervalo_min: int = INTERVALO_MIN_PADRAO
    exportar_handoff: bool = False
    provedor: str = PROVEDOR_MERCADOPHONE
    ultima_sincronizacao_em: datetime | None = None
    ultimo_status: str | None = None
    ultimo_relatorio: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.provedor != PROVEDOR_MERCADOPHONE:
            raise ConexaoErpInvalida("provedor", f"provedor não suportado: {self.provedor}")
        if self.system_unit_id <= 0:
            raise ConexaoErpInvalida("system_unit_id", "deve ser maior que zero")
        if not INTERVALO_MIN_MINIMO <= self.intervalo_min <= INTERVALO_MIN_MAXIMO:
            raise ConexaoErpInvalida(
                "intervalo_min",
                f"deve estar entre {INTERVALO_MIN_MINIMO} e {INTERVALO_MIN_MAXIMO} minutos",
            )
        filtro = (self.filtro_loja or "").strip() or None
        object.__setattr__(self, "filtro_loja", filtro)
