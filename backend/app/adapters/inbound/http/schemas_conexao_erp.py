"""Schemas da API da conexao da loja com o ERP.

A chave de acesso do ERP NAO existe aqui (fica no .env do servidor): o corpo de entrada recusa
qualquer campo desconhecido, e o status da ultima sincronizacao e so de saida.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ConexaoErpEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_unit_id: int
    """Unidade do Mercado Phone a que a loja aponta (> 0)."""
    filtro_loja: str | None = None
    """Filtro de loja, quando duas lojas dividem a mesma unidade."""
    ativo: bool = False
    intervalo_min: int = 15
    """Intervalo da sincronizacao em minutos (5 a 1440)."""
    exportar_handoff: bool = False


class ConexaoErpSaida(BaseModel):
    configurada: bool
    """False quando a loja nunca configurou o ERP (os demais campos vem com os padroes)."""
    provedor: str
    system_unit_id: int | None
    filtro_loja: str | None
    ativo: bool
    intervalo_min: int
    exportar_handoff: bool
    ultima_sincronizacao_em: datetime | None
    ultimo_status: str | None
    ultimo_relatorio: dict[str, Any] | None
