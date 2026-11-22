"""`FonteEstoqueErp` sobre o Mercado Phone: pagina `list_inventory` e mapeia por loja.

Uma leitura = marcas (uma vez) + todas as paginas do inventario da unidade. Se qualquer pagina
falhar, a excecao sobe e nada parcial e devolvido (o caso de uso mantem o estoque anterior).
O argumento que escolhe a unidade nas ferramentas do MCP e `store_id` (a "loja" do MCP e a
`system_unit_id` da conexao); `list_brands` e pedido sem ele e, se o servidor exigir a loja
(`store_selection_required`), repetido com ele.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from app.adapters.outbound.mercadophone.cliente import (
    ClienteMercadoPhone,
    MercadoPhoneUsoIndevido,
)
from app.adapters.outbound.mercadophone.mapear import mapa_de_marcas, mapear_inventario
from app.application.estoque_erp import LeituraErp, LeituraUnidade
from app.domain.conexao_erp import ConexaoErp

ARG_UNIDADE: Final = "store_id"
_CHAVES_ID_DA_UNIDADE: Final = ("system_unit_id", "systemUnitId", "unit_id", "store_id", "id")
_LOJA_OBRIGATORIA: Final = "store_selection_required"


@dataclass(frozen=True, slots=True)
class InventarioMercadoPhone:
    """Itens crus de uma unidade + marcas; mapeia (puro, sem rede) para cada filtro de loja."""

    itens: tuple[Mapping[str, Any], ...]
    marcas: Mapping[int, str]

    def para_loja(self, filtro_loja: str | None) -> LeituraErp:
        resultado = mapear_inventario(self.itens, self.marcas, filtro_loja)
        relatorio = resultado.relatorio
        return LeituraErp(
            linhas=tuple(
                replace(x.linha, erp_produto_id=x.erp_produto_id) for x in resultado.linhas
            ),
            lidos=relatorio.lidos,
            outra_loja=relatorio.outra_loja,
            descartes=dict(relatorio.por_motivo),
        )


class FonteEstoqueMercadoPhone:
    def __init__(self, cliente: ClienteMercadoPhone) -> None:
        self._cliente = cliente

    async def ler_unidade(self, system_unit_id: int) -> LeituraUnidade:
        marcas = await self._marcas(system_unit_id)
        itens = await self._cliente.paginar("list_inventory", {ARG_UNIDADE: system_unit_id})
        return InventarioMercadoPhone(tuple(itens), marcas)

    async def ler(self, conexao: ConexaoErp) -> LeituraErp:
        unidade = await self.ler_unidade(conexao.system_unit_id)
        return unidade.para_loja(conexao.filtro_loja)

    async def unidade_existe(self, system_unit_id: int) -> bool:
        resposta = await self._cliente.chamar("list_my_stores", {})
        itens = resposta.get("items")
        if not isinstance(itens, list):
            return False
        return any(_id_da_unidade(i) == system_unit_id for i in itens)

    async def _marcas(self, system_unit_id: int) -> dict[int, str]:
        try:
            brutas = await self._cliente.paginar("list_brands", {})
        except MercadoPhoneUsoIndevido as exc:
            if exc.codigo != _LOJA_OBRIGATORIA:
                raise
            brutas = await self._cliente.paginar("list_brands", {ARG_UNIDADE: system_unit_id})
        return mapa_de_marcas(brutas)


def _id_da_unidade(item: Any) -> int | None:
    if isinstance(item, int) and not isinstance(item, bool):
        return item
    if not isinstance(item, dict):
        return None
    for chave in _CHAVES_ID_DA_UNIDADE:
        valor = item.get(chave)
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        if isinstance(valor, str) and valor.strip().isdigit():
            return int(valor)
    return None
