import asyncio

from app.adapters.outbound.auth.hasher import HasherSenhaArgon2


async def test_hash_nao_e_a_senha_e_usa_argon2id() -> None:
    h = await HasherSenhaArgon2().gerar("minha-senha-123")
    assert "minha-senha-123" not in h
    assert h.startswith("$argon2id$")


async def test_confere_certo_e_errado() -> None:
    hasher = HasherSenhaArgon2()
    h = await hasher.gerar("minha-senha-123")
    assert await hasher.conferir("minha-senha-123", h) is True
    assert await hasher.conferir("outra-senha", h) is False


async def test_hashes_do_mesmo_texto_diferem_por_causa_do_sal() -> None:
    hasher = HasherSenhaArgon2()
    assert await hasher.gerar("x" * 12) != await hasher.gerar("x" * 12)


async def test_hash_invalido_nao_confere_nem_explode() -> None:
    assert await HasherSenhaArgon2().conferir("qualquer", "isto-nao-e-um-hash") is False


async def test_argon2_nao_trava_o_event_loop() -> None:
    """O argon2 gasta CPU de proposito: rodando no loop, um login congelaria a API (e o SSE)."""
    hasher = HasherSenhaArgon2()
    h = await hasher.gerar("minha-senha-123")
    batidas = 0

    async def relogio() -> None:
        nonlocal batidas
        while True:
            await asyncio.sleep(0)
            batidas += 1

    tarefa = asyncio.create_task(relogio())
    await asyncio.sleep(0)
    antes = batidas
    await hasher.conferir("minha-senha-123", h)
    durante = batidas - antes
    tarefa.cancel()
    assert durante > 1
