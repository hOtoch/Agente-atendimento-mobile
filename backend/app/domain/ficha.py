"""Ficha de qualificacao (dados PARCIAIS coletados na conversa) e trava de preco.

A ficha guarda o que o cliente ja informou; todos os campos sao opcionais (`None` =
ainda nao informado). `pendencias` calcula, de forma deterministica, o que falta, e
`pode_passar_preco` so libera o preco quando nao falta nada. A conversao para os
tipos completos de avaliacao (troca, pagamento) e responsabilidade da camada de
aplicacao.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, Self

from app.domain.estoque import Condicao
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho


def _atualizar[T](objeto: T, campos: dict[str, Any]) -> T:
    """`dataclasses.replace` (TypeError para campo desconhecido ou nao inicializavel)."""
    return replace(objeto, **campos)  # type: ignore[type-var]


@dataclass(frozen=True, slots=True)
class InteresseInformado:
    """Aparelho desejado. `cor` e `condicao` (novo/seminovo) sao opcionais, sem pendencia."""

    modelo: ModeloAparelho | None = None
    capacidade: Capacidade | None = None
    cor: str | None = None
    sku_estoque_confirmado: str | None = None
    condicao: Condicao | None = None


@dataclass(frozen=True, slots=True)
class UsadoInformado:
    """Aparelho usado da troca. `outros_defeitos`: None = nao perguntado, () = nenhum.

    A avaliacao pergunta so modelo, capacidade, tela, traseira, carcaca e bateria. Camera,
    outros defeitos e peca trocada nao sao perguntados: so entram se o cliente contar.
    `avaliacao_na_loja`: o codigo viu que a tabela da loja nao da valor a esse modelo/capacidade;
    as perguntas de estado nao sao feitas (o valor sai na loja).
    """

    modelo: ModeloAparelho | None = None
    capacidade: Capacidade | None = None
    tela_danificada: bool | None = None
    traseira_danificada: bool | None = None
    carcaca_marcada: bool | None = None
    bateria_pct: int | None = None
    camera_ok: bool | None = None
    outros_defeitos: tuple[str, ...] | None = None
    peca_trocada: bool | None = None
    avaliacao_na_loja: bool = False


class TipoPagamento(StrEnum):
    PIX = "pix"
    DEBITO = "debito"
    CREDITO = "credito"
    ENTRADA_MAIS_CREDITO = "entrada_mais_credito"


@dataclass(frozen=True, slots=True)
class PagamentoInformado:
    """Forma de pagamento ainda em coleta."""

    tipo: TipoPagamento | None = None
    parcelas: int | None = None
    bandeira: Bandeira | None = None
    entrada: Dinheiro | None = None


class Pendencia(Enum):
    """Itens que faltam na ficha, na ordem natural de pergunta."""

    APARELHO_MODELO = 1
    APARELHO_CAPACIDADE = 2
    ESTOQUE_CONFIRMADO = 3
    TEM_TROCA = 4
    USADO_MODELO = 5
    USADO_CAPACIDADE = 6
    USADO_TELA = 7
    USADO_TRASEIRA = 8
    USADO_CARCACA = 9
    USADO_BATERIA = 10
    DATA_COMPRA = 14
    PAGAMENTO_TIPO = 15
    PAGAMENTO_PARCELAS = 16
    PAGAMENTO_BANDEIRA = 17
    PAGAMENTO_ENTRADA = 18


_P = Pendencia
_EXIGE_PARCELAS = {TipoPagamento.CREDITO, TipoPagamento.ENTRADA_MAIS_CREDITO}
_EXIGE_BANDEIRA = {
    TipoPagamento.DEBITO,
    TipoPagamento.CREDITO,
    TipoPagamento.ENTRADA_MAIS_CREDITO,
}


@dataclass(frozen=True, slots=True)
class Ficha:
    """Ficha imutavel. `tem_troca` None = ainda nao perguntado."""

    interesse: InteresseInformado = field(default_factory=InteresseInformado)
    tem_troca: bool | None = None
    usado: UsadoInformado = field(default_factory=UsadoInformado)
    data_prevista_compra: date | None = None
    pagamento: PagamentoInformado = field(default_factory=PagamentoInformado)

    @classmethod
    def vazia(cls) -> Self:
        return cls()

    # --- atualizacao parcial (nova ficha; None explicito apaga o campo) -----------

    def com_interesse(self, **campos: Any) -> Self:
        return replace(self, interesse=_atualizar(self.interesse, campos))

    def com_usado(self, **campos: Any) -> Self:
        return replace(self, usado=_atualizar(self.usado, campos))

    def com_pagamento(self, **campos: Any) -> Self:
        return replace(self, pagamento=_atualizar(self.pagamento, campos))

    def com(self, *, tem_troca: Any = ..., data_prevista_compra: Any = ...) -> Self:
        """Atualiza os campos escalares. Use `com_interesse/usado/pagamento` para os blocos."""
        campos: dict[str, Any] = {}
        if tem_troca is not ...:
            campos["tem_troca"] = tem_troca
        if data_prevista_compra is not ...:
            campos["data_prevista_compra"] = data_prevista_compra
        return replace(self, **campos)

    # --- serializacao (JSONB) -----------------------------------------------------

    def para_dict(self) -> dict[str, Any]:
        i, u, p = self.interesse, self.usado, self.pagamento
        return {
            "interesse": {
                "modelo": _modelo_para_dict(i.modelo),
                "capacidade": None if i.capacidade is None else int(i.capacidade),
                "cor": i.cor,
                "sku_estoque_confirmado": i.sku_estoque_confirmado,
                "condicao": None if i.condicao is None else i.condicao.value,
            },
            "tem_troca": self.tem_troca,
            "usado": {
                "modelo": _modelo_para_dict(u.modelo),
                "capacidade": None if u.capacidade is None else int(u.capacidade),
                "tela_danificada": u.tela_danificada,
                "traseira_danificada": u.traseira_danificada,
                "carcaca_marcada": u.carcaca_marcada,
                "bateria_pct": u.bateria_pct,
                "camera_ok": u.camera_ok,
                "outros_defeitos": None if u.outros_defeitos is None else list(u.outros_defeitos),
                "peca_trocada": u.peca_trocada,
                "avaliacao_na_loja": u.avaliacao_na_loja,
            },
            "data_prevista_compra": (
                None if self.data_prevista_compra is None else self.data_prevista_compra.isoformat()
            ),
            "pagamento": {
                "tipo": None if p.tipo is None else p.tipo.value,
                "parcelas": p.parcelas,
                "bandeira": None if p.bandeira is None else p.bandeira.value,
                "entrada": None if p.entrada is None else str(p.entrada.valor),
            },
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> Self:
        """Inverso de `para_dict`. Chaves ausentes viram campos nao informados."""
        i = dados.get("interesse") or {}
        u = dados.get("usado") or {}
        p = dados.get("pagamento") or {}
        defeitos = u.get("outros_defeitos")
        data = dados.get("data_prevista_compra")
        return cls(
            interesse=InteresseInformado(
                modelo=_modelo_de_dict(i.get("modelo")),
                capacidade=_capacidade(i.get("capacidade")),
                cor=i.get("cor"),
                sku_estoque_confirmado=i.get("sku_estoque_confirmado"),
                condicao=None if i.get("condicao") is None else Condicao(i["condicao"]),
            ),
            tem_troca=dados.get("tem_troca"),
            usado=UsadoInformado(
                modelo=_modelo_de_dict(u.get("modelo")),
                capacidade=_capacidade(u.get("capacidade")),
                tela_danificada=u.get("tela_danificada"),
                traseira_danificada=u.get("traseira_danificada"),
                carcaca_marcada=u.get("carcaca_marcada"),
                bateria_pct=u.get("bateria_pct"),
                camera_ok=u.get("camera_ok"),
                outros_defeitos=None if defeitos is None else tuple(defeitos),
                peca_trocada=u.get("peca_trocada"),
                avaliacao_na_loja=bool(u.get("avaliacao_na_loja", False)),
            ),
            data_prevista_compra=None if data is None else date.fromisoformat(data),
            pagamento=PagamentoInformado(
                tipo=None if p.get("tipo") is None else TipoPagamento(p["tipo"]),
                parcelas=p.get("parcelas"),
                bandeira=None if p.get("bandeira") is None else Bandeira(p["bandeira"]),
                entrada=None if p.get("entrada") is None else Dinheiro(Decimal(p["entrada"])),
            ),
        )


def _modelo_para_dict(modelo: ModeloAparelho | None) -> dict[str, Any] | None:
    if modelo is None:
        return None
    return {"marca": modelo.marca, "nome": modelo.nome, "conhecido": modelo.conhecido}


def _modelo_de_dict(dados: dict[str, Any] | None) -> ModeloAparelho | None:
    if dados is None:
        return None
    if "conhecido" in dados:
        return ModeloAparelho(dados["marca"], dados["nome"], dados["conhecido"])
    return ModeloAparelho.de(dados["nome"], dados["marca"])


def _capacidade(valor: int | None) -> Capacidade | None:
    return None if valor is None else Capacidade(valor)


def _faltas_usado(u: UsadoInformado) -> list[Pendencia]:
    if u.avaliacao_na_loja and u.modelo is not None:
        return []
    checagens = (
        (u.modelo, _P.USADO_MODELO),
        (u.capacidade, _P.USADO_CAPACIDADE),
        (u.tela_danificada, _P.USADO_TELA),
        (u.traseira_danificada, _P.USADO_TRASEIRA),
        (u.carcaca_marcada, _P.USADO_CARCACA),
        (u.bateria_pct, _P.USADO_BATERIA),
    )
    return [pend for valor, pend in checagens if valor is None]


def _faltas_pagamento(p: PagamentoInformado) -> list[Pendencia]:
    if p.tipo is None:
        return [_P.PAGAMENTO_TIPO]
    faltas: list[Pendencia] = []
    if p.tipo in _EXIGE_PARCELAS and p.parcelas is None:
        faltas.append(_P.PAGAMENTO_PARCELAS)
    if p.tipo in _EXIGE_BANDEIRA and p.bandeira is None:
        faltas.append(_P.PAGAMENTO_BANDEIRA)
    if p.tipo is TipoPagamento.ENTRADA_MAIS_CREDITO and p.entrada is None:
        faltas.append(_P.PAGAMENTO_ENTRADA)
    return faltas


def pendencias(ficha: Ficha) -> list[Pendencia]:
    """O que ainda falta para liberar o preco, na ordem natural de pergunta."""
    i = ficha.interesse
    faltas: list[Pendencia] = []
    if i.modelo is None:
        faltas.append(_P.APARELHO_MODELO)
    if i.capacidade is None:
        faltas.append(_P.APARELHO_CAPACIDADE)
    if i.sku_estoque_confirmado is None:
        faltas.append(_P.ESTOQUE_CONFIRMADO)
    if ficha.tem_troca is None:
        faltas.append(_P.TEM_TROCA)
    elif ficha.tem_troca:
        faltas.extend(_faltas_usado(ficha.usado))
    if ficha.data_prevista_compra is None:
        faltas.append(_P.DATA_COMPRA)
    faltas.extend(_faltas_pagamento(ficha.pagamento))
    return faltas


def pode_passar_preco(ficha: Ficha) -> bool:
    """Trava de preco: True somente sem nenhuma pendencia."""
    return not pendencias(ficha)
