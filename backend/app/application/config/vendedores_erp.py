"""Importacao dos vendedores do ERP (Mercado Phone) para a loja.

Regras (o codigo decide, nao o prompt):
- o vendedor do ERP e identificado por `codigo_erp`; ativos criam ou atualizam (so o nome);
- telefone e peso sao do painel: a importacao nunca mexe neles; vendedor novo entra com peso 0
  (fora da distribuicao ate definirem o peso; o checklist avisa);
- quem tem `codigo_erp` e sumiu do ERP (ou veio inativo) fica inativo, nunca e apagado;
- vendedor criado a mao (sem `codigo_erp`) nunca e desativado nem fundido por nome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.application.config.modelos import LojaNaoEncontrada
from app.application.config.portas import (
    RepositorioConexaoErp,
    RepositorioLojas,
    RepositorioVendedores,
)
from app.application.estoque import EstoqueIndisponivel


@dataclass(frozen=True, slots=True)
class VendedorErp:
    """Vendedor como o ERP o descreve, ja traduzido para o nosso vocabulario."""

    codigo_erp: str
    nome: str
    ativo: bool


class LeitorVendedoresErp(Protocol):
    """Porta: lista os vendedores de uma unidade do ERP (so leitura)."""

    async def listar(self, system_unit_id: int) -> list[VendedorErp]: ...


class ErroIntegracaoErp(Exception):
    """Falha da integracao com o ERP, com mensagem pronta para o painel (sem segredos)."""

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class LojaSemConexaoErp(ErroIntegracaoErp):
    def __init__(self) -> None:
        super().__init__("Loja sem conexão com o ERP.")


class ErpNaoConfigurado(ErroIntegracaoErp):
    """O servidor nao tem a chave do ERP (`MERCADOPHONE_API_KEY`)."""

    def __init__(self) -> None:
        super().__init__("Integração com o ERP não configurada no servidor.")


class ErpIndisponivel(ErroIntegracaoErp):
    """ERP fora, lento ou limitando as chamadas: vale tentar de novo daqui a pouco."""

    def __init__(self) -> None:
        super().__init__("ERP indisponível no momento. Tente novamente em instantes.")


class ErpCredencialInvalida(ErroIntegracaoErp):
    """O ERP recusou a chave ou a unidade: so a configuracao resolve."""

    def __init__(self) -> None:
        super().__init__("O ERP recusou o acesso. Confira a chave do servidor e a unidade da loja.")


class LeitorVendedoresErpNaoConfigurado:
    """Implementacao nula: sem chave no servidor, toda leitura falha com mensagem clara."""

    async def listar(self, system_unit_id: int) -> list[VendedorErp]:
        raise ErpNaoConfigurado


@dataclass(frozen=True, slots=True)
class ResumoImportacaoVendedores:
    criados: int
    atualizados: int
    desativados: int
    sem_alteracao: int


class ImportarVendedoresErp:
    def __init__(
        self,
        lojas: RepositorioLojas,
        conexoes: RepositorioConexaoErp,
        vendedores: RepositorioVendedores,
        leitor: LeitorVendedoresErp,
    ) -> None:
        self._lojas = lojas
        self._conexoes = conexoes
        self._vendedores = vendedores
        self._leitor = leitor

    async def executar(self, loja_id: UUID) -> ResumoImportacaoVendedores:
        if not await self._lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)
        conexao = await self._conexoes.obter(loja_id)
        if conexao is None:
            raise LojaSemConexaoErp
        try:
            do_erp = await self._leitor.listar(conexao.system_unit_id)
        except EstoqueIndisponivel as exc:
            raise _traduzir(exc) from None

        por_codigo: dict[str, VendedorErp] = {}
        for item in do_erp:
            por_codigo.setdefault(item.codigo_erp, item)
        locais = {v.codigo_erp: v for v in await self._vendedores.listar(loja_id) if v.codigo_erp}

        criados = atualizados = desativados = sem_alteracao = 0
        for codigo, item in por_codigo.items():
            local = locais.get(codigo)
            if local is None:
                if item.ativo:
                    await self._vendedores.criar_do_erp(loja_id, codigo, item.nome)
                    criados += 1
                continue
            if (local.nome, local.ativo) == (item.nome, item.ativo):
                sem_alteracao += 1
                continue
            await self._vendedores.atualizar_do_erp(
                loja_id, local.id, nome=item.nome, ativo=item.ativo
            )
            if local.ativo and not item.ativo:
                desativados += 1
            else:
                atualizados += 1
        for codigo, local in locais.items():
            if codigo not in por_codigo and local.ativo:
                await self._vendedores.atualizar_do_erp(
                    loja_id, local.id, nome=local.nome, ativo=False
                )
                desativados += 1
        return ResumoImportacaoVendedores(criados, atualizados, desativados, sem_alteracao)


def _traduzir(exc: EstoqueIndisponivel) -> ErroIntegracaoErp:
    # Mensagem fixa: o texto da excecao original nunca chega ao painel.
    if exc.retentavel:
        return ErpIndisponivel()
    return ErpCredencialInvalida()
