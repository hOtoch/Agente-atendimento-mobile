"""API REST da configuracao da loja, com o app real e um banco de teste isolado."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.dependencias import get_session
from app.main import app
from tests.integration.conftest import aplicar_migrations
from tests.integration.lojas import criar_loja_no_banco

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    await aplicar_migrations(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            try:
                yield s
            except BaseException:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _sessao
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def criar_loja(client: httpx.AsyncClient) -> str:
    return await criar_loja_no_banco("Loja API")


PRECO: dict[str, Any] = {
    "max_parcelas": 18,
    "repassa_taxa": True,
    "desconto_pix_tipo": "percentual",
    "desconto_pix_valor": "5",
    "aceita_entrada_mais_cartao": True,
    "desconto_teto": "100",
    "desconto_degrau": "50",
    "oportunidade_ativa": True,
    "oportunidade_dias_minimos": 14,
    "oportunidade_valor": "100",
    "oportunidade_conta_no_teto": False,
}

LINHA_TROCA: dict[str, Any] = {
    "marca": "Apple",
    "modelo": "iPhone 16",
    "capacidade_gb": 128,
    "valor_sem_detalhes": "3100",
    "desconto_tela": "600",
    "desconto_tela_sem": False,
    "desconto_traseira": "300",
    "desconto_traseira_sem": False,
    "desconto_carcaca": "0",
    "desconto_carcaca_sem": False,
    "desconto_bateria": "190",
    "desconto_bateria_sem": False,
    "limite_bateria_pct": 80,
}


async def test_loja_inexistente_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/lojas/00000000-0000-0000-0000-000000000001/config/perfil")
    assert r.status_code == 404


async def test_perfil_put_e_get(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    assert (await client.get(f"/lojas/{loja}/config/perfil")).json() is None
    corpo = {
        "nome_exibicao": "Loja Centro",
        "tom_de_voz": "Direto",
        "endereco": "Rua A, 10",
        "horarios": {"seg-sex": "09:00-18:00"},
        "whatsapp_contato": "5511999990000",
        "responder_em_audio": False,
    }
    r = await client.put(f"/lojas/{loja}/config/perfil", json=corpo)
    assert r.status_code == 200
    assert (await client.get(f"/lojas/{loja}/config/perfil")).json() == corpo


async def test_perfil_sem_responder_em_audio_assume_ligado(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    r = await client.put(f"/lojas/{loja}/config/perfil", json={"nome_exibicao": "Loja"})
    assert r.status_code == 200
    assert r.json()["responder_em_audio"] is True


async def test_perfil_put_invalido_422(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/perfil",
        json={
            "nome_exibicao": "",
            "tom_de_voz": "",
            "endereco": "",
            "horarios": {},
            "whatsapp_contato": "1",
        },
    )
    assert r.status_code == 422
    caminhos = {e["caminho"] for e in r.json()["erros"]}
    assert {"nome_exibicao", "whatsapp_contato"} <= caminhos


async def test_preco_put_get_e_invalido(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    r = await client.put(f"/lojas/{loja}/config/preco", json=PRECO)
    assert r.status_code == 200, r.text
    lido = (await client.get(f"/lojas/{loja}/config/preco")).json()
    assert lido["max_parcelas"] == 18
    assert Decimal_eq(lido["desconto_teto"], "100")

    ruim = await client.put(f"/lojas/{loja}/config/preco", json={**PRECO, "max_parcelas": 30})
    assert ruim.status_code == 422
    assert ruim.json()["erros"] == [
        {"caminho": "max_parcelas", "mensagem": ruim.json()["erros"][0]["mensagem"]}
    ]
    # nada mudou
    assert (await client.get(f"/lojas/{loja}/config/preco")).json()["max_parcelas"] == 18


def Decimal_eq(a: str, b: str) -> bool:  # noqa: N802
    from decimal import Decimal

    return Decimal(a) == Decimal(b)


async def test_preco_corpo_malformado_vira_422_com_caminho(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    r = await client.put(f"/lojas/{loja}/config/preco", json={"max_parcelas": "abc"})
    assert r.status_code == 422
    caminhos = {e["caminho"] for e in r.json()["erros"]}
    assert "max_parcelas" in caminhos
    assert "repassa_taxa" in caminhos  # campo obrigatorio ausente


async def test_taxas_ida_e_volta_com_igual(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    corpo = {
        "taxas": [
            {"chave": 12, "bandeira": "mastercard", "taxa_pct": "10.54"},
            {"chave": 12, "bandeira": "visa", "taxa_pct": None},
            {"chave": "debito", "bandeira": "elo", "taxa_pct": "1.5"},
        ]
    }
    assert (await client.put(f"/lojas/{loja}/config/taxas", json=corpo)).status_code == 200
    lido = (await client.get(f"/lojas/{loja}/config/taxas")).json()["taxas"]
    por_chave = {(t["chave"], t["bandeira"]): t["taxa_pct"] for t in lido}
    assert por_chave[(12, "visa")] is None
    assert Decimal_eq(por_chave[(12, "mastercard")], "10.54")
    assert Decimal_eq(por_chave[("debito", "elo")], "1.5")


async def test_taxas_invalida_422_por_celula(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    r = await client.put(
        f"/lojas/{loja}/config/taxas",
        json={"taxas": [{"chave": 1, "bandeira": "visa", "taxa_pct": "-1"}]},
    )
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "taxas[0].taxa_pct"


async def test_troca_ida_e_volta_com_sem_e_422(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    com_sem = {
        **LINHA_TROCA,
        "modelo": "iPhone 15",
        "desconto_tela": None,
        "desconto_tela_sem": True,
    }
    r = await client.put(
        f"/lojas/{loja}/config/troca", json={"tabela_troca": [LINHA_TROCA, com_sem]}
    )
    assert r.status_code == 200, r.text
    linhas = (await client.get(f"/lojas/{loja}/config/troca")).json()["tabela_troca"]
    assert [x["modelo"] for x in linhas] == ["iPhone 16", "iPhone 15"]
    assert linhas[1]["desconto_tela"] is None
    assert linhas[1]["desconto_tela_sem"] is True
    assert linhas[0]["desconto_tela_sem"] is False
    assert Decimal_eq(linhas[0]["desconto_carcaca"], "0")

    ruim = {**LINHA_TROCA, "modelo": "iPhone 14", "desconto_tela": "9999"}
    r = await client.put(
        f"/lojas/{loja}/config/troca",
        json={"tabela_troca": [LINHA_TROCA, LINHA_TROCA | {"modelo": "iPhone 13"}, ruim]},
    )
    assert r.status_code == 422
    assert [e["caminho"] for e in r.json()["erros"]] == ["tabela_troca[2].desconto_tela"]
    # a gravacao invalida nao alterou nada
    assert len((await client.get(f"/lojas/{loja}/config/troca")).json()["tabela_troca"]) == 2


async def test_estoque_e_mapeamento(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)
    estoque = {
        "estoque": [
            {
                "sku": "IP16-128-PT",
                "marca": "Apple",
                "modelo": "iPhone 16",
                "capacidade_gb": 128,
                "cor": "Preto",
                "condicao": "novo",
                "preco_pix": "4500",
                "quantidade": 3,
                "bateria_pct": None,
            }
        ]
    }
    assert (await client.put(f"/lojas/{loja}/config/estoque", json=estoque)).status_code == 200
    lido = (await client.get(f"/lojas/{loja}/config/estoque")).json()["estoque"]
    assert lido[0]["sku"] == "IP16-128-PT"
    assert lido[0]["bateria_pct"] is None

    estoque["estoque"][0]["condicao"] = "usado"
    r = await client.put(f"/lojas/{loja}/config/estoque", json=estoque)
    assert r.status_code == 422
    assert r.json()["erros"][0]["caminho"] == "estoque[0].condicao"

    mapa = {
        "mapeamento_sku": [
            {
                "sku_externo": "ERP-1",
                "marca": "Apple",
                "modelo": "iPhone 16",
                "capacidade_gb": 128,
                "cor": "Preto",
                "condicao": "novo",
            }
        ]
    }
    assert (await client.put(f"/lojas/{loja}/config/mapeamento-sku", json=mapa)).status_code == 200
    lido = (await client.get(f"/lojas/{loja}/config/mapeamento-sku")).json()["mapeamento_sku"]
    assert lido[0]["sku_externo"] == "ERP-1"


async def test_checklist_reflete_o_que_esta_vazio(client: httpx.AsyncClient) -> None:
    loja = await criar_loja(client)

    async def estado() -> dict[str, bool]:
        r = await client.get(f"/lojas/{loja}/onboarding/checklist")
        assert r.status_code == 200
        return {i["chave"]: i["completo"] for i in r.json()["itens"]}

    inicial = await estado()
    assert inicial["perfil"] is False
    assert inicial["regras_preco"] is False
    assert inicial["tabela_troca"] is False
    assert inicial["estoque"] is False

    await client.put(f"/lojas/{loja}/config/preco", json=PRECO)
    await client.put(f"/lojas/{loja}/config/troca", json={"tabela_troca": [LINHA_TROCA]})
    depois = await estado()
    assert depois["regras_preco"] is True
    assert depois["tabela_troca"] is True
    assert depois["perfil"] is False

    item = (await client.get(f"/lojas/{loja}/onboarding/checklist")).json()["itens"][0]
    assert set(item) == {"chave", "rotulo_ptbr", "completo", "detalhe"}
