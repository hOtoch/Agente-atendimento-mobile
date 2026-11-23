"""Avaliação de troca do usado (context.md §3.1).

O código decide o valor; o LLM só conversa. Tudo aqui é puro (sem IO).

Ordem de precedência das checagens em `avaliar_troca` (a primeira que falhar vence):

1. peça já trocada                      -> PECA_TROCADA
2. câmera com defeito / outros defeitos -> OUTRO_DEFEITO
3. sem linha do modelo na tabela        -> OUTRA_MARCA (marca != Apple)
                                           ou MODELO_FORA_DA_TABELA (Apple)
4. capacidade menor que todas da tabela -> CAPACIDADE_ABAIXO_DA_TABELA
5. desconto SEM em problema relatado    -> SEM_VALOR_WHATSAPP
6. valor final <= 0                     -> VALOR_NAO_POSITIVO

Defeitos vêm antes da busca na tabela porque, com eles, a resposta é "avaliação na loja"
independentemente do modelo. SEM em problema que o cliente não tem é ignorado.

Câmera, outros defeitos e peça trocada não são perguntados ao cliente; só contam se ele contar
(o padrão é "sem esse problema"). Os itens 3 e 4 (`motivo_fora_da_tabela`) são checados já ao
registrar o modelo do usado, para não perguntar o estado de um aparelho que a tabela não avalia.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final

from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

_MARCA_APPLE: Final = "Apple"


class _Sem(enum.Enum):
    SEM = "SEM"

    def __repr__(self) -> str:
        return "SEM"


SEM: Final = _Sem.SEM
"""Sentinela: a loja não dá valor pelo WhatsApp para aquele problema."""

DescontoTroca = Dinheiro | _Sem


class MotivoLoja(enum.Enum):
    SEM_VALOR_WHATSAPP = "sem_valor_whatsapp"
    OUTRO_DEFEITO = "outro_defeito"
    PECA_TROCADA = "peca_trocada"
    OUTRA_MARCA = "outra_marca"
    MODELO_FORA_DA_TABELA = "modelo_fora_da_tabela"
    VALOR_NAO_POSITIVO = "valor_nao_positivo"
    CAPACIDADE_ABAIXO_DA_TABELA = "capacidade_abaixo_da_tabela"


@dataclass(frozen=True, slots=True)
class LinhaTroca:
    """Uma linha da tabela: modelo + capacidade."""

    modelo: ModeloAparelho
    capacidade: Capacidade
    valor_sem_detalhes: Dinheiro
    desconto_tela: DescontoTroca
    desconto_traseira: DescontoTroca
    desconto_carcaca: DescontoTroca
    desconto_bateria: DescontoTroca
    limite_bateria_pct: int


@dataclass(frozen=True, slots=True)
class TabelaTroca:
    """Linhas Apple e, opcionalmente, de outras marcas ("Outras marcas")."""

    linhas_apple: tuple[LinhaTroca, ...] = ()
    linhas_outras_marcas: tuple[LinhaTroca, ...] = ()

    def _linhas_do_modelo(self, modelo: ModeloAparelho) -> list[LinhaTroca]:
        pool = self.linhas_apple if modelo.marca == _MARCA_APPLE else self.linhas_outras_marcas
        return [
            linha
            for linha in pool
            if linha.modelo.marca == modelo.marca and linha.modelo.nome == modelo.nome
        ]

    def buscar(self, modelo: ModeloAparelho, capacidade: Capacidade) -> LinhaTroca | None:
        """Linha do modelo com a capacidade pedida ou a menor mais próxima (maior que seja <=).

        None se o modelo não tem linha ou se a capacidade é menor que todas as da tabela.
        """
        candidatas = [x for x in self._linhas_do_modelo(modelo) if x.capacidade <= capacidade]
        return max(candidatas, key=lambda x: x.capacidade, default=None)


@dataclass(frozen=True, slots=True)
class CondicaoUsado:
    """Estado completo do aparelho usado (só se avalia com todos os dados)."""

    tela_danificada: bool
    traseira_danificada: bool
    carcaca_marcada: bool
    bateria_pct: int
    camera_ok: bool = True
    outros_defeitos: tuple[str, ...] = ()
    peca_trocada: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.bateria_pct <= 100:
            raise ValueError(f"bateria_pct fora de 0-100: {self.bateria_pct}")


@dataclass(frozen=True, slots=True)
class ValorTroca:
    valor: Dinheiro
    descontos_aplicados: tuple[tuple[str, Dinheiro], ...]


@dataclass(frozen=True, slots=True)
class AvaliacaoNaLoja:
    motivo: MotivoLoja


def _problemas_relatados(
    linha: LinhaTroca, condicao: CondicaoUsado
) -> list[tuple[str, DescontoTroca]]:
    problemas: list[tuple[str, DescontoTroca]] = []
    if condicao.tela_danificada:
        problemas.append(("tela", linha.desconto_tela))
    if condicao.traseira_danificada:
        problemas.append(("traseira", linha.desconto_traseira))
    if condicao.carcaca_marcada:
        problemas.append(("carcaca", linha.desconto_carcaca))
    if condicao.bateria_pct < linha.limite_bateria_pct:
        problemas.append(("bateria", linha.desconto_bateria))
    return problemas


def motivo_fora_da_tabela(
    tabela: TabelaTroca, modelo: ModeloAparelho, capacidade: Capacidade | None
) -> MotivoLoja | None:
    """Por que a tabela não dá valor a esse usado (sem olhar o estado); None se dá.

    Sem capacidade informada, só confere se o modelo tem alguma linha.
    """
    if not tabela._linhas_do_modelo(modelo):
        return (
            MotivoLoja.MODELO_FORA_DA_TABELA
            if modelo.marca == _MARCA_APPLE
            else MotivoLoja.OUTRA_MARCA
        )
    if capacidade is not None and tabela.buscar(modelo, capacidade) is None:
        return MotivoLoja.CAPACIDADE_ABAIXO_DA_TABELA
    return None


def avaliar_troca(
    tabela: TabelaTroca,
    modelo: ModeloAparelho,
    capacidade: Capacidade,
    condicao: CondicaoUsado,
) -> ValorTroca | AvaliacaoNaLoja:
    """Valor da troca ou avaliação na loja (precedência: docstring do módulo)."""
    if condicao.peca_trocada:
        return AvaliacaoNaLoja(MotivoLoja.PECA_TROCADA)
    if not condicao.camera_ok or condicao.outros_defeitos:
        return AvaliacaoNaLoja(MotivoLoja.OUTRO_DEFEITO)
    fora = motivo_fora_da_tabela(tabela, modelo, capacidade)
    if fora is not None:
        return AvaliacaoNaLoja(fora)
    linha = tabela.buscar(modelo, capacidade)
    assert linha is not None

    aplicados: list[tuple[str, Dinheiro]] = []
    for motivo, desconto in _problemas_relatados(linha, condicao):
        if desconto is SEM:
            return AvaliacaoNaLoja(MotivoLoja.SEM_VALOR_WHATSAPP)
        assert isinstance(desconto, Dinheiro)
        if not desconto.zerado:
            aplicados.append((motivo, desconto))

    valor = linha.valor_sem_detalhes - Dinheiro.somar(d for _, d in aplicados)
    if not valor > Dinheiro.zero():
        return AvaliacaoNaLoja(MotivoLoja.VALOR_NAO_POSITIVO)
    return ValorTroca(valor=valor, descontos_aplicados=tuple(aplicados))
