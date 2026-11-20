"""Suite de contrato REUTILIZAVEL da `EstoquePort`.

Todo adaptador de estoque (planilha, ERP simulado, decorator de resiliencia, ERPs
reais) deve passar nesta mesma suite. Como reutilizar em um novo adaptador:

1. Crie `tests/contract/test_<adaptador>_contrato.py`.
2. Importe `ContratoEstoque` e crie uma subclasse cujo nome comece com `Test`
   (a base nao e coletada pelo pytest, so as subclasses `Test*`).
3. Sobrescreva a fixture `criar_adaptador`: ela devolve uma funcao
   `(itens_por_loja: Mapping[UUID, list[ItemEstoque]]) -> EstoquePort` que monta o
   adaptador ja populado com os itens (ex.: semeando o ERP simulado, ou uma fonte
   em memoria). Pode ser fixture async (`async def` + `yield`) se precisar de
   setup/teardown.

    class TestMeuAdaptadorContrato(ContratoEstoque):
        @pytest.fixture
        def criar_adaptador(self) -> CriarAdaptador:
            def _criar(itens_por_loja):
                return MeuAdaptador(...)
            return _criar

Os casos usam apenas a API publica da porta (`buscar`, `obter`, `capacidades`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.estoque import CapacidadesEstoque, EstoquePort
from app.domain.estoque import Condicao, ItemEstoque
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

CriarAdaptador = Callable[[Mapping[UUID, list[ItemEstoque]]], EstoquePort]

LOJA_A = UUID("00000000-0000-0000-0000-00000000000a")
LOJA_B = UUID("00000000-0000-0000-0000-00000000000b")


def item(
    sku: str,
    modelo: str = "iPhone 15 Pro",
    capacidade: int = 256,
    cor: str | None = "Titânio Natural",
    condicao: Condicao = Condicao.NOVO,
    quantidade: int = 2,
    bateria_pct: int | None = None,
) -> ItemEstoque:
    return ItemEstoque(
        sku=sku,
        modelo=ModeloAparelho.de(modelo),
        capacidade=Capacidade(capacidade),
        cor=cor,
        condicao=condicao,
        preco_pix=Dinheiro.de(Decimal("7000")),
        quantidade=quantidade,
        bateria_pct=bateria_pct,
    )


class ContratoEstoque:
    """Casos de contrato. Subclasses `Test*` sobrescrevem `criar_adaptador`."""

    @pytest.fixture
    def criar_adaptador(self) -> CriarAdaptador:
        raise NotImplementedError("sobrescreva a fixture criar_adaptador na subclasse")

    async def test_loja_sem_itens_retorna_vazio(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({})
        assert await adaptador.buscar(uuid4(), "iPhone 15 Pro") == []

    async def test_item_esgotado_nao_aparece(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({LOJA_A: [item("ESG", quantidade=0), item("OK")]})
        achados = await adaptador.buscar(LOJA_A, "iPhone 15 Pro")
        assert [i.sku for i in achados] == ["OK"]

    async def test_capacidade_inexistente_retorna_vazio(
        self, criar_adaptador: CriarAdaptador
    ) -> None:
        adaptador = criar_adaptador({LOJA_A: [item("A", capacidade=256)]})
        assert await adaptador.buscar(LOJA_A, "iPhone 15 Pro", Capacidade("1TB")) == []

    async def test_filtra_por_capacidade(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador(
            {LOJA_A: [item("A", capacidade=128), item("B", capacidade=256)]}
        )
        achados = await adaptador.buscar(LOJA_A, "iPhone 15 Pro", Capacidade("256GB"))
        assert [i.sku for i in achados] == ["B"]

    async def test_busca_tolerante(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({LOJA_A: [item("A")]})
        achados = await adaptador.buscar(LOJA_A, "iphone 15 pro")
        assert [i.sku for i in achados] == ["A"]
        achados_vo = await adaptador.buscar(LOJA_A, ModeloAparelho.de("iPhone 15 Pro"))
        assert [i.sku for i in achados_vo] == ["A"]

    async def test_busca_nao_mistura_modelos(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador(
            {LOJA_A: [item("PRO"), item("MAX", modelo="iPhone 15 Pro Max")]}
        )
        achados = await adaptador.buscar(LOJA_A, "iPhone 15 Pro")
        assert [i.sku for i in achados] == ["PRO"]

    async def test_filtra_por_cor(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador(
            {LOJA_A: [item("NAT", cor="Titânio Natural"), item("AZ", cor="Titânio Azul")]}
        )
        achados = await adaptador.buscar(LOJA_A, "iPhone 15 Pro", cor="titanio azul")
        assert [i.sku for i in achados] == ["AZ"]

    async def test_obter_inexistente_retorna_none(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({LOJA_A: [item("A")]})
        assert await adaptador.obter(LOJA_A, "NAO-EXISTE") is None

    async def test_obter_existente_retorna_item(self, criar_adaptador: CriarAdaptador) -> None:
        esperado = item("A")
        adaptador = criar_adaptador({LOJA_A: [esperado]})
        assert await adaptador.obter(LOJA_A, "A") == esperado

    async def test_isolamento_entre_lojas(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({LOJA_A: [item("A1")], LOJA_B: [item("B1")]})
        assert [i.sku for i in await adaptador.buscar(LOJA_A, "iPhone 15 Pro")] == ["A1"]
        assert [i.sku for i in await adaptador.buscar(LOJA_B, "iPhone 15 Pro")] == ["B1"]
        assert await adaptador.obter(LOJA_A, "B1") is None
        assert await adaptador.obter(LOJA_B, "A1") is None

    async def test_novos_e_seminovos_juntos(self, criar_adaptador: CriarAdaptador) -> None:
        novo = item("N")
        semi = item("S", condicao=Condicao.SEMINOVO, bateria_pct=87)
        adaptador = criar_adaptador({LOJA_A: [novo, semi]})
        achados = await adaptador.buscar(LOJA_A, "iPhone 15 Pro")
        assert {i.sku for i in achados} == {"N", "S"}
        assert {i.condicao for i in achados} == {Condicao.NOVO, Condicao.SEMINOVO}

    async def test_declara_capacidades(self, criar_adaptador: CriarAdaptador) -> None:
        adaptador = criar_adaptador({})
        assert isinstance(adaptador.capacidades, CapacidadesEstoque)
