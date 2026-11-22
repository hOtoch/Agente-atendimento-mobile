"""Conexao da loja com o ERP: configuracao pelo painel (a chave nunca passa por aqui)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.config.modelos import ErroCampo, ErrosDeValidacao, LojaNaoEncontrada
from app.application.config.portas import RepositorioConexaoErp, RepositorioLojas
from app.domain.conexao_erp import INTERVALO_MIN_PADRAO, ConexaoErp, ConexaoErpInvalida


@dataclass(frozen=True, slots=True)
class EntradaConexaoErp:
    system_unit_id: int
    filtro_loja: str | None = None
    ativo: bool = False
    intervalo_min: int = INTERVALO_MIN_PADRAO
    exportar_handoff: bool = False


class ConfigurarConexaoErp:
    def __init__(self, lojas: RepositorioLojas, repo: RepositorioConexaoErp) -> None:
        self._lojas = lojas
        self._repo = repo

    async def obter(self, loja_id: UUID) -> ConexaoErp | None:
        """A conexao da loja, ou None se ela nunca configurou o ERP."""
        await self._loja(loja_id)
        return await self._repo.obter(loja_id)

    async def atualizar(self, loja_id: UUID, entrada: EntradaConexaoErp) -> ConexaoErp:
        await self._loja(loja_id)
        try:
            conexao = ConexaoErp(
                loja_id=loja_id,
                system_unit_id=entrada.system_unit_id,
                filtro_loja=entrada.filtro_loja,
                ativo=entrada.ativo,
                intervalo_min=entrada.intervalo_min,
                exportar_handoff=entrada.exportar_handoff,
            )
        except ConexaoErpInvalida as exc:
            raise ErrosDeValidacao([ErroCampo(exc.campo, exc.mensagem)]) from exc
        await self._repo.salvar(conexao)
        # o status da sincronizacao e de quem sincroniza: devolve o que ficou gravado
        salva = await self._repo.obter(loja_id)
        return salva if salva is not None else conexao

    async def _loja(self, loja_id: UUID) -> None:
        if not await self._lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)
