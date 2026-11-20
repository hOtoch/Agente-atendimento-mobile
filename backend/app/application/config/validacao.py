"""Validacao e montagem dos objetos de dominio a partir das entradas (coleta erros por campo)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaMapeamento,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
)
from app.application.config.modelos import (
    CONDICOES,
    ConfigPreco,
    ErroCampo,
    ErrosDeValidacao,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
)
from app.domain.bandeira import Bandeira
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.pagamento import (
    DEBITO,
    PARCELAS_MAX,
    PARCELAS_MIN,
    ChaveTaxa,
    DescontoPix,
    DescontoPixNenhum,
    DescontoPixPercentual,
    DescontoPixValor,
    RegrasPreco,
    TabelaTaxas,
)
from app.domain.troca import SEM, DescontoTroca, LinhaTroca, TabelaTroca
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

_CEM: Final = Decimal(100)
_ZERO: Final = Decimal(0)
_MARCA_APPLE: Final = "Apple"


def _levantar(erros: list[ErroCampo]) -> None:
    if erros:
        raise ErrosDeValidacao(erros)


def _finito(valor: Decimal) -> bool:
    return valor.is_finite()


def _int_valido(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


# --- perfil -----------------------------------------------------------------------------------


def validar_perfil(perfil: PerfilLoja) -> None:
    erros: list[ErroCampo] = []
    if not perfil.nome_exibicao.strip():
        erros.append(ErroCampo("nome_exibicao", "Informe o nome de exibição da loja."))
    contato = perfil.whatsapp_contato.strip()
    if contato and not 10 <= len(re.sub(r"\D", "", contato)) <= 15:
        erros.append(ErroCampo("whatsapp_contato", "WhatsApp deve ter de 10 a 15 dígitos."))
    _levantar(erros)


# --- preco ------------------------------------------------------------------------------------


def montar_config_preco(e: EntradaPreco) -> ConfigPreco:
    erros: list[ErroCampo] = []

    if not _int_valido(e.max_parcelas) or not PARCELAS_MIN <= e.max_parcelas <= PARCELAS_MAX:
        erros.append(
            ErroCampo(
                "max_parcelas",
                f"Máximo de parcelas deve estar entre {PARCELAS_MIN} e {PARCELAS_MAX}.",
            )
        )

    desconto_pix: DescontoPix = DescontoPixNenhum()
    valor_pix = e.desconto_pix_valor
    if e.desconto_pix_tipo == "nenhum":
        pass
    elif e.desconto_pix_tipo in ("percentual", "valor"):
        if valor_pix is None or not _finito(valor_pix):
            erros.append(ErroCampo("desconto_pix_valor", "Informe o valor do desconto Pix."))
        elif e.desconto_pix_tipo == "percentual":
            if not _ZERO <= valor_pix <= _CEM:
                erros.append(
                    ErroCampo(
                        "desconto_pix_valor", "Percentual do desconto Pix deve ser de 0 a 100."
                    )
                )
            else:
                desconto_pix = DescontoPixPercentual(valor_pix)
        elif valor_pix < _ZERO:
            erros.append(ErroCampo("desconto_pix_valor", "Desconto Pix não pode ser negativo."))
        else:
            desconto_pix = DescontoPixValor(Dinheiro.de(valor_pix))
    else:
        erros.append(
            ErroCampo("desconto_pix_tipo", "Tipo deve ser 'nenhum', 'percentual' ou 'valor'.")
        )

    teto = degrau = valor_oport = None
    if not _finito(e.desconto_teto) or e.desconto_teto < _ZERO:
        erros.append(ErroCampo("desconto_teto", "Desconto máximo não pode ser negativo."))
    else:
        teto = Dinheiro.de(e.desconto_teto)
    if not _finito(e.desconto_degrau) or e.desconto_degrau <= _ZERO:
        erros.append(ErroCampo("desconto_degrau", "Degrau do desconto deve ser maior que zero."))
    else:
        degrau = Dinheiro.de(e.desconto_degrau)
        if degrau.zerado:
            erros.append(
                ErroCampo("desconto_degrau", "Degrau do desconto deve ser de ao menos R$ 0,01.")
            )
            degrau = None
    if not _int_valido(e.oportunidade_dias_minimos) or e.oportunidade_dias_minimos < 0:
        erros.append(ErroCampo("oportunidade_dias_minimos", "Dias mínimos não pode ser negativo."))
    if not _finito(e.oportunidade_valor) or e.oportunidade_valor < _ZERO:
        erros.append(
            ErroCampo("oportunidade_valor", "Valor da oportunidade não pode ser negativo.")
        )
    else:
        valor_oport = Dinheiro.de(e.oportunidade_valor)

    _levantar(erros)
    assert teto is not None
    assert degrau is not None
    assert valor_oport is not None
    return ConfigPreco(
        RegrasPreco(
            max_parcelas=e.max_parcelas,
            repassa_taxa=e.repassa_taxa,
            desconto_pix=desconto_pix,
            aceita_entrada_mais_cartao=e.aceita_entrada_mais_cartao,
        ),
        PoliticaDesconto(teto=teto, degrau=degrau),
        RegraOportunidadeUnica(
            ativa=e.oportunidade_ativa,
            dias_minimos=e.oportunidade_dias_minimos,
            valor=valor_oport,
            conta_no_teto=e.oportunidade_conta_no_teto,
        ),
    )


# --- taxas ------------------------------------------------------------------------------------


def _parse_chave(chave: int | str) -> ChaveTaxa | None:
    if isinstance(chave, int) and not isinstance(chave, bool):
        return chave if PARCELAS_MIN <= chave <= PARCELAS_MAX else None
    texto = str(chave).strip().lower()
    if texto == DEBITO:
        return DEBITO
    if texto.isdigit() and PARCELAS_MIN <= int(texto) <= PARCELAS_MAX:
        return int(texto)
    return None


def montar_taxas(entradas: Sequence[EntradaTaxa]) -> TabelaTaxas:
    erros: list[ErroCampo] = []
    taxas: dict[tuple[ChaveTaxa, Bandeira], Decimal | None] = {}
    for i, e in enumerate(entradas):
        base = f"taxas[{i}]"
        chave = _parse_chave(e.chave)
        if chave is None:
            erros.append(
                ErroCampo(
                    f"{base}.chave",
                    f"Chave deve ser de {PARCELAS_MIN} a {PARCELAS_MAX} ou 'debito'.",
                )
            )
        try:
            bandeira: Bandeira | None = Bandeira.parse(e.bandeira)
        except ValueError:
            bandeira = None
            erros.append(ErroCampo(f"{base}.bandeira", f"Bandeira desconhecida: {e.bandeira!r}."))
        taxa_ok = True
        if e.taxa_pct is not None and (not _finito(e.taxa_pct) or not _ZERO <= e.taxa_pct <= _CEM):
            taxa_ok = False
            erros.append(ErroCampo(f"{base}.taxa_pct", "Taxa deve estar entre 0 e 100 (%)."))
        if chave is not None and bandeira is not None:
            if (chave, bandeira) in taxas:
                erros.append(
                    ErroCampo(f"{base}.bandeira", "Taxa repetida para esta chave e bandeira.")
                )
            elif taxa_ok:
                taxas[(chave, bandeira)] = e.taxa_pct
    _levantar(erros)
    return TabelaTaxas(taxas)


# --- troca ------------------------------------------------------------------------------------


def _modelo(marca: str, modelo: str, base: str, erros: list[ErroCampo]) -> ModeloAparelho | None:
    antes = len(erros)
    if not marca.strip():
        erros.append(ErroCampo(f"{base}.marca", "Informe a marca."))
    if not modelo.strip():
        erros.append(ErroCampo(f"{base}.modelo", "Informe o modelo."))
    if len(erros) > antes:
        return None
    return ModeloAparelho.de(modelo, marca)


def _capacidade(gb: int, base: str, erros: list[ErroCampo]) -> Capacidade | None:
    try:
        return Capacidade(gb)
    except (ValueError, TypeError):
        erros.append(
            ErroCampo(f"{base}.capacidade_gb", "Capacidade deve ser um inteiro positivo em GB.")
        )
        return None


def _desconto_troca(
    campo: str,
    valor: Decimal | None,
    sem: bool,
    base_valor: Dinheiro | None,
    base: str,
    erros: list[ErroCampo],
) -> DescontoTroca | None:
    caminho = f"{base}.desconto_{campo}"
    if sem:
        if valor is not None:
            erros.append(ErroCampo(caminho, "Informe o valor ou marque SEM, não os dois."))
            return None
        return SEM
    if valor is None:
        erros.append(ErroCampo(caminho, "Informe o valor, 0 ou SEM."))
        return None
    if not _finito(valor) or valor < _ZERO:
        erros.append(ErroCampo(caminho, "Desconto não pode ser negativo."))
        return None
    desconto = Dinheiro.de(valor)
    if base_valor is not None and desconto > base_valor:
        erros.append(ErroCampo(caminho, f"Desconto maior que o valor base ({base_valor})."))
        return None
    return desconto


def montar_tabela_troca(entradas: Sequence[EntradaLinhaTroca]) -> TabelaTroca:
    erros: list[ErroCampo] = []
    apple: list[LinhaTroca] = []
    outras: list[LinhaTroca] = []
    vistos: set[tuple[str, str, int]] = set()
    for i, e in enumerate(entradas):
        base = f"tabela_troca[{i}]"
        antes = len(erros)
        modelo = _modelo(e.marca, e.modelo, base, erros)
        capacidade = _capacidade(e.capacidade_gb, base, erros)
        valor_base: Dinheiro | None = None
        if not _finito(e.valor_sem_detalhes) or e.valor_sem_detalhes < _ZERO:
            erros.append(
                ErroCampo(f"{base}.valor_sem_detalhes", "Valor sem detalhes não pode ser negativo.")
            )
        else:
            valor_base = Dinheiro.de(e.valor_sem_detalhes)
        descontos = [
            _desconto_troca(c, v, s, valor_base, base, erros)
            for c, v, s in (
                ("tela", e.desconto_tela, e.desconto_tela_sem),
                ("traseira", e.desconto_traseira, e.desconto_traseira_sem),
                ("carcaca", e.desconto_carcaca, e.desconto_carcaca_sem),
                ("bateria", e.desconto_bateria, e.desconto_bateria_sem),
            )
        ]
        if not _int_valido(e.limite_bateria_pct) or not 0 <= e.limite_bateria_pct <= 100:
            erros.append(
                ErroCampo(
                    f"{base}.limite_bateria_pct", "Limite de bateria deve ser de 0 a 100 (%)."
                )
            )
        if modelo is not None and capacidade is not None:
            chave = (modelo.marca, modelo.nome, int(capacidade))
            if chave in vistos:
                erros.append(
                    ErroCampo(f"{base}.modelo", "Linha repetida (mesmo modelo e capacidade).")
                )
            vistos.add(chave)
        if len(erros) > antes:
            continue
        assert modelo is not None
        assert capacidade is not None
        assert valor_base is not None
        tela, traseira, carcaca, bateria = descontos
        assert tela is not None
        assert traseira is not None
        assert carcaca is not None
        assert bateria is not None
        linha = LinhaTroca(
            modelo=modelo,
            capacidade=capacidade,
            valor_sem_detalhes=valor_base,
            desconto_tela=tela,
            desconto_traseira=traseira,
            desconto_carcaca=carcaca,
            desconto_bateria=bateria,
            limite_bateria_pct=e.limite_bateria_pct,
        )
        (apple if modelo.marca == _MARCA_APPLE else outras).append(linha)
    _levantar(erros)
    return TabelaTroca(linhas_apple=tuple(apple), linhas_outras_marcas=tuple(outras))


# --- estoque e mapeamento ---------------------------------------------------------------------


def _condicao(condicao: str, base: str, erros: list[ErroCampo]) -> None:
    if condicao not in CONDICOES:
        erros.append(ErroCampo(f"{base}.condicao", "Condição deve ser 'novo' ou 'seminovo'."))


def _obrigatorio(texto: str, campo: str, base: str, erros: list[ErroCampo], rotulo: str) -> None:
    if not texto.strip():
        erros.append(ErroCampo(f"{base}.{campo}", f"Informe {rotulo}."))


def montar_estoque(entradas: Sequence[EntradaLinhaEstoque]) -> list[LinhaEstoqueLocal]:
    erros: list[ErroCampo] = []
    linhas: list[LinhaEstoqueLocal] = []
    skus: set[str] = set()
    for i, e in enumerate(entradas):
        base = f"estoque[{i}]"
        antes = len(erros)
        sku = e.sku.strip()
        _obrigatorio(e.sku, "sku", base, erros, "o SKU")
        if sku and sku in skus:
            erros.append(ErroCampo(f"{base}.sku", "SKU repetido."))
        skus.add(sku)
        modelo = _modelo(e.marca, e.modelo, base, erros)
        capacidade = _capacidade(e.capacidade_gb, base, erros)
        _obrigatorio(e.cor, "cor", base, erros, "a cor")
        _condicao(e.condicao, base, erros)
        preco: Dinheiro | None = None
        if not _finito(e.preco_pix) or e.preco_pix < _ZERO:
            erros.append(ErroCampo(f"{base}.preco_pix", "Preço Pix não pode ser negativo."))
        else:
            preco = Dinheiro.de(e.preco_pix)
        if not _int_valido(e.quantidade) or e.quantidade < 0:
            erros.append(ErroCampo(f"{base}.quantidade", "Quantidade não pode ser negativa."))
        if e.bateria_pct is not None and (
            not _int_valido(e.bateria_pct) or not 0 <= e.bateria_pct <= 100
        ):
            erros.append(ErroCampo(f"{base}.bateria_pct", "Bateria deve ser de 0 a 100 (%)."))
        if len(erros) > antes:
            continue
        assert modelo is not None
        assert capacidade is not None
        assert preco is not None
        linhas.append(
            LinhaEstoqueLocal(
                sku=sku,
                modelo=modelo,
                capacidade=capacidade,
                cor=e.cor.strip(),
                condicao=e.condicao,
                preco_pix=preco,
                quantidade=e.quantidade,
                bateria_pct=e.bateria_pct,
            )
        )
    _levantar(erros)
    return linhas


def montar_mapeamento(entradas: Sequence[EntradaLinhaMapeamento]) -> list[LinhaMapeamentoSku]:
    erros: list[ErroCampo] = []
    linhas: list[LinhaMapeamentoSku] = []
    skus: set[str] = set()
    for i, e in enumerate(entradas):
        base = f"mapeamento_sku[{i}]"
        antes = len(erros)
        sku = e.sku_externo.strip()
        _obrigatorio(e.sku_externo, "sku_externo", base, erros, "o SKU externo")
        if sku and sku in skus:
            erros.append(ErroCampo(f"{base}.sku_externo", "SKU externo repetido."))
        skus.add(sku)
        modelo = _modelo(e.marca, e.modelo, base, erros)
        capacidade = _capacidade(e.capacidade_gb, base, erros)
        _obrigatorio(e.cor, "cor", base, erros, "a cor")
        _condicao(e.condicao, base, erros)
        if len(erros) > antes:
            continue
        assert modelo is not None
        assert capacidade is not None
        linhas.append(
            LinhaMapeamentoSku(
                sku_externo=sku,
                modelo=modelo,
                capacidade=capacidade,
                cor=e.cor.strip(),
                condicao=e.condicao,
            )
        )
    _levantar(erros)
    return linhas


# --- vendedores -------------------------------------------------------------------------------


def validar_pesos_vendedores(pesos: Sequence[Decimal]) -> list[ErroCampo]:
    """Percentual de cada vendedor deve estar em 0..100 (CRUD de vendedores: outra issue)."""
    return [
        ErroCampo(f"vendedores[{i}].peso_percentual", "Percentual deve ser de 0 a 100.")
        for i, p in enumerate(pesos)
        if not _finito(p) or not _ZERO <= p <= _CEM
    ]
