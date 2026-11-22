"""Gancho do handoff que exporta o lead para o ERP: cliente e orcamento do vendedor atribuido.

Roda DEPOIS da atribuicao do vendedor (precisa do `codigo_erp` dele), em sessoes proprias e
curtas: uma para ler (conexao, lead, vendedor, produto), a chamada ao ERP com a sessao FECHADA
(nunca ha HTTP segurando transacao) e outra para gravar os ids no lead e o evento do painel.

Nada aqui decide ou recalcula valor: os dados saem de `montar_dados_pedido` (que so reorganiza a
proposta calculada pelo dominio). Falha do ERP e sempre contida: vira `ResultadoExportacao`
com `ok=False`, log e o evento `erp_handoff` (o painel mostra o aviso); o handoff e o aviso ao
vendedor ja aconteceram e nada e desfeito.

Escrita num sistema de terceiro: so acontece com `ConexaoErp.exportar_handoff` ligado.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.application.config.portas import (
    RepositorioConexaoErp,
    RepositorioEstoqueLocal,
    RepositorioVendedores,
)
from app.application.handoff import ResumoHandoff
from app.application.painel.portas import RepositorioPainel
from app.application.pedido_erp import (
    DadosHandoff,
    FalhaPedidoErp,
    PedidoPort,
    VinculoErp,
    VinculosErpLead,
    montar_dados_pedido,
)
from app.domain.conexao_erp import ConexaoErp

log = logging.getLogger(__name__)

EVENTO_ERP_HANDOFF = "erp_handoff"


@dataclass(frozen=True, slots=True)
class ServicosDaExportacao:
    """O que uma transacao da exportacao precisa, todos sobre a MESMA sessao."""

    conexoes: RepositorioConexaoErp
    repo: RepositorioPainel
    vendedores: RepositorioVendedores
    estoque: RepositorioEstoqueLocal
    vinculos: VinculosErpLead


AbrirExportacao = Callable[[], AbstractAsyncContextManager[ServicosDaExportacao]]
"""Abre uma transacao: commita ao sair com sucesso, faz rollback se levantar excecao."""


@dataclass(frozen=True, slots=True)
class ResultadoExportacao:
    ok: bool
    cliente_id: int | None
    orcamento_id: int | None
    avisos: tuple[str, ...] = ()
    erro: str | None = None
    orcamento_editado: bool = False

    def para_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cliente_id": self.cliente_id,
            "orcamento_id": self.orcamento_id,
            "orcamento_editado": self.orcamento_editado,
            "avisos": list(self.avisos),
            "erro": self.erro,
        }


class ExportarHandoffParaErp:
    """Implementa `AoSolicitarHandoff`."""

    def __init__(self, *, abrir: AbrirExportacao, pedido: PedidoPort) -> None:
        self._abrir = abrir
        self._pedido = pedido

    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        try:
            await self.exportar(loja_id, lead_id, resumo)
        except Exception:
            log.exception("exportacao do handoff do lead %s para o ERP falhou", lead_id)

    async def exportar(
        self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff
    ) -> ResultadoExportacao | None:
        """None quando nao ha o que fazer (exportacao desligada, sem conexao ou lead sumido)."""
        async with self._abrir() as s:
            conexao = await s.conexoes.obter(loja_id)
            if conexao is None or not conexao.exportar_handoff:
                return None
            lead = await s.repo.obter_lead(loja_id, lead_id)
            if lead is None:
                log.warning("exportacao do handoff: lead %s nao encontrado na loja", lead_id)
                return None
            vinculo = await s.vinculos.obter(loja_id, lead_id)
            vendedores = await s.vendedores.listar(loja_id)
            codigo = next((v.codigo_erp for v in vendedores if v.id == lead.vendedor_id), None)
            produtos = {
                x.sku: x.erp_produto_id
                for x in await s.estoque.listar(loja_id)
                if x.erp_produto_id is not None
            }
        # sessao fechada: daqui em diante pode haver rede
        dados, avisos = montar_dados_pedido(
            nome=lead.nome,
            telefone=lead.telefone,
            canal=lead.canal,
            estado=lead.estado,
            vinculo=vinculo,
            resumo=resumo,
            codigo_erp_vendedor=codigo,
            produtos=produtos,
        )
        resultado = await self._chamar_erp(conexao, dados, avisos, vinculo)
        try:
            await self._gravar(loja_id, lead_id, resultado)
        except Exception:
            log.exception("exportacao do lead %s: nao gravou o resultado", lead_id)
        _logar(lead_id, resultado)
        return resultado

    async def _chamar_erp(
        self, conexao: ConexaoErp, dados: DadosHandoff, avisos: tuple[str, ...], vinculo: VinculoErp
    ) -> ResultadoExportacao:
        editando = dados.orcamento is not None and dados.orcamento_id is not None
        try:
            registro = await self._pedido.registrar_handoff(conexao, dados)
        except FalhaPedidoErp as falha:
            return ResultadoExportacao(
                False,
                falha.cliente_id or vinculo.cliente_id,
                vinculo.orcamento_id,
                avisos,
                str(falha),
            )
        except Exception as exc:
            return ResultadoExportacao(
                False,
                vinculo.cliente_id,
                vinculo.orcamento_id,
                avisos,
                f"erro inesperado na exportação: {type(exc).__name__}: {exc}",
            )
        return ResultadoExportacao(
            True,
            registro.cliente_id,
            registro.orcamento_id,
            (*avisos, *registro.avisos),
            orcamento_editado=editando and registro.orcamento_id is not None,
        )

    async def _gravar(self, loja_id: UUID, lead_id: UUID, r: ResultadoExportacao) -> None:
        async with self._abrir() as s:
            await s.vinculos.gravar(
                loja_id, lead_id, cliente_id=r.cliente_id, orcamento_id=r.orcamento_id
            )
            await s.repo.registrar_evento(loja_id, lead_id, EVENTO_ERP_HANDOFF, r.para_dict())


def _logar(lead_id: UUID, r: ResultadoExportacao) -> None:
    if r.ok:
        log.info(
            "handoff do lead %s exportado ao ERP: cliente=%s orcamento=%s%s avisos=%s",
            lead_id,
            r.cliente_id,
            r.orcamento_id,
            " (editado)" if r.orcamento_editado else "",
            list(r.avisos),
        )
    else:
        log.warning("handoff do lead %s NAO exportado ao ERP: %s", lead_id, r.erro)
