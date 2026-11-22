"""Agregados e tipos de aplicacao da configuracao da loja."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.chave_pix import ChavePix
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.estoque import Condicao
from app.domain.formas_pagamento import FormasAceitas
from app.domain.pagamento import RegrasPreco
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

CONDICOES: tuple[str, ...] = tuple(c.value for c in Condicao)


@dataclass(frozen=True, slots=True)
class ErroCampo:
    """Erro de validacao de um campo/celula. `caminho` ex.: `tabela_troca[3].desconto_tela`."""

    caminho: str
    mensagem: str


class ErrosDeValidacao(Exception):
    def __init__(self, erros: Sequence[ErroCampo]) -> None:
        super().__init__("; ".join(f"{e.caminho}: {e.mensagem}" for e in erros))
        self.erros: tuple[ErroCampo, ...] = tuple(erros)


class LojaNaoEncontrada(Exception):
    def __init__(self, loja_id: object) -> None:
        super().__init__(f"loja nao encontrada: {loja_id}")
        self.loja_id = loja_id


@dataclass(frozen=True, slots=True)
class PerfilLoja:
    nome_exibicao: str
    tom_de_voz: str
    endereco: str
    horarios: Mapping[str, str]
    whatsapp_contato: str
    responder_em_audio: bool = True
    """Responde tambem em audio quando o cliente mandou audio (o texto sai sempre)."""


@dataclass(frozen=True, slots=True)
class ConfigPreco:
    """Tudo o que o agente precisa para precificar: pagamento, desconto e oportunidade."""

    regras: RegrasPreco
    politica: PoliticaDesconto
    oportunidade: RegraOportunidadeUnica


@dataclass(frozen=True, slots=True)
class ConfigPagamento:
    """O que a loja grava sobre pagamento: Pix, debito e credito ligados e a chave Pix.

    Entrada + cartao nao esta aqui: vem de `RegrasPreco.aceita_entrada_mais_cartao`.
    """

    aceita_pix: bool = True
    aceita_debito: bool = True
    aceita_credito: bool = True
    chave_pix: ChavePix | None = None


@dataclass(frozen=True, slots=True)
class PagamentoLoja:
    """Visao completa de pagamento da loja: formas aceitas (com entrada + cartao) e chave Pix.

    E o que `CasosDeUsoConfig.obter_pagamento` devolve; a ferramenta que entrega a chave Pix ao
    cliente le `chave_pix` daqui (a chave nao entra no prompt de sistema).
    """

    formas: FormasAceitas
    chave_pix: ChavePix | None


@dataclass(frozen=True, slots=True)
class LinhaEstoqueLocal:
    sku: str
    modelo: ModeloAparelho
    capacidade: Capacidade
    cor: str
    condicao: Condicao
    preco_pix: Dinheiro
    quantidade: int
    bateria_pct: int | None
    erp_produto_id: int | None = None
    """Id do produto no ERP (so nas linhas sincronizadas; planilha e painel deixam vazio)."""


@dataclass(frozen=True, slots=True)
class LinhaMapeamentoSku:
    sku_externo: str
    modelo: ModeloAparelho
    capacidade: Capacidade
    cor: str
    condicao: Condicao


@dataclass(frozen=True, slots=True)
class ItemChecklist:
    chave: str
    rotulo_ptbr: str
    completo: bool
    detalhe: str


@dataclass(frozen=True, slots=True)
class VendedorLoja:
    id: UUID
    nome: str
    telefone: str | None
    peso_percentual: Decimal
    ativo: bool
    codigo_erp: str | None = None
    """Id do vendedor no ERP; None = criado a mao no painel."""
