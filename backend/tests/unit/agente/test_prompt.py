"""Prompt de sistema por loja e mensagem de estado (#23). Sem chamadas a API."""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.application.agente.prompt import (
    ROTULOS_PENDENCIA,
    carregar_prefixo,
    mensagem_estado,
    montar_sistema,
)
from app.application.config.modelos import ConfigPreco, PerfilLoja
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.ficha import Ficha, Pendencia, TipoPagamento, pendencias
from app.domain.formas_pagamento import FormasAceitas
from app.domain.pagamento import DescontoPixNenhum, RegrasPreco
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

SNAPSHOTS = Path(__file__).parent / "snapshots"
HOJE = date(2026, 11, 20)

FERRAMENTAS = (
    "registrar_interesse",
    "consultar_estoque",
    "confirmar_item",
    "registrar_usado",
    "registrar_compra",
    "registrar_leitura_imagem",
    "calcular_proposta",
    "liberar_desconto",
    "fechar_acordo",
    "chamar_vendedor",
)


def perfil_demo() -> PerfilLoja:
    return PerfilLoja(
        nome_exibicao="Loja Demo Celulares",
        tom_de_voz="Amigável e direto, sem gírias pesadas.",
        endereco="Rua das Palmeiras, 123, Centro",
        horarios={"seg": "09:00-18:00", "sab": "09:00-14:00"},
        whatsapp_contato="+55 11 90000-0000",
    )


def perfil_outra() -> PerfilLoja:
    return PerfilLoja(
        nome_exibicao="Mobile Sul",
        tom_de_voz="Descontraído.",
        endereco="Av. Brasil, 1",
        horarios={"seg-sex": "10:00-19:00"},
        whatsapp_contato="+55 51 90000-1111",
    )


def config_demo() -> ConfigPreco:
    return ConfigPreco(
        regras=RegrasPreco(
            max_parcelas=18,
            repassa_taxa=True,
            desconto_pix=DescontoPixNenhum(),
            aceita_entrada_mais_cartao=True,
        ),
        politica=PoliticaDesconto(teto=Dinheiro.de(100), degrau=Dinheiro.de(50)),
        oportunidade=RegraOportunidadeUnica(ativa=True, dias_minimos=14, valor=Dinheiro.de(100)),
    )


def ficha_intermediaria() -> Ficha:
    return (
        Ficha.vazia()
        .com_interesse(
            modelo=ModeloAparelho.de("iPhone 15 Pro"),
            capacidade=Capacidade(256),
            cor="Titânio natural",
            sku_estoque_confirmado="SKU-1",
        )
        .com(tem_troca=True)
        .com_usado(
            modelo=ModeloAparelho.de("iPhone 13"),
            capacidade=Capacidade(128),
            tela_danificada=False,
            traseira_danificada=True,
        )
    )


def ficha_completa() -> Ficha:
    return (
        ficha_intermediaria()
        .com_usado(
            carcaca_marcada=False,
            bateria_pct=87,
            camera_ok=True,
            outros_defeitos=(),
            peca_trocada=False,
        )
        .com(data_prevista_compra=date(2026, 11, 27))
        .com_pagamento(tipo=TipoPagamento.PIX)
    )


def estado(
    ficha: Ficha,
    *,
    estoque_consultado: bool = True,
    proposta_apresentada: bool = False,
    desconto_liberado: str | None = None,
    handoff_solicitado: bool = False,
    formas: FormasAceitas | None = None,
    acordo_fechado: bool = False,
) -> str:
    return mensagem_estado(
        ficha,
        hoje=HOJE,
        estoque_consultado=estoque_consultado,
        proposta_apresentada=proposta_apresentada,
        desconto_liberado=desconto_liberado,
        handoff_solicitado=handoff_solicitado,
        formas=formas,
        acordo_fechado=acordo_fechado,
    )


def _linha_proxima_pergunta(msg: str) -> str:
    return next(x for x in msg.splitlines() if x.startswith("PRÓXIMA PERGUNTA"))


def _snapshot(nome: str, conteudo: str) -> None:
    caminho = SNAPSHOTS / nome
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        caminho.write_text(conteudo, encoding="utf-8", newline="\n")
    assert caminho.exists(), f"snapshot ausente: rode com UPDATE_SNAPSHOTS=1 ({nome})"
    esperado = caminho.read_text(encoding="utf-8")
    assert conteudo == esperado, f"snapshot {nome} mudou; revise e atualize com UPDATE_SNAPSHOTS=1"


# --- snapshot -----------------------------------------------------------------------------


def test_snapshot_sistema_loja_demo() -> None:
    sistema = montar_sistema(perfil_demo(), config_demo())
    _snapshot("sistema_loja_demo.txt", "\n\n=====BREAKPOINT=====\n\n".join(sistema) + "\n")


def test_snapshot_mensagem_estado_ficha_intermediaria() -> None:
    _snapshot("estado_ficha_intermediaria.txt", estado(ficha_intermediaria()) + "\n")


# --- prefixo estavel ----------------------------------------------------------------------


def test_prefixo_identico_entre_lojas_diferentes() -> None:
    a = montar_sistema(perfil_demo(), config_demo())
    b = montar_sistema(perfil_outra(), None)
    assert a[0] == b[0] == carregar_prefixo()
    assert a[1] != b[1]


def test_montar_sistema_tem_dois_blocos() -> None:
    assert len(montar_sistema(perfil_demo(), config_demo())) == 2


def test_prefixo_tem_tamanho_minimo_para_cache() -> None:
    palavras = len(carregar_prefixo().split())
    assert palavras * 1.3 > 600, f"prefixo curto demais: {palavras} palavras"


def test_prefixo_cita_todas_as_ferramentas() -> None:
    prefixo = carregar_prefixo()
    for nome in FERRAMENTAS:
        assert nome in prefixo, nome


def test_prefixo_sem_data_e_sem_nome_de_loja() -> None:
    prefixo = carregar_prefixo()
    for nome in (perfil_demo().nome_exibicao, perfil_outra().nome_exibicao):
        assert nome not in prefixo
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}", prefixo)
    assert not re.search(r"R\$\s*\d", prefixo)


def test_bloco_da_loja_tem_dados_e_pagamentos_sem_taxas() -> None:
    bloco = montar_sistema(perfil_demo(), config_demo())[1]
    for trecho in (
        "Loja Demo Celulares",
        "Amigável e direto",
        "Rua das Palmeiras",
        "09:00-18:00",
        "+55 11 90000-0000",
        "18",
        "Pix",
        "débito",
        "crédito",
        "entrada",
    ):
        assert trecho in bloco, trecho
    assert "%" not in bloco
    assert "100" not in bloco  # nem teto de desconto nem valor da oportunidade


def test_prefixo_nao_e_so_de_iphone() -> None:
    prefixo = carregar_prefixo()
    assert "loja de iPhones" not in prefixo
    assert "celulares" in prefixo


def test_bloco_da_loja_lista_as_marcas_do_estoque() -> None:
    bloco = montar_sistema(perfil_demo(), config_demo(), marcas=["Apple", "Samsung", "Xiaomi"])[1]
    linha = next(x for x in bloco.splitlines() if x.startswith("Marcas"))
    assert "iPhone" in linha and "Samsung" in linha and "Xiaomi" in linha


def test_bloco_da_loja_sem_estoque_nao_fala_de_marcas() -> None:
    assert "Marcas" not in montar_sistema(perfil_demo(), config_demo())[1]


def test_bloco_da_loja_sem_config_omite_pagamento() -> None:
    bloco = montar_sistema(perfil_outra(), None)[1]
    assert "Mobile Sul" in bloco
    assert "parcela" not in bloco.lower()


# --- mensagem de estado -------------------------------------------------------------------


def test_estado_inclui_data_de_hoje() -> None:
    assert "2026-11-20" in estado(Ficha.vazia())


def test_pendencias_aparecem_na_ordem() -> None:
    ficha = ficha_intermediaria()
    msg = estado(ficha)
    posicoes = [msg.index(ROTULOS_PENDENCIA[p]) for p in pendencias(ficha)]
    assert posicoes == sorted(posicoes)
    assert len(set(posicoes)) == len(posicoes)


def test_proxima_pergunta_corresponde_a_primeira_pendencia() -> None:
    ficha = ficha_intermediaria()
    assert pendencias(ficha)[0] is Pendencia.USADO_CARCACA
    assert "carcaça" in _linha_proxima_pergunta(estado(ficha)).lower()


def test_ficha_vazia_pergunta_aparelho_desejado() -> None:
    msg = estado(Ficha.vazia(), estoque_consultado=False)
    assert "modelo" in _linha_proxima_pergunta(msg).lower()
    assert "iphone" not in _linha_proxima_pergunta(msg).lower()


def test_ficha_conhecida_aparece_em_linguagem_natural() -> None:
    msg = estado(ficha_intermediaria())
    assert "iPhone 15 Pro" in msg
    assert "256GB" in msg
    assert "iPhone 13" in msg
    assert "traseira" in msg.lower()


def test_sem_troca_dispensa_perguntas_do_usado() -> None:
    ficha = (
        Ficha.vazia()
        .com_interesse(
            modelo=ModeloAparelho.de("iPhone 15"),
            capacidade=Capacidade(128),
            sku_estoque_confirmado="SKU-2",
        )
        .com(tem_troca=False)
    )
    msg = estado(ficha)
    assert "sem aparelho na troca" in msg.lower()
    for p in Pendencia:
        if p.name.startswith("USADO_"):
            assert ROTULOS_PENDENCIA[p] not in msg
    assert "quando" in _linha_proxima_pergunta(msg).lower()


def test_pronto_para_proposta() -> None:
    msg = estado(ficha_completa())
    assert "PODE chamar calcular_proposta" in msg
    assert "PRÓXIMA PERGUNTA" not in msg


def test_nao_pode_chamar_calcular_proposta_com_pendencias() -> None:
    assert "NÃO chame calcular_proposta" in estado(ficha_intermediaria())


def test_estado_reflete_proposta_desconto_e_handoff() -> None:
    msg = estado(
        ficha_completa(),
        proposta_apresentada=True,
        desconto_liberado="R$ 50,00",
        handoff_solicitado=True,
    )
    assert "proposta já foi apresentada" in msg.lower()
    assert "R$ 50,00" in msg
    assert "chamar_vendedor" in msg


def test_estado_avisa_para_consultar_estoque_quando_nao_consultado() -> None:
    ficha = Ficha.vazia().com_interesse(
        modelo=ModeloAparelho.de("iPhone 15"), capacidade=Capacidade(128)
    )
    assert "consultar_estoque" in estado(ficha, estoque_consultado=False)


def test_so_com_modelo_manda_consultar_o_estoque_para_listar_as_capacidades() -> None:
    ficha = Ficha.vazia().com_interesse(modelo=ModeloAparelho.de("iPhone 16"))
    proxima = _linha_proxima_pergunta(estado(ficha, estoque_consultado=False)).lower()
    assert "consultar_estoque" in proxima
    assert "todas as capacidades" in proxima
    assert "consultar_estoque" in estado(ficha, estoque_consultado=False).split("Lembretes")[0]


def test_com_capacidades_ja_listadas_pergunta_qual_capacidade() -> None:
    ficha = Ficha.vazia().com_interesse(modelo=ModeloAparelho.de("iPhone 16"))
    proxima = _linha_proxima_pergunta(estado(ficha, estoque_consultado=True)).lower()
    assert "capacidade" in proxima and "consultar_estoque" in proxima


def test_com_capacidade_escolhida_manda_consultar_para_ver_as_cores() -> None:
    ficha = Ficha.vazia().com_interesse(
        modelo=ModeloAparelho.de("iPhone 16"), capacidade=Capacidade(128)
    )
    proxima = _linha_proxima_pergunta(estado(ficha, estoque_consultado=False)).lower()
    assert "consultar_estoque" in proxima and "cor" in proxima


def test_metodologia_pede_capacidade_antes_de_cor_e_todas_as_opcoes() -> None:
    sistema = montar_sistema(perfil_demo(), config_demo())[0]
    assert "TODAS as capacidades" in sistema
    assert "depois de ele escolher a capacidade" in sistema.lower()
    assert "nunca ofereça só uma opção" in sistema.lower()


def test_pagamento_e_data_aparecem_quando_informados() -> None:
    ficha = ficha_completa().com_pagamento(
        tipo=TipoPagamento.ENTRADA_MAIS_CREDITO, parcelas=10, entrada=Dinheiro(Decimal(500))
    )
    msg = estado(ficha)
    assert "2026-11-27" in msg
    assert "10x" in msg


# --- rotulos ------------------------------------------------------------------------------


def test_rotulos_cobrem_todas_as_pendencias() -> None:
    assert set(ROTULOS_PENDENCIA) == set(Pendencia)
    assert all(v.strip() for v in ROTULOS_PENDENCIA.values())
    assert len(set(ROTULOS_PENDENCIA.values())) == len(Pendencia)


# --- formas de pagamento aceitas pela loja ------------------------------------------------


def _formas(**sobre: bool) -> FormasAceitas:
    base = {"pix": True, "debito": True, "credito": True, "entrada_mais_cartao": True}
    return FormasAceitas.de(**(base | sobre))


def _linha_formas(bloco: str) -> str:
    return next(x for x in bloco.splitlines() if x.startswith("Formas de pagamento aceitas"))


def _ficha_so_falta_pagamento() -> Ficha:
    return (
        ficha_intermediaria()
        .com_usado(
            carcaca_marcada=False,
            bateria_pct=87,
            camera_ok=True,
            outros_defeitos=(),
            peca_trocada=False,
        )
        .com(data_prevista_compra=date(2026, 11, 27))
    )


def test_bloco_da_loja_com_todas_as_formas_mantem_o_texto() -> None:
    bloco = montar_sistema(perfil_demo(), config_demo(), formas=_formas())[1]
    assert _linha_formas(bloco) == (
        "Formas de pagamento aceitas: Pix, débito, crédito em até 18 parcelas, entrada mais cartão"
    )
    assert bloco == montar_sistema(perfil_demo(), config_demo())[1]


def test_bloco_da_loja_lista_so_as_formas_ligadas() -> None:
    formas = _formas(debito=False, entrada_mais_cartao=False)
    bloco = montar_sistema(perfil_demo(), config_demo(), formas=formas)[1]
    assert _linha_formas(bloco) == "Formas de pagamento aceitas: Pix, crédito em até 18 parcelas"
    assert "débito" not in bloco
    assert "entrada" not in bloco


def test_bloco_da_loja_sem_credito_nao_fala_de_parcelas() -> None:
    bloco = montar_sistema(perfil_demo(), config_demo(), formas=_formas(credito=False))[1]
    assert "parcela" not in bloco.lower()
    assert "crédito" not in bloco


def test_bloco_da_loja_nao_inclui_a_chave_pix() -> None:
    bloco = montar_sistema(perfil_demo(), config_demo(), formas=_formas())[1]
    assert "chave" not in bloco.lower()


def test_bloco_da_loja_sem_nenhuma_forma() -> None:
    formas = _formas(pix=False, debito=False, credito=False)
    bloco = montar_sistema(perfil_demo(), config_demo(), formas=formas)[1]
    assert "Formas de pagamento aceitas: nenhuma" in bloco


def test_pergunta_de_pagamento_sem_formas_mantem_o_texto_antigo() -> None:
    ficha = _ficha_so_falta_pagamento()
    assert pendencias(ficha) == [Pendencia.PAGAMENTO_TIPO]
    linha = _linha_proxima_pergunta(estado(ficha))
    assert linha.endswith("Pix, débito, crédito ou entrada mais cartão.")
    assert linha == _linha_proxima_pergunta(estado(ficha, formas=_formas()))


def test_pergunta_de_pagamento_lista_so_as_formas_aceitas() -> None:
    ficha = _ficha_so_falta_pagamento()
    linha = _linha_proxima_pergunta(estado(ficha, formas=_formas(debito=False, credito=False)))
    assert "Pix" in linha and "entrada" not in linha  # entrada exige crédito
    assert "débito" not in linha and "crédito" not in linha


def test_pergunta_de_pagamento_com_duas_formas_usa_ou() -> None:
    ficha = _ficha_so_falta_pagamento()
    linha = _linha_proxima_pergunta(
        estado(ficha, formas=_formas(debito=False, credito=False, entrada_mais_cartao=False))
    )
    assert "Pix" in linha
    linha2 = _linha_proxima_pergunta(
        estado(ficha, formas=_formas(credito=False, entrada_mais_cartao=False))
    )
    assert "Pix ou débito" in linha2


def test_pergunta_de_pagamento_sem_nenhuma_forma_manda_chamar_vendedor() -> None:
    ficha = _ficha_so_falta_pagamento()
    formas = _formas(pix=False, debito=False, credito=False)
    assert "chamar_vendedor" in _linha_proxima_pergunta(estado(ficha, formas=formas))


# --- fechamento do acordo pela IA (#74) -----------------------------------------------------


def test_proposta_apresentada_com_ficha_completa_lembra_de_fechar_o_acordo() -> None:
    msg = estado(ficha_completa(), proposta_apresentada=True)
    assert "fechar_acordo" in msg
    assert "chamar_vendedor" in msg
    assert "acordo_fechado" in msg


def test_sem_proposta_apresentada_nao_manda_fechar_o_acordo() -> None:
    assert "fechar_acordo" not in estado(ficha_completa())
    assert "fechar_acordo" not in estado(ficha_intermediaria(), proposta_apresentada=True)


def test_acordo_ja_fechado_manda_enviar_os_dados_e_chamar_o_vendedor() -> None:
    msg = estado(ficha_completa(), proposta_apresentada=True, acordo_fechado=True)
    assert "acordo já foi fechado" in msg.lower()
    assert "chamar_vendedor" in msg
    assert "NÃO chame fechar_acordo" not in msg


def test_lembrete_final_nao_manda_chamar_vendedor_so_porque_quer_fechar() -> None:
    msg = estado(ficha_intermediaria())
    assert "quiser fechar" not in msg
    assert "falar com uma pessoa" in msg


def test_prefixo_conduz_ate_o_fechamento_do_acordo() -> None:
    prefixo = carregar_prefixo()
    assert "Fechar o acordo" in prefixo
    assert "fechar_acordo" in prefixo
    assert "acordo_fechado" in prefixo
    assert "agradeça a preferência" in prefixo.lower()
    # o vendedor so entra por pedido de pessoa, reclamacao, fora do escopo, avaliacao ou acordo
    secao = prefixo.split("# Quando chamar o vendedor")[1].split("# Estilo")[0]
    for trecho in ("pedir para falar com uma pessoa", "reclamação", "fugir do escopo"):
        assert trecho in secao, trecho
    assert "quiser fechar a compra" not in secao
