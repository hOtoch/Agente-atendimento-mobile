import math

from fastapi.testclient import TestClient

from app.repositorio import carregar_produtos
from tests.conftest import AUTH


def test_total_de_produtos_na_faixa_esperada() -> None:
    produtos = carregar_produtos()
    assert 38 <= len(produtos) <= 45
    assert len({p.sku for p in produtos}) == len(produtos)


def test_dados_tem_estoque_zero_e_itens_que_nao_sao_celular() -> None:
    produtos = carregar_produtos()
    assert any(p.estoque == 0 for p in produtos)
    celulares = ("IPH", "IP ", "APPLE IPHONE")
    nao_celular = [p for p in produtos if not p.descricao.upper().startswith(celulares)]
    assert 2 <= len(nao_celular) <= 3


def test_formato_do_produto(client: TestClient) -> None:
    item = client.get("/produtos", headers=AUTH).json()["itens"][0]
    assert set(item) == {"sku", "descricao", "preco", "estoque", "atualizado_em"}
    assert isinstance(item["preco"], str)
    assert len(item["preco"].split(".")[1]) == 2
    assert isinstance(item["estoque"], int)


def test_paginacao_padrao(client: TestClient) -> None:
    corpo = client.get("/produtos", headers=AUTH).json()
    total = len(carregar_produtos())
    assert corpo["pagina"] == 1
    assert corpo["tamanho"] == 50
    assert corpo["total"] == total
    assert corpo["total_paginas"] == 1
    assert len(corpo["itens"]) == total


def test_paginacao_ultima_pagina_parcial(client: TestClient) -> None:
    total = len(carregar_produtos())
    tamanho = 15
    paginas = math.ceil(total / tamanho)
    corpo = client.get(f"/produtos?pagina={paginas}&tamanho={tamanho}", headers=AUTH).json()
    assert corpo["total_paginas"] == paginas
    assert len(corpo["itens"]) == total - (paginas - 1) * tamanho
    assert len(corpo["itens"]) < tamanho


def test_paginas_cobrem_tudo_sem_repetir(client: TestClient) -> None:
    vistos: list[str] = []
    pagina = 1
    while True:
        corpo = client.get(f"/produtos?pagina={pagina}&tamanho=7", headers=AUTH).json()
        vistos += [i["sku"] for i in corpo["itens"]]
        if pagina >= corpo["total_paginas"]:
            break
        pagina += 1
    assert vistos == [p.sku for p in carregar_produtos()]


def test_pagina_alem_do_fim_retorna_vazio(client: TestClient) -> None:
    resp = client.get("/produtos?pagina=99&tamanho=10", headers=AUTH)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["itens"] == []
    assert corpo["pagina"] == 99
    assert corpo["total"] == len(carregar_produtos())


def test_tamanho_maximo_100(client: TestClient) -> None:
    assert client.get("/produtos?tamanho=100", headers=AUTH).status_code == 200
    assert client.get("/produtos?tamanho=101", headers=AUTH).status_code == 422


def test_parametros_invalidos_422(client: TestClient) -> None:
    assert client.get("/produtos?pagina=0", headers=AUTH).status_code == 422
    assert client.get("/produtos?tamanho=0", headers=AUTH).status_code == 422
    assert client.get("/produtos?pagina=abc", headers=AUTH).status_code == 422


def test_obter_por_sku(client: TestClient) -> None:
    esperado = carregar_produtos()[3]
    resp = client.get(f"/produtos/{esperado.sku}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["sku"] == esperado.sku
    assert resp.json()["descricao"] == esperado.descricao


def test_sku_inexistente_404(client: TestClient) -> None:
    resp = client.get("/produtos/NAO-EXISTE", headers=AUTH)
    assert resp.status_code == 404
