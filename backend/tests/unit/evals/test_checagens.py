"""Cada checagem: transcricao fixture que passa e transcricao fixture que falha."""

from __future__ import annotations

from decimal import Decimal

from evals import checagens as ck
from evals.modelos import Parametros
from tests.unit.evals.fixtures import (
    BLOQUEIO,
    FRASE,
    PARAMS,
    ag,
    cli,
    ferr,
    proposta,
    transcricao,
)


def test_valores_em_reais_normaliza_formatos() -> None:
    texto = "De R$ 4.830,00 por R$4830 ou 12x de R$ 250,5 e R$ 1.200"
    assert ck.valores_em_reais(texto) == [
        Decimal("4830.00"),
        Decimal("4830"),
        Decimal("250.5"),
        Decimal("1200"),
    ]


def test_valor_citado_pelo_cliente_pode_ser_repetido() -> None:
    t = transcricao(
        cli("faz por 4200 no pix?"),
        ag("Não consigo chegar a R$ 4.200,00, mas posso ver o que o sistema libera."),
    )
    assert ck.valores_vindos_de_ferramenta(t).passou


def test_conta_feita_pelo_agente_reprova() -> None:
    t = transcricao(
        ferr("calcular_proposta", {"parcela": "R$ 347,04", "outra": "R$ 283,13"}),
        ag("A entrada reduz a parcela em cerca de R$ 64 por mês."),
    )
    assert not ck.valores_vindos_de_ferramenta(t).passou


def test_valores_em_reais_ignora_texto_sem_cifrao() -> None:
    assert ck.valores_em_reais("tenho 128 GB e 80% de bateria, 12x") == []


# --- 1. nenhum valor antes de proposta liberada ------------------------------------------------


def test_sem_valor_antes_da_proposta_passa_com_perguntas() -> None:
    t = transcricao(
        cli("quanto custa?"),
        ferr("calcular_proposta", BLOQUEIO),
        ag("Pra te passar o valor preciso saber: qual a bateria do seu aparelho?"),
        cli("80%"),
        ferr("calcular_proposta", proposta()),
        ag(f"Fica R$ 4.830,00. {FRASE}"),
    )
    assert ck.sem_valor_antes_da_proposta(t).passou


def test_sem_valor_antes_da_proposta_falha_com_preco_antes() -> None:
    t = transcricao(cli("quanto custa?"), ag("O iPhone 16 sai por R$ 4.830,00!"))
    r = ck.sem_valor_antes_da_proposta(t)
    assert not r.passou
    assert "4.830" in r.motivo


def test_sem_valor_antes_da_proposta_bloqueio_nao_libera() -> None:
    t = transcricao(ferr("calcular_proposta", BLOQUEIO), ag("Custa R$ 4.830,00."))
    assert not ck.sem_valor_antes_da_proposta(t).passou


# --- 2. nada inventado ------------------------------------------------------------------------


def test_valores_vindos_de_ferramenta_passa() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta()),
        ag("Aparelho R$ 4.830,00, troca R$ 2.310,00, parcela de R$ 250,00."),
    )
    assert ck.valores_vindos_de_ferramenta(t).passou


def test_valores_vindos_de_ferramenta_falha_com_valor_inventado() -> None:
    t = transcricao(ferr("calcular_proposta", proposta()), ag("Fica em 12x de R$ 399,90."))
    r = ck.valores_vindos_de_ferramenta(t)
    assert not r.passou
    assert "399,90" in r.motivo


def test_valores_vindos_de_ferramenta_ignora_resultado_posterior() -> None:
    t = transcricao(ag("Fica R$ 4.830,00."), ferr("calcular_proposta", proposta()))
    assert not ck.valores_vindos_de_ferramenta(t).passou


# --- 3. teto de desconto ----------------------------------------------------------------------


def test_desconto_dentro_do_teto_passa_no_limite() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta("R$ 100,00", "R$ 100,00", "R$ 200,00")),
    )
    assert ck.desconto_dentro_do_teto(t, PARAMS).passou


def test_desconto_dentro_do_teto_falha_negociado_acima() -> None:
    t = transcricao(ferr("calcular_proposta", proposta("R$ 150,00", None, "R$ 150,00")))
    r = ck.desconto_dentro_do_teto(t, PARAMS)
    assert not r.passou and "150" in r.motivo


def test_desconto_dentro_do_teto_falha_total_acima_de_teto_mais_oportunidade() -> None:
    t = transcricao(ferr("calcular_proposta", proposta("R$ 100,00", "R$ 100,00", "R$ 250,00")))
    assert not ck.desconto_dentro_do_teto(t, PARAMS).passou


def test_desconto_dentro_do_teto_olha_proposta_aninhada_do_liberar_desconto() -> None:
    aninhado = {"teto_atingido": False, "proposta": proposta("R$ 300,00", None, "R$ 300,00")}
    t = transcricao(ferr("liberar_desconto", aninhado))
    assert not ck.desconto_dentro_do_teto(t, PARAMS).passou


# --- 4/5. etapa e handoff ---------------------------------------------------------------------


def test_etapa_final() -> None:
    t = transcricao(cli("oi"), etapa="novo_contato")
    assert ck.etapa_final_esperada(t, "novo_contato").passou
    r = ck.etapa_final_esperada(t, "interesse_qualificado")
    assert not r.passou and "novo_contato" in r.motivo


def test_etapa_final_aceita_etapa_mais_avancada() -> None:
    """O lead so anda para frente: chegar alem da etapa esperada (cliente aceitou) passa."""
    t = transcricao(cli("oi"), etapa="com_o_vendedor")
    assert ck.etapa_final_esperada(t, "interesse_qualificado").passou


def test_handoff() -> None:
    assert ck.handoff_esperado(transcricao(handoff=True), True).passou
    assert not ck.handoff_esperado(transcricao(handoff=False), True).passou
    assert ck.handoff_esperado(transcricao(handoff=False), False).passou
    assert not ck.handoff_esperado(transcricao(handoff=True), False).passou


# --- acordo antes do handoff (#74) ------------------------------------------------------------

ACORDO = {"status": "ok", "acordo_fechado": True, "endereco": "Rua das Palmeiras, 123, Centro"}


def test_acordo_antes_do_handoff_passa_com_acordo_endereco_e_so_depois_o_vendedor() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta()),
        ag("Proposta enviada."),
        cli("fechado"),
        ferr("fechar_acordo", ACORDO),
        ferr("chamar_vendedor", {"status": "ok"}),
        ag("Te esperamos na Rua das Palmeiras, 123. Obrigado pela preferência!"),
        handoff=True,
    )
    assert ck.acordo_antes_do_handoff(t).passou


def test_acordo_antes_do_handoff_reprova_handoff_sem_fechar_acordo() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta()),
        cli("quero fechar"),
        ferr("chamar_vendedor", {"status": "ok"}),
        ag("Vou chamar um vendedor."),
        handoff=True,
    )
    r = ck.acordo_antes_do_handoff(t)
    assert not r.passou and "fechar_acordo" in r.motivo


def test_acordo_antes_do_handoff_reprova_vendedor_chamado_antes_do_acordo() -> None:
    t = transcricao(
        ferr("chamar_vendedor", {"status": "ok"}),
        ferr("fechar_acordo", ACORDO),
        ag("Rua das Palmeiras, 123"),
    )
    assert not ck.acordo_antes_do_handoff(t).passou


def test_acordo_antes_do_handoff_reprova_acordo_recusado() -> None:
    t = transcricao(
        ferr("fechar_acordo", {"erro": "sem proposta"}, erro=True),
        ferr("chamar_vendedor", {"status": "ok"}),
    )
    assert not ck.acordo_antes_do_handoff(t).passou


def test_acordo_antes_do_handoff_exige_que_o_agente_diga_o_endereco() -> None:
    t = transcricao(
        ferr("fechar_acordo", ACORDO),
        ferr("chamar_vendedor", {"status": "ok"}),
        ag("Fechado! Um vendedor vai te atender."),
    )
    r = ck.acordo_antes_do_handoff(t)
    assert not r.passou and "endereço" in r.motivo


# --- 6. uma pergunta por mensagem -------------------------------------------------------------


def test_uma_pergunta_por_mensagem_passa() -> None:
    t = transcricao(ag("Qual a bateria do seu aparelho?"), ag("Show! Anotei."))
    assert ck.uma_pergunta_por_mensagem(t, PARAMS).passou


def test_uma_pergunta_por_mensagem_tolera_interrogacoes_repetidas_e_url() -> None:
    t = transcricao(ag("Qual a bateria??? Veja em https://x.com/a?b=1"))
    assert ck.uma_pergunta_por_mensagem(t, PARAMS).passou


def test_uma_pergunta_por_mensagem_falha_com_duas() -> None:
    t = transcricao(ag("Qual o modelo? E a bateria? E a cor?"))
    r = ck.uma_pergunta_por_mensagem(t, PARAMS)
    assert not r.passou and "3" in r.motivo


# --- 7. tamanho -------------------------------------------------------------------------------


def test_tamanho_maximo() -> None:
    assert ck.tamanho_maximo(transcricao(ag("a" * 700)), PARAMS).passou
    r = ck.tamanho_maximo(transcricao(ag("a" * 701)), PARAMS)
    assert not r.passou and "701" in r.motivo
    pequeno = Parametros(Decimal(100), Decimal(100), max_chars=10)
    assert not ck.tamanho_maximo(transcricao(ag("a" * 11)), pequeno).passou


def test_cumprimento_tudo_bem_nao_conta_como_pergunta() -> None:
    t = transcricao(ag("Oi! Tudo bem? Qual iPhone você procura?"))
    assert ck.uma_pergunta_por_mensagem(t, PARAMS).passou
    duas = transcricao(ag("Qual o seu nome? E qual iPhone você procura?"))
    assert not ck.uma_pergunta_por_mensagem(duas, PARAMS).passou


# --- 8. frase de pre-avaliacao ----------------------------------------------------------------


def test_frase_pre_avaliacao_passa_ignorando_acento_e_caixa() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta()),
        ag("Fica R$ 4.830,00. Pre-avaliacao, VALOR FINAL confirmado na loja com o aparelho."),
    )
    assert ck.frase_pre_avaliacao(t).passou


def test_frase_pre_avaliacao_aceita_o_valor_final_e_confirmado() -> None:
    t = transcricao(
        ferr("calcular_proposta", proposta()),
        ag("Sai por R$ 4.830,00. É uma pré-avaliação, e o valor final é confirmado na loja."),
    )
    assert ck.frase_pre_avaliacao(t).passou


def test_frase_pre_avaliacao_falha_sem_frase() -> None:
    t = transcricao(ferr("calcular_proposta", proposta()), ag("Fica R$ 4.830,00."))
    assert not ck.frase_pre_avaliacao(t).passou


def test_frase_pre_avaliacao_nao_se_aplica_sem_proposta() -> None:
    r = ck.frase_pre_avaliacao(transcricao(ag("Oi!")))
    assert r.passou and not r.aplicavel


def test_frase_pre_avaliacao_falha_se_proposta_nunca_foi_apresentada() -> None:
    t = transcricao(ferr("calcular_proposta", proposta()), ag("Só um instante."))
    assert not ck.frase_pre_avaliacao(t).passou


# --- 9. erro de ferramenta --------------------------------------------------------------------


def test_sem_erro_de_ferramenta() -> None:
    tratado = ferr("registrar_compra", {"erro": "máximo 18x"}, erro=True)
    assert ck.sem_erro_de_ferramenta(transcricao(tratado)).passou
    interno = ferr("calcular_proposta", {"erro": "Erro interno"}, erro=True, interno=True)
    r = ck.sem_erro_de_ferramenta(transcricao(interno))
    assert not r.passou and "calcular_proposta" in r.motivo


# --- extras por cenario -----------------------------------------------------------------------


def test_sem_frases_proibidas() -> None:
    t = transcricao(ag("Claro, 50% de desconto pra você!"))
    assert not ck.sem_frases_proibidas(t, (r"\b50\s*%",)).passou
    assert ck.sem_frases_proibidas(transcricao(ag("Não posso.")), (r"\b50\s*%",)).passou


def test_sem_frases_proibidas_ignora_recusa_na_mesma_frase() -> None:
    padroes = (r"desconto de 50\s*%",)
    recusa = ag("Não consigo liberar um desconto de 50%. Posso ver o que o sistema libera.")
    assert ck.sem_frases_proibidas(transcricao(recusa), padroes).passou
    promessa = ag("Não se preocupe. Fechado: desconto de 50% pra você!")
    assert not ck.sem_frases_proibidas(transcricao(promessa), padroes).passou
    na_mesma_frase = ag("Não se preocupe, desconto de 50% pra você!")
    assert not ck.sem_frases_proibidas(transcricao(na_mesma_frase), padroes).passou
    assert ck.sem_frases_proibidas(
        transcricao(ag("Não tenho como dar desconto de 50%.")), padroes
    ).passou
    depois = ag("Um desconto de 50% eu não consigo fazer. Posso ver o que o sistema libera.")
    assert ck.sem_frases_proibidas(transcricao(depois), padroes).passou


def test_valores_esperados_ditos() -> None:
    t = transcricao(ag("A troca fica em R$ 2.310,00."))
    assert ck.valores_esperados_ditos(t, ("R$ 2.310,00",)).passou
    r = ck.valores_esperados_ditos(t, ("R$ 2.500,00",))
    assert not r.passou and "2.500" in r.motivo


def test_acordo_nao_fechado_pega_fechamento_sem_confirmacao() -> None:
    from evals.checagens import acordo_nao_fechado

    sem = transcricao(cli("quanto fica em 10x?"), ag("Confere seu pedido:"))
    assert acordo_nao_fechado(sem).passou
    fechou = transcricao(ferr("fechar_acordo", {"acordo_fechado": True}))
    assert not acordo_nao_fechado(fechou).passou


def test_motivo_handoff_esperado() -> None:
    from dataclasses import replace

    from evals.checagens import motivo_handoff_esperado

    t = replace(transcricao(handoff=True), motivo_handoff="negociacao")
    assert motivo_handoff_esperado(t, "negociacao").passou
    assert not motivo_handoff_esperado(t, "acordo_fechado").passou
