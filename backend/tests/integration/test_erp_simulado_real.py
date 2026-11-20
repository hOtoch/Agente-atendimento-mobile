"""ErpSimuladoAdapter contra o ERP simulado REAL (localhost:8090). Pula se estiver fora.

Nao honra EXIGIR_INTEGRACAO: o ERP e um servico opcional de desenvolvimento.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest

from app.adapters.outbound.estoque.erp_simulado import ErpSimuladoAdapter
from app.adapters.outbound.estoque.memoria import FonteMapeamentoEmMemoria

pytestmark = [pytest.mark.integration, pytest.mark.erp]

URL = "http://localhost:8090"
LOJA = UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.fixture
async def adaptador() -> AsyncIterator[ErpSimuladoAdapter]:
    async with httpx.AsyncClient() as cliente:
        try:
            (await cliente.get(f"{URL}/health", timeout=1.0)).raise_for_status()
        except httpx.HTTPError as exc:
            pytest.skip(f"ERP simulado fora em {URL}: {exc!r}")
        yield ErpSimuladoAdapter(cliente, URL, "token-dev", FonteMapeamentoEmMemoria({}))


async def test_busca_e_obtem_no_erp_real(adaptador: ErpSimuladoAdapter) -> None:
    # sem mapeamento: tudo vem do parser heuristico (fallback de confianca alta)
    achados = await adaptador.buscar(LOJA, "iPhone 15 Pro")
    assert achados
    assert all(i.modelo.nome == "iPhone 15 Pro" and i.quantidade > 0 for i in achados)
    # os 3 acessorios do seed ficam de fora e sao registrados
    assert {"APL-000040", "APL-000041", "APL-000042"} <= set(adaptador.skus_nao_mapeados(LOJA))
    item = await adaptador.obter(LOJA, "APL-000014")
    assert item is not None
    assert item.cor == "Titânio Natural"
    assert await adaptador.obter(LOJA, "NAO-EXISTE") is None
