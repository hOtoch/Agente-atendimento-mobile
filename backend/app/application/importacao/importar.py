"""Caso de uso: importar planilha xlsx (troca, taxas+regras, estoque) com relatorio de validacao."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.application.config import validacao
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.modelos import ErroCampo, ErrosDeValidacao, LojaNaoEncontrada
from app.application.importacao.portas import LINHA, LeitorPlanilha

type TipoImportacao = Literal["troca", "taxas", "estoque"]
type ModoImportacao = Literal["validar", "aplicar"]

_CAMINHO_LINHA = re.compile(r"^(?P<lista>\w+)\[(?P<i>\d+)\](?:\.(?P<campo>\w+))?$")


@dataclass(frozen=True, slots=True)
class RelatorioImportacao:
    ok: bool
    erros: list[ErroCampo]
    resumo: dict[str, Any] = field(default_factory=dict)


Acao = Callable[[], Awaitable[None]]


async def _nada() -> None:
    return None


def _mapear_lista(
    erros: Sequence[ErroCampo], lista: str, origens: Sequence[dict[str, str]]
) -> list[ErroCampo]:
    """Troca `lista[i].campo` pela celula da planilha de onde veio a entrada i."""
    mapeados: list[ErroCampo] = []
    for erro in erros:
        m = _CAMINHO_LINHA.match(erro.caminho)
        if m is None or m["lista"] != lista or int(m["i"]) >= len(origens):
            mapeados.append(erro)
            continue
        origem = origens[int(m["i"])]
        celula = origem.get(m["campo"] or "") or origem.get(LINHA)
        mapeados.append(ErroCampo(celula, erro.mensagem) if celula else erro)
    return mapeados


def _mapear_campos(erros: Sequence[ErroCampo], origens: dict[str, str]) -> list[ErroCampo]:
    return [ErroCampo(origens.get(e.caminho) or e.caminho, e.mensagem) for e in erros]


def _erros_de(acao: Callable[[], object]) -> list[ErroCampo]:
    try:
        acao()
    except ErrosDeValidacao as exc:
        return list(exc.erros)
    return []


class ImportarPlanilha:
    """Valida (e, em `aplicar`, grava) uma planilha.

    `validar` nunca grava. `aplicar` valida tudo antes e so entao grava, chamando `commit` uma
    vez no final (uma transacao); se a gravacao falhar, chama `rollback` e propaga a excecao.
    """

    def __init__(
        self,
        casos: CasosDeUsoConfig,
        leitor: LeitorPlanilha,
        *,
        commit: Acao | None = None,
        rollback: Acao | None = None,
    ) -> None:
        self._casos = casos
        self._leitor = leitor
        self._commit = commit or _nada
        self._rollback = rollback or _nada

    async def executar(
        self, loja_id: UUID, tipo: TipoImportacao, conteudo: bytes, modo: ModoImportacao
    ) -> RelatorioImportacao:
        if not await self._casos.lojas.existe(loja_id):
            raise LojaNaoEncontrada(loja_id)
        match tipo:
            case "troca":
                erros, resumo, gravar = self._troca(loja_id, conteudo)
            case "taxas":
                erros, resumo, gravar = self._taxas(loja_id, conteudo)
            case "estoque":
                erros, resumo, gravar = self._estoque(loja_id, conteudo)
        if erros:
            return RelatorioImportacao(False, erros, resumo)
        if modo == "aplicar":
            try:
                await gravar()
                await self._commit()
            except BaseException:
                await self._rollback()
                raise
        return RelatorioImportacao(True, [], resumo)

    # --- por tipo: (erros, resumo, gravar) ----------------------------------------------------

    def _troca(
        self, loja_id: UUID, conteudo: bytes
    ) -> tuple[list[ErroCampo], dict[str, Any], Acao]:
        leitura = self._leitor.ler_troca(conteudo)
        erros = list(leitura.erros)
        if not leitura.entradas and not erros:
            erros.append(ErroCampo("troca", "Nenhuma linha preenchida na tabela de troca."))
        entradas = leitura.entradas
        erros += _mapear_lista(
            _erros_de(lambda: validacao.montar_tabela_troca(entradas)),
            "tabela_troca",
            leitura.origens,
        )
        resumo: dict[str, Any] = {
            "linhas": len(entradas),
            "apple": sum(1 for e in entradas if e.marca == "Apple"),
            "outras_marcas": sum(1 for e in entradas if e.marca != "Apple"),
        }

        async def gravar() -> None:
            await self._casos.atualizar_troca(loja_id, entradas)

        return erros, resumo, gravar

    def _estoque(
        self, loja_id: UUID, conteudo: bytes
    ) -> tuple[list[ErroCampo], dict[str, Any], Acao]:
        leitura = self._leitor.ler_estoque(conteudo)
        erros = list(leitura.erros)
        if not leitura.entradas and not erros:
            erros.append(ErroCampo("estoque", "Nenhuma linha preenchida no estoque."))
        entradas = leitura.entradas
        erros += _mapear_lista(
            _erros_de(lambda: validacao.montar_estoque(entradas)), "estoque", leitura.origens
        )
        resumo: dict[str, Any] = {
            "linhas": len(entradas),
            "unidades": sum(e.quantidade for e in entradas),
        }

        async def gravar() -> None:
            await self._casos.atualizar_estoque(loja_id, entradas)

        return erros, resumo, gravar

    def _taxas(
        self, loja_id: UUID, conteudo: bytes
    ) -> tuple[list[ErroCampo], dict[str, Any], Acao]:
        taxas, regras = self._leitor.ler_taxas(conteudo)
        erros = [*regras.erros, *taxas.erros]
        if not taxas.entradas and not taxas.erros:
            erros.append(ErroCampo("taxas", "Nenhuma taxa preenchida."))
        entradas = taxas.entradas
        preco = regras.entrada
        if preco is not None:
            erros += _mapear_campos(
                _erros_de(lambda: validacao.montar_config_preco(preco)), regras.origens
            )
        erros += _mapear_lista(
            _erros_de(lambda: validacao.montar_taxas(entradas)), "taxas", taxas.origens
        )
        resumo: dict[str, Any] = {"taxas": len(entradas), "regras": preco is not None}

        async def gravar() -> None:
            assert preco is not None
            await self._casos.atualizar_preco(loja_id, preco)
            await self._casos.atualizar_taxas(loja_id, entradas)

        return erros, resumo, gravar
