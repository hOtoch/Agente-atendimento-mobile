"""Debounce, reagendamento e trava por conversa, com relogio falso (sem Redis)."""

import asyncio
from uuid import UUID, uuid4

import pytest

from app.application.agendamento import (
    AgendadorEmMemoria,
    ProcessarQuandoQuieto,
    TravaEmMemoria,
)
from app.application.relogio import RelogioFalso

JANELA = 4.0


class Cenario:
    def __init__(self) -> None:
        self.relogio = RelogioFalso(inicio=1000.0)
        self.agendador = AgendadorEmMemoria(self.relogio, janela_s=JANELA)
        self.trava = TravaEmMemoria(self.relogio)
        self.chamadas: list[tuple[UUID, float]] = []
        self.caso = self.novo_caso(self._processar)

    def novo_caso(self, processar: "object") -> ProcessarQuandoQuieto:
        return ProcessarQuandoQuieto(
            agendador=self.agendador,
            trava=self.trava,
            relogio=self.relogio,
            processar=processar,  # type: ignore[arg-type]
            janela_s=JANELA,
            trava_ttl_s=60.0,
            espera_trava_s=0.5,
        )

    async def _processar(self, conversa_id: UUID) -> None:
        self.chamadas.append((conversa_id, self.relogio.agora()))

    async def rodar(self) -> None:
        await self.agendador.rodar_ate_ocioso(self.caso)


async def test_tres_mensagens_em_2s_geram_um_processamento_depois_da_janela_da_ultima() -> None:
    c = Cenario()
    conversa = uuid4()
    await c.agendador.agendar(conversa)  # t=1000
    c.relogio.avancar(1.0)
    await c.agendador.agendar(conversa)  # t=1001
    c.relogio.avancar(1.0)
    await c.agendador.agendar(conversa)  # t=1002
    await c.rodar()
    assert c.chamadas == [(conversa, 1002.0 + JANELA)]


async def test_mensagem_apos_a_janela_gera_novo_processamento() -> None:
    c = Cenario()
    conversa = uuid4()
    await c.agendador.agendar(conversa)
    await c.rodar()
    c.relogio.avancar(30.0)
    await c.agendador.agendar(conversa)
    await c.rodar()
    assert len(c.chamadas) == 2


async def test_job_que_dispara_cedo_reagenda_para_o_fim_da_janela() -> None:
    c = Cenario()
    conversa = uuid4()
    await c.agendador.agendar(conversa)  # t=1000
    c.relogio.avancar(3.0)
    await c.agendador.agendar(conversa)  # t=1003 (ultima)
    # dispara na mao o job antigo (devido em 1004): so passou 1s desde a ultima.
    c.relogio.avancar(1.0)
    await c.caso(conversa)
    assert c.chamadas == []
    await c.rodar()
    assert c.chamadas == [(conversa, 1003.0 + JANELA)]


async def test_conversas_independentes_processam_cada_uma_no_seu_tempo() -> None:
    c = Cenario()
    a, b = uuid4(), uuid4()
    await c.agendador.agendar(a)  # 1000
    c.relogio.avancar(2.0)
    await c.agendador.agendar(b)  # 1002
    await c.rodar()
    assert c.chamadas == [(a, 1004.0), (b, 1006.0)]


async def test_trava_ocupada_reagenda_curto_e_processa_depois() -> None:
    c = Cenario()
    conversa = uuid4()
    assert await c.trava.adquirir(conversa, 60.0)  # outro worker processando
    await c.agendador.agendar(conversa)
    c.relogio.avancar(JANELA)
    await c.caso(conversa)
    assert c.chamadas == []
    await c.trava.liberar(conversa)
    await c.rodar()
    assert len(c.chamadas) == 1
    assert c.chamadas[0][1] >= 1000.0 + JANELA


async def test_trava_e_liberada_apos_processar_mesmo_com_erro() -> None:
    c = Cenario()
    conversa = uuid4()

    async def falha(_: UUID) -> None:
        raise RuntimeError("boom")

    caso = c.novo_caso(falha)
    await c.agendador.agendar(conversa)
    c.relogio.avancar(JANELA)
    with pytest.raises(RuntimeError):
        await caso(conversa)
    assert await c.trava.adquirir(conversa, 1.0)


async def test_trava_impede_processamento_concorrente_da_mesma_conversa() -> None:
    c = Cenario()
    conversa = uuid4()
    dentro = 0
    maximo = 0
    liberar_primeiro = asyncio.Event()

    async def lento(_: UUID) -> None:
        nonlocal dentro, maximo
        dentro += 1
        maximo = max(maximo, dentro)
        await liberar_primeiro.wait()
        dentro -= 1

    caso = c.novo_caso(lento)
    await c.agendador.agendar(conversa)
    c.relogio.avancar(JANELA)
    primeiro = asyncio.create_task(caso(conversa))
    await asyncio.sleep(0)
    await caso(conversa)  # segundo worker: trava ocupada, so reagenda
    assert maximo == 1
    liberar_primeiro.set()
    await primeiro


async def test_duas_conversas_processam_em_paralelo() -> None:
    c = Cenario()
    a, b = uuid4(), uuid4()
    ativos: set[UUID] = set()
    simultaneos = 0
    portao = asyncio.Event()

    async def processar(conversa_id: UUID) -> None:
        nonlocal simultaneos
        ativos.add(conversa_id)
        simultaneos = max(simultaneos, len(ativos))
        if len(ativos) == 2:
            portao.set()
        await asyncio.wait_for(portao.wait(), timeout=1)

    caso = c.novo_caso(processar)
    await c.agendador.agendar(a)
    await c.agendador.agendar(b)
    c.relogio.avancar(JANELA)
    await asyncio.gather(caso(a), caso(b))
    assert simultaneos == 2


async def test_trava_expira_pelo_ttl() -> None:
    relogio = RelogioFalso(inicio=0.0)
    trava = TravaEmMemoria(relogio)
    conversa = uuid4()
    assert await trava.adquirir(conversa, 10.0)
    assert not await trava.adquirir(conversa, 10.0)
    relogio.avancar(10.1)
    assert await trava.adquirir(conversa, 10.0)


async def test_job_sem_mensagem_pendente_nao_processa() -> None:
    c = Cenario()
    conversa = uuid4()
    await c.agendador.agendar(conversa)
    await c.rodar()
    await c.caso(conversa)  # job duplicado/atrasado: nada novo desde o ultimo processamento
    assert len(c.chamadas) == 1


async def test_mensagem_durante_o_processamento_nao_se_perde() -> None:
    c = Cenario()
    conversa = uuid4()
    chamadas: list[float] = []

    async def processar(conversa_id: UUID) -> None:
        chamadas.append(c.relogio.agora())
        if len(chamadas) == 1:
            c.relogio.avancar(1.0)
            await c.agendador.agendar(conversa_id)  # chega enquanto processa

    c.caso = c.novo_caso(processar)
    await c.agendador.agendar(conversa)
    await c.rodar()
    assert len(chamadas) == 2
