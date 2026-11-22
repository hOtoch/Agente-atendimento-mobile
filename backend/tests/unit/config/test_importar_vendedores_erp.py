"""Importacao de vendedores do ERP: caso de uso com repositorios em memoria e leitor falso.

Dados sinteticos; nenhuma chamada ao Mercado Phone.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.entradas import EntradaVendedor
from app.application.config.memoria import (
    MemoriaConexaoErp,
    MemoriaLojas,
    MemoriaVendedores,
    criar_casos_em_memoria,
)
from app.application.config.modelos import LojaNaoEncontrada, VendedorLoja
from app.application.config.vendedores_erp import (
    ErpCredencialInvalida,
    ErpIndisponivel,
    ErpNaoConfigurado,
    ImportarVendedoresErp,
    LeitorVendedoresErpNaoConfigurado,
    LojaSemConexaoErp,
    VendedorErp,
)
from app.application.estoque import EstoqueIndisponivel
from app.domain.conexao_erp import ConexaoErp

D = Decimal


class LeitorFalso:
    def __init__(self, itens: list[VendedorErp] | None = None) -> None:
        self.itens = itens or []
        self.erro: Exception | None = None
        self.unidades: list[int] = []

    async def listar(self, system_unit_id: int) -> list[VendedorErp]:
        self.unidades.append(system_unit_id)
        if self.erro is not None:
            raise self.erro
        return list(self.itens)


def erp(codigo: str, nome: str, ativo: bool = True) -> VendedorErp:
    return VendedorErp(codigo_erp=codigo, nome=nome, ativo=ativo)


class Ctx:
    def __init__(self) -> None:
        self.lojas = MemoriaLojas()
        self.conexoes = MemoriaConexaoErp()
        self.vendedores = MemoriaVendedores()
        self.leitor = LeitorFalso()
        self.caso = ImportarVendedoresErp(self.lojas, self.conexoes, self.vendedores, self.leitor)
        self.loja_id: UUID

    @classmethod
    async def nova(cls, *, conectada: bool = True) -> Ctx:
        c = cls()
        c.loja_id = await c.lojas.criar("Loja")
        if conectada:
            await c.conexoes.salvar(ConexaoErp(loja_id=c.loja_id, system_unit_id=12))
        return c

    async def listar(self) -> list[VendedorLoja]:
        return await self.vendedores.listar(self.loja_id)


async def test_cria_ativos_com_peso_zero_codigo_e_nome_legivel() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("9", "FULANO DE TAL"), erp("10", "Beltrana")]

    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.atualizados, resumo.desativados) == (2, 0, 0)
    lista = await c.listar()
    assert [(v.codigo_erp, v.nome, v.peso_percentual, v.ativo) for v in lista] == [
        ("9", "FULANO DE TAL", D(0), True),
        ("10", "Beltrana", D(0), True),
    ]
    assert all(v.telefone is None for v in lista)


async def test_usa_a_unidade_da_conexao_da_loja() -> None:
    c = await Ctx.nova()
    await c.caso.executar(c.loja_id)
    assert c.leitor.unidades == [12]


async def test_ignora_vendedor_inativo_que_ainda_nao_existe() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana"), erp("2", "Bruno", ativo=False)]
    resumo = await c.caso.executar(c.loja_id)
    assert resumo.criados == 1
    assert [v.codigo_erp for v in await c.listar()] == ["1"]


async def test_reimportar_nao_duplica() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana"), erp("2", "Bruno")]
    await c.caso.executar(c.loja_id)
    antes = await c.listar()

    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.atualizados, resumo.desativados) == (0, 0, 0)
    assert resumo.sem_alteracao == 2
    assert await c.listar() == antes


async def test_item_repetido_na_resposta_do_erp_vira_um_vendedor() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana"), erp("1", "Ana")]
    resumo = await c.caso.executar(c.loja_id)
    assert resumo.criados == 1
    assert len(await c.listar()) == 1


async def test_atualiza_so_o_nome_e_preserva_telefone_e_peso_editados() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "ana silva")]
    await c.caso.executar(c.loja_id)
    (ana,) = await c.listar()
    await c.vendedores.substituir(
        c.loja_id,
        [
            EntradaVendedor(
                id=ana.id, nome=ana.nome, telefone="+55 11 90000-0001", peso_percentual=D("100")
            )
        ],
    )

    c.leitor.itens = [erp("1", "ANA SOUZA")]
    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.atualizados, resumo.desativados) == (0, 1, 0)
    (depois,) = await c.listar()
    assert depois.id == ana.id
    assert depois.codigo_erp == "1"
    assert depois.nome == "ANA SOUZA"
    assert depois.telefone == "+55 11 90000-0001"
    assert depois.peso_percentual == D("100")


async def test_quem_sumiu_do_erp_fica_inativo_e_nao_e_apagado() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana"), erp("2", "Bruno")]
    await c.caso.executar(c.loja_id)
    ana, bruno = await c.listar()
    await c.vendedores.substituir(
        c.loja_id,
        [
            EntradaVendedor(id=ana.id, nome="Ana", telefone=None, peso_percentual=D("60")),
            EntradaVendedor(
                id=bruno.id, nome="Bruno", telefone="+55 11 90000-0002", peso_percentual=D("40")
            ),
        ],
    )

    c.leitor.itens = [erp("1", "Ana")]
    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.atualizados, resumo.desativados) == (0, 0, 1)
    por_id = {v.id: v for v in await c.listar()}
    assert por_id[bruno.id].ativo is False
    assert por_id[bruno.id].peso_percentual == D("40")
    assert por_id[bruno.id].telefone == "+55 11 90000-0002"
    assert por_id[ana.id].ativo is True


async def test_quem_veio_inativo_do_erp_e_desativado() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana")]
    await c.caso.executar(c.loja_id)

    c.leitor.itens = [erp("1", "Ana", ativo=False)]
    resumo = await c.caso.executar(c.loja_id)

    assert resumo.desativados == 1
    assert resumo.atualizados == 0
    (ana,) = await c.listar()
    assert ana.ativo is False
    # e reimportar o mesmo estado nao conta de novo
    outra = await c.caso.executar(c.loja_id)
    assert (outra.desativados, outra.atualizados, outra.sem_alteracao) == (0, 0, 1)


async def test_vendedor_que_voltou_ao_erp_e_reativado_com_o_peso_que_tinha() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana")]
    await c.caso.executar(c.loja_id)
    (ana,) = await c.listar()
    await c.vendedores.substituir(
        c.loja_id,
        [EntradaVendedor(id=ana.id, nome="Ana", telefone=None, peso_percentual=D("100"))],
    )
    c.leitor.itens = []
    await c.caso.executar(c.loja_id)
    assert (await c.listar())[0].ativo is False

    c.leitor.itens = [erp("1", "Ana")]
    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.atualizados) == (0, 1)
    (volta,) = await c.listar()
    assert (volta.id, volta.ativo, volta.peso_percentual) == (ana.id, True, D("100"))


async def test_vendedor_manual_nao_e_desativado_nem_fundido_por_nome() -> None:
    c = await Ctx.nova()
    await c.vendedores.substituir(
        c.loja_id,
        [EntradaVendedor(id=None, nome="Ana", telefone=None, peso_percentual=D("100"))],
    )
    c.leitor.itens = [erp("1", "Ana")]

    resumo = await c.caso.executar(c.loja_id)

    assert (resumo.criados, resumo.desativados) == (1, 0)
    lista = await c.listar()
    manual = next(v for v in lista if v.codigo_erp is None)
    do_erp = next(v for v in lista if v.codigo_erp == "1")
    assert manual.ativo is True and manual.peso_percentual == D("100")
    assert do_erp.peso_percentual == D(0)

    c.leitor.itens = []
    await c.caso.executar(c.loja_id)
    por_codigo = {v.codigo_erp: v for v in await c.listar()}
    assert por_codigo[None].ativo is True
    assert por_codigo["1"].ativo is False


async def test_loja_inexistente() -> None:
    c = await Ctx.nova()
    with pytest.raises(LojaNaoEncontrada):
        await c.caso.executar(UUID(int=1))


async def test_loja_sem_conexao_com_o_erp() -> None:
    c = await Ctx.nova(conectada=False)
    with pytest.raises(LojaSemConexaoErp):
        await c.caso.executar(c.loja_id)
    assert c.leitor.unidades == []


async def test_erp_fora_vira_erp_indisponivel_e_nada_e_gravado() -> None:
    c = await Ctx.nova()
    c.leitor.itens = [erp("1", "Ana")]
    await c.caso.executar(c.loja_id)
    antes = await c.listar()

    erro = EstoqueIndisponivel("ERP caiu com a chave segredo-123")
    c.leitor.erro = erro
    c.leitor.itens = []
    with pytest.raises(ErpIndisponivel) as info:
        await c.caso.executar(c.loja_id)

    assert "segredo-123" not in str(info.value)
    assert await c.listar() == antes


async def test_erro_de_configuracao_do_erp_vira_credencial_invalida() -> None:
    c = await Ctx.nova()
    erro = EstoqueIndisponivel("chave recusada")
    erro.retentavel = False
    c.leitor.erro = erro
    with pytest.raises(ErpCredencialInvalida):
        await c.caso.executar(c.loja_id)


async def test_leitor_nao_configurado_levanta_erp_nao_configurado() -> None:
    c = await Ctx.nova()
    caso = ImportarVendedoresErp(
        c.lojas, c.conexoes, c.vendedores, LeitorVendedoresErpNaoConfigurado()
    )
    with pytest.raises(ErpNaoConfigurado):
        await caso.executar(c.loja_id)


async def test_put_de_vendedores_preserva_o_codigo_erp() -> None:
    casos: CasosDeUsoConfig = criar_casos_em_memoria()
    loja = await casos.criar_loja("L")
    await casos.vendedores.criar_do_erp(loja, "7", "Ana")
    (ana,) = await casos.obter_vendedores(loja)
    salvos = await casos.atualizar_vendedores(
        loja,
        [EntradaVendedor(id=ana.id, nome="Ana", telefone=None, peso_percentual=D("100"))],
    )
    assert salvos[0].codigo_erp == "7"
    # omitido da lista = desativado, e o codigo continua la
    de_novo = await casos.atualizar_vendedores(
        loja, [EntradaVendedor(id=None, nome="Bia", telefone=None, peso_percentual=D("100"))]
    )
    por_nome = {v.nome: v for v in de_novo}
    assert por_nome["Ana"].ativo is False
    assert por_nome["Ana"].codigo_erp == "7"
    assert por_nome["Bia"].codigo_erp is None
