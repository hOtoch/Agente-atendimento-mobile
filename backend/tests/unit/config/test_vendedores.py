"""CRUD de vendedores (substituicao da lista) com repositorio em memoria."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.entradas import EntradaVendedor
from app.application.config.memoria import criar_casos_em_memoria
from app.application.config.modelos import ErrosDeValidacao, LojaNaoEncontrada

D = Decimal


def entrada(nome: str, peso: str, **sobre: object) -> EntradaVendedor:
    base: dict[str, object] = {
        "id": None,
        "nome": nome,
        "telefone": None,
        "peso_percentual": D(peso),
        "ativo": True,
    }
    base.update(sobre)
    return EntradaVendedor(**base)  # type: ignore[arg-type]


@pytest.fixture
def casos() -> CasosDeUsoConfig:
    return criar_casos_em_memoria()


def caminhos(exc: pytest.ExceptionInfo[ErrosDeValidacao]) -> list[str]:
    return [e.caminho for e in exc.value.erros]


async def test_sem_vendedores_lista_vazia(casos: CasosDeUsoConfig) -> None:
    assert await casos.obter_vendedores(await casos.criar_loja("L")) == []


async def test_salvar_cria_com_ids_e_o_get_devolve(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    salvos = await casos.atualizar_vendedores(
        lj, [entrada("Ana", "60", telefone="+55 11 90000-0001"), entrada("Bruno", "40")]
    )
    assert [v.nome for v in salvos] == ["Ana", "Bruno"]
    assert all(v.id is not None for v in salvos)
    assert salvos[0].telefone == "+55 11 90000-0001"
    assert salvos[1].telefone is None
    assert await casos.obter_vendedores(lj) == salvos


async def test_id_existente_e_mantido_e_atualizado(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    ana, bruno = await casos.atualizar_vendedores(
        lj, [entrada("Ana", "60"), entrada("Bruno", "40")]
    )
    depois = await casos.atualizar_vendedores(
        lj, [entrada("Ana Souza", "70", id=ana.id), entrada("Bruno", "30", id=bruno.id)]
    )
    assert [v.id for v in depois] == [ana.id, bruno.id]
    assert depois[0].nome == "Ana Souza"
    assert depois[0].peso_percentual == D("70")


async def test_vendedor_ausente_e_desativado_nao_apagado(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    ana, bruno = await casos.atualizar_vendedores(
        lj, [entrada("Ana", "60"), entrada("Bruno", "40")]
    )
    await casos.atualizar_vendedores(lj, [entrada("Ana", "100", id=ana.id)])
    todos = {v.id: v for v in await casos.obter_vendedores(lj)}
    assert set(todos) == {ana.id, bruno.id}
    assert todos[ana.id].ativo is True
    assert todos[bruno.id].ativo is False


async def test_vendedor_inativo_pode_voltar_com_o_mesmo_id(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    ana, bruno = await casos.atualizar_vendedores(
        lj, [entrada("Ana", "60"), entrada("Bruno", "40")]
    )
    await casos.atualizar_vendedores(lj, [entrada("Ana", "100", id=ana.id)])
    await casos.atualizar_vendedores(
        lj, [entrada("Ana", "50", id=ana.id), entrada("Bruno", "50", id=bruno.id)]
    )
    assert all(v.ativo for v in await casos.obter_vendedores(lj))


async def test_soma_so_considera_ativos(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    salvos = await casos.atualizar_vendedores(
        lj, [entrada("Ana", "100"), entrada("Bruno", "30", ativo=False)]
    )
    assert [v.ativo for v in salvos] == [True, False]


async def test_soma_diferente_de_100_e_erro_em_vendedores(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(lj, [entrada("Ana", "60"), entrada("Bruno", "30")])
    assert caminhos(exc) == ["vendedores"]
    assert "90" in exc.value.erros[0].mensagem
    assert await casos.obter_vendedores(lj) == []


async def test_lista_vazia_nao_soma_100(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(lj, [])
    assert caminhos(exc) == ["vendedores"]


async def test_nome_obrigatorio_e_peso_de_0_a_100_por_linha(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(
            lj, [entrada("Ana", "100"), entrada("  ", "10"), entrada("Carla", "150")]
        )
    assert caminhos(exc) == ["vendedores[1].nome", "vendedores[2].peso_percentual"]


async def test_telefone_invalido(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(lj, [entrada("Ana", "100", telefone="123")])
    assert caminhos(exc) == ["vendedores[0].telefone"]


async def test_id_desconhecido_e_id_repetido(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    (ana,) = await casos.atualizar_vendedores(lj, [entrada("Ana", "100")])
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(
            lj,
            [
                entrada("Ana", "50", id=ana.id),
                entrada("Ana de novo", "25", id=ana.id),
                entrada("Fantasma", "25", id=uuid4()),
            ],
        )
    assert caminhos(exc) == ["vendedores[1].id", "vendedores[2].id"]


async def test_vendedor_de_outra_loja_conta_como_desconhecido(casos: CasosDeUsoConfig) -> None:
    a = await casos.criar_loja("A")
    b = await casos.criar_loja("B")
    (ana,) = await casos.atualizar_vendedores(a, [entrada("Ana", "100")])
    with pytest.raises(ErrosDeValidacao) as exc:
        await casos.atualizar_vendedores(b, [entrada("Ana", "100", id=ana.id)])
    assert caminhos(exc) == ["vendedores[0].id"]


async def test_loja_inexistente(casos: CasosDeUsoConfig) -> None:
    with pytest.raises(LojaNaoEncontrada):
        await casos.obter_vendedores(uuid4())
    with pytest.raises(LojaNaoEncontrada):
        await casos.atualizar_vendedores(uuid4(), [entrada("Ana", "100")])


async def test_checklist_reflete_vendedores_salvos(casos: CasosDeUsoConfig) -> None:
    lj = await casos.criar_loja("L")
    await casos.atualizar_vendedores(lj, [entrada("Ana", "60"), entrada("Bruno", "40")])
    item = next(i for i in await casos.checklist(lj) if i.chave == "vendedores")
    assert item.completo is True
