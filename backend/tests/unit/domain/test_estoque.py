"""ItemEstoque e a funcao pura de filtro."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain.estoque import (
    Condicao,
    ItemEstoque,
    ModeloAmbiguo,
    ModeloForaDoEstoque,
    ModeloResolvido,
    filtrar,
    resolver_modelo,
)
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho


def item(
    sku: str = "S1",
    modelo: str = "iPhone 15 Pro",
    capacidade: int = 256,
    cor: str | None = "Titânio Natural",
    condicao: Condicao = Condicao.NOVO,
    quantidade: int = 3,
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


class TestItemEstoque:
    def test_condicao_valores(self) -> None:
        assert Condicao.NOVO.value == "novo"
        assert Condicao.SEMINOVO.value == "seminovo"

    def test_e_imutavel(self) -> None:
        with pytest.raises(FrozenInstanceError):
            item().quantidade = 1  # type: ignore[misc]

    def test_disponivel_com_quantidade(self) -> None:
        assert item(quantidade=1).disponivel is True

    def test_indisponivel_com_quantidade_zero(self) -> None:
        assert item(quantidade=0).disponivel is False

    def test_quantidade_negativa_invalida(self) -> None:
        with pytest.raises(ValueError):
            item(quantidade=-1)

    def test_desatualizado_padrao_falso(self) -> None:
        assert item().desatualizado is False

    def test_bateria_so_para_seminovo(self) -> None:
        with pytest.raises(ValueError):
            item(condicao=Condicao.NOVO, bateria_pct=90)
        assert item(condicao=Condicao.SEMINOVO, bateria_pct=90).bateria_pct == 90

    @pytest.mark.parametrize("pct", [-1, 101])
    def test_bateria_fora_de_0_a_100_invalida(self, pct: int) -> None:
        with pytest.raises(ValueError):
            item(condicao=Condicao.SEMINOVO, bateria_pct=pct)


class TestFiltrar:
    def test_lista_vazia(self) -> None:
        assert filtrar([], "iPhone 15") == []

    def test_modelo_tolerante_a_texto(self) -> None:
        itens = [item()]
        assert filtrar(itens, "iphone 15 pro") == itens
        assert filtrar(itens, "iPhone15Pro") == itens

    def test_modelo_aceita_value_object(self) -> None:
        itens = [item()]
        assert filtrar(itens, ModeloAparelho.de("iPhone 15 Pro")) == itens

    def test_nao_confunde_modelos_parecidos(self) -> None:
        pro = item(sku="P", modelo="iPhone 15 Pro")
        promax = item(sku="M", modelo="iPhone 15 Pro Max")
        assert filtrar([pro, promax], "iPhone 15 Pro") == [pro]

    def test_exclui_esgotados(self) -> None:
        assert filtrar([item(quantidade=0)], "iPhone 15 Pro") == []

    def test_filtra_por_capacidade(self) -> None:
        a, b = item(sku="A", capacidade=128), item(sku="B", capacidade=256)
        assert filtrar([a, b], "iPhone 15 Pro", capacidade=Capacidade("256GB")) == [b]
        assert filtrar([a, b], "iPhone 15 Pro", capacidade=Capacidade("512GB")) == []

    def test_cor_sem_acento_e_sem_caixa(self) -> None:
        a = item(sku="A", cor="Titânio Natural")
        b = item(sku="B", cor="Azul")
        assert filtrar([a, b], "iPhone 15 Pro", cor="titanio natural") == [a]
        assert filtrar([a, b], "iPhone 15 Pro", cor="AZUL") == [b]

    def test_cor_filtrada_exclui_item_sem_cor(self) -> None:
        assert filtrar([item(cor=None)], "iPhone 15 Pro", cor="azul") == []

    def test_sem_filtro_de_cor_mantem_item_sem_cor(self) -> None:
        sem_cor = item(cor=None)
        assert filtrar([sem_cor], "iPhone 15 Pro") == [sem_cor]

    def test_novos_e_seminovos_juntos(self) -> None:
        novo = item(sku="N")
        semi = item(sku="S", condicao=Condicao.SEMINOVO, bateria_pct=88)
        assert filtrar([novo, semi], "iPhone 15 Pro") == [novo, semi]

    def test_modelo_vazio_levanta(self) -> None:
        with pytest.raises(ValueError):
            filtrar([item()], "   ")


class TestResolverModelo:
    """Modelo pedido pelo cliente -> modelo da loja (iPhone conhecido ou o que esta no estoque)."""

    GALAXY_A07 = ModeloAparelho.de("Galaxy A07 4G", "Samsung")
    GALAXY_S23 = ModeloAparelho.de("Galaxy S23", "Samsung")
    REDMI = ModeloAparelho.de("Redmi 15C", "Xiaomi")
    IPHONE_18_PRO = ModeloAparelho.de("IPHONE 18 PRO")
    IPHONE_18_PRO_MAX = ModeloAparelho.de("IPHONE 18 PRO MAX")
    ESTOQUE = (GALAXY_A07, GALAXY_S23, REDMI, IPHONE_18_PRO, IPHONE_18_PRO_MAX)

    def test_iphone_conhecido_vale_mesmo_fora_do_estoque(self) -> None:
        assert resolver_modelo("iphone15 pro", ()) == ModeloResolvido(
            ModeloAparelho.de("iPhone 15 Pro")
        )

    def test_outra_marca_casa_com_o_estoque_sem_a_marca_e_pelo_comeco_do_nome(self) -> None:
        assert resolver_modelo("galaxy a07", self.ESTOQUE) == ModeloResolvido(self.GALAXY_A07)

    def test_outra_marca_casa_com_a_marca_na_frente_e_sem_acento_ou_caixa(self) -> None:
        assert resolver_modelo("SAMSUNG galáxy-a07 4g", self.ESTOQUE) == ModeloResolvido(
            self.GALAXY_A07
        )

    def test_nome_exato_ganha_do_prefixo(self) -> None:
        assert resolver_modelo("iphone 18 pro", self.ESTOQUE) == ModeloResolvido(self.IPHONE_18_PRO)

    def test_mais_de_um_candidato_e_ambiguo(self) -> None:
        r = resolver_modelo("galaxy", self.ESTOQUE)
        assert isinstance(r, ModeloAmbiguo)
        assert set(r.candidatos) == {self.GALAXY_A07, self.GALAXY_S23}

    def test_so_a_marca_lista_os_modelos_dela(self) -> None:
        r = resolver_modelo("samsung", self.ESTOQUE)
        assert isinstance(r, ModeloAmbiguo)
        assert set(r.candidatos) == {self.GALAXY_A07, self.GALAXY_S23}

    def test_modelo_que_a_loja_nao_tem(self) -> None:
        assert resolver_modelo("moto g84", self.ESTOQUE) == ModeloForaDoEstoque()
        assert resolver_modelo("   ", self.ESTOQUE) == ModeloForaDoEstoque()
        assert resolver_modelo("?!", self.ESTOQUE) == ModeloForaDoEstoque()
