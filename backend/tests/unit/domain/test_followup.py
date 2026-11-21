"""Quem recebe follow-up e quando: funcao pura, relogio = parametro `agora`."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from app.domain.followup import (
    ConfigFollowup,
    ConfigFollowupInvalida,
    FatosFollowup,
    MotivoEspera,
    decidir_followup,
    dentro_do_horario,
)
from app.domain.kanban import Etapa

# 2026-11-20 e sexta. 15:00 UTC = 12:00 em Sao Paulo (UTC-3).
MEIO_DIA = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def config(**campos: object) -> ConfigFollowup:
    base: dict[str, object] = {
        "ligado": True,
        "horas_por_etapa": {Etapa.INTERESSE_QUALIFICADO: 2},
        "max_tentativas": 2,
        "intervalo_horas": 24,
        "hora_inicio": time(9, 0),
        "hora_fim": time(18, 0),
        "max_dias_parado": 7,
    }
    base.update(campos)
    return ConfigFollowup(**base)  # type: ignore[arg-type]


def fatos(**campos: object) -> FatosFollowup:
    base: dict[str, object] = {
        "etapa": Etapa.INTERESSE_QUALIFICADO,
        "dono_e_ia": True,
        "ultima_mensagem_em": MEIO_DIA - timedelta(hours=3),
        "ultima_mensagem_do_cliente": False,
        "tentativas": 0,
        "ultimo_followup_em": None,
    }
    base.update(campos)
    return FatosFollowup(**base)  # type: ignore[arg-type]


def test_lead_parado_na_etapa_configurada_recebe() -> None:
    d = decidir_followup(config(), fatos(), MEIO_DIA)
    assert d.enviar is True
    assert d.motivo is None
    assert d.tentativa == 1


def test_ainda_nao_passou_o_tempo_da_etapa_espera() -> None:
    f = fatos(ultima_mensagem_em=MEIO_DIA - timedelta(hours=1, minutes=59))
    d = decidir_followup(config(), f, MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.AINDA_NAO_PARADO)


def test_exatamente_no_limite_do_tempo_recebe() -> None:
    f = fatos(ultima_mensagem_em=MEIO_DIA - timedelta(hours=2))
    assert decidir_followup(config(), f, MEIO_DIA).enviar is True


def test_dono_vendedor_nunca_recebe() -> None:
    d = decidir_followup(config(), fatos(dono_e_ia=False), MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.DONO_VENDEDOR)


@pytest.mark.parametrize("etapa", [Etapa.COM_O_VENDEDOR, Etapa.VENDA_FECHADA])
def test_etapas_finais_nao_recebem_nem_se_configuradas(etapa: Etapa) -> None:
    with pytest.raises(ConfigFollowupInvalida):
        config(horas_por_etapa={etapa: 1})


def test_etapa_sem_tempo_configurado_nao_recebe() -> None:
    f = fatos(etapa=Etapa.INTERESSE_IDENTIFICADO)
    d = decidir_followup(config(), f, MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.ETAPA_NAO_CONFIGURADA)


def test_desligado_nao_recebe() -> None:
    d = decidir_followup(config(ligado=False), fatos(), MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.DESLIGADO)


def test_ultima_mensagem_do_cliente_espera_a_ia_responder() -> None:
    d = decidir_followup(config(), fatos(ultima_mensagem_do_cliente=True), MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.AGUARDANDO_IA)


def test_maximo_de_tentativas_para_de_enviar() -> None:
    f = fatos(
        tentativas=2,
        ultimo_followup_em=MEIO_DIA - timedelta(hours=48),
        ultima_mensagem_em=MEIO_DIA - timedelta(hours=48),
    )
    d = decidir_followup(config(max_tentativas=2), f, MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.MAXIMO_DE_TENTATIVAS)


def test_segunda_tentativa_so_depois_do_intervalo() -> None:
    cedo = fatos(
        tentativas=1,
        ultimo_followup_em=MEIO_DIA - timedelta(hours=23),
        ultima_mensagem_em=MEIO_DIA - timedelta(hours=23),
    )
    d = decidir_followup(config(horas_por_etapa={Etapa.INTERESSE_QUALIFICADO: 2}), cedo, MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.INTERVALO)

    tarde = fatos(
        tentativas=1,
        ultimo_followup_em=MEIO_DIA - timedelta(hours=24),
        ultima_mensagem_em=MEIO_DIA - timedelta(hours=24),
    )
    d2 = decidir_followup(config(), tarde, MEIO_DIA)
    assert d2.enviar is True
    assert d2.tentativa == 2


def test_followup_recem_enviado_nao_dispara_outro() -> None:
    f = fatos(
        tentativas=1,
        ultimo_followup_em=MEIO_DIA - timedelta(minutes=5),
        ultima_mensagem_em=MEIO_DIA - timedelta(minutes=5),
    )
    assert decidir_followup(config(), f, MEIO_DIA).enviar is False


def test_fora_do_horario_comercial_espera() -> None:
    noite = datetime(2026, 11, 20, 22, 0, tzinfo=UTC)  # 19:00 em Sao Paulo
    f = fatos(ultima_mensagem_em=noite - timedelta(hours=5))
    d = decidir_followup(config(), f, noite)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.FORA_DO_HORARIO)


def test_de_madrugada_espera_e_ao_abrir_envia() -> None:
    madrugada = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)  # 07:00 em Sao Paulo
    f = fatos(ultima_mensagem_em=madrugada - timedelta(hours=10))
    assert decidir_followup(config(), f, madrugada).motivo is MotivoEspera.FORA_DO_HORARIO
    abriu = madrugada + timedelta(hours=2)  # 09:00
    assert decidir_followup(config(), f, abriu).enviar is True


def test_horario_usa_fuso_de_sao_paulo_e_nao_utc() -> None:
    # 20:00 UTC e 17:00 em Sao Paulo (dentro); 21:00 UTC e 18:00 (fim exclusivo, fora)
    c = config()
    assert dentro_do_horario(c, datetime(2026, 11, 20, 20, 0, tzinfo=UTC)) is True
    assert dentro_do_horario(c, datetime(2026, 11, 20, 21, 0, tzinfo=UTC)) is False


def test_lead_abandonado_ha_muito_tempo_nao_recebe() -> None:
    f = fatos(ultima_mensagem_em=MEIO_DIA - timedelta(days=8))
    d = decidir_followup(config(max_dias_parado=7), f, MEIO_DIA)
    assert (d.enviar, d.motivo) == (False, MotivoEspera.ABANDONADO)


def test_relogio_naive_e_recusado() -> None:
    with pytest.raises(ValueError):
        decidir_followup(config(), fatos(), datetime(2026, 11, 20, 12, 0))


@pytest.mark.parametrize(
    "campos",
    [
        {"horas_por_etapa": {Etapa.INTERESSE_QUALIFICADO: 0}},
        {"max_tentativas": 0},
        {"max_tentativas": 6},
        {"intervalo_horas": 0},
        {"hora_inicio": time(18, 0), "hora_fim": time(9, 0)},
        {"max_dias_parado": 0},
    ],
)
def test_config_invalida_e_recusada(campos: dict[str, object]) -> None:
    with pytest.raises(ConfigFollowupInvalida):
        config(**campos)


def test_config_padrao_vem_desligada() -> None:
    padrao = ConfigFollowup.padrao()
    assert padrao.ligado is False
    assert Etapa.INTERESSE_QUALIFICADO in padrao.horas_por_etapa
