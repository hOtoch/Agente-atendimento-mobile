"""Composicao: worker usa o orquestrador real por padrao; API usa o agendador arq."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.application.canal import Canal
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
