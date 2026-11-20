"""Testes do decorator EstoqueResiliente (relogio falso, sem dormir de verdade).

Timeout: `asyncio.wait_for` usa o relogio do event loop, nao o `RelogioPort`. Em vez de
injetar um mecanismo, os testes de timeout usam um `timeout_s` real pequeno (0.05 s) e um
adapter fake que dorme 5 s de verdade; o `wait_for` cancela a espera, entao o teste leva
~0.05 s por tentativa. O backoff, que seria o trecho lento, passa pelo RelogioFalso.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

import pytest

from app.application.estoque import CapacidadesEstoque, EstoqueIndisponivel
from app.application.estoque_resiliente import EstoqueResiliente
from app.application.relogio import RelogioFalso
from app.domain.estoque import ItemEstoque
from app.domain.valores import Capacidade, ModeloAparelho
from tests.contract.estoque_contrato import LOJA_A, LOJA_B, item

MODELO = "iPhone 15 Pro"


class AdapterFalso:
    """Adapter que executa `comportamento(n)` na n-esima chamada (1-based)."""

    capacidades = CapacidadesEstoque(suporta_reserva=True, suporta_webhook=False)

    def __init__(self, comportamento: Callable[[int], list[ItemEstoque]]) -> None:
        self._comportamento = comportamento
        self.chamadas = 0

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        self.chamadas += 1
        return self._comportamento(self.chamadas)

    async def obter(self, loja_id: UUID, sku: str) -> ItemEstoque | None:
        self.chamadas += 1
        itens = self._comportamento(self.chamadas)
        return itens[0] if itens else None


class AdapterLento(AdapterFalso):
    """Responde na 1a chamada se `primeira_ok`; nas demais dorme 5 s (real)."""

    def __init__(self, primeira_ok: bool = False) -> None:
        super().__init__(lambda n: [])
        self._primeira_ok = primeira_ok

    async def buscar(
        self,
        loja_id: UUID,
        modelo: str | ModeloAparelho,
        capacidade: Capacidade | None = None,
        cor: str | None = None,
    ) -> list[ItemEstoque]:
        self.chamadas += 1
        if self._primeira_ok and self.chamadas == 1:
            return [item("A")]
        await asyncio.sleep(5)
        return [item("LENTO")]


def _falha(_: int) -> list[ItemEstoque]:
    raise EstoqueIndisponivel("erp fora")


def _montar(
    adapter: AdapterFalso,
    *,
    cache_ttl_s: float = 60,
    tentativas: int = 3,
    timeout_s: float = 3.0,
    backoff_base_s: float = 0.2,
    jitter: Callable[[], float] | None = None,
) -> tuple[EstoqueResiliente, RelogioFalso]:
    relogio = RelogioFalso()
    resiliente = EstoqueResiliente(
        adapter,
        relogio,
        cache_ttl_s=cache_ttl_s,
        tentativas=tentativas,
        timeout_s=timeout_s,
        backoff_base_s=backoff_base_s,
        jitter=jitter if jitter is not None else (lambda: 0.0),
    )
    return resiliente, relogio


async def test_sucesso_direto_nao_dorme() -> None:
    adapter = AdapterFalso(lambda n: [item("A")])
    resiliente, relogio = _montar(adapter)
    assert [i.sku for i in await resiliente.buscar(LOJA_A, MODELO)] == ["A"]
    assert relogio.dormidos == []
    assert resiliente.metricas.tentativas == 1


async def test_capacidades_repassa_as_do_adapter() -> None:
    adapter = AdapterFalso(lambda n: [])
    resiliente, _ = _montar(adapter)
    assert resiliente.capacidades is adapter.capacidades


async def test_falha_duas_vezes_e_acerta_na_terceira() -> None:
    def comportamento(n: int) -> list[ItemEstoque]:
        if n < 3:
            raise EstoqueIndisponivel("fora")
        return [item("A")]

    adapter = AdapterFalso(comportamento)
    resiliente, _ = _montar(adapter)
    assert [i.sku for i in await resiliente.buscar(LOJA_A, MODELO)] == ["A"]
    assert adapter.chamadas == 3
    assert resiliente.metricas.tentativas == 3
    assert resiliente.metricas.fallbacks == 0


async def test_erro_de_configuracao_nao_e_retentado() -> None:
    class ErroDeConfiguracao(EstoqueIndisponivel):
        retentavel = False

    def comportamento(n: int) -> list[ItemEstoque]:
        raise ErroDeConfiguracao("credencial invalida")

    adapter = AdapterFalso(comportamento)
    resiliente, relogio = _montar(adapter)
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_A, MODELO)
    assert adapter.chamadas == 1
    assert resiliente.metricas.tentativas == 1
    assert relogio.dormidos == []


@pytest.mark.parametrize("erro", [TimeoutError("t"), OSError("rede")])
async def test_faz_retry_em_timeout_e_oserror(erro: Exception) -> None:
    def comportamento(n: int) -> list[ItemEstoque]:
        if n == 1:
            raise erro
        return [item("A")]

    adapter = AdapterFalso(comportamento)
    resiliente, _ = _montar(adapter)
    assert len(await resiliente.buscar(LOJA_A, MODELO)) == 1
    assert adapter.chamadas == 2


async def test_erro_nao_retryavel_e_repassado_sem_retry() -> None:
    def comportamento(_: int) -> list[ItemEstoque]:
        raise ValueError("argumento invalido")

    adapter = AdapterFalso(comportamento)
    resiliente, relogio = _montar(adapter)
    with pytest.raises(ValueError, match="argumento invalido"):
        await resiliente.buscar(LOJA_A, MODELO)
    assert adapter.chamadas == 1
    assert relogio.dormidos == []


async def test_backoff_cresce_exponencialmente() -> None:
    adapter = AdapterFalso(_falha)
    resiliente, relogio = _montar(adapter, tentativas=4, backoff_base_s=0.2)
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_A, MODELO)
    assert adapter.chamadas == 4
    assert relogio.dormidos == pytest.approx([0.2, 0.4, 0.8])  # sem dormir apos a ultima


async def test_backoff_soma_jitter() -> None:
    adapter = AdapterFalso(_falha)
    resiliente, relogio = _montar(adapter, tentativas=3, backoff_base_s=1.0, jitter=lambda: 0.05)
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_A, MODELO)
    assert relogio.dormidos == pytest.approx([1.05, 2.05])


async def test_sem_cache_e_sempre_falhando_levanta_indisponivel() -> None:
    resiliente, _ = _montar(AdapterFalso(_falha))
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_A, MODELO)


async def test_fallback_devolve_cache_expirado_marcado_desatualizado() -> None:
    estado = {"ok": True}

    def comportamento(_: int) -> list[ItemEstoque]:
        if estado["ok"]:
            return [item("A")]
        raise EstoqueIndisponivel("fora")

    resiliente, relogio = _montar(AdapterFalso(comportamento), cache_ttl_s=60)
    primeira = await resiliente.buscar(LOJA_A, MODELO)
    assert primeira[0].desatualizado is False

    estado["ok"] = False
    relogio.avancar(61)  # cache expirado, mas ainda serve de fallback
    achados = await resiliente.buscar(LOJA_A, MODELO)
    assert achados == [replace(item("A"), desatualizado=True)]
    assert resiliente.metricas.fallbacks == 1


async def test_fallback_do_obter() -> None:
    estado = {"ok": True}

    def comportamento(_: int) -> list[ItemEstoque]:
        if estado["ok"]:
            return [item("A")]
        raise EstoqueIndisponivel("fora")

    resiliente, relogio = _montar(AdapterFalso(comportamento), cache_ttl_s=10)
    assert (await resiliente.obter(LOJA_A, "A")) == item("A")
    estado["ok"] = False
    relogio.avancar(11)
    assert await resiliente.obter(LOJA_A, "A") == replace(item("A"), desatualizado=True)
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.obter(LOJA_A, "OUTRO")


async def test_obter_inexistente_tambem_e_cacheado() -> None:
    adapter = AdapterFalso(lambda n: [])
    resiliente, _ = _montar(adapter)
    assert await resiliente.obter(LOJA_A, "X") is None
    assert await resiliente.obter(LOJA_A, "X") is None
    assert adapter.chamadas == 1


async def test_cache_valido_evita_nova_consulta() -> None:
    adapter = AdapterFalso(lambda n: [item("A")])
    resiliente, relogio = _montar(adapter, cache_ttl_s=60)
    await resiliente.buscar(LOJA_A, MODELO)
    relogio.avancar(59)
    await resiliente.buscar(LOJA_A, MODELO)
    assert adapter.chamadas == 1
    assert resiliente.metricas.acertos_cache == 1


async def test_ttl_expirado_consulta_de_novo() -> None:
    versao = {"sku": "V1"}
    adapter = AdapterFalso(lambda n: [item(versao["sku"])])
    resiliente, relogio = _montar(adapter, cache_ttl_s=60)
    assert (await resiliente.buscar(LOJA_A, MODELO))[0].sku == "V1"
    versao["sku"] = "V2"
    relogio.avancar(60)
    assert (await resiliente.buscar(LOJA_A, MODELO))[0].sku == "V2"
    assert adapter.chamadas == 2


async def test_argumentos_equivalentes_compartilham_cache() -> None:
    adapter = AdapterFalso(lambda n: [item("A")])
    resiliente, _ = _montar(adapter)
    await resiliente.buscar(LOJA_A, "iPhone 15 Pro", cor="Titânio Azul")
    await resiliente.buscar(LOJA_A, ModeloAparelho.de("iphone 15 pro"), cor=" titânio  azul ")
    assert adapter.chamadas == 1


async def test_cache_isolado_entre_lojas() -> None:
    adapter = AdapterFalso(lambda n: [item(f"CHAMADA{n}")])
    resiliente, _ = _montar(adapter)
    a = await resiliente.buscar(LOJA_A, MODELO)
    b = await resiliente.buscar(LOJA_B, MODELO)
    assert adapter.chamadas == 2
    assert a[0].sku != b[0].sku


async def test_fallback_nao_vaza_entre_lojas() -> None:
    estado = {"ok": True}

    def comportamento(_: int) -> list[ItemEstoque]:
        if estado["ok"]:
            return [item("A")]
        raise EstoqueIndisponivel("fora")

    resiliente, _ = _montar(AdapterFalso(comportamento))
    await resiliente.buscar(LOJA_A, MODELO)
    estado["ok"] = False
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_B, MODELO)


async def test_timeout_conta_como_falha_e_faz_retry() -> None:
    adapter = AdapterLento()
    resiliente, relogio = _montar(adapter, timeout_s=0.05, tentativas=3, backoff_base_s=0.2)
    with pytest.raises(EstoqueIndisponivel):
        await resiliente.buscar(LOJA_A, MODELO)
    assert adapter.chamadas == 3
    assert relogio.dormidos == pytest.approx([0.2, 0.4])


async def test_timeout_com_cache_cai_no_fallback() -> None:
    resiliente, relogio = _montar(AdapterLento(primeira_ok=True), timeout_s=0.05, cache_ttl_s=1)
    await resiliente.buscar(LOJA_A, MODELO)
    relogio.avancar(2)
    achados = await resiliente.buscar(LOJA_A, MODELO)
    assert achados[0].desatualizado is True


async def test_tentativas_invalidas() -> None:
    with pytest.raises(ValueError):
        EstoqueResiliente(AdapterFalso(lambda n: []), RelogioFalso(), tentativas=0)
