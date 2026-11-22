"""`ConferenciaItemErp` sobre o Mercado Phone: confere UM SKU ao vivo (1 chamada, sem marcas).

`list_inventory(sku=..., system_unit_id=..., limit=...)` faz busca PARCIAL por SKU e, por padrao,
so devolve itens com quantidade > 0: o resultado e filtrado pelo SKU EXATO e nenhum item exato
significa vendido. A marca (`marcaId -> nome`) vem da linha local, entao nao ha `list_brands` por
conferencia. Sem conexao ativa ou sem chave no servidor, nada e conferido (nem chama a rede).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from app.adapters.outbound.mercadophone.cliente import (
    LIMITE_MAXIMO_PAGINA,
    ClienteMercadoPhone,
    ErroMercadoPhone,
)
from app.adapters.outbound.mercadophone.fonte import ARG_UNIDADE
from app.adapters.outbound.mercadophone.mapear import LinhaErp, mapear_item
from app.application.config.portas import RepositorioConexaoErp
from app.application.estoque_ao_vivo import ConferenciaAoVivo
from app.domain.estoque import ItemEstoque

_PREFIXO_SKU_SINTETICO: Final = "MP-"
"""`mapear_item` inventa `MP-<id>` quando o item do ERP nao tem SKU: nao da para filtrar por ele."""


class ConferenciaItemMercadoPhone:
    def __init__(
        self,
        conexoes: RepositorioConexaoErp,
        cliente: Callable[[], ClienteMercadoPhone | None],
    ) -> None:
        self._conexoes = conexoes
        self._cliente = cliente

    async def conferir(self, loja_id: UUID, item: ItemEstoque) -> ConferenciaAoVivo:
        conexao = await self._conexoes.obter(loja_id)
        if conexao is None or not conexao.ativo:
            return ConferenciaAoVivo.nao_conferido()
        cliente = self._cliente()
        if cliente is None:
            return ConferenciaAoVivo.nao_conferido()

        resposta = await cliente.chamar(
            "list_inventory",
            {ARG_UNIDADE: conexao.system_unit_id, "sku": item.sku, "limit": LIMITE_MAXIMO_PAGINA},
        )
        itens = resposta.get("items")
        if not isinstance(itens, list):
            raise ErroMercadoPhone("list_inventory: resposta sem 'items'")
        exato = next((i for i in itens if _sku_do_item(i) == item.sku), None)
        if exato is None:
            if item.sku.startswith(_PREFIXO_SKU_SINTETICO):
                return ConferenciaAoVivo.nao_conferido()
            return ConferenciaAoVivo.indisponivel()

        resultado = mapear_item(exato, _marcas_da_linha_local(exato, item), conexao.filtro_loja)
        if isinstance(resultado, LinhaErp):
            return ConferenciaAoVivo.disponivel(
                replace(resultado.linha, erp_produto_id=resultado.erp_produto_id)
            )
        return (
            ConferenciaAoVivo.indisponivel()
        )  # descartado (sem preco, reservado...) ou outra loja


def _sku_do_item(bruto: Any) -> str | None:
    if not isinstance(bruto, Mapping):
        return None
    sku = bruto.get("sku")
    return " ".join(sku.split()) if isinstance(sku, str) else None


def _marcas_da_linha_local(bruto: Mapping[str, Any], item: ItemEstoque) -> dict[int, str]:
    marca_id = bruto.get("marcaId")
    if isinstance(marca_id, int) and not isinstance(marca_id, bool):
        return {marca_id: item.modelo.marca}
    return {}
