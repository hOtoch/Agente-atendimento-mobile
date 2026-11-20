"""Parser de xlsx: tolerancias e referencia de celula nos erros."""

from decimal import Decimal

from app.adapters.outbound.planilhas.leitor import ler_estoque, ler_taxas, ler_troca
from app.application.config.modelos import ErroCampo
from tests.unit.importacao.planilhas import (
    CAB_TAXAS,
    REGRAS_OK,
    estoque_xlsx,
    regras_com,
    taxas_xlsx,
    troca_xlsx,
    xlsx,
)

D = Decimal


def test_troca_sem_igual_e_virgula_decimal() -> None:
    leitura = ler_troca(
        troca_xlsx(
            [
                ["iPhone 16", 128, "R$ 3.100", 600, 300, 0, "sem", "80"],
                [None] * 8,  # linha vazia ignorada
                ["iPhone 15", 128, None, None, None, None, None, None],  # sem valor: ignorada
                ["iPhone 14", "1TB", "2.500,50", "SEM", "Sem", 0, 100, 85],
            ]
        )
    )
    assert leitura.erros == []
    a, b = leitura.entradas
    assert (a.marca, a.modelo, a.capacidade_gb) == ("Apple", "iPhone 16", 128)
    assert a.valor_sem_detalhes == D("3100")
    assert a.desconto_tela == D("600") and not a.desconto_tela_sem
    assert a.desconto_carcaca == D("0")
    assert a.desconto_bateria is None and a.desconto_bateria_sem
    assert a.limite_bateria_pct == 80
    assert b.capacidade_gb == 1024
    assert b.valor_sem_detalhes == D("2500.50")
    assert b.desconto_tela is None and b.desconto_tela_sem
    assert b.desconto_traseira_sem and b.desconto_bateria == D("100")


def test_troca_celula_invalida_traz_referencia() -> None:
    leitura = ler_troca(
        troca_xlsx(
            [
                ["iPhone 16", 128, 3100, 600, 300, 0, 190, 80],  # linha 2
                ["iPhone 15", "abc", 2000, 0, 0, 0, 0, 80],  # linha 3, capacidade em B3
                ["iPhone 14", 128, "dois mil", 0, 0, 0, 0, 80],  # linha 4, valor em C4
            ]
        )
    )
    assert [e.caminho for e in leitura.erros] == ["troca!B3", "troca!C4"]
    assert "abc" in leitura.erros[0].mensagem
    assert len(leitura.entradas) == 1


def test_troca_outras_marcas() -> None:
    leitura = ler_troca(
        troca_xlsx(
            [],
            outras=[["Samsung", "Galaxy S23", 256, 2000, 0, 0, 0, 0, 80], [None] * 9],
        )
    )
    assert leitura.erros == []
    (e,) = leitura.entradas
    assert (e.marca, e.modelo, e.capacidade_gb) == ("Samsung", "Galaxy S23", 256)
    assert leitura.origens[0]["valor_sem_detalhes"] == "outras_marcas!D2"


def test_troca_aba_ausente_e_arquivo_invalido() -> None:
    assert ler_troca(xlsx({"Qualquer": [["x"]]})).erros[0].caminho == "arquivo"
    assert ler_troca(b"isto nao e um xlsx").erros == [
        ErroCampo("arquivo", "O arquivo não é uma planilha .xlsx válida.")
    ]


def test_taxas_igual_virgula_debito() -> None:
    linhas, regras = ler_taxas(
        taxas_xlsx(
            [
                [1, "1,99", "igual", "IGUAL", None, "2,5"],
                [None] * 6,
                ["12x", "10,54", "11,2", None, None, None],
                ["Débito", 1.5, "igual", None, None, None],
            ]
        )
    )
    assert linhas.erros == [] and regras.erros == []
    por = {(t.chave, t.bandeira): t.taxa_pct for t in linhas.entradas}
    assert por[(1, "mastercard")] == D("1.99")
    assert por[(1, "visa")] is None and por[(1, "elo")] is None
    assert (1, "hipercard") not in por
    assert por[(1, "amex")] == D("2.5")
    assert por[(12, "mastercard")] == D("10.54")
    assert por[("debito", "mastercard")] == D("1.5")
    assert linhas.origens[0]["taxa_pct"] == "taxas!B2"


def test_taxas_celula_invalida() -> None:
    linhas, _ = ler_taxas(taxas_xlsx([[1, "1,99", "xx", None, None, None], ["zzz", 1, 1, 1, 1, 1]]))
    assert [e.caminho for e in linhas.erros] == ["taxas!C2", "taxas!A3"]


def test_taxas_bandeira_desconhecida_no_cabecalho() -> None:
    cab = [*CAB_TAXAS[:-1], "Banco XPTO"]
    linhas, _ = ler_taxas(
        xlsx({"Regras de preço": [["Pergunta", "Resposta"]], "Taxas": [cab, [1, 1, 1, 1, 1, 1]]})
    )
    assert linhas.erros[0].caminho == "taxas!F1"


def test_regras_de_preco() -> None:
    _, regras = ler_taxas(taxas_xlsx([]))
    assert regras.erros == []
    e = regras.entrada
    assert e is not None
    assert e.max_parcelas == 18 and e.repassa_taxa is True
    assert (e.desconto_pix_tipo, e.desconto_pix_valor) == ("percentual", D("5"))
    assert (e.desconto_teto, e.desconto_degrau) == (D("100"), D("50"))
    assert e.oportunidade_ativa and e.oportunidade_dias_minimos == 14
    assert e.oportunidade_valor == D("100")
    assert e.aceita_entrada_mais_cartao is False
    assert regras.origens["max_parcelas"] == "regras!B2"


def _pix(resposta: object) -> tuple[str, Decimal | None]:
    regras = [
        ["Desconto Pix/dinheiro (% ou R$)", resposta] if "Pix" in str(r[0]) else r
        for r in REGRAS_OK
    ]
    _, leitura = ler_taxas(taxas_xlsx([], regras))
    assert leitura.erros == [], leitura.erros
    assert leitura.entrada is not None
    return leitura.entrada.desconto_pix_tipo, leitura.entrada.desconto_pix_valor


def test_regras_pix_formas() -> None:
    assert _pix("R$ 100") == ("valor", D("100"))
    assert _pix("5,5%") == ("percentual", D("5.5"))
    assert _pix("nenhum") == ("nenhum", None)
    assert _pix(None) == ("nenhum", None)


def test_regras_com_erros_de_celula() -> None:
    regras = regras_com(**{"Máximo_de_parcelas": "dezoito", "Repassa": "talvez"})
    _, leitura = ler_taxas(taxas_xlsx([], regras))
    assert [e.caminho for e in leitura.erros] == ["regras!B2", "regras!B3"]
    assert leitura.entrada is None


def test_regras_pergunta_ausente() -> None:
    _, leitura = ler_taxas(taxas_xlsx([], REGRAS_OK[1:]))
    assert [e.caminho for e in leitura.erros] == ["regras"]


def test_estoque() -> None:
    leitura = ler_estoque(
        estoque_xlsx(
            [
                ["IP15P", "iPhone 15 Pro", "256GB", "Titânio", "Novo", "R$ 7.500", 2, None],
                [None] * 8,
                ["IP13", "iPhone 13", 128, "Preto", "semi-novo", "3.200,00", "1", "91%"],
                ["IP12", "iPhone 12", "xx", "Azul", "novo", 2000, 1, None],
            ]
        )
    )
    assert [e.caminho for e in leitura.erros] == ["estoque!C5"]
    a, b = leitura.entradas
    assert (a.sku, a.modelo, a.capacidade_gb, a.condicao) == ("IP15P", "iPhone 15 Pro", 256, "novo")
    assert a.preco_pix == D("7500") and a.quantidade == 2 and a.bateria_pct is None
    assert (b.condicao, b.preco_pix, b.quantidade, b.bateria_pct) == ("seminovo", D("3200"), 1, 91)
    assert a.marca == "Apple"
