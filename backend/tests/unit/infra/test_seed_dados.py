"""Dados do seed da loja demo: passam na validacao dos casos de uso e sao coerentes."""

from decimal import Decimal

from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.memoria import criar_casos_em_memoria
from app.application.config.validacao import validar_pesos_vendedores
from app.domain.bandeira import Bandeira
from app.domain.troca import SEM
from app.domain.valores import MODELOS_IPHONE, Capacidade, Dinheiro, ModeloAparelho
from app.infra.seed import LOJA_DEMO_ID, aplicar_dados
from app.infra.seed_data.vendedores import VENDEDORES

D = Decimal
MASTERCARD = [
    "3.44", "4.65", "5.44", "6.36", "7.15", "7.99", "9.33", "9.34", "9.58",
    "9.59", "10.53", "10.54", "12.69", "13.44", "14.19", "14.94", "15.03", "15.04",
]  # fmt: skip


async def _semeado() -> tuple[CasosDeUsoConfig, object]:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    return casos, loja_id


def test_id_fixo_da_loja_demo() -> None:
    assert str(LOJA_DEMO_ID) == "00000000-0000-4000-8000-00000000de30"


async def test_dados_passam_pela_validacao_dos_casos_de_uso() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)  # levanta ErrosDeValidacao se algo estiver invalido
    assert await casos.obter_perfil(loja_id) is not None
    assert await casos.obter_preco(loja_id) is not None
    assert len(await casos.obter_estoque(loja_id)) >= 20


def test_vendedores_50_30_20_ativos_e_validos() -> None:
    assert [v.peso_percentual for v in VENDEDORES] == [D(50), D(30), D(20)]
    assert all(v.ativo for v in VENDEDORES)
    assert validar_pesos_vendedores([v.peso_percentual for v in VENDEDORES]) == []
    assert len({v.id for v in VENDEDORES}) == 3


async def test_regras_de_preco_da_demo() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    preco = await casos.obter_preco(loja_id)
    assert preco is not None
    assert preco.regras.max_parcelas == 18
    assert preco.regras.repassa_taxa
    assert preco.regras.aceita_entrada_mais_cartao
    assert preco.politica.teto == Dinheiro.de(100)
    assert preco.politica.degrau == Dinheiro.de(50)
    assert preco.oportunidade.ativa
    assert preco.oportunidade.dias_minimos == 14
    assert preco.oportunidade.valor == Dinheiro.de(100)
    assert not preco.oportunidade.conta_no_teto


async def test_taxas_completas_com_mastercard_oficial() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    taxas = (await casos.obter_taxas(loja_id)).taxas
    for bandeira in Bandeira:
        for chave in (*range(1, 19), "debito"):
            assert (chave, bandeira) in taxas
    assert [taxas[(n, Bandeira.MASTERCARD)] for n in range(1, 19)] == [D(x) for x in MASTERCARD]
    assert all(taxas[(n, Bandeira.VISA)] is None for n in range(1, 19))
    assert taxas[("debito", Bandeira.MASTERCARD)] == D("1.49")


async def test_troca_cobre_iphone_11_a_17_pro_max_e_linha_oficial() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    tabela = await casos.obter_troca(loja_id)
    nomes = {linha.modelo.nome for linha in tabela.linhas_apple}
    assert nomes == set(MODELOS_IPHONE[MODELOS_IPHONE.index("iPhone 11") :])
    linha = tabela.buscar(ModeloAparelho.de("iPhone 16"), Capacidade(128))
    assert linha is not None
    assert linha.valor_sem_detalhes == Dinheiro.de(3100)
    assert linha.desconto_tela == Dinheiro.de(600)
    assert linha.desconto_traseira is SEM
    assert linha.desconto_carcaca == Dinheiro.de(300)
    assert linha.desconto_bateria == Dinheiro.de(190)
    assert linha.limite_bateria_pct == 80


async def test_troca_coerente_capacidade_geracao_e_descontos() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    linhas = (await casos.obter_troca(loja_id)).linhas_apple
    por_modelo: dict[str, dict[int, Dinheiro]] = {}
    for linha in linhas:
        por_modelo.setdefault(linha.modelo.nome, {})[int(linha.capacidade)] = (
            linha.valor_sem_detalhes
        )
        soma = Dinheiro.zero()
        for d in (
            linha.desconto_tela,
            linha.desconto_traseira,
            linha.desconto_carcaca,
            linha.desconto_bateria,
        ):
            if d is not SEM:
                assert isinstance(d, Dinheiro)
                soma = soma + d
        assert soma < linha.valor_sem_detalhes
    for caps in por_modelo.values():
        valores = [caps[c] for c in sorted(caps)]
        assert valores == sorted(valores)
        assert len(set(valores)) == len(valores)
    # mesma variante e capacidade: geracao mais nova vale mais
    for sufixo in ("", " Plus", " Pro", " Pro Max"):
        for cap in (64, 128, 256, 512, 1024):
            serie = [
                por_modelo[f"iPhone {g}{sufixo}"][cap]
                for g in (11, 12, 13, 14, 15, 16, 17)
                if cap in por_modelo.get(f"iPhone {g}{sufixo}", {})
            ]
            assert serie == sorted(serie)
            assert len(set(serie)) == len(serie)
    tela = {linha.modelo.nome: linha.desconto_tela for linha in linhas}
    assert isinstance(tela["iPhone 15 Pro"], Dinheiro)
    assert isinstance(tela["iPhone 15"], Dinheiro)
    assert tela["iPhone 15 Pro"] > tela["iPhone 15"]
    assert any(
        linha.modelo.nome == "iPhone 11" and linha.desconto_traseira is SEM for linha in linhas
    )


async def test_estoque_com_seminovos_e_quantidade_zero() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    estoque = await casos.obter_estoque(loja_id)
    assert 20 <= len(estoque) <= 35
    assert {e.condicao for e in estoque} == {"novo", "seminovo"}
    assert any(e.quantidade == 0 for e in estoque)
    assert any(e.condicao == "seminovo" and e.bateria_pct is None for e in estoque)
    assert len({e.sku for e in estoque}) == len(estoque)
    for e in estoque:
        if e.condicao == "seminovo":
            if e.bateria_pct is None:  # ao menos um seminovo sem bateria cadastrada, de proposito
                continue
            assert 85 <= e.bateria_pct <= 100


async def test_estoque_vale_mais_que_a_troca_do_mesmo_modelo() -> None:
    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    tabela = await casos.obter_troca(loja_id)
    checados = 0
    for e in await casos.obter_estoque(loja_id):
        linha = tabela.buscar(e.modelo, e.capacidade)
        if linha is not None and linha.capacidade == e.capacidade:
            assert e.preco_pix > linha.valor_sem_detalhes, e.sku
            checados += 1
    assert checados >= 20


async def test_pagamento_da_demo_liga_todas_as_formas_e_tem_chave_pix_ficticia() -> None:
    from app.domain.ficha import TipoPagamento

    casos = criar_casos_em_memoria()
    loja_id = await casos.criar_loja("Demo")
    await aplicar_dados(casos, loja_id)
    pagamento = await casos.obter_pagamento(loja_id)
    assert set(pagamento.formas.tipos()) == set(TipoPagamento)
    assert pagamento.chave_pix is not None
    assert pagamento.chave_pix.chave == "pix@lojademo.exemplo"  # fictícia (domínio .exemplo)
    checklist = await casos.checklist(loja_id)
    assert next(i for i in checklist if i.chave == "pagamento").completo
