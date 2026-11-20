"""Adaptador do ERP simulado: traduz o modelo do ERP para o dominio via mapeamento de SKU."""

from __future__ import annotations

from decimal import InvalidOperation
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from app.application.estoque import CapacidadesEstoque, EstoqueIndisponivel, FonteMapeamentoSku
from app.domain.estoque import Condicao, ItemEstoque, MapeamentoSku, filtrar
from app.domain.parser_sku import Confianca, extrair_bateria, interpretar_descricao
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

_TAMANHO_PAGINA = 100
_MAX_PAGINAS = 1000


class ErpCredencialInvalida(EstoqueIndisponivel):
    """O ERP recusou o token (401): erro de configuracao, retry nao resolve."""


class ErpSimuladoAdapter:
    """Implementa `EstoquePort` sobre a API HTTP do ERP simulado."""

    capacidades = CapacidadesEstoque(suporta_reserva=False, suporta_webhook=False)

    def __init__(
        self,
        cliente: httpx.AsyncClient,
        base_url: str,
        token: str,
        mapeamentos: FonteMapeamentoSku,
        timeout_s: float = 3.0,
    ) -> None:
        self._cliente = cliente
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._mapeamentos = mapeamentos
        self._timeout_s = timeout_s
        self._nao_mapeados: dict[UUID, set[str]] = {}

    def skus_nao_mapeados(self, loja_id: UUID) -> list[str]:
        """SKUs do ERP ignorados por falta de mapeamento (alimenta o checklist do onboarding)."""
        return sorted(self._nao_mapeados.get(loja_id, set()))

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        mapa = await self._mapeamentos.listar(loja_id)
        itens: list[ItemEstoque] = []
        ignorados: set[str] = set()
        for bruto in await self._listar_todos():
            item = self._converter(bruto, mapa)
            if item is None:
                ignorados.add(str(bruto.get("sku")))
            else:
                itens.append(item)
        self._nao_mapeados[loja_id] = ignorados
        return filtrar(itens, modelo, capacidade, cor)

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        resposta = await self._get(f"/produtos/{quote(sku, safe='')}", permitir_404=True)
        if resposta is None:
            return None
        bruto = self._json(resposta)
        item = self._converter(bruto, await self._mapeamentos.listar(loja_id))
        if item is None:
            self._nao_mapeados.setdefault(loja_id, set()).add(sku)
        return item

    async def _listar_todos(self) -> list[dict[str, Any]]:
        todos: list[dict[str, Any]] = []
        for pagina in range(1, _MAX_PAGINAS + 1):
            resposta = await self._get("/produtos", {"pagina": pagina, "tamanho": _TAMANHO_PAGINA})
            corpo = self._json(resposta)
            try:
                todos.extend(corpo["itens"])
                total_paginas = int(corpo["total_paginas"])
            except (KeyError, TypeError, ValueError) as exc:
                raise EstoqueIndisponivel(f"resposta inesperada do ERP: {exc!r}") from exc
            if pagina >= total_paginas:
                break
        return todos

    async def _get(
        self, caminho: str, params: dict[str, int] | None = None, permitir_404: bool = False
    ) -> httpx.Response | None:
        try:
            resposta = await self._cliente.get(
                f"{self._base_url}{caminho}",
                params=params,
                headers=self._headers,
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:  # timeout, rede, protocolo
            raise EstoqueIndisponivel(f"ERP inacessivel: {exc!r}") from exc
        if resposta.status_code == 401:
            raise ErpCredencialInvalida("ERP recusou o token (401)")
        if resposta.status_code == 404 and permitir_404:
            return None
        if resposta.status_code != 200:
            raise EstoqueIndisponivel(f"ERP respondeu {resposta.status_code}")
        return resposta

    @staticmethod
    def _json(resposta: httpx.Response | None) -> dict[str, Any]:
        try:
            corpo = resposta.json() if resposta is not None else None
        except ValueError as exc:
            raise EstoqueIndisponivel("ERP devolveu corpo que nao e JSON") from exc
        if not isinstance(corpo, dict):
            raise EstoqueIndisponivel("ERP devolveu JSON inesperado")
        return corpo

    @staticmethod
    def _converter(bruto: dict[str, Any], mapa: dict[str, MapeamentoSku]) -> ItemEstoque | None:
        try:
            sku = str(bruto["sku"])
            descricao = str(bruto.get("descricao", ""))
            preco = Dinheiro.de(str(bruto["preco"]))
            quantidade = max(0, int(bruto["estoque"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise EstoqueIndisponivel(f"item do ERP malformado: {exc!r}") from exc

        mapeamento = mapa.get(sku)
        if mapeamento is not None:
            modelo, capacidade = mapeamento.modelo, mapeamento.capacidade
            cor, condicao = mapeamento.cor, mapeamento.condicao
            bateria = extrair_bateria(descricao)
        else:
            sugestao = interpretar_descricao(descricao)
            if (
                sugestao is None
                or sugestao.confianca is not Confianca.ALTA
                or sugestao.capacidade is None
            ):
                return None
            modelo, capacidade = sugestao.modelo, sugestao.capacidade
            cor, condicao, bateria = sugestao.cor, sugestao.condicao, sugestao.bateria_pct

        return ItemEstoque(
            sku=sku,
            modelo=modelo,
            capacidade=capacidade,
            cor=cor,
            condicao=condicao,
            preco_pix=preco,
            quantidade=quantidade,
            bateria_pct=bateria if condicao is Condicao.SEMINOVO else None,
        )
