"""Caso de uso `SincronizarEstoqueErp`: leitura inteira ou nada, relatorio e cron.

Fonte do ERP falsa em memoria (a porta `FonteEstoqueErp`); nenhuma rede.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.config.memoria import MemoriaConexaoErp, MemoriaEstoqueLocal
from app.application.config.modelos import LinhaEstoqueLocal
from app.application.estoque import EstoqueIndisponivel
from app.application.estoque_erp import (
    LeituraErp,
    SincronizarEstoqueErp,
)
from app.application.relogio import RelogioFalso
from app.domain.conexao_erp import ConexaoErp
from app.domain.estoque import Condicao
from app.domain.oferta import MotivoDescarte
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

AGORA = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def linha(sku: str, *, preco: str = "4200", erp_id: int | None = None) -> LinhaEstoqueLocal:
    return LinhaEstoqueLocal(
        sku=sku,
        modelo=ModeloAparelho.de("iPhone 15 Pro", "Apple"),
        capacidade=Capacidade("256gb"),
        cor="Preto",
        condicao=Condicao.SEMINOVO,
        preco_pix=Dinheiro.de(Decimal(preco)),
        quantidade=1,
        bateria_pct=None,
        erp_produto_id=erp_id,
    )


class ErroDeConexao(EstoqueIndisponivel):
    retentavel = True
    codigo = "falha_de_rede"


@dataclass
class UnidadeFalsa:
    """O que o ERP devolveu para uma unidade: itens por tag de loja (o 'filtro')."""

    por_loja: Mapping[str | None, Sequence[LinhaEstoqueLocal]]
    lidos: int | None = None
    descartes: Mapping[MotivoDescarte, int] = field(default_factory=dict)

    def para_loja(self, filtro_loja: str | None) -> LeituraErp:
        linhas = tuple(self.por_loja.get(filtro_loja, ()))
        total = sum(len(v) for v in self.por_loja.values())
        lidos = self.lidos if self.lidos is not None else total + sum(self.descartes.values())
        return LeituraErp(
            linhas=linhas,
            lidos=lidos,
            outra_loja=total - len(linhas),
            descartes=dict(self.descartes),
        )


class FonteFalsa:
    def __init__(
        self,
        relogio: RelogioFalso,
        unidades: Mapping[int, UnidadeFalsa] | None = None,
        *,
        segundos_por_leitura: float = 0.0,
    ) -> None:
        self.relogio = relogio
        self.unidades: dict[int, UnidadeFalsa] = dict(unidades or {})
        self.falhas: dict[int, Exception] = {}
        self.existentes: set[int] = set(self.unidades)
        self.lidas: list[int] = []
        self.segundos_por_leitura = segundos_por_leitura

    async def ler_unidade(self, system_unit_id: int) -> UnidadeFalsa:
        self.lidas.append(system_unit_id)
        self.relogio.avancar(self.segundos_por_leitura)
        if system_unit_id in self.falhas:
            raise self.falhas[system_unit_id]
        return self.unidades[system_unit_id]

    async def ler(self, conexao: ConexaoErp) -> LeituraErp:
        return (await self.ler_unidade(conexao.system_unit_id)).para_loja(conexao.filtro_loja)

    async def unidade_existe(self, system_unit_id: int) -> bool:
        if system_unit_id in self.falhas:
            raise self.falhas[system_unit_id]
        return system_unit_id in self.existentes


class EstoqueQueFalhaAoGravar(MemoriaEstoqueLocal):
    async def substituir(self, loja_id: UUID, linhas: Sequence[LinhaEstoqueLocal]) -> None:
        raise RuntimeError("banco caiu")


@dataclass
class Cenario:
    caso: SincronizarEstoqueErp
    fonte: FonteFalsa
    conexoes: MemoriaConexaoErp
    estoque: MemoriaEstoqueLocal
    relogio: RelogioFalso
    relogio_parede: list[datetime]
    transacoes: list[str]

    def passar(self, **kw: float) -> None:
        self.relogio_parede[0] += timedelta(**kw)

    async def ligar(self, **campos: object) -> ConexaoErp:
        base: dict[str, object] = {"loja_id": uuid4(), "system_unit_id": 4, "ativo": True}
        conexao = ConexaoErp(**{**base, **campos})  # type: ignore[arg-type]
        await self.conexoes.salvar(conexao)
        return conexao

    async def estado(self, conexao: ConexaoErp) -> ConexaoErp:
        atual = await self.conexoes.obter(conexao.loja_id)
        assert atual is not None
        return atual


def montar(
    unidades: Mapping[int, UnidadeFalsa] | None = None,
    *,
    estoque: MemoriaEstoqueLocal | None = None,
    segundos_por_leitura: float = 0.0,
) -> Cenario:
    relogio = RelogioFalso()
    fonte = FonteFalsa(relogio, unidades, segundos_por_leitura=segundos_por_leitura)
    conexoes = MemoriaConexaoErp()
    estoque = estoque or MemoriaEstoqueLocal()
    relogio_parede = [AGORA]
    transacoes: list[str] = []

    async def commit() -> None:
        transacoes.append("commit")

    async def rollback() -> None:
        transacoes.append("rollback")

    caso = SincronizarEstoqueErp(
        conexoes,
        estoque,
        fonte,
        relogio=relogio,
        agora=lambda: relogio_parede[0],
        commit=commit,
        rollback=rollback,
    )
    return Cenario(caso, fonte, conexoes, estoque, relogio, relogio_parede, transacoes)


UNIDADE_4 = UnidadeFalsa({None: [linha("A-1", erp_id=11), linha("A-2", erp_id=12)]})


# --- sincronizar uma loja ----------------------------------------------------------------------


async def test_sincroniza_substitui_o_estoque_e_grava_status_ok_com_relatorio() -> None:
    c = montar(
        {
            4: UnidadeFalsa(
                {None: [linha("A-1", erp_id=11)]}, lidos=5, descartes={MotivoDescarte.SEM_PRECO: 2}
            )
        },
        segundos_por_leitura=2.5,
    )
    conexao = await c.ligar()
    await c.estoque.substituir(conexao.loja_id, [linha("VELHO")])

    resultado = await c.caso.sincronizar(conexao)

    assert resultado.status == "ok"
    assert [x.sku for x in await c.estoque.listar(conexao.loja_id)] == ["A-1"]
    assert (await c.estoque.listar(conexao.loja_id))[0].erp_produto_id == 11
    gravada = await c.estado(conexao)
    assert gravada.ultimo_status == "ok"
    assert gravada.ultima_sincronizacao_em == AGORA
    assert gravada.ultimo_relatorio == {
        "lidos": 5,
        "importados": 1,
        "outra_loja": 0,
        "descartados": 2,
        "por_motivo": {"sem_preco": 2},
        "duracao_s": 2.5,
    }
    assert resultado.relatorio == gravada.ultimo_relatorio
    assert c.transacoes == ["commit"]


async def test_rodar_duas_vezes_da_o_mesmo_estoque() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar()
    await c.caso.sincronizar(conexao)
    primeiro = await c.estoque.listar(conexao.loja_id)
    await c.caso.sincronizar(conexao)
    assert await c.estoque.listar(conexao.loja_id) == primeiro
    assert len(primeiro) == 2


async def test_falha_na_leitura_mantem_o_ultimo_estoque_bom_e_grava_erro() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar()
    await c.caso.sincronizar(conexao)
    antes = await c.estoque.listar(conexao.loja_id)
    c.fonte.falhas[4] = ErroDeConexao("Mercado Phone respondeu HTTP 503")
    c.passar(minutes=15)

    resultado = await c.caso.sincronizar(await c.estado(conexao))

    assert resultado.status == "erro"
    assert await c.estoque.listar(conexao.loja_id) == antes
    gravada = await c.estado(conexao)
    assert gravada.ultimo_status == "erro"
    assert gravada.ultima_sincronizacao_em == AGORA + timedelta(minutes=15)
    assert gravada.ultimo_relatorio is not None
    assert "Mercado Phone respondeu HTTP 503" in gravada.ultimo_relatorio["erro"]
    assert gravada.ultimo_relatorio["retentavel"] is True
    assert gravada.ultimo_relatorio["codigo"] == "falha_de_rede"
    assert "duracao_s" in gravada.ultimo_relatorio


async def test_falha_ao_gravar_o_estoque_desfaz_a_transacao_e_grava_erro() -> None:
    c = montar({4: UNIDADE_4}, estoque=EstoqueQueFalhaAoGravar())
    conexao = await c.ligar()

    resultado = await c.caso.sincronizar(conexao)

    assert resultado.status == "erro"
    assert c.transacoes == ["rollback", "commit"]  # desfaz a tentativa e confirma so o status
    gravada = await c.estado(conexao)
    assert gravada.ultimo_status == "erro"
    assert gravada.ultimo_relatorio is not None
    assert "Erro inesperado" in gravada.ultimo_relatorio["erro"]


async def test_leitura_vazia_nao_apaga_o_estoque() -> None:
    c = montar({4: UnidadeFalsa({})})
    conexao = await c.ligar()
    await c.estoque.substituir(conexao.loja_id, [linha("VELHO")])

    resultado = await c.caso.sincronizar(conexao)

    assert resultado.status == "erro"
    assert [x.sku for x in await c.estoque.listar(conexao.loja_id)] == ["VELHO"]
    assert "nenhum item" in resultado.relatorio["erro"].lower()


async def test_nada_importado_de_um_inventario_com_itens_nao_apaga_o_estoque() -> None:
    # filtro de loja errado: o ERP tem itens, mas nenhum e desta loja
    c = montar({4: UnidadeFalsa({"Loja B": [linha("B-1", erp_id=1)]})})
    conexao = await c.ligar(filtro_loja="Loja A")
    await c.estoque.substituir(conexao.loja_id, [linha("VELHO")])

    resultado = await c.caso.sincronizar(conexao)

    assert resultado.status == "erro"
    assert [x.sku for x in await c.estoque.listar(conexao.loja_id)] == ["VELHO"]
    assert "filtro" in resultado.relatorio["erro"].lower()
    assert resultado.relatorio["lidos"] == 1
    assert resultado.relatorio["outra_loja"] == 1


async def test_sku_duplicado_mantem_o_primeiro_e_conta_como_descarte() -> None:
    c = montar(
        {
            4: UnidadeFalsa(
                {
                    None: [
                        linha("A-1", preco="100", erp_id=1),
                        linha("A-1", preco="999", erp_id=2),
                        linha("A-2"),
                    ]
                }
            )
        }
    )
    conexao = await c.ligar()

    resultado = await c.caso.sincronizar(conexao)

    assert resultado.status == "ok"
    guardadas = await c.estoque.listar(conexao.loja_id)
    assert [(x.sku, x.erp_produto_id) for x in guardadas] == [("A-1", 1), ("A-2", None)]
    assert resultado.relatorio["importados"] == 2
    assert resultado.relatorio["por_motivo"] == {"sku_duplicado": 1}
    assert resultado.relatorio["descartados"] == 1


async def test_sincronizar_manual_funciona_com_a_conexao_inativa() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar(ativo=False)
    resultado = await c.caso.sincronizar(conexao)
    assert resultado.status == "ok"


# --- testar conexao ----------------------------------------------------------------------------


async def test_testar_unidade_existente() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar()
    teste = await c.caso.testar(conexao)
    assert teste.ok is True
    assert "4" in teste.mensagem


async def test_testar_unidade_que_nao_existe_na_chave() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar(system_unit_id=99)
    teste = await c.caso.testar(conexao)
    assert teste.ok is False
    assert "99" in teste.mensagem


async def test_testar_com_erp_fora_nao_levanta() -> None:
    c = montar({4: UNIDADE_4})
    c.fonte.falhas[4] = ErroDeConexao("timeout")
    teste = await c.caso.testar(await c.ligar())
    assert teste.ok is False
    assert "indispon" in teste.mensagem.lower()


async def test_testar_nao_grava_nada() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar()
    await c.caso.testar(conexao)
    assert (await c.estado(conexao)).ultimo_status is None
    assert await c.estoque.listar(conexao.loja_id) == []


# --- cron --------------------------------------------------------------------------------------


async def test_cron_sincroniza_quem_nunca_sincronizou_e_pula_quem_ainda_nao_venceu() -> None:
    c = montar({4: UNIDADE_4})
    nova = await c.ligar()
    recente = await c.ligar(ultima_sincronizacao_em=AGORA - timedelta(minutes=3))
    vencida = await c.ligar(ultima_sincronizacao_em=AGORA - timedelta(minutes=20))

    resultados = await c.caso.sincronizar_vencidas()

    assert {r.loja_id for r in resultados} == {nova.loja_id, vencida.loja_id}
    assert await c.estoque.listar(recente.loja_id) == []
    assert len(await c.estoque.listar(nova.loja_id)) == 2


async def test_cron_com_relogio_fake_respeita_o_intervalo_de_cada_loja() -> None:
    c = montar({4: UNIDADE_4})
    conexao = await c.ligar(intervalo_min=15)

    assert len(await c.caso.sincronizar_vencidas()) == 1  # primeira vez
    for _ in range(2):  # ticks de 5 em 5 minutos
        c.passar(minutes=5)
        assert await c.caso.sincronizar_vencidas() == []
    c.passar(minutes=5)  # 15 min depois
    assert len(await c.caso.sincronizar_vencidas()) == 1
    assert (await c.estado(conexao)).ultima_sincronizacao_em == AGORA + timedelta(minutes=15)


async def test_cron_ignora_loja_inativa_e_loja_sem_conexao() -> None:
    c = montar({4: UNIDADE_4})
    inativa = await c.ligar(ativo=False)
    resultados = await c.caso.sincronizar_vencidas()  # a outra loja nunca teve conexao
    assert resultados == []
    assert c.fonte.lidas == []
    assert (await c.estado(inativa)).ultimo_status is None


async def test_cron_le_cada_unidade_uma_vez_e_aplica_o_filtro_de_cada_loja() -> None:
    unidade = UnidadeFalsa(
        {
            "Loja A": [linha("A-1", erp_id=1), linha("A-2", erp_id=2)],
            "Loja B": [linha("B-1", erp_id=3)],
        }
    )
    c = montar({4: unidade})
    loja_a = await c.ligar(filtro_loja="Loja A")
    loja_b = await c.ligar(filtro_loja="Loja B")

    resultados = await c.caso.sincronizar_vencidas()

    assert c.fonte.lidas == [4]  # uma leitura so
    assert [x.status for x in resultados] == ["ok", "ok"]
    assert [x.sku for x in await c.estoque.listar(loja_a.loja_id)] == ["A-1", "A-2"]
    assert [x.sku for x in await c.estoque.listar(loja_b.loja_id)] == ["B-1"]
    assert (await c.estado(loja_a)).ultimo_relatorio is not None
    assert (await c.estado(loja_a)).ultimo_relatorio["outra_loja"] == 1  # type: ignore[index]


async def test_cron_unidade_compartilhada_com_falha_marca_erro_nas_duas_lojas() -> None:
    c = montar({4: UnidadeFalsa({"Loja A": [linha("A-1")], "Loja B": [linha("B-1")]})})
    loja_a = await c.ligar(filtro_loja="Loja A")
    loja_b = await c.ligar(filtro_loja="Loja B")
    await c.estoque.substituir(loja_a.loja_id, [linha("VELHO")])
    c.fonte.falhas[4] = ErroDeConexao("fora do ar")

    resultados = await c.caso.sincronizar_vencidas()

    assert c.fonte.lidas == [4]
    assert [x.status for x in resultados] == ["erro", "erro"]
    assert [x.sku for x in await c.estoque.listar(loja_a.loja_id)] == ["VELHO"]
    assert (await c.estado(loja_b)).ultimo_status == "erro"


async def test_cron_falha_de_uma_unidade_nao_impede_as_outras() -> None:
    c = montar({4: UNIDADE_4, 5: UNIDADE_4})
    ruim = await c.ligar(system_unit_id=4)
    boa = await c.ligar(system_unit_id=5)
    c.fonte.falhas[4] = ErroDeConexao("fora do ar")

    resultados = await c.caso.sincronizar_vencidas()

    assert {r.loja_id: r.status for r in resultados} == {ruim.loja_id: "erro", boa.loja_id: "ok"}
    assert len(await c.estoque.listar(boa.loja_id)) == 2
