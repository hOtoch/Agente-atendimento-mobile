"""Prompt de sistema por loja e mensagem de estado injetada a cada turno.

`montar_sistema` devolve `[prefixo_estavel, bloco_da_loja]`: o prefixo e identico para todas
as lojas (cacheavel, nada variavel) e o bloco da loja vem depois do breakpoint de cache.
`mensagem_estado` e a mensagem de sistema do meio da conversa (data, ficha, pendencias).
Nenhum valor monetario entra aqui: preco, troca, parcela e desconto vem so das ferramentas.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from functools import cache
from importlib import resources
from typing import Final

from app.application.config.modelos import ConfigPreco, LinhaEstoqueLocal, PerfilLoja
from app.domain.ficha import Ficha, Pendencia, TipoPagamento, pendencias

_DIAS_SEMANA: Final = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

_P = Pendencia

ROTULOS_PENDENCIA: Final[dict[Pendencia, str]] = {
    _P.APARELHO_MODELO: "modelo do aparelho desejado",
    _P.APARELHO_CAPACIDADE: "capacidade do aparelho desejado",
    _P.ESTOQUE_CONFIRMADO: "item do estoque escolhido pelo cliente",
    _P.TEM_TROCA: "se há aparelho para dar na troca",
    _P.USADO_MODELO: "modelo do aparelho usado",
    _P.USADO_CAPACIDADE: "capacidade do aparelho usado",
    _P.USADO_TELA: "estado da tela do usado",
    _P.USADO_TRASEIRA: "estado da traseira do usado",
    _P.USADO_CARCACA: "marcas na carcaça do usado",
    _P.USADO_BATERIA: "saúde da bateria do usado",
    _P.USADO_CAMERA: "funcionamento da câmera do usado",
    _P.USADO_OUTROS_DEFEITOS: "outros defeitos do usado",
    _P.USADO_PECA_TROCADA: "peça já trocada no usado",
    _P.DATA_COMPRA: "data prevista da compra",
    _P.PAGAMENTO_TIPO: "forma de pagamento",
    _P.PAGAMENTO_PARCELAS: "número de parcelas",
    _P.PAGAMENTO_BANDEIRA: "bandeira do cartão",
    _P.PAGAMENTO_ENTRADA: "valor da entrada",
}

_PERGUNTAS: Final[dict[Pendencia, str]] = {
    _P.APARELHO_MODELO: "Pergunte qual aparelho (marca e modelo) o cliente quer.",
    _P.APARELHO_CAPACIDADE: "Pergunte qual capacidade de armazenamento ele prefere.",
    _P.ESTOQUE_CONFIRMADO: (
        "Mostre as opções devolvidas por consultar_estoque e pergunte qual ele quer."
    ),
    _P.TEM_TROCA: "Pergunte se ele tem um aparelho para dar na troca.",
    _P.USADO_MODELO: "Pergunte qual é o modelo do aparelho que ele daria na troca.",
    _P.USADO_CAPACIDADE: "Pergunte a capacidade de armazenamento do aparelho usado.",
    _P.USADO_TELA: "Pergunte se a tela do aparelho usado tem trincos, riscos fundos ou manchas.",
    _P.USADO_TRASEIRA: "Pergunte se o vidro traseiro do aparelho usado está trincado ou quebrado.",
    _P.USADO_CARCACA: "Pergunte se a carcaça (laterais e bordas) tem marcas ou amassados.",
    _P.USADO_BATERIA: (
        "Peça um print de Ajustes > Bateria > Saúde da Bateria, ou o percentual de lá. "
        "Se ele mandar o print, use registrar_leitura_imagem."
    ),
    _P.USADO_CAMERA: "Pergunte se as câmeras do aparelho usado funcionam normalmente.",
    _P.USADO_OUTROS_DEFEITOS: "Pergunte se o aparelho usado tem algum outro defeito.",
    _P.USADO_PECA_TROCADA: "Pergunte se o aparelho usado já teve alguma peça trocada.",
    _P.DATA_COMPRA: "Pergunte quando o cliente pretende comprar.",
    _P.PAGAMENTO_TIPO: (
        "Pergunte como ele prefere pagar: Pix, débito, crédito ou entrada mais cartão."
    ),
    _P.PAGAMENTO_PARCELAS: "Pergunte em quantas parcelas ele quer pagar no crédito.",
    _P.PAGAMENTO_BANDEIRA: "Pergunte qual a bandeira do cartão.",
    _P.PAGAMENTO_ENTRADA: "Pergunte qual valor ele quer dar de entrada.",
}

_PAGAMENTO_NOME: Final[dict[TipoPagamento, str]] = {
    TipoPagamento.PIX: "Pix",
    TipoPagamento.DEBITO: "débito",
    TipoPagamento.CREDITO: "crédito",
    TipoPagamento.ENTRADA_MAIS_CREDITO: "entrada mais crédito",
}


@cache
def carregar_prefixo() -> str:
    """Le o prefixo estavel empacotado em `templates/sistema_base.md`."""
    texto = (
        resources.files("app.application.agente.templates")
        .joinpath("sistema_base.md")
        .read_text(encoding="utf-8")
    )
    return texto.strip()


def montar_sistema(
    perfil: PerfilLoja, config: ConfigPreco | None, marcas: Sequence[str] = ()
) -> list[str]:
    """`[prefixo_estavel, bloco_da_loja]`; so o prefixo (indice 0) e cacheado.

    `marcas` sao as do estoque da loja (de `marcas_do_estoque`): ficam no bloco da loja.
    """
    return [carregar_prefixo(), _bloco_loja(perfil, config, marcas)]


def marcas_do_estoque(linhas: Iterable[LinhaEstoqueLocal]) -> list[str]:
    """Marcas com unidades disponiveis, da que tem mais unidades para a que tem menos."""
    contagem = Counter(linha.modelo.marca for linha in linhas if linha.quantidade > 0)
    return [marca for marca, _ in contagem.most_common()]


def _rotulo_marca(marca: str) -> str:
    return "iPhone (Apple)" if marca == "Apple" else marca


def _bloco_loja(perfil: PerfilLoja, config: ConfigPreco | None, marcas: Sequence[str]) -> str:
    horarios = "; ".join(f"{dia}: {faixa}" for dia, faixa in perfil.horarios.items())
    linhas = [
        "# Dados da loja",
        "",
        f"Nome: {perfil.nome_exibicao}",
        f"Tom de voz: {perfil.tom_de_voz}",
        f"Endereço: {perfil.endereco}",
        f"Horários: {horarios or 'não informados'}",
        f"WhatsApp da loja: {perfil.whatsapp_contato}",
    ]
    if marcas:
        linhas.append(f"Marcas no estoque: {', '.join(_rotulo_marca(m) for m in marcas)}")
    if config is not None:
        regras = config.regras
        formas = ["Pix", "débito", f"crédito em até {regras.max_parcelas} parcelas"]
        if regras.aceita_entrada_mais_cartao:
            formas.append("entrada mais cartão")
        linhas.append(f"Formas de pagamento aceitas: {', '.join(formas)}")
        linhas.append(f"Máximo de parcelas no crédito: {regras.max_parcelas}")
    return "\n".join(linhas)


def mensagem_estado(
    ficha: Ficha,
    *,
    hoje: date,
    estoque_consultado: bool,
    proposta_apresentada: bool,
    desconto_liberado: str | None,
    handoff_solicitado: bool,
) -> str:
    """Mensagem de sistema do turno: data, ficha, pendencias, proxima pergunta e lembretes."""
    faltas = pendencias(ficha)
    linhas = [
        "ESTADO DO ATENDIMENTO (atualizado a cada turno; é só para você, não repita ao cliente)",
        f"Hoje é {hoje.isoformat()} ({_DIAS_SEMANA[hoje.weekday()]}).",
        "",
        "O que já sabemos:",
        *(f"- {item}" for item in _conhecido(ficha)),
        "",
    ]
    if faltas:
        linhas.append("Pendências, em ordem:")
        linhas.extend(f"{n}. {ROTULOS_PENDENCIA[p]}" for n, p in enumerate(faltas, start=1))
        linhas.append(f"PRÓXIMA PERGUNTA: {_pergunta(faltas[0], estoque_consultado)}")
        linhas.append(
            f"NÃO chame calcular_proposta ainda (faltam {len(faltas)} itens). "
            "Se o cliente pedir preço, explique que faltam informações e faça a próxima pergunta."
        )
    else:
        linhas.append("Sem pendências: a ficha está completa.")
        if proposta_apresentada:
            linhas.append(
                "A proposta já foi apresentada. Chame calcular_proposta de novo só se o cliente "
                "mudar algum dado."
            )
        else:
            linhas.append("PODE chamar calcular_proposta agora e apresentar as opções.")
    linhas.append("")
    if proposta_apresentada and faltas:
        linhas.append("A proposta já foi apresentada, mas algum dado mudou: refaça a qualificação.")
    if desconto_liberado is not None:
        linhas.append(
            f"Desconto já liberado pela ferramenta: {desconto_liberado}. "
            "Não ofereça mais que isso; para mais, só chamando liberar_desconto."
        )
    if handoff_solicitado:
        linhas.append(
            "Um vendedor já foi chamado (chamar_vendedor): avise o cliente e não prossiga "
            "com a venda."
        )
    elif _pede_estoque(ficha, estoque_consultado):
        linhas.append("Ainda não consultou o estoque: chame consultar_estoque antes de oferecer.")
    linhas.extend(
        [
            "Lembretes: uma pergunta por mensagem, no máximo 3 frases, sem inventar valores.",
            "Registre cada resposta do cliente com a ferramenta certa antes da próxima pergunta.",
            "Se o cliente pedir um vendedor, quiser fechar, reclamar ou sair do escopo: "
            "chamar_vendedor.",
        ]
    )
    return "\n".join(linhas)


def _pede_estoque(ficha: Ficha, estoque_consultado: bool) -> bool:
    i = ficha.interesse
    return not estoque_consultado and i.modelo is not None and i.capacidade is not None


def _pergunta(pendencia: Pendencia, estoque_consultado: bool) -> str:
    if pendencia is Pendencia.ESTOQUE_CONFIRMADO and not estoque_consultado:
        return "Chame consultar_estoque com o modelo e a capacidade e depois apresente as opções."
    return _PERGUNTAS[pendencia]


def _conhecido(ficha: Ficha) -> list[str]:
    i = ficha.interesse
    itens: list[str] = []
    if i.modelo is not None:
        cap = f" {i.capacidade}" if i.capacidade is not None else ""
        cor = f", cor {i.cor}" if i.cor else ""
        conf = " (item de estoque confirmado)" if i.sku_estoque_confirmado else ""
        itens.append(f"Aparelho desejado: {i.modelo}{cap}{cor}{conf}")
    elif i.capacidade is not None:
        itens.append(f"Aparelho desejado: capacidade {i.capacidade}")
    if ficha.tem_troca is False:
        itens.append("Troca: não, sem aparelho na troca (dispensa as perguntas do usado)")
    elif ficha.tem_troca:
        itens.append("Troca: sim, com aparelho usado")
        itens.extend(_conhecido_usado(ficha))
    if ficha.data_prevista_compra is not None:
        itens.append(f"Compra prevista para {ficha.data_prevista_compra.isoformat()}")
    if ficha.pagamento.tipo is not None:
        itens.append(f"Pagamento: {descrever_pagamento(ficha)}")
    return itens or ["Nada ainda: é o início da conversa."]


def _conhecido_usado(ficha: Ficha) -> list[str]:
    u = ficha.usado
    itens: list[str] = []
    if u.modelo is not None:
        cap = f" {u.capacidade}" if u.capacidade is not None else ""
        itens.append(f"Usado: {u.modelo}{cap}")
    sim_nao = (
        ("tela", u.tela_danificada, "danificada", "sem danos"),
        ("traseira", u.traseira_danificada, "danificada", "sem danos"),
        ("carcaça", u.carcaca_marcada, "marcada", "sem marcas"),
    )
    for nome, valor, sim, nao in sim_nao:
        if valor is not None:
            itens.append(f"Usado, {nome}: {sim if valor else nao}")
    if u.bateria_pct is not None:
        itens.append(f"Usado, bateria: {u.bateria_pct}%")
    if u.camera_ok is not None:
        itens.append(f"Usado, câmera: {'funciona' if u.camera_ok else 'com problema'}")
    if u.outros_defeitos is not None:
        defeitos = ", ".join(u.outros_defeitos) or "nenhum"
        itens.append(f"Usado, defeitos extras: {defeitos}")
    if u.peca_trocada is not None:
        itens.append(f"Usado, peça trocada: {'sim' if u.peca_trocada else 'não'}")
    return itens


def descrever_pagamento(ficha: Ficha) -> str:
    p = ficha.pagamento
    assert p.tipo is not None
    partes = [_PAGAMENTO_NOME[p.tipo]]
    if p.parcelas is not None:
        partes.append(f"{p.parcelas}x")
    if p.bandeira is not None:
        partes.append(f"bandeira {p.bandeira.value}")
    if p.entrada is not None:
        partes.append(f"entrada de {p.entrada}")
    return ", ".join(partes)


def resumo_do_que_sabemos(ficha: Ficha) -> list[str]:
    """Itens da ficha ja conhecidos, em texto (reaproveitado pelo follow-up)."""
    return _conhecido(ficha)
