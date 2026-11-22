"""Confirmacao ao vivo do item no ERP antes da proposta (decorator de `EstoquePort.obter`).

Entre duas sincronizacoes o aparelho pode ser vendido no balcao ou ter o preco mudado. Antes de
o agente confirmar o item ou calcular a proposta, `EstoqueConferidoAoVivo` pergunta ao ERP (porta
`ConferenciaItemErp`, 1 chamada com filtro de SKU) e corrige o estoque local:

- vendido/indisponivel/sem preco no ERP -> o item volta esgotado (quantidade 0) e a linha local
  sai do estoque, para a busca nao oferece-lo de novo;
- preco (ou quantidade) mudou -> vale o dado do ERP e a linha local e atualizada;
- ERP fora, lento (`timeout_s`), com erro ou credencial recusada -> segue com o dado local marcado
  `desatualizado`, sem travar a conversa; sem conexao ativa nada muda.

Ordem dos decorators: este fica POR FORA de `EstoqueResiliente`, senao o cache de 60 s da
resiliencia entregaria o item sem a conferencia. `buscar` nao muda (continua no local).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.application.config.modelos import LinhaEstoqueLocal
from app.application.config.portas import RepositorioEstoqueLocal
from app.application.estoque import CapacidadesEstoque, EstoqueIndisponivel, EstoquePort
from app.domain.estoque import Condicao, ItemEstoque
from app.domain.valores import Capacidade, ModeloAparelho

log = logging.getLogger(__name__)

TIMEOUT_PADRAO_S = 2.0

_ja_avisou: set[str] = set()


class SituacaoAoVivo(StrEnum):
    NAO_CONFERIDO = "nao_conferido"
    """Sem conexao ativa (ou sem chave no servidor): o dado local vale como esta."""
    DISPONIVEL = "disponivel"
    INDISPONIVEL = "indisponivel"


@dataclass(frozen=True, slots=True)
class ConferenciaAoVivo:
    situacao: SituacaoAoVivo
    linha: LinhaEstoqueLocal | None = None
    """Linha como o ERP a tem agora (so em `DISPONIVEL`)."""

    @classmethod
    def nao_conferido(cls) -> ConferenciaAoVivo:
        return cls(SituacaoAoVivo.NAO_CONFERIDO)

    @classmethod
    def indisponivel(cls) -> ConferenciaAoVivo:
        return cls(SituacaoAoVivo.INDISPONIVEL)

    @classmethod
    def disponivel(cls, linha: LinhaEstoqueLocal) -> ConferenciaAoVivo:
        return cls(SituacaoAoVivo.DISPONIVEL, linha)


class ConferenciaItemErp(Protocol):
    """Leitura ao vivo de UM item no ERP da loja."""

    async def conferir(self, loja_id: UUID, item: ItemEstoque) -> ConferenciaAoVivo:
        """Levanta `EstoqueIndisponivel` se o ERP falhar; `NAO_CONFERIDO` se nao ha integracao."""
        ...


def linha_de_item(item: ItemEstoque) -> LinhaEstoqueLocal:
    return LinhaEstoqueLocal(
        sku=item.sku,
        modelo=item.modelo,
        capacidade=item.capacidade,
        cor=item.cor or "",
        condicao=item.condicao,
        preco_pix=item.preco_pix,
        quantidade=item.quantidade,
        bateria_pct=item.bateria_pct,
    )


def _item_de_linha(linha: LinhaEstoqueLocal) -> ItemEstoque:
    modelo: ModeloAparelho = linha.modelo
    capacidade: Capacidade = linha.capacidade
    return ItemEstoque(
        sku=linha.sku,
        modelo=modelo,
        capacidade=capacidade,
        cor=linha.cor or None,
        condicao=linha.condicao,
        preco_pix=linha.preco_pix,
        quantidade=linha.quantidade,
        bateria_pct=linha.bateria_pct if linha.condicao is Condicao.SEMINOVO else None,
    )


def _mudou(local: ItemEstoque, ao_vivo: ItemEstoque) -> bool:
    return (
        local.preco_pix != ao_vivo.preco_pix
        or local.quantidade != ao_vivo.quantidade
        or local.cor != ao_vivo.cor
        or local.bateria_pct != ao_vivo.bateria_pct
    )


class EstoqueConferidoAoVivo:
    """Implementa `EstoquePort` conferindo o SKU no ERP em `obter`."""

    def __init__(
        self,
        base: EstoquePort,
        conferencia: ConferenciaItemErp,
        estoque_local: RepositorioEstoqueLocal,
        *,
        timeout_s: float = TIMEOUT_PADRAO_S,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._base = base
        self._conferencia = conferencia
        self._local = estoque_local
        self._timeout = timeout_s
        self._commit = commit

    @property
    def capacidades(self) -> CapacidadesEstoque:
        return self._base.capacidades

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        return await self._base.buscar(loja_id, modelo, capacidade, cor)

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        item = await self._base.obter(loja_id, sku)
        if item is None:
            return None
        try:
            conferencia = await asyncio.wait_for(
                self._conferencia.conferir(loja_id, item), self._timeout
            )
        except TimeoutError:
            log.warning(
                "confirmacao ao vivo do sku %s estourou %.1fs; usando o local", sku, self._timeout
            )
            return replace(item, desatualizado=True)
        except EstoqueIndisponivel as exc:
            self._registrar_falha(loja_id, sku, exc)
            return replace(item, desatualizado=True)
        except Exception:
            log.exception("erro inesperado na confirmacao ao vivo do sku %s; usando o local", sku)
            return replace(item, desatualizado=True)

        if conferencia.situacao is SituacaoAoVivo.INDISPONIVEL:
            await self._gravar(loja_id, sku, None)
            return replace(item, quantidade=0)
        if conferencia.situacao is SituacaoAoVivo.DISPONIVEL and conferencia.linha is not None:
            ao_vivo = _item_de_linha(conferencia.linha)
            if _mudou(item, ao_vivo):
                await self._gravar(loja_id, sku, conferencia.linha)
            return ao_vivo
        return item

    async def _gravar(self, loja_id: UUID, sku: str, linha: LinhaEstoqueLocal | None) -> None:
        await self._local.atualizar_linha(loja_id, sku, linha)
        if self._commit is not None:
            await self._commit()

    @staticmethod
    def _registrar_falha(loja_id: UUID, sku: str, exc: EstoqueIndisponivel) -> None:
        if exc.retentavel:
            log.info("ERP indisponivel ao confirmar o sku %s (%s); usando o local", sku, exc)
            return
        chave = f"{type(exc).__name__}:{getattr(exc, 'codigo', None)}"
        if chave not in _ja_avisou:
            _ja_avisou.add(chave)
            log.warning(
                "ERP recusou a confirmacao ao vivo (loja %s): %s. Usando o estoque local; "
                "confira a chave do Mercado Phone.",
                loja_id,
                exc,
            )
