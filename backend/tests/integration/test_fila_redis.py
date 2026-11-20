"""TravaRedis e AgendadorArq contra um Redis real (e um worker arq em modo burst)."""

import asyncio
import time
from uuid import UUID, uuid4

import pytest
from arq.connections import ArqRedis
from arq.worker import Worker, func

from app.application.agendamento import ProcessarQuandoQuieto
from app.infra.fila import AgendadorArq, RelogioParede, TravaRedis

pytestmark = pytest.mark.integration


async def test_trava_adquire_e_nega_concorrente(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    a = TravaRedis(redis_pool, prefixo=prefixo_redis)
    b = TravaRedis(redis_pool, prefixo=prefixo_redis)
    conversa = uuid4()
    assert await a.adquirir(conversa, 10.0)
    assert not await b.adquirir(conversa, 10.0)
    assert not await a.adquirir(conversa, 10.0)


async def test_trava_so_libera_com_o_token_certo(redis_pool: ArqRedis, prefixo_redis: str) -> None:
    a = TravaRedis(redis_pool, prefixo=prefixo_redis)
    b = TravaRedis(redis_pool, prefixo=prefixo_redis)
    conversa = uuid4()
    assert await a.adquirir(conversa, 10.0)
    await b.liberar(conversa)  # nao e o dono: nao pode liberar
    assert not await b.adquirir(conversa, 10.0)
    await a.liberar(conversa)
    assert await b.adquirir(conversa, 10.0)


async def test_trava_expira_e_dono_antigo_nao_derruba_a_nova(
    redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    a = TravaRedis(redis_pool, prefixo=prefixo_redis)
    b = TravaRedis(redis_pool, prefixo=prefixo_redis)
    conversa = uuid4()
    assert await a.adquirir(conversa, 0.1)
    await asyncio.sleep(0.25)
    assert await b.adquirir(conversa, 10.0)  # ttl venceu: worker morto nao trava a conversa
    await a.liberar(conversa)  # token velho: nao derruba a trava de b
    assert not await TravaRedis(redis_pool, prefixo=prefixo_redis).adquirir(conversa, 10.0)


async def test_agendador_grava_ultima_mensagem_e_deduplica_o_job(
    redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    fila = f"{prefixo_redis}fila"
    agendador = AgendadorArq(redis_pool, janela_s=30.0, prefixo=prefixo_redis, nome_fila=fila)
    conversa = uuid4()
    assert await agendador.pendente(conversa) is None
    antes = time.time()
    await agendador.agendar(conversa)
    ts = await agendador.pendente(conversa)
    assert ts is not None
    assert antes - 0.002 <= ts <= time.time() + 0.002  # gravado em ms
    # reagendar para a mesma mensagem usa o mesmo job_id: o arq ignora o duplicado
    await agendador.reagendar(conversa, 30.0)
    assert await redis_pool.zcard(fila) == 1
    # nova mensagem: novo job_id (a ultima mensagem mudou)
    await asyncio.sleep(0.01)
    await agendador.agendar(conversa)
    assert await redis_pool.zcard(fila) == 2
    # o job antigo, ao disparar cedo, reagenda: cai no id do mais novo e converge
    await agendador.reagendar(conversa, 30.0)
    assert await redis_pool.zcard(fila) == 2


async def test_concluir_so_limpa_se_nao_chegou_mensagem_nova(
    redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    agendador = AgendadorArq(
        redis_pool, janela_s=30.0, prefixo=prefixo_redis, nome_fila=f"{prefixo_redis}fila"
    )
    conversa = uuid4()
    await agendador.agendar(conversa)
    ts = await agendador.pendente(conversa)
    assert ts is not None
    await asyncio.sleep(0.01)
    await agendador.agendar(conversa)
    await agendador.concluir(conversa, ts)
    novo = await agendador.pendente(conversa)
    assert novo is not None
    await agendador.concluir(conversa, novo)
    assert await agendador.pendente(conversa) is None


async def test_ponta_a_ponta_tres_mensagens_um_processamento(
    redis_pool: ArqRedis, prefixo_redis: str
) -> None:
    fila = f"{prefixo_redis}fila"
    janela = 0.6
    agendador = AgendadorArq(redis_pool, janela_s=janela, prefixo=prefixo_redis, nome_fila=fila)
    chamadas: list[UUID] = []

    async def processar(conversa_id: UUID) -> None:
        chamadas.append(conversa_id)

    caso = ProcessarQuandoQuieto(
        agendador=agendador,
        trava=TravaRedis(redis_pool, prefixo=prefixo_redis),
        relogio=RelogioParede(),
        processar=processar,
        janela_s=janela,
        espera_trava_s=0.1,
    )

    async def processar_conversa(ctx: dict[str, object], conversa_id: str) -> None:
        await caso(UUID(conversa_id))

    conversa = uuid4()
    for _ in range(3):
        await agendador.agendar(conversa)
        await asyncio.sleep(0.2)
    worker = Worker(
        functions=[func(processar_conversa, name="processar_conversa", keep_result=0)],
        redis_pool=redis_pool,
        queue_name=fila,
        burst=True,
        poll_delay=0.05,
        handle_signals=False,
    )
    await worker.main()  # burst: roda ate a fila (inclusive os jobs adiados) esvaziar
    assert chamadas == [conversa]
