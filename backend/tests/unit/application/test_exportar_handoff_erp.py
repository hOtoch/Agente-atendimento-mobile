"""Exportacao do handoff para o ERP: cliente + orcamento, idempotencia e isolamento de falhas.

Tudo com fakes em memoria; o `PedidoPort` falso so registra o que receberia. Nenhuma chamada ao
Mercado Phone real. Os valores da proposta sao sinteticos e propositalmente "quebrados" (nao
fecham em conta) para provar que nada e recalculado no caminho.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.application.agente.estado import EstadoAtendimento
from app.application.canal import Canal
from app.application.config.entradas import EntradaVendedor
from app.application.config.memoria import MemoriaConexaoErp, MemoriaEstoqueLocal, MemoriaVendedores
from app.application.config.modelos import LinhaEstoqueLocal
from app.application.exportar_handoff_erp import (
    EVENTO_ERP_HANDOFF,
    ExportarHandoffParaErp,
    ServicosDaExportacao,
)
from app.application.handoff import ResumoHandoff
from app.application.painel.memoria import RepositorioPainelEmMemoria
from app.application.pedido_erp import (
    DadosHandoff,
    FalhaPedidoErp,
    FormaPedido,
    RegistroErp,
    VinculoErp,
)
from app.domain.conexao_erp import ConexaoErp
from app.domain.estoque import Condicao
from app.domain.ficha import Ficha, TipoPagamento
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

D = Decimal
SKU = "TESTE-00042"
AGORA = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)


def resumo(**campos: Any) -> ResumoHandoff:
    base: dict[str, Any] = {
        "motivo": "Cliente quer fechar",
        "aparelho_desejado": "iPhone 15 Pro 256GB",
        "troca": "iPhone 13 128GB",
        "valor_troca": D("1200"),
        "proposta": "Cartão de crédito em 12x",
        "valor_proposta": D("3333.33"),
        "forma_pagamento": "Crédito 12x Mastercard",
        "data_prevista": date(2026, 11, 30),
        "pendencias": [],
        "observacoes": "Quer fechar na sexta.",
        "gerado_em": AGORA,
    }
    base.update(campos)
    return ResumoHandoff(**base)


def proposta_credito() -> dict[str, Any]:
    """Formato real de `montar_proposta`; os numeros NAO fecham em conta de proposito."""
    return {
        "bloqueado": False,
        "aparelho": {"sku": SKU, "modelo": "iPhone 15 Pro", "capacidade": "256GB"},
        "preco_aparelho": "4200.00",
        "troca": {"status": "avaliada", "valor": "1200.00", "descontos_aplicados": []},
        "desconto": {"negociado": "50.00", "oportunidade_unica": "50.00", "total": "100.00"},
        "base_parcelamento": "2900.00",
        "forma_escolhida": {
            "rotulo": "Cartão de crédito em 12x Mastercard",
            "parcelas": 12,
            "valor_parcela": "277.77",
            "total_pago": "3333.24",
            "taxa": "9,00%",
        },
    }


def estado(
    *,
    proposta: dict[str, Any] | None = None,
    tipo: TipoPagamento = TipoPagamento.CREDITO,
    sku: str | None = SKU,
) -> EstadoAtendimento:
    ficha = Ficha.vazia().com_interesse(sku_estoque_confirmado=sku)
    ficha = ficha.com_pagamento(tipo=tipo, parcelas=12, bandeira=Bandeira.MASTERCARD)
    return EstadoAtendimento(ficha=ficha, ultima_proposta=proposta)


class VinculosEmMemoria:
    def __init__(self) -> None:
        self.dados: dict[UUID, VinculoErp] = {}
        self.gravacoes: list[tuple[UUID, int | None, int | None]] = []

    async def obter(self, loja_id: UUID, lead_id: UUID) -> VinculoErp:
        return self.dados.get(lead_id, VinculoErp())

    async def gravar(
        self,
        loja_id: UUID,
        lead_id: UUID,
        *,
        cliente_id: int | None = None,
        orcamento_id: int | None = None,
    ) -> None:
        atual = await self.obter(loja_id, lead_id)
        self.dados[lead_id] = VinculoErp(
            cliente_id=cliente_id if cliente_id is not None else atual.cliente_id,
            orcamento_id=orcamento_id if orcamento_id is not None else atual.orcamento_id,
        )
        self.gravacoes.append((lead_id, cliente_id, orcamento_id))


class PedidoFalso:
    def __init__(self, *, falha: FalhaPedidoErp | None = None) -> None:
        self.chamadas: list[DadosHandoff] = []
        self.falha = falha
        self.sessoes_abertas_na_chamada: list[int] = []
        self.avisos: tuple[str, ...] = ()
        self._ids = (501, 701)
        self.conexoes: list[ConexaoErp] = []
        self.ao_chamar: Any = None

    async def registrar_handoff(self, conexao: ConexaoErp, dados: DadosHandoff) -> RegistroErp:
        self.conexoes.append(conexao)
        self.chamadas.append(dados)
        if self.ao_chamar is not None:
            self.ao_chamar()
        if self.falha is not None:
            raise self.falha
        cliente = dados.cliente_id or self._ids[0]
        orcamento = None
        if dados.orcamento is not None:
            orcamento = dados.orcamento_id or self._ids[1]
        return RegistroErp(cliente_id=cliente, orcamento_id=orcamento, avisos=self.avisos)


class Cenario:
    def __init__(self, *, exportar: bool = True, pedido: PedidoFalso | None = None) -> None:
        self.loja = uuid4()
        self.conexoes = MemoriaConexaoErp()
        self.repo = RepositorioPainelEmMemoria()
        self.vendedores = MemoriaVendedores()
        self.estoque = MemoriaEstoqueLocal()
        self.vinculos = VinculosEmMemoria()
        self.pedido = pedido or PedidoFalso()
        self.exportar_ligado = exportar
        self.sessoes = 0
        self.sessoes_abertas = 0
        self.caso = ExportarHandoffParaErp(abrir=self._abrir, pedido=self.pedido)
        self.pedido.ao_chamar = lambda: self.pedido.sessoes_abertas_na_chamada.append(
            self.sessoes_abertas
        )

    @asynccontextmanager
    async def _abrir(self) -> AsyncIterator[ServicosDaExportacao]:
        self.sessoes += 1
        self.sessoes_abertas += 1
        try:
            yield ServicosDaExportacao(
                conexoes=self.conexoes,
                repo=self.repo,
                vendedores=self.vendedores,
                estoque=self.estoque,
                vinculos=self.vinculos,
            )
        finally:
            self.sessoes_abertas -= 1

    async def preparar(
        self,
        *,
        nome: str | None = "Marcos",
        telefone: str = "5511912345678",
        canal: Canal = Canal.WHATSAPP,
        estado_lead: EstadoAtendimento | None = None,
        codigo_erp: str | None = "9",
        produto_id: int | None = 777,
        com_vendedor: bool = True,
        com_conexao: bool = True,
    ) -> UUID:
        if com_conexao:
            await self.conexoes.salvar(
                ConexaoErp(self.loja, 12, ativo=True, exportar_handoff=self.exportar_ligado)
            )
        vendedor_id = None
        if com_vendedor:
            if codigo_erp is None:  # criado a mao no painel: sem codigo do ERP
                (v,) = await self.vendedores.substituir(
                    self.loja, [EntradaVendedor(None, "Carla", None, D("100"), True)]
                )
            else:
                v = await self.vendedores.criar_do_erp(self.loja, codigo_erp, "Carla")
            vendedor_id = v.id
            self.repo.adicionar_vendedor(self.loja, v.id, "Carla")
        await self.estoque.substituir(self.loja, [_linha(produto_id)])
        return self.repo.adicionar_lead(
            self.loja,
            telefone=telefone,
            nome=nome,
            canal=canal,
            dono="vendedor",
            vendedor_id=vendedor_id,
            estado=estado_lead if estado_lead is not None else estado(proposta=proposta_credito()),
        )

    def eventos(self, lead: UUID) -> list[Any]:
        return [e for e in self.repo.eventos_de(lead) if e.tipo == EVENTO_ERP_HANDOFF]


def _linha(produto_id: int | None) -> LinhaEstoqueLocal:
    return LinhaEstoqueLocal(
        sku=SKU,
        modelo=ModeloAparelho.de("iPhone 15 Pro", "Apple"),
        capacidade=Capacidade("256gb"),
        cor="PRETO",
        condicao=Condicao.SEMINOVO,
        preco_pix=Dinheiro.de("4200"),
        quantidade=1,
        bateria_pct=90,
        erp_produto_id=produto_id,
    )


# --- criterio: 1 cliente + 1 orcamento com os valores da proposta ------------------------------


async def test_handoff_gera_cliente_e_orcamento_com_os_valores_da_proposta() -> None:
    c = Cenario()
    lead = await c.preparar()
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert resultado is not None and resultado.ok
    assert (resultado.cliente_id, resultado.orcamento_id) == (501, 701)
    (dados,) = c.pedido.chamadas
    assert dados.nome_cliente == "Marcos" and dados.telefone == "5511912345678"
    assert dados.cliente_id is None and dados.orcamento_id is None
    o = dados.orcamento
    assert o is not None and o.vendedor_id_erp == 9
    (item,) = o.itens
    # valores EXATAMENTE os da proposta do dominio (nada recalculado no caminho)
    assert (item.produto_id, item.quantidade) == (777, 1)
    assert (item.valor_unitario, item.desconto) == (D("4200.00"), D("100.00"))
    assert [(p.forma, p.valor, p.parcelas) for p in o.pagamentos] == [
        (FormaPedido.CREDITO, D("3333.24"), 12),
        (FormaPedido.APARELHO, D("1200.00"), 1),
    ]
    assert "pré-avaliação, valor final confirmado na loja" in o.observacao.lower()
    assert "iPhone 15 Pro 256GB" in o.observacao and "Cliente quer fechar" in o.observacao
    assert o.previsao == date(2026, 11, 30)


async def test_grava_os_ids_no_lead_e_registra_o_evento_para_o_painel() -> None:
    c = Cenario()
    lead = await c.preparar()
    await c.caso.exportar(c.loja, lead, resumo())

    assert c.vinculos.dados[lead] == VinculoErp(cliente_id=501, orcamento_id=701)
    (evento,) = c.eventos(lead)
    assert evento.payload["ok"] is True
    assert (evento.payload["cliente_id"], evento.payload["orcamento_id"]) == (501, 701)
    assert evento.payload["avisos"] == [] and evento.payload["erro"] is None


async def test_pix_usa_o_valor_a_vista_da_proposta() -> None:
    proposta = proposta_credito()
    proposta["forma_escolhida"] = {"rotulo": "Pix ou dinheiro à vista", "valor_a_vista": "1.23"}
    proposta["troca"] = {"status": "sem_troca"}
    c = Cenario()
    lead = await c.preparar(estado_lead=estado(proposta=proposta, tipo=TipoPagamento.PIX))
    await c.caso.exportar(c.loja, lead, resumo(troca=None, valor_troca=None))

    o = c.pedido.chamadas[0].orcamento
    assert o is not None
    assert [(p.forma, p.valor, p.parcelas) for p in o.pagamentos] == [
        (FormaPedido.PIX, D("1.23"), 1)
    ]


async def test_debito_vira_uma_parcela_no_valor_total_da_proposta() -> None:
    proposta = proposta_credito()
    proposta["forma_escolhida"] = {"rotulo": "Débito Visa", "parcelas": 1, "total_pago": "2950.01"}
    c = Cenario()
    lead = await c.preparar(estado_lead=estado(proposta=proposta, tipo=TipoPagamento.DEBITO))
    await c.caso.exportar(c.loja, lead, resumo())

    o = c.pedido.chamadas[0].orcamento
    assert o is not None
    assert (o.pagamentos[0].forma, o.pagamentos[0].valor) == (FormaPedido.DEBITO, D("2950.01"))


async def test_entrada_mais_credito_separa_a_entrada_em_pix_e_o_resto_no_cartao() -> None:
    proposta = proposta_credito()
    proposta["troca"] = {"status": "sem_troca"}
    proposta["forma_escolhida"] = {
        "rotulo": "Entrada de 1000.00 + cartão em 10x",
        "parcelas": 10,
        "valor_parcela": "321.00",
        "total_pago": "4210.00",
        "entrada": "1000.00",
    }
    c = Cenario()
    lead = await c.preparar(
        estado_lead=estado(proposta=proposta, tipo=TipoPagamento.ENTRADA_MAIS_CREDITO)
    )
    await c.caso.exportar(c.loja, lead, resumo())

    o = c.pedido.chamadas[0].orcamento
    assert o is not None
    assert [(p.forma, p.valor, p.parcelas) for p in o.pagamentos] == [
        (FormaPedido.PIX, D("1000.00"), 1),
        (FormaPedido.CREDITO, D("3210.00"), 10),
    ]


async def test_troca_nao_avaliada_nao_gera_pagamento_aparelho() -> None:
    proposta = proposta_credito()
    proposta["troca"] = {"status": "avaliacao_na_loja", "motivo": "x"}
    c = Cenario()
    lead = await c.preparar(estado_lead=estado(proposta=proposta))
    await c.caso.exportar(c.loja, lead, resumo())

    o = c.pedido.chamadas[0].orcamento
    assert o is not None
    assert [p.forma for p in o.pagamentos] == [FormaPedido.CREDITO]


# --- criterio: idempotencia -----------------------------------------------------------------


async def test_segundo_handoff_do_mesmo_lead_edita_o_orcamento() -> None:
    c = Cenario()
    lead = await c.preparar()
    await c.caso.exportar(c.loja, lead, resumo())
    segundo = await c.caso.exportar(c.loja, lead, resumo())

    primeiro, editado = c.pedido.chamadas
    assert (primeiro.cliente_id, primeiro.orcamento_id) == (None, None)
    assert (editado.cliente_id, editado.orcamento_id) == (501, 701)
    assert segundo is not None and segundo.orcamento_editado is True
    assert c.vinculos.dados[lead] == VinculoErp(501, 701)


# --- criterio: falha do ERP nao afeta o handoff ----------------------------------------------


async def test_falha_do_erp_nao_levanta_e_vira_aviso_e_evento() -> None:
    c = Cenario(pedido=PedidoFalso(falha=FalhaPedidoErp("ERP fora do ar")))
    lead = await c.preparar()
    resultado = await c.caso.exportar(c.loja, lead, resumo())  # nao levanta

    assert resultado is not None and resultado.ok is False
    assert resultado.erro == "ERP fora do ar"
    (evento,) = c.eventos(lead)
    assert evento.payload["ok"] is False and evento.payload["erro"] == "ERP fora do ar"
    assert c.vinculos.dados.get(lead, VinculoErp()) == VinculoErp()
    # o lead continua com o vendedor (a exportacao so le)
    assert c.repo.leads[lead].dono == "vendedor"


async def test_falha_depois_de_criar_o_cliente_guarda_o_cliente_para_a_proxima_tentativa() -> None:
    c = Cenario(pedido=PedidoFalso(falha=FalhaPedidoErp("orcamento recusado", cliente_id=55)))
    lead = await c.preparar()
    await c.caso.exportar(c.loja, lead, resumo())

    assert c.vinculos.dados[lead] == VinculoErp(cliente_id=55, orcamento_id=None)
    c.pedido.falha = None
    await c.caso.exportar(c.loja, lead, resumo())
    assert c.pedido.chamadas[-1].cliente_id == 55


async def test_excecao_inesperada_do_adaptador_tambem_e_contida() -> None:
    class Quebrado(PedidoFalso):
        async def registrar_handoff(self, conexao: ConexaoErp, dados: DadosHandoff) -> RegistroErp:
            raise RuntimeError("bug")

    c = Cenario(pedido=Quebrado())
    lead = await c.preparar()
    resultado = await c.caso.exportar(c.loja, lead, resumo())
    assert resultado is not None and resultado.ok is False
    assert len(c.eventos(lead)) == 1


# --- criterio: exportar_handoff desligado --------------------------------------------------------


async def test_exportar_handoff_desligado_nao_chama_o_erp() -> None:
    c = Cenario(exportar=False)
    lead = await c.preparar()
    assert await c.caso.exportar(c.loja, lead, resumo()) is None
    assert c.pedido.chamadas == []
    assert c.eventos(lead) == [] and c.vinculos.gravacoes == []


async def test_loja_sem_conexao_com_o_erp_nao_chama_o_erp() -> None:
    c = Cenario()
    lead = await c.preparar(com_conexao=False)
    assert await c.caso.exportar(c.loja, lead, resumo()) is None
    assert c.pedido.chamadas == []


async def test_lead_inexistente_so_loga() -> None:
    c = Cenario()
    await c.preparar()
    assert await c.caso.exportar(c.loja, uuid4(), resumo()) is None
    assert c.pedido.chamadas == []


# --- cliente sem orcamento: o que falta vira aviso ---------------------------------------------


async def test_sem_proposta_cria_so_o_cliente_e_registra_o_motivo() -> None:
    c = Cenario()
    lead = await c.preparar(estado_lead=estado(proposta=None))
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert c.pedido.chamadas[0].orcamento is None
    assert resultado is not None and resultado.ok and resultado.orcamento_id is None
    assert any("proposta" in a for a in resultado.avisos)
    assert c.vinculos.dados[lead] == VinculoErp(cliente_id=501, orcamento_id=None)


async def test_vendedor_sem_codigo_erp_cria_so_o_cliente_e_avisa() -> None:
    c = Cenario()
    lead = await c.preparar(codigo_erp=None)
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert c.pedido.chamadas[0].orcamento is None
    assert resultado is not None and any("vendedor" in a for a in resultado.avisos)


async def test_sem_vendedor_atribuido_cria_so_o_cliente_e_avisa() -> None:
    c = Cenario()
    lead = await c.preparar(com_vendedor=False)
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert c.pedido.chamadas[0].orcamento is None
    assert resultado is not None and any("vendedor" in a for a in resultado.avisos)


async def test_sku_sem_produto_do_erp_cria_so_o_cliente_e_avisa() -> None:
    c = Cenario()
    lead = await c.preparar(produto_id=None)
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert c.pedido.chamadas[0].orcamento is None
    assert resultado is not None and any(SKU in a for a in resultado.avisos)


async def test_avisos_do_adaptador_entram_no_resultado_e_no_evento() -> None:
    pedido = PedidoFalso()
    pedido.avisos = ("forma de pagamento 'credito' nao encontrada no ERP",)
    c = Cenario(pedido=pedido)
    lead = await c.preparar()
    resultado = await c.caso.exportar(c.loja, lead, resumo())

    assert resultado is not None and resultado.avisos == pedido.avisos
    assert c.eventos(lead)[0].payload["avisos"] == list(pedido.avisos)


# --- cliente: nome e telefone ----------------------------------------------------------------


async def test_lead_sem_nome_vira_cliente_whatsapp_com_os_ultimos_4_digitos() -> None:
    c = Cenario()
    lead = await c.preparar(nome=None, telefone="5511912345678")
    await c.caso.exportar(c.loja, lead, resumo())
    assert c.pedido.chamadas[0].nome_cliente == "Cliente WhatsApp 5678"


async def test_canal_sem_telefone_real_nao_envia_telefone_ao_erp() -> None:
    c = Cenario()
    lead = await c.preparar(canal=Canal.WEBCHAT, telefone="sessao-abc-123")
    await c.caso.exportar(c.loja, lead, resumo())
    assert c.pedido.chamadas[0].telefone is None


async def test_a_conexao_chega_ao_adaptador() -> None:
    c = Cenario()
    lead = await c.preparar()
    await c.caso.exportar(c.loja, lead, resumo())
    assert c.pedido.conexoes[0].system_unit_id == 12


# --- transacao ---------------------------------------------------------------------------------


async def test_a_chamada_ao_erp_acontece_com_a_sessao_fechada() -> None:
    c = Cenario()
    lead = await c.preparar()
    await c.caso.exportar(c.loja, lead, resumo())
    assert c.pedido.sessoes_abertas_na_chamada == [0]
    assert c.sessoes == 2  # leitura + gravacao dos ids/evento


async def test_o_gancho_nunca_levanta_mesmo_com_o_banco_falhando() -> None:
    c = Cenario()
    lead = await c.preparar()

    @asynccontextmanager
    async def quebrada() -> AsyncIterator[ServicosDaExportacao]:
        raise ConnectionError("banco fora")
        yield  # pragma: no cover

    caso = ExportarHandoffParaErp(abrir=quebrada, pedido=c.pedido)
    await caso.handoff_solicitado(c.loja, lead, resumo())  # nao levanta
    assert c.pedido.chamadas == []


async def test_handoff_solicitado_e_o_gancho_que_exporta() -> None:
    c = Cenario()
    lead = await c.preparar()
    await c.caso.handoff_solicitado(c.loja, lead, resumo())
    assert len(c.pedido.chamadas) == 1
