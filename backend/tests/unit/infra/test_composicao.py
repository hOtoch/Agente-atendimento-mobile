"""Composicao: worker usa o orquestrador real por padrao; API usa o agendador arq."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.application.canal import Canal
from app.application.notificar_vendedor import NotificarVendedorNoHandoff
from app.infra import composicao, dependencias, worker
from app.infra.fila import AgendadorArq
from app.infra.settings import Settings


class _Redis:
    """Basta para montar os objetos; nada aqui fala com o Redis."""


async def test_worker_injeta_o_processador_real_quando_nao_ha_hook() -> None:
    ctx: dict[str, Any] = {"redis": _Redis()}
    await worker.iniciar(ctx)
    try:
        assert callable(ctx["processar"])
        assert ctx["processar"].__qualname__.startswith("criar_processador")
        assert ctx["caso"] is not None
    finally:
        await worker.encerrar(ctx)


async def test_worker_respeita_hook_injetado() -> None:
    async def meu(conversa_id: Any) -> None: ...

    ctx: dict[str, Any] = {"redis": _Redis(), "processar": meu}
    await worker.iniciar(ctx)
    assert ctx["processar"] is meu
    assert "engine" not in ctx


def test_get_agendar_usa_o_agendador_arq_com_prefixo_e_janela_do_worker() -> None:
    agendar = dependencias.get_agendar()
    dono = agendar.__self__  # type: ignore[attr-defined]
    assert isinstance(dono, AgendadorArq)
    agendador = composicao.criar_agendador(_Redis())  # type: ignore[arg-type]
    assert dono._prefixo == agendador._prefixo == composicao.PREFIXO_FILA
    assert dono._janela_s == agendador._janela_s


def test_hoje_brasil_e_uma_data() -> None:
    assert composicao.hoje_brasil().year >= 2026


def test_painel_envia_pelo_whatsapp_quando_ha_adaptador() -> None:
    sem = composicao.montar_casos_painel(MagicMock(), MagicMock())
    assert set(sem._canais) == {Canal.WEBCHAT}
    zap = MagicMock()
    com = composicao.montar_casos_painel(MagicMock(), MagicMock(), whatsapp=zap)
    assert com._canais[Canal.WHATSAPP] is zap


def test_canal_whatsapp_usa_a_url_publica_da_api_para_midia_local() -> None:
    settings = Settings(_env_file=None, api_publica_url="http://api.exemplo/")
    canal = composicao.criar_canal_whatsapp(MagicMock(), MagicMock(), settings)
    assert canal._prefixo_midia == "http://api.exemplo/midias/"


def test_aviso_de_handoff_usa_o_painel_url_das_settings() -> None:
    settings = Settings(_env_file=None, painel_url="https://painel.exemplo")
    aviso = composicao.criar_aviso_handoff(MagicMock(), redis=MagicMock(), settings=settings)
    assert isinstance(aviso, NotificarVendedorNoHandoff)
    assert aviso._url_painel == "https://painel.exemplo"


async def test_worker_liga_o_aviso_de_handoff_no_processador(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recebido: dict[str, Any] = {}

    def falso(*args: Any, **kwargs: Any) -> Any:
        recebido.update(kwargs)

        async def processar(conversa_id: Any) -> None: ...

        return processar

    monkeypatch.setattr(worker, "criar_processador", falso)
    ctx: dict[str, Any] = {"redis": _Redis()}
    await worker.iniciar(ctx)
    try:
        from app.application.handoff import GanchosHandoff

        assert isinstance(recebido["aviso_handoff"], GanchosHandoff)
        assert isinstance(recebido["aviso_handoff"].ganchos[0], NotificarVendedorNoHandoff)
    finally:
        await worker.encerrar(ctx)


async def test_criar_transcritor_usa_o_stt_dado_e_o_armazenamento_da_midia(tmp_path: Any) -> None:
    from app.adapters.outbound.audio.stt_fake import STTFake
    from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
    from app.infra.composicao import criar_transcritor

    nome = await ArmazenamentoMidiaDisco(tmp_path).salvar(b"audio", "audio/ogg")
    stt = STTFake("ola")
    transcrever = criar_transcritor(Settings(_env_file=None, midia_dir=str(tmp_path)), stt)
    assert await transcrever(f"http://api/midias/{nome}") == "ola"
    assert stt.chamadas == [(b"audio", "audio/ogg")]


def test_gancho_de_handoff_compoe_o_aviso_e_depois_a_exportacao_ao_erp() -> None:
    from app.application.exportar_handoff_erp import ExportarHandoffParaErp
    from app.application.handoff import GanchosHandoff

    settings = Settings(_env_file=None, painel_url="https://painel.exemplo")
    gancho = composicao.criar_gancho_handoff(MagicMock(), redis=MagicMock(), settings=settings)
    assert isinstance(gancho, GanchosHandoff)
    aviso, exportar = gancho.ganchos
    assert isinstance(aviso, NotificarVendedorNoHandoff)  # o comportamento atual, intacto
    assert isinstance(exportar, ExportarHandoffParaErp)  # depois da atribuicao do vendedor


async def test_sem_chave_do_erp_a_exportacao_falha_com_erro_tipado_e_sem_rede(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application.pedido_erp import DadosHandoff, FalhaPedidoErp
    from app.infra.mercadophone import MercadoPhoneNaoConfigurado

    def sem_chave() -> Any:
        raise MercadoPhoneNaoConfigurado("x")

    monkeypatch.setattr(composicao, "get_cliente_mercadophone", sem_chave)
    pedido = composicao.criar_pedido_erp()
    dados = DadosHandoff("N", None, None, None, None)
    with pytest.raises(FalhaPedidoErp, match="MERCADOPHONE_API_KEY"):
        await pedido.registrar_handoff(MagicMock(), dados)


def test_estoque_do_agente_confere_ao_vivo_por_fora_da_resiliencia() -> None:
    """A ordem importa: o cache de 60 s da resiliencia nao pode esconder a conferencia."""
    from app.application.estoque_ao_vivo import EstoqueConferidoAoVivo
    from app.application.estoque_resiliente import EstoqueResiliente

    estoque = composicao.montar_estoque_do_agente(MagicMock(), MagicMock(), lambda: None)

    assert isinstance(estoque, EstoqueConferidoAoVivo)
    assert isinstance(estoque._base, EstoqueResiliente)
