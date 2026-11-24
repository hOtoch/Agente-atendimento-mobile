"""Ferramentas do agente. O LLM conversa e chama estas funcoes; o CODIGO decide.

A trava de preco vive em `calcular_proposta`: com a ficha incompleta ela devolve so as
pendencias (nunca um valor). `consultar_estoque` nunca devolve preco. O estado e imutavel:
cada execucao devolve um novo `EstadoAtendimento`; persistir e registrar eventos fica com o
orquestrador.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from app.application.agente.aceite import parece_aceite
from app.application.agente.acordo import (
    MOTIVO_ACORDO_FECHADO,
    conteudo_para_ia,
    ficha_confirmacao,
    mesmo_acordo,
    montar_acordo,
)
from app.application.agente.contexto import ContextoFerramentas, ErroFerramenta
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.imagem import LeituraImagem, TipoImagem, decidir_leitura
from app.application.agente.pergunta_pagamento import (
    ROTULOS_INSTRUCAO,
    pergunta_pagamento_ao_cliente,
    rotulos_aceitos,
)
from app.application.agente.proposta import FRASE_OBRIGATORIA, montar_proposta
from app.application.config.modelos import LojaNaoEncontrada
from app.application.estoque import EstoqueIndisponivel
from app.application.llm import DefinicaoFerramenta
from app.domain.desconto import (
    DescontoLiberado,
    PassarAoVendedor,
    PedidoCliente,
    PoliticaDesconto,
    decidir_pedido_desconto,
)
from app.domain.estoque import (
    Condicao,
    ItemEstoque,
    ModeloAmbiguo,
    ModeloResolvido,
    filtrar,
    resolver_modelo,
)
from app.domain.ficha import Ficha, Pendencia, TipoPagamento, UsadoInformado, pendencias
from app.domain.metricas import MOTIVO_NEGOCIACAO
from app.domain.troca import MotivoLoja, motivo_fora_da_tabela
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

__all__ = [
    "FRASE_OBRIGATORIA",
    "CatalogoFerramentas",
    "ContextoFerramentas",
    "ResultadoFerramenta",
    "parece_aceite",
]

_MAX_OPCOES = 10
_RESUMO_MAX = 400
_MARCAS_OUTRAS = {
    "samsung": "Samsung",
    "motorola": "Motorola",
    "xiaomi": "Xiaomi",
    "lg": "LG",
    "huawei": "Huawei",
    "asus": "Asus",
    "oneplus": "OnePlus",
    "realme": "Realme",
    "oppo": "Oppo",
    "google": "Google",
}

_P = Pendencia
_TEXTOS_PENDENCIA: dict[Pendencia, tuple[str, str]] = {
    _P.APARELHO_MODELO: ("modelo do aparelho desejado", "Qual aparelho você está procurando?"),
    _P.APARELHO_CAPACIDADE: (
        "capacidade do aparelho desejado",
        "Qual capacidade de armazenamento você prefere?",
    ),
    _P.ESTOQUE_CONFIRMADO: (
        "item do estoque confirmado",
        "Qual das opções disponíveis no estoque você prefere?",
    ),
    _P.TEM_TROCA: ("se tem aparelho para dar na troca", "Você vai dar um aparelho usado na troca?"),
    _P.USADO_MODELO: ("modelo do aparelho usado", "Qual é o modelo do seu aparelho usado?"),
    _P.USADO_CAPACIDADE: (
        "capacidade do aparelho usado",
        "Qual a capacidade de armazenamento dele?",
    ),
    _P.USADO_TELA: ("estado da tela do usado", "A tela dele está trincada ou com algum dano?"),
    _P.USADO_TRASEIRA: (
        "estado do vidro traseiro do usado",
        "O vidro traseiro está trincado ou danificado?",
    ),
    _P.USADO_CARCACA: ("estado da carcaça do usado", "A carcaça tem marcas ou amassados?"),
    _P.USADO_BATERIA: (
        "saúde da bateria do usado",
        "Qual a saúde da bateria dele (em Ajustes, Bateria)?",
    ),
    _P.DATA_COMPRA: ("data prevista da compra", "Quando você pretende fazer a compra?"),
    _P.PAGAMENTO_TIPO: (
        "forma de pagamento",
        "Como você prefere pagar: Pix, débito, cartão de crédito ou entrada mais cartão?",
    ),
    _P.PAGAMENTO_PARCELAS: ("número de parcelas", "Em quantas vezes você quer parcelar?"),
    _P.PAGAMENTO_BANDEIRA: ("bandeira do cartão", "Qual a bandeira do cartão?"),
    _P.PAGAMENTO_ENTRADA: ("valor da entrada", "Quanto você quer dar de entrada?"),
}


@dataclass(frozen=True, slots=True)
class ResultadoFerramenta:
    conteudo: dict[str, Any]
    """JSON curto que volta para o LLM."""
    estado: EstadoAtendimento
    eventos: list[dict[str, Any]] = field(default_factory=list)
    erro: bool = False


@dataclass(frozen=True, slots=True)
class _Saida:
    conteudo: dict[str, Any]
    estado: EstadoAtendimento


type _Handler = Callable[
    [dict[str, Any], EstadoAtendimento, ContextoFerramentas], Awaitable[_Saida]
]


# --- leitura da entrada (o LLM pode errar tipos mesmo com esquema strict) -------------------


def _texto_obrigatorio(entrada: dict[str, Any], campo: str) -> str:
    valor = entrada.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErroFerramenta(f"O campo '{campo}' é obrigatório e deve ser um texto.")
    return valor.strip()


def _texto_opcional(entrada: dict[str, Any], campo: str) -> str | None:
    valor = entrada.get(campo)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErroFerramenta(f"O campo '{campo}' deve ser um texto ou null.")
    return valor.strip() or None


def _condicao_opcional(entrada: dict[str, Any]) -> Condicao | None:
    texto = _texto_opcional(entrada, "condicao")
    if texto is None:
        return None
    try:
        return Condicao(texto.lower())
    except ValueError:
        raise ErroFerramenta(
            f"Condição inválida: {texto!r}. Use 'novo', 'seminovo' ou null."
        ) from None


def _bool_opcional(entrada: dict[str, Any], campo: str) -> bool | None:
    valor = entrada.get(campo)
    if valor is None or isinstance(valor, bool):
        return valor
    raise ErroFerramenta(f"O campo '{campo}' deve ser verdadeiro, falso ou null.")


def _int_opcional(entrada: dict[str, Any], campo: str) -> int | None:
    valor = entrada.get(campo)
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ErroFerramenta(f"O campo '{campo}' deve ser um número inteiro.")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    raise ErroFerramenta(f"O campo '{campo}' deve ser um número inteiro.")


def _capacidade_opcional(entrada: dict[str, Any], campo: str = "capacidade") -> Capacidade | None:
    valor = entrada.get(campo)
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, str | int):
        raise ErroFerramenta(f"O campo '{campo}' deve ser um texto como '128GB'.")
    try:
        return Capacidade(valor)
    except ValueError:
        raise ErroFerramenta(
            f"Capacidade inválida: {valor!r}. Use algo como '128GB', '256GB' ou '1TB'."
        ) from None


_MAX_MODELOS_LISTADOS = 40


def _nome_exibicao(modelo: ModeloAparelho) -> str:
    """'iPhone 15' para Apple; 'Samsung Galaxy S23' para as demais marcas."""
    if modelo.marca == "Apple" or modelo.nome.lower().startswith(modelo.marca.lower()):
        return modelo.nome
    return f"{modelo.marca} {modelo.nome}"


async def _modelos_em_estoque(ctx: ContextoFerramentas) -> list[ModeloAparelho]:
    try:
        linhas = await ctx.config.obter_estoque(ctx.loja_id)
    except LojaNaoEncontrada:
        return []
    return list(dict.fromkeys(linha.modelo for linha in linhas if linha.quantidade > 0))


def _lista(modelos: list[ModeloAparelho]) -> list[str]:
    return [_nome_exibicao(m) for m in modelos[:_MAX_MODELOS_LISTADOS]]


async def _modelo_da_loja(texto: str, ctx: ContextoFerramentas) -> ModeloAparelho:
    """iPhone conhecido ou modelo que a loja tem no estoque; senao, erro com as opcoes."""
    em_estoque = await _modelos_em_estoque(ctx)
    resolucao = resolver_modelo(texto, em_estoque)
    if isinstance(resolucao, ModeloResolvido):
        return resolucao.modelo
    if isinstance(resolucao, ModeloAmbiguo):
        candidatos = _lista(list(resolucao.candidatos))
        raise ErroFerramenta(
            f"'{texto}' corresponde a mais de um modelo da loja: {', '.join(candidatos)}. "
            "Pergunte ao cliente qual deles.",
            modelos_no_estoque=candidatos,
        )
    nomes = _lista(em_estoque)
    extra = (
        " Modelos no estoque agora: " + ", ".join(nomes) + "."
        if nomes
        else " Consulte o estoque com consultar_estoque para ver as opções."
    )
    raise ErroFerramenta(
        f"Não encontrei '{texto}' entre os aparelhos da loja.{extra}",
        modelos_no_estoque=nomes,
    )


def _modelo_usado(texto: str) -> ModeloAparelho:
    primeira, _, resto = texto.partition(" ")
    marca = _MARCAS_OUTRAS.get(primeira.lower())
    try:
        if marca is not None and resto.strip():
            return ModeloAparelho.de(resto, marca)
        return ModeloAparelho.de(texto)
    except ValueError:
        raise ErroFerramenta("Informe o modelo do aparelho usado.") from None


# --- ficha ----------------------------------------------------------------------------------


def _situacao(ficha: Ficha) -> dict[str, Any]:
    faltas = pendencias(ficha)
    return {
        "faltam": [_TEXTOS_PENDENCIA[p][0] for p in faltas],
        "proxima_pergunta": _TEXTOS_PENDENCIA[faltas[0]][1] if faltas else None,
    }


async def _com_formas_na_pergunta(saida: _Saida, ctx: ContextoFerramentas) -> dict[str, Any]:
    """A `proxima_pergunta` de pagamento lista so as formas que a loja aceita.

    Os handlers montam a pergunta com o texto padrao (todas as formas); aqui, num ponto so, ela e
    trocada pela versao da config da loja (lida a cada chamada).
    """
    conteudo = saida.conteudo
    faltas = pendencias(saida.estado.ficha)
    if "proxima_pergunta" not in conteudo or not faltas or faltas[0] is not _P.PAGAMENTO_TIPO:
        return conteudo
    formas = (await ctx.config.obter_pagamento(ctx.loja_id)).formas
    return {**conteudo, "proxima_pergunta": pergunta_pagamento_ao_cliente(formas)}


def _bloqueio(ficha: Ficha) -> dict[str, Any]:
    faltas = pendencias(ficha)
    return {
        "bloqueado": True,
        "mensagem": (
            "Ainda não posso informar valores: a ficha de qualificação está incompleta. "
            "Pergunte ao cliente o que falta, uma coisa por vez."
        ),
        "pendencias": [_TEXTOS_PENDENCIA[p][0] for p in faltas],
        "proxima_pergunta": _TEXTOS_PENDENCIA[faltas[0]][1],
    }


def _opcao(item: ItemEstoque) -> dict[str, Any]:
    """Item para o LLM: sem preco, de proposito."""
    opcao: dict[str, Any] = {
        "sku": item.sku,
        "modelo": item.modelo.nome,
        "capacidade": str(item.capacidade),
        "cor": item.cor,
        "condicao": item.condicao.value,
    }
    if item.condicao is Condicao.SEMINOVO:
        # sem o dado, `null` explicito: o LLM nao pode inventar nem travar procurando
        opcao["bateria_pct"] = item.bateria_pct
        opcao["bateria_informada"] = item.bateria_pct is not None
    if item.desatualizado:
        opcao["dados_desatualizados"] = True
    return opcao


_INSTRUCAO_SEM_BATERIA = (
    "A bateria deste seminovo não está cadastrada: diga que o vendedor confirma a saúde da "
    "bateria na loja e siga o atendimento; não invente percentual."
)


def _sem_bateria(item: ItemEstoque) -> bool:
    return item.condicao is Condicao.SEMINOVO and item.bateria_pct is None


def _filtrar_bateria_minima(
    itens: list[ItemEstoque], minima: int
) -> tuple[list[ItemEstoque], str | None]:
    """Seminovos com bateria conhecida >= minima (novos ficam; sem dado nao entram no filtro).

    Sem nenhum que atenda devolve o de maior bateria conhecida; sem nenhuma bateria conhecida
    nao filtra (a resposta nunca fica vazia por falta do dado). Devolve tambem o aviso.
    """
    seminovos = [i for i in itens if i.condicao is Condicao.SEMINOVO]
    if not seminovos:
        return itens, None
    sem_dado = [i for i in seminovos if _sem_bateria(i)]
    conhecidos = [i for i in seminovos if i.bateria_pct is not None]
    avisos: list[str] = []
    if sem_dado:
        n = len(sem_dado)
        plural = "seminovos sem bateria cadastrada" if n > 1 else "seminovo sem bateria cadastrada"
        avisos.append(f"Há {n} {plural}; o vendedor confirma a saúde da bateria na loja.")
    if not conhecidos:
        return itens, " ".join(avisos)
    atendem = [i for i in conhecidos if (i.bateria_pct or 0) >= minima]
    if atendem:
        mantidos = atendem
    else:
        melhor = max(conhecidos, key=lambda i: i.bateria_pct or 0)
        mantidos = [melhor]
        avisos.insert(
            0,
            f"Não há seminovo com bateria de {minima}% ou mais; o melhor disponível tem "
            f"{melhor.bateria_pct}%. Ofereça uma alternativa (esse seminovo, o novo ou o vendedor "
            "confirmar na loja) e siga a conversa.",
        )
    escolhidos = {i.sku for i in mantidos}
    resultado = [i for i in itens if i.condicao is not Condicao.SEMINOVO or i.sku in escolhidos]
    return resultado, " ".join(avisos)


def _aplicar_interesse(
    ficha: Ficha,
    modelo: ModeloAparelho,
    capacidade: Capacidade | None,
    cor: str | None,
    condicao: Condicao | None = None,
) -> tuple[Ficha, bool]:
    """Atualiza o interesse; se algo mudou, a confirmacao do item cai. Devolve (ficha, mudou)."""
    atual = ficha.interesse
    mesmo_modelo = atual.modelo == modelo
    nova_cap = capacidade or (atual.capacidade if mesmo_modelo else None)
    nova_cor = cor or (atual.cor if mesmo_modelo else None)
    nova_cond = condicao or (atual.condicao if mesmo_modelo else None)
    mudou = (modelo, nova_cap, nova_cor, nova_cond) != (
        atual.modelo,
        atual.capacidade,
        atual.cor,
        atual.condicao,
    )
    campos: dict[str, Any] = {
        "modelo": modelo,
        "capacidade": nova_cap,
        "cor": nova_cor,
        "condicao": nova_cond,
    }
    if mudou:
        campos["sku_estoque_confirmado"] = None
    return ficha.com_interesse(**campos), mudou


# --- handlers -------------------------------------------------------------------------------


async def _registrar_interesse(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    modelo = await _modelo_da_loja(_texto_obrigatorio(entrada, "modelo"), ctx)
    capacidade = _capacidade_opcional(entrada)
    cor = _texto_opcional(entrada, "cor")
    condicao = _condicao_opcional(entrada)
    ficha, mudou = _aplicar_interesse(estado.ficha, modelo, capacidade, cor, condicao)
    novo = replace(estado, ficha=ficha, estoque_consultado=estado.estoque_consultado and not mudou)
    conteudo: dict[str, Any] = {"status": "ok", **_situacao(ficha)}
    if novo.ficha.interesse.sku_estoque_confirmado is None:
        conteudo["proximo_passo"] = "Chame consultar_estoque para ver as opções disponíveis."
        # a pergunta ao cliente vem do consultar_estoque: duas fontes = pergunta duplicada
        conteudo.pop("proxima_pergunta", None)
    return _Saida(conteudo, novo)


def _ordem_condicao(condicao: Condicao) -> int:
    return 0 if condicao is Condicao.NOVO else 1


def _resumo_capacidades(itens: list[ItemEstoque]) -> list[dict[str, Any]]:
    """Todas as capacidades em ordem crescente, com condicoes e unidades. Sem preco."""
    por_cap: dict[Capacidade, dict[Condicao, int]] = {}
    for i in itens:
        unidades = por_cap.setdefault(i.capacidade, {})
        unidades[i.condicao] = unidades.get(i.condicao, 0) + i.quantidade
    return [
        {
            "capacidade": str(cap),
            "condicoes": [
                {"condicao": c.value, "unidades": n}
                for c, n in sorted(por_cap[cap].items(), key=lambda par: _ordem_condicao(par[0]))
            ],
        }
        for cap in sorted(por_cap)
    ]


def _resumo_cores(itens: list[ItemEstoque]) -> list[dict[str, Any]]:
    """Cores (por condicao) na ordem do estoque, com as unidades. Sem preco nem sku."""
    por_cor: dict[tuple[str | None, Condicao], int] = {}
    for i in itens:
        chave = (i.cor, i.condicao)
        por_cor[chave] = por_cor.get(chave, 0) + i.quantidade
    return [
        {"cor": cor, "condicao": cond.value, "unidades": n} for (cor, cond), n in por_cor.items()
    ]


def _chave_cor(item: ItemEstoque) -> str:
    return (item.cor or "").strip().lower()


def _etapa_capacidades(itens: list[ItemEstoque], aviso: str = "") -> dict[str, Any]:
    return {
        "etapa": "capacidades",
        "capacidades": _resumo_capacidades(itens),
        "mensagem": (
            f"{aviso}Apresente TODAS as capacidades listadas, com a condição de cada uma "
            "(novo/seminovo), sem falar de cor ainda. Pergunte qual capacidade o "
            "cliente prefere; não escolha por ele. Depois chame consultar_estoque com a "
            "capacidade escolhida."
        ),
    }


def _etapa_cores(
    itens: list[ItemEstoque], capacidade: Capacidade, aviso: str = "", unica: bool = False
) -> dict[str, Any]:
    ja_dito = "Esta é a única capacidade do modelo; avise o cliente. " if unica else ""
    return {
        "etapa": "cores",
        "capacidade": str(capacidade),
        "cores": _resumo_cores(itens),
        "mensagem": (
            f"{aviso}{ja_dito}Apresente TODAS as cores disponíveis da capacidade {capacidade}, "
            "com a condição de cada uma. Pergunte qual cor o cliente prefere. Depois chame "
            "consultar_estoque de novo com a capacidade e a cor escolhidas."
        ),
    }


async def _consultar_estoque(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    """Estoque em etapas: capacidades, depois cores, depois as opcoes (sku) do que ele escolheu."""
    modelo = await _modelo_da_loja(_texto_obrigatorio(entrada, "modelo"), ctx)
    capacidade = _capacidade_opcional(entrada)
    cor = _texto_opcional(entrada, "cor")
    condicao = _condicao_opcional(entrada)
    bateria_minima = _int_opcional(entrada, "bateria_minima")
    if bateria_minima is not None and not 0 <= bateria_minima <= 100:
        raise ErroFerramenta(
            "A bateria mínima deve estar entre 0 e 100 (%). Confirme com o cliente."
        )
    atual = estado.ficha.interesse
    if atual.modelo == modelo:
        capacidade = capacidade or atual.capacidade
        cor = cor or atual.cor
        condicao = condicao or atual.condicao

    todos = await ctx.estoque.buscar(ctx.loja_id, modelo)
    aviso_condicao = ""
    if condicao is not None and not any(
        i.condicao is condicao and (capacidade is None or i.capacidade == capacidade)
        for i in filtrar(todos, modelo)
    ):
        # o cliente quer novo/seminovo e nao ha: avisa e mostra o que existe
        da_cap = f" {capacidade}" if capacidade else ""
        aviso_condicao = f"Não há {condicao.value}{da_cap} deste modelo. "
        condicao, capacidade, cor = None, None, None
    itens = [i for i in filtrar(todos, modelo, capacidade, cor) if condicao in (None, i.condicao)]
    aviso_bateria: str | None = None
    if bateria_minima is not None and itens:
        itens, aviso_bateria = _filtrar_bateria_minima(itens, bateria_minima)

    ficha, _ = _aplicar_interesse(estado.ficha, modelo, capacidade, cor, condicao)
    if aviso_condicao:
        ficha = ficha.com_interesse(
            capacidade=None, cor=None, condicao=None, sku_estoque_confirmado=None
        )
    confirmado = ficha.interesse.sku_estoque_confirmado
    if confirmado is not None and confirmado not in {i.sku for i in itens}:
        ficha = ficha.com_interesse(sku_estoque_confirmado=None)

    etapa: dict[str, Any]
    if not todos:
        etapa = {"mensagem": "Não há unidades disponíveis com esses critérios."}
    elif aviso_condicao:
        etapa = _etapa_capacidades(filtrar(todos, modelo), aviso_condicao)
    elif capacidade is not None and not any(i.capacidade == capacidade for i in todos):
        # a capacidade pedida nao existe: diz quais existem e nao grava a escolha
        ficha = ficha.com_interesse(capacidade=None, cor=None, sku_estoque_confirmado=None)
        etapa = _etapa_capacidades(todos, f"Não há {capacidade} disponível deste modelo. ")
    elif not itens:
        # a capacidade existe, mas nao nessa cor
        ficha = ficha.com_interesse(cor=None, sku_estoque_confirmado=None)
        da_capacidade = [
            i for i in todos if i.capacidade == capacidade and condicao in (None, i.condicao)
        ]
        assert capacidade is not None  # sem filtro nenhum, `itens` nunca fica vazio
        etapa = _etapa_cores(da_capacidade, capacidade, f"Não há a cor {cor} nessa capacidade. ")
    elif len(itens) == 1 or _novos_iguais(itens):
        i = itens[0]
        ficha = ficha.com_interesse(
            capacidade=i.capacidade, cor=i.cor, sku_estoque_confirmado=i.sku
        )
        etapa = {
            "sku_confirmado": i.sku,
            "mensagem": (
                "Só existe uma opção compatível e ela já foi confirmada; confirme com o cliente."
            ),
        }
    else:
        etapa, unica = _etapa_apos_filtros(itens, capacidade)
        if unica is not None:
            ficha = ficha.com_interesse(capacidade=unica)

    conteudo: dict[str, Any] = {
        "status": "ok",
        "total_opcoes": len(itens),
        "confirmado": ficha.interesse.sku_estoque_confirmado is not None,
        **etapa,
    }
    if "etapa" not in conteudo:
        conteudo["opcoes"] = [_opcao(i) for i in itens[:_MAX_OPCOES]]
    exibidos = itens[:_MAX_OPCOES] if "opcoes" in conteudo else []
    if "sku_confirmado" in conteudo:
        exibidos = [i for i in itens if i.sku == conteudo["sku_confirmado"]]
    if any(_sem_bateria(i) for i in exibidos):
        conteudo["instrucao_bateria"] = _INSTRUCAO_SEM_BATERIA
    if aviso_bateria:
        conteudo["aviso_bateria"] = aviso_bateria
    return _Saida(conteudo, replace(estado, ficha=ficha, estoque_consultado=True))


def _novos_iguais(itens: list[ItemEstoque]) -> bool:
    """Todos novos, mesma capacidade e cor: sao a mesma opcao para o cliente (sem bateria)."""
    return all(i.condicao is Condicao.NOVO for i in itens) and (
        len({(i.capacidade, _chave_cor(i)) for i in itens}) == 1
    )


def _etapa_apos_filtros(
    itens: list[ItemEstoque], capacidade: Capacidade | None
) -> tuple[dict[str, Any], Capacidade | None]:
    """Varios itens compativeis: capacidades se ainda houver mais de uma, depois cores.

    Devolve a etapa e, se o modelo so tem uma capacidade (nao ha o que escolher), qual e.
    """
    unica: Capacidade | None = None
    if capacidade is None:
        capacidades = {i.capacidade for i in itens}
        if len(capacidades) > 1:
            return _etapa_capacidades(itens), None
        capacidade = unica = next(iter(capacidades))
    if len({_chave_cor(i) for i in itens}) > 1:
        return _etapa_cores(itens, capacidade, unica=unica is not None), unica
    etapa = {
        "etapa": "opcoes",
        "opcoes": [_opcao(i) for i in itens[:_MAX_OPCOES]],
        "mensagem": (
            "Há mais de uma opção da mesma cor: mostre todas ao cliente (seminovo com a "
            "bateria), pergunte qual prefere e use confirmar_item com o sku escolhido."
        ),
    }
    return etapa, unica


async def _confirmar_item(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    sku = _texto_obrigatorio(entrada, "sku")
    item = await ctx.estoque.obter(ctx.loja_id, sku)
    if item is None:
        raise ErroFerramenta(
            f"O sku '{sku}' não existe no estoque. "
            "Use apenas um sku devolvido por consultar_estoque."
        )
    if not item.disponivel:
        raise ErroFerramenta(
            "Esse item está esgotado. Consulte o estoque e ofereça outra opção ao cliente."
        )
    ficha = estado.ficha.com_interesse(
        modelo=item.modelo,
        capacidade=item.capacidade,
        cor=item.cor,
        sku_estoque_confirmado=item.sku,
    )
    conteudo = {"status": "ok", "item": _opcao(item), **_situacao(ficha)}
    if _sem_bateria(item):
        conteudo["instrucao_bateria"] = _INSTRUCAO_SEM_BATERIA
    return _Saida(conteudo, replace(estado, ficha=ficha, estoque_consultado=True))


_FALA_DE_TROCA = re.compile(
    r"troc|usad|(pra|para) dar|dar (o|um|meu)|na entrada|celular antigo|aparelho antigo"
)


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def cliente_falou_de_troca(fala: str) -> bool:
    """O cliente mencionou troca/usado nesta mensagem (sem acento e sem caixa)."""
    return _FALA_DE_TROCA.search(_sem_acento(fala)) is not None


def _exigir_que_o_cliente_disse_sem_troca(
    estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> None:
    """ "Sem troca" so vale se o cliente disse: a IA ja perguntou ou ele falou de troca agora.

    O modelo as vezes presume que nao ha troca e pula a pergunta; aqui o codigo recusa.
    """
    if ctx.fala_do_cliente is None or estado.troca_perguntada:
        return
    if cliente_falou_de_troca(ctx.fala_do_cliente):
        return
    raise ErroFerramenta(
        "O cliente ainda não disse se tem aparelho para dar na troca: não presuma. Pergunte a "
        "ele com a proxima_pergunta e só registre depois que ele responder.",
        proxima_pergunta=_TEXTOS_PENDENCIA[_P.TEM_TROCA][1],
    )


async def _registrar_usado(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    tem_troca = entrada.get("tem_troca")
    if not isinstance(tem_troca, bool):
        raise ErroFerramenta("O campo 'tem_troca' é obrigatório (verdadeiro ou falso).")
    if not tem_troca:
        _exigir_que_o_cliente_disse_sem_troca(estado, ctx)
        ficha = replace(estado.ficha.com(tem_troca=False), usado=UsadoInformado())
        return _Saida({"status": "ok", **_situacao(ficha)}, replace(estado, ficha=ficha))

    campos: dict[str, Any] = {}
    texto_modelo = _texto_opcional(entrada, "modelo")
    if texto_modelo is not None:
        campos["modelo"] = _modelo_usado(texto_modelo)
    capacidade = _capacidade_opcional(entrada)
    if capacidade is not None:
        campos["capacidade"] = capacidade
    for nome in (
        "tela_danificada",
        "traseira_danificada",
        "carcaca_marcada",
        "camera_ok",
        "peca_trocada",
    ):
        valor = _bool_opcional(entrada, nome)
        if valor is not None:
            campos[nome] = valor
    bateria = _int_opcional(entrada, "bateria_pct")
    if bateria is not None:
        if not 0 <= bateria <= 100:
            raise ErroFerramenta(
                "A saúde da bateria deve estar entre 0 e 100 (%). Confirme com o cliente."
            )
        campos["bateria_pct"] = bateria
    defeitos = entrada.get("outros_defeitos")
    if defeitos is not None:
        if not isinstance(defeitos, list) or not all(isinstance(d, str) for d in defeitos):
            raise ErroFerramenta("O campo 'outros_defeitos' deve ser uma lista de textos.")
        campos["outros_defeitos"] = tuple(d.strip() for d in defeitos if d.strip())

    ficha = estado.ficha.com(tem_troca=True).com_usado(**campos)
    motivo = await _fora_da_tabela(ficha, ctx)
    if motivo is not None:
        return _troca_nao_aceita(estado, ficha, motivo)
    ficha = ficha.com_usado(avaliacao_na_loja=False)
    return _Saida({"status": "ok", **_situacao(ficha)}, replace(estado, ficha=ficha))


_MOTIVOS_RECUSA: dict[MotivoLoja, str] = {
    MotivoLoja.MODELO_FORA_DA_TABELA: "modelo fora da tabela de troca da loja",
    MotivoLoja.OUTRA_MARCA: "a loja não tem essa marca na tabela de troca",
    MotivoLoja.CAPACIDADE_ABAIXO_DA_TABELA: "capacidade fora da tabela de troca da loja",
}


async def _fora_da_tabela(ficha: Ficha, ctx: ContextoFerramentas) -> MotivoLoja | None:
    """O codigo confere na tabela da loja (lida agora) se ela aceita esse usado na troca."""
    u = ficha.usado
    if u.modelo is None:
        return None
    tabela = await ctx.config.obter_troca(ctx.loja_id)
    return motivo_fora_da_tabela(tabela, u.modelo, u.capacidade)


def _troca_nao_aceita(estado: EstadoAtendimento, ficha: Ficha, motivo: MotivoLoja) -> _Saida:
    """Aparelho fora da tabela de troca: a loja nao aceita, e a ficha segue SEM troca."""
    u = ficha.usado
    assert u.modelo is not None
    nome = u.modelo.nome if u.modelo.marca == "Apple" else f"{u.modelo.marca} {u.modelo.nome}"
    aparelho = f"{nome} {u.capacidade}" if u.capacidade is not None else nome
    sem_troca = replace(ficha.com(tem_troca=False), usado=UsadoInformado())
    conteudo: dict[str, Any] = {
        "status": "ok",
        "troca": {
            "status": "nao_aceito",
            "aparelho": aparelho,
            "motivo": _MOTIVOS_RECUSA[motivo],
            "mensagem": (
                f"A loja não aceita o {aparelho} na troca. Avise o cliente, em uma frase, que "
                "a loja não aceita esse aparelho na troca e siga para a próxima pergunta, sem "
                "perguntar o estado dele. O atendimento continua sem troca; se o cliente tiver "
                "outro aparelho para dar, registre com registrar_usado."
            ),
        },
        **_situacao(sem_troca),
    }
    return _Saida(conteudo, replace(estado, ficha=sem_troca))


async def _registrar_leitura_imagem(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    """O LLM so le a imagem; `decidir_leitura` (codigo) diz se grava ou manda confirmar."""
    texto_tipo = _texto_obrigatorio(entrada, "tipo")
    try:
        tipo = TipoImagem(texto_tipo.lower())
    except ValueError:
        validos = ", ".join(t.value for t in TipoImagem)
        raise ErroFerramenta(
            f"Tipo de imagem inválido: {texto_tipo!r}. Use um de: {validos}."
        ) from None
    bateria = _int_opcional(entrada, "bateria_pct")
    if bateria is not None and not 0 <= bateria <= 100:
        raise ErroFerramenta(
            "A saúde da bateria deve estar entre 0 e 100 (%). Se não estiver legível, "
            "use null e peça outro print."
        )
    confianca = entrada.get("confianca")
    if (
        isinstance(confianca, bool)
        or not isinstance(confianca, int | float)
        or not 0 <= confianca <= 1
    ):
        raise ErroFerramenta("O campo 'confianca' deve ser um número entre 0 e 1.")
    texto_modelo = _texto_opcional(entrada, "modelo_provavel")
    leitura = LeituraImagem(
        tipo=tipo,
        bateria_pct=bateria,
        tela_danificada=_bool_opcional(entrada, "tela_danificada"),
        traseira_danificada=_bool_opcional(entrada, "traseira_danificada"),
        carcaca_marcada=_bool_opcional(entrada, "carcaca_marcada"),
        modelo=_modelo_usado(texto_modelo) if texto_modelo is not None else None,
        confianca=float(confianca),
    )
    decisao = decidir_leitura(estado.ficha, leitura)
    if decisao.gravado:
        conteudo: dict[str, Any] = {
            "status": "ok",
            "registrado": list(decisao.campos),
            **_situacao(decisao.ficha),
        }
        return _Saida(conteudo, replace(estado, ficha=decisao.ficha))
    if decisao.pergunta is not None:
        return _Saida(
            {
                "status": "confirmar",
                "pergunta": decisao.pergunta,
                "mensagem": (
                    "Nada foi gravado na ficha. Faça essa pergunta ao cliente e, só se ele "
                    "confirmar, registre com registrar_usado."
                ),
            },
            estado,
        )
    return _Saida(
        {
            "status": "nada_registrado",
            "mensagem": (
                "Não deu para aproveitar a imagem. Peça com educação uma foto ou print mais "
                "nítido (para a bateria: Ajustes > Bateria > Saúde da Bateria) ou pergunte "
                "a informação por texto."
            ),
        },
        estado,
    )


def _normalizar_pagamento(
    tipo: TipoPagamento | None,
    parcelas: int | None,
    bandeira: Bandeira | None,
    entrada: Dinheiro | None,
) -> dict[str, Any]:
    """Descarta campos que nao se aplicam ao tipo (ex.: parcelas no Pix)."""
    if tipo is TipoPagamento.PIX:
        parcelas = bandeira = entrada = None
    elif tipo is TipoPagamento.DEBITO:
        parcelas = entrada = None
    elif tipo is TipoPagamento.CREDITO:
        entrada = None
    return {"tipo": tipo, "parcelas": parcelas, "bandeira": bandeira, "entrada": entrada}


async def _exigir_forma_aceita(tipo: TipoPagamento, ctx: ContextoFerramentas) -> None:
    """O dominio decide: forma desligada pela loja e recusada, e o erro lista as aceitas."""
    formas = (await ctx.config.obter_pagamento(ctx.loja_id)).formas
    if formas.aceita(tipo):
        return
    aceitas = rotulos_aceitos(formas)
    if aceitas:
        oferta = f"Formas aceitas: {', '.join(aceitas)}. Peça ao cliente para escolher uma delas."
    else:
        oferta = "A loja não tem forma de pagamento configurada. Chame o vendedor."
    raise ErroFerramenta(
        f"A loja não aceita {ROTULOS_INSTRUCAO[tipo]} como forma de pagamento. {oferta}",
        formas_aceitas=[t.value for t in formas.tipos()],
    )


async def _registrar_compra(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    ficha = estado.ficha

    data: date | None = None
    texto_data = _texto_opcional(entrada, "data_prevista")
    if texto_data is not None:
        try:
            data = date.fromisoformat(texto_data)
        except ValueError:
            raise ErroFerramenta(
                f"Data inválida: {texto_data!r}. "
                "Use o formato AAAA-MM-DD (converta o que o cliente disse)."
            ) from None
        if data < ctx.hoje:
            raise ErroFerramenta(
                "Essa data já passou. Pergunte ao cliente quando ele pretende comprar."
            )

    tipo: TipoPagamento | None = None
    texto_tipo = _texto_opcional(entrada, "tipo_pagamento")
    if texto_tipo is not None:
        try:
            tipo = TipoPagamento(texto_tipo.lower())
        except ValueError:
            validos = ", ".join(t.value for t in TipoPagamento)
            raise ErroFerramenta(
                f"Tipo de pagamento inválido: {texto_tipo!r}. Use um de: {validos}."
            ) from None

    parcelas = _int_opcional(entrada, "parcelas")
    if parcelas is not None and parcelas < 1:
        raise ErroFerramenta("O número de parcelas deve ser pelo menos 1.")

    bandeira: Bandeira | None = None
    texto_bandeira = _texto_opcional(entrada, "bandeira")
    if texto_bandeira is not None:
        try:
            bandeira = Bandeira.parse(texto_bandeira)
        except ValueError:
            validas = ", ".join(b.value for b in Bandeira)
            raise ErroFerramenta(
                f"Bandeira desconhecida: {texto_bandeira!r}. Bandeiras aceitas: {validas}."
            ) from None

    valor_entrada: Dinheiro | None = None
    bruto = entrada.get("entrada")
    if bruto is not None:
        if isinstance(bruto, bool) or not isinstance(bruto, str | int):
            raise ErroFerramenta("O campo 'entrada' deve ser um valor em reais (texto).")
        try:
            valor_entrada = Dinheiro.de(bruto)
        except ValueError:
            raise ErroFerramenta(f"Valor de entrada inválido: {bruto!r}.") from None
        if valor_entrada.negativo:
            raise ErroFerramenta("A entrada não pode ser negativa.")

    if tipo is not None:
        await _exigir_forma_aceita(tipo, ctx)

    atual = ficha.pagamento
    tipo_efetivo = tipo or atual.tipo
    if parcelas is not None or tipo_efetivo is TipoPagamento.ENTRADA_MAIS_CREDITO:
        preco = await ctx.config.obter_preco(ctx.loja_id)
        if preco is None:
            raise ErroFerramenta("A loja ainda não definiu as regras de preço. Chame o vendedor.")
        if parcelas is not None and parcelas > preco.regras.max_parcelas:
            raise ErroFerramenta(
                f"A loja parcela em no máximo {preco.regras.max_parcelas}x. "
                "Peça ao cliente outra quantidade."
            )
        if (
            tipo_efetivo is TipoPagamento.ENTRADA_MAIS_CREDITO
            and not preco.regras.aceita_entrada_mais_cartao
        ):
            raise ErroFerramenta("A loja não aceita entrada mais parcelas no cartão.")

    if data is not None:
        ficha = ficha.com(data_prevista_compra=data)
    ficha = ficha.com_pagamento(
        **_normalizar_pagamento(
            tipo_efetivo,
            parcelas if parcelas is not None else atual.parcelas,
            bandeira or atual.bandeira,
            valor_entrada if valor_entrada is not None else atual.entrada,
        )
    )
    return _Saida({"status": "ok", **_situacao(ficha)}, replace(estado, ficha=ficha))


_AGUARDAR_CONFIRMACAO = (
    "Aguarde o cliente confirmar a ficha: o sistema envia a mensagem_ao_cliente como a resposta "
    "deste turno, então não reescreva nem cite outros valores. Se ele pedir desconto, use "
    "liberar_desconto; se mudar algo (parcelas, forma de pagamento, aparelho), registre e chame "
    "calcular_proposta de novo. 'Quanto fica em Nx?' é só simulação: registre as parcelas e "
    "calcule, nunca feche. Só depois de o cliente dizer 'sim' numa mensagem seguinte use "
    "confirmar_pedido."
)
_TEXTO_PEDIDO_MAX = 140
_APOS_CONFIRMAR = (
    "Pedido confirmado pelo cliente. Chame fechar_acordo agora, depois chamar_vendedor com "
    f"motivo '{MOTIVO_ACORDO_FECHADO}'."
)


def _com_confirmacao(
    estado: EstadoAtendimento, proposta: dict[str, Any], ctx: ContextoFerramentas
) -> EstadoAtendimento:
    """A ficha mostrada agora vira a `confirmacao` (com a rodada); o aceite antigo cai."""
    return replace(
        estado,
        proposta_apresentada=True,
        ultima_proposta=proposta,
        confirmacao={"proposta": proposta, "rodada": ctx.rodada},
        pedido_confirmado=False,
    )


async def _politica(ctx: ContextoFerramentas) -> PoliticaDesconto:
    preco = await ctx.config.obter_preco(ctx.loja_id)
    if preco is None:
        raise ErroFerramenta("A loja ainda não definiu as regras de preço. Chame o vendedor.")
    return preco.politica


async def _calcular_proposta(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    if pendencias(estado.ficha):
        return _Saida(_bloqueio(estado.ficha), estado)
    base = estado
    conseguido: str | None = None
    if estado.desconto_pedido_antes:
        # o cliente pediu desconto antes da ficha: o primeiro degrau ja vem nela
        politica = await _politica(ctx)
        decisao = decidir_pedido_desconto(politica, estado.desconto, PedidoCliente.MAIS_DESCONTO)
        base = replace(estado, desconto_pedido_antes=False)
        if isinstance(decisao, DescontoLiberado):
            base = replace(base, desconto=decisao.estado)
            conseguido = str(decisao.total - estado.desconto.liberado)
    proposta = await montar_proposta(ctx, base)
    mesma = (
        conseguido is None
        and base.confirmacao is not None
        and base.confirmacao.get("proposta") == proposta
    )
    if mesma:
        # nada mudou: a ficha vale com a rodada em que foi mostrada (o aceite nao e refeito)
        novo = replace(base, proposta_apresentada=True, ultima_proposta=proposta)
    else:
        novo = _com_confirmacao(base, proposta, ctx)
    conteudo = {
        **proposta,
        "mensagem_ao_cliente": ficha_confirmacao(novo, proposta, desconto_conseguido=conseguido),
        "mensagem": "Ficha de confirmação pronta; ela é a resposta deste turno.",
        "proximo_passo": _AGUARDAR_CONFIRMACAO,
    }
    return _Saida(conteudo, novo)


def _pedido_cliente(entrada: dict[str, Any]) -> PedidoCliente:
    valor = entrada.get("pedido")
    if valor is None:
        return PedidoCliente.MAIS_DESCONTO
    try:
        return PedidoCliente(valor)
    except ValueError:
        validos = ", ".join(p.value for p in PedidoCliente)
        raise ErroFerramenta(f"Pedido inválido: {valor!r}. Use um de: {validos}.") from None


def _passar_negociacao(
    estado: EstadoAtendimento,
    passagem: PassarAoVendedor,
    pedido: PedidoCliente,
    texto: str,
    teto: str,
) -> _Saida:
    negociacao = {
        "motivo": passagem.motivo.value,
        "pedido": pedido.value,
        "texto": texto[:_TEXTO_PEDIDO_MAX],
        "liberado": str(passagem.liberado),
        "teto": teto,
    }
    novo = replace(
        estado, handoff_solicitado=True, motivo_handoff=MOTIVO_NEGOCIACAO, negociacao=negociacao
    )
    conteudo = {
        "status": "ok",
        "passou_ao_vendedor": True,
        "motivo": passagem.motivo.value,
        "mensagem": (
            "Isso é com o vendedor: avise o cliente, em uma frase, que um vendedor da loja vai "
            "continuar a negociação com ele em instantes. Não prometa desconto nem brinde."
        ),
    }
    return _Saida(conteudo, novo)


async def _liberar_desconto(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    motivo = _texto_obrigatorio(entrada, "motivo")
    pedido = _pedido_cliente(entrada)
    if estado.handoff_solicitado:
        return _Saida(
            {"status": "ok", "mensagem": "O vendedor já foi acionado e vai continuar a conversa."},
            estado,
        )
    politica = await _politica(ctx)
    ficha_no_ar = estado.confirmacao is not None and not pendencias(estado.ficha)
    if not ficha_no_ar and pedido is PedidoCliente.MAIS_DESCONTO:
        # antes da ficha nao se negocia: anota, e a primeira ficha ja traz o primeiro degrau
        return _Saida(
            {
                "status": "ok",
                "negociacao_adiada": True,
                "mensagem": (
                    "Diga ao cliente que o desconto é visto quando a ficha do pedido estiver "
                    "pronta e siga a qualificação com a próxima pergunta. Não cite valor."
                ),
            },
            replace(estado, desconto_pedido_antes=True),
        )
    decisao = decidir_pedido_desconto(politica, estado.desconto, pedido)
    if isinstance(decisao, PassarAoVendedor):
        return _passar_negociacao(estado, decisao, pedido, motivo, str(politica.teto))
    novo = replace(estado, desconto=decisao.estado)
    proposta = await montar_proposta(ctx, novo)  # se falhar, nada foi liberado
    novo = _com_confirmacao(novo, proposta, ctx)
    ganho = str(decisao.total - estado.desconto.liberado)
    conteudo = {
        **proposta,
        "status": "ok",
        "desconto_liberado_agora": ganho,
        "mensagem_ao_cliente": ficha_confirmacao(novo, proposta, desconto_conseguido=ganho),
        "mensagem": "Desconto liberado e ficha refeita; ela é a resposta deste turno.",
        "proximo_passo": _AGUARDAR_CONFIRMACAO,
    }
    return _Saida(conteudo, novo)


async def _confirmar_pedido(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    """O cliente aceitou a ficha? So vale com a ficha mostrada numa rodada ANTERIOR, a proposta
    atual igual a confirmada e uma fala de aceite (que nao seja pergunta nem pedido)."""
    conf = estado.confirmacao
    if conf is None or pendencias(estado.ficha):
        raise ErroFerramenta(
            "A ficha de confirmação ainda não foi mostrada ao cliente. Chame calcular_proposta, "
            "deixe o sistema enviar a ficha e pergunte se está tudo certo; só confirme depois "
            "do 'sim' dele, numa mensagem seguinte."
        )
    if estado.pedido_confirmado:
        return _Saida(
            {"status": "ok", "pedido_confirmado": True, "mensagem": _APOS_CONFIRMAR}, estado
        )
    if conf.get("rodada") == ctx.rodada:
        raise ErroFerramenta(
            "O cliente ainda não confirmou: a ficha foi mostrada agora, nesta mesma rodada. "
            "Pergunte se a ficha está correta e aguarde a resposta dele."
        )
    if await montar_proposta(ctx, estado) != conf.get("proposta"):
        raise ErroFerramenta(
            "A ficha mudou desde a que o cliente viu. Chame calcular_proposta, deixe o sistema "
            "enviar a ficha nova e pergunte se está tudo certo."
        )
    if ctx.fala_do_cliente is not None and not parece_aceite(ctx.fala_do_cliente):
        raise ErroFerramenta(
            "O cliente ainda não confirmou: a fala dele não é um aceite (é pergunta, pedido de "
            "desconto ou mudança). Responda o que ele disse e pergunte se a ficha está correta."
        )
    return _Saida(
        {"status": "ok", "pedido_confirmado": True, "mensagem": _APOS_CONFIRMAR},
        replace(estado, pedido_confirmado=True),
    )


async def _fechar_acordo(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    """O codigo decide se da para fechar: proposta apresentada e vigente, ficha completa, forma
    aceita pela loja e pedido confirmado pelo cliente. Grava o acordo e devolve endereco, horarios
    e (no Pix) a chave da loja."""
    if not estado.proposta_apresentada or estado.ultima_proposta is None:
        raise ErroFerramenta(
            "Ainda não há proposta apresentada ao cliente. Chame calcular_proposta, deixe o "
            "sistema enviar a ficha e só feche o acordo depois que ele confirmar."
        )
    faltas = pendencias(estado.ficha)
    if faltas:
        raise ErroFerramenta(
            "A ficha está incompleta, não dá para fechar o acordo. Falta: "
            + ", ".join(_TEXTOS_PENDENCIA[p][0] for p in faltas)
            + ". Pergunte ao cliente, uma coisa por vez.",
            faltam=[_TEXTOS_PENDENCIA[p][0] for p in faltas],
            proxima_pergunta=_TEXTOS_PENDENCIA[faltas[0]][1],
        )
    tipo = estado.ficha.pagamento.tipo
    assert tipo is not None  # sem pendencias, a forma de pagamento esta na ficha
    await _exigir_forma_aceita(tipo, ctx)
    if await montar_proposta(ctx, estado) != estado.ultima_proposta:
        raise ErroFerramenta(
            "A proposta mudou desde a última que o cliente viu (a ficha ou o estoque mudou). "
            "Chame calcular_proposta, deixe o sistema enviar a ficha nova e só feche o acordo "
            "depois que ele confirmar."
        )
    if not estado.pedido_confirmado:
        raise ErroFerramenta(
            "O cliente ainda não confirmou a ficha do pedido. Mostre a ficha (calcular_proposta), "
            "pergunte se está tudo certo e, só depois do 'sim' dele numa mensagem seguinte, "
            "chame confirmar_pedido e então fechar_acordo."
        )
    acordo = montar_acordo(
        estado,
        estado.ultima_proposta,
        perfil=await ctx.config.obter_perfil(ctx.loja_id),
        pagamento=await ctx.config.obter_pagamento(ctx.loja_id),
        fechado_em=ctx.agora(),
    )
    if estado.acordo is not None and mesmo_acordo(estado.acordo, acordo):
        acordo["fechado_em"] = estado.acordo["fechado_em"]  # idempotente: nada mudou
    return _Saida(conteudo_para_ia(acordo, tipo), replace(estado, acordo=acordo))


async def _chamar_vendedor(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    motivo = _texto_obrigatorio(entrada, "motivo")
    if estado.handoff_solicitado:
        return _Saida(
            {"status": "ok", "mensagem": "O vendedor já foi acionado e vai continuar a conversa."},
            estado,
        )
    if motivo.strip().lower() == MOTIVO_ACORDO_FECHADO and estado.acordo is None:
        raise ErroFerramenta(
            "Ainda não há acordo fechado: o motivo 'acordo_fechado' só vale depois de "
            "fechar_acordo, que exige o 'sim' do cliente à ficha do pedido. Siga o fluxo: "
            "calcular_proposta, ficha, confirmação do cliente, confirmar_pedido e fechar_acordo."
        )
    novo = replace(estado, handoff_solicitado=True, motivo_handoff=motivo)
    return _Saida(
        {
            "status": "ok",
            "mensagem": (
                "Vendedor acionado. Avise o cliente que um vendedor da loja vai "
                "continuar o atendimento em instantes."
            ),
        },
        novo,
    )


# --- definicoes (esquemas strict: todas as propriedades em required, opcionais com null) ----
# A API soma no maximo 16 campos com uniao (null/anyOf) entre as ferramentas strict: as que so
# recebem texto (ja validado no handler) ficam sem strict para caber no limite.


def _objeto(propriedades: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": propriedades,
        "required": list(propriedades),
        "additionalProperties": False,
    }


def _txt(descricao: str, nulo: bool = True) -> dict[str, Any]:
    return {"type": ["string", "null"] if nulo else "string", "description": descricao}


def _bool(descricao: str, nulo: bool = True) -> dict[str, Any]:
    return {"type": ["boolean", "null"] if nulo else "boolean", "description": descricao}


_TIPOS_PAGAMENTO = [t.value for t in TipoPagamento]


def _condicao_esquema() -> dict[str, Any]:
    # Enum anulavel vai em anyOf: a API recusa `enum` com `type` em lista.
    return {
        "anyOf": [{"type": "string", "enum": [c.value for c in Condicao]}, {"type": "null"}],
        "description": "Condição que o cliente quer: novo ou seminovo; null se ele não disse.",
    }


_DEFINICOES: tuple[DefinicaoFerramenta, ...] = (
    DefinicaoFerramenta(
        nome="registrar_interesse",
        descricao=(
            "Registra na ficha o aparelho que o cliente quer comprar. Chame assim que o cliente "
            "disser o modelo (capacidade e cor quando souber; use null no que ainda não foi dito). "
            "Aceita iPhones e os modelos de outras marcas que a loja tem no estoque; se não "
            "reconhecer ou houver mais de um modelo possível, devolve erro com as opções. "
            "Depois chame consultar_estoque."
        ),
        esquema_json=_objeto(
            {
                "modelo": _txt(
                    "Marca e modelo desejados, ex.: 'iPhone 16 Pro' ou 'Galaxy S24'.", nulo=False
                ),
                "capacidade": _txt("Capacidade, ex.: '128GB'; null se não informada."),
                "cor": _txt("Cor desejada; null se não informada."),
                "condicao": _condicao_esquema(),
            }
        ),
        estrita=False,
    ),
    DefinicaoFerramenta(
        nome="consultar_estoque",
        descricao=(
            "Consulta o estoque do modelo em etapas. Sem capacidade: devolve TODAS as capacidades "
            "(ordem crescente, com condição e unidades); apresente todas e pergunte qual ele "
            "prefere. Com capacidade e sem cor: devolve as cores dessa capacidade; pergunte a cor. "
            "Com capacidade e cor: devolve os itens (sku, condição e bateria do seminovo) para ele "
            "escolher com confirmar_item. Só existindo um item compatível ele já é confirmado. "
            "Se o cliente disse que quer novo ou seminovo, passe condicao: a consulta traz só "
            "essa condição (e lembra dela nas próximas). Se ele pediu bateria mínima em um "
            "seminovo, passe bateria_minima: a consulta filtra pelos que têm bateria cadastrada "
            "e avisa dos sem dado ou da falta de um que atenda (siga o aviso e a "
            "instrucao_bateria). "
            "NUNCA devolve valores: para falar de dinheiro use calcular_proposta. Nunca ofereça "
            "só uma opção quando a ferramenta devolveu outras. Se o estoque estiver fora do ar, "
            "avise o cliente e tente de novo depois."
        ),
        esquema_json=_objeto(
            {
                "modelo": _txt("Marca e modelo, ex.: 'iPhone 15' ou 'Galaxy A07'.", nulo=False),
                "capacidade": _txt(
                    "Capacidade que o cliente escolheu, ex.: '256GB'; null para listar todas as "
                    "capacidades do modelo."
                ),
                "cor": _txt("Cor que o cliente escolheu; null para listar as cores."),
                "condicao": _condicao_esquema(),
                "bateria_minima": {
                    "type": ["integer", "null"],
                    "description": (
                        "Saúde mínima da bateria em % (0 a 100) que o cliente pediu para "
                        "seminovo; null se ele não pediu."
                    ),
                },
            }
        ),
        estrita=False,
    ),
    DefinicaoFerramenta(
        nome="confirmar_item",
        descricao=(
            "Confirma na ficha o item que o cliente escolheu entre as opções devolvidas por "
            "consultar_estoque. Só aceita um sku que exista no estoque e esteja disponível; "
            "nunca invente um sku."
        ),
        esquema_json=_objeto({"sku": _txt("sku exatamente como veio do estoque.", nulo=False)}),
    ),
    DefinicaoFerramenta(
        nome="registrar_usado",
        descricao=(
            "Registra na ficha o aparelho usado que o cliente dará na troca, ou que ele não tem "
            "troca (tem_troca=false). Só use tem_troca=false quando o cliente disser que não tem "
            "aparelho para a troca; nunca presuma. Pode ser chamada várias vezes, conforme o "
            "cliente responde: "
            "preencha só o que foi dito e use null no resto (null não apaga o que já foi "
            "registrado). bateria_pct é a saúde da bateria de 0 a 100. camera_ok, "
            "outros_defeitos e peca_trocada não são perguntados: preencha só se o cliente contar "
            "por conta própria (null no resto)."
        ),
        esquema_json=_objeto(
            {
                "tem_troca": _bool(
                    "true se vai dar um aparelho na troca; false se não.", nulo=False
                ),
                "modelo": _txt("Modelo do aparelho usado; null se não informado."),
                "capacidade": _txt("Capacidade do usado, ex.: '128GB'; null se não informada."),
                "tela_danificada": _bool("Tela/vidro frontal trincado ou danificado?"),
                "traseira_danificada": _bool("Vidro traseiro trincado ou danificado?"),
                "carcaca_marcada": _bool("Carcaça com marcas ou amassados?"),
                "bateria_pct": {
                    "type": ["integer", "null"],
                    "description": "Saúde da bateria em %, de 0 a 100; null se não informada.",
                },
                "camera_ok": _bool("Só se o cliente contar: a câmera funciona?"),
                "outros_defeitos": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Só se o cliente contar: outros defeitos (Face ID, alto-falante...); "
                        "null se ele não falou nada."
                    ),
                },
                "peca_trocada": _bool("Só se o cliente contar: alguma peça já foi trocada?"),
            }
        ),
    ),
    DefinicaoFerramenta(
        nome="registrar_compra",
        descricao=(
            "Registra na ficha a data prevista da compra e a forma de pagamento. Pode ser chamada "
            "aos poucos; use null no que ainda não foi dito. data_prevista em AAAA-MM-DD (não pode "
            "ser no passado). tipo_pagamento: pix, debito, credito ou entrada_mais_credito. "
            "Parcelas respeitam o máximo da loja; devolve erro amigável se algo for inválido."
        ),
        esquema_json=_objeto(
            {
                "data_prevista": _txt(
                    "Quando pretende comprar, AAAA-MM-DD; null se não informada."
                ),
                # Enum anulavel vai em anyOf: a API recusa `enum` com `type` em lista.
                "tipo_pagamento": {
                    "anyOf": [{"type": "string", "enum": _TIPOS_PAGAMENTO}, {"type": "null"}],
                    "description": "Forma de pagamento; null se não informada.",
                },
                "parcelas": {
                    "type": ["integer", "null"],
                    "description": "Número de parcelas no cartão; null se não se aplica.",
                },
                "bandeira": _txt(
                    "Bandeira do cartão (Mastercard, Visa, Elo...); null se não dita."
                ),
                "entrada": _txt("Valor da entrada em reais, ex.: '1000'; null se não houver."),
            }
        ),
    ),
    DefinicaoFerramenta(
        nome="registrar_leitura_imagem",
        descricao=(
            "Use quando o cliente mandar uma imagem: registra o que VOCÊ enxergou nela. tipo: "
            "print_bateria (tela de Ajustes > Bateria > Saúde da Bateria), foto_aparelho ou "
            "outro. Preencha só o que está visível e legível; use null no resto (um vidro "
            "traseiro que não aparece na foto é null, nunca false). modelo_provavel só se "
            "der para identificar. confianca de 0 a 1 é o quanto você tem certeza da leitura "
            "(imagem borrada, cortada ou número duvidoso = baixa). O sistema decide: com "
            "confiança alta grava na ficha do aparelho usado; com baixa devolve "
            "status=confirmar e a pergunta que você deve fazer ao cliente antes de gravar. "
            "Nunca informe valores ao cliente a partir da imagem."
        ),
        esquema_json=_objeto(
            {
                "tipo": {
                    "type": "string",
                    "enum": [t.value for t in TipoImagem],
                    "description": "O que a imagem mostra.",
                },
                "bateria_pct": {
                    "type": ["integer", "null"],
                    "description": "Saúde da bateria em %, lida do print; null se não visível.",
                },
                "tela_danificada": _bool("Tela trincada ou danificada? null se não visível."),
                "traseira_danificada": _bool(
                    "Vidro traseiro trincado ou danificado? null se não visível."
                ),
                "carcaca_marcada": _bool("Carcaça com marcas ou amassados? null se não visível."),
                "modelo_provavel": _txt("Modelo provável do aparelho; null se incerto."),
                "confianca": {
                    "type": "number",
                    "description": "Certeza da leitura, de 0 (nenhuma) a 1 (total).",
                },
            }
        ),
        # Campos anulaveis: sem strict para caber no limite de unioes da API (o handler valida).
        estrita=False,
    ),
    DefinicaoFerramenta(
        nome="calcular_proposta",
        descricao=(
            "ÚNICA fonte de valores (preço, troca, parcelas). Chame quando o cliente pedir preço "
            "ou valores. Se a ficha estiver incompleta devolve bloqueado=true com as pendências e "
            "a proxima_pergunta: faça essa pergunta e NÃO cite nenhum valor. Com a ficha completa "
            "devolve a proposta pronta (formatada em reais) e a frase obrigatória, que deve ser "
            "dita ao cliente. Repasse os valores exatamente como vieram; nunca calcule nem "
            "arredonde por conta própria."
        ),
        esquema_json=_objeto({}),
    ),
    DefinicaoFerramenta(
        nome="liberar_desconto",
        descricao=(
            "Trata o pedido de desconto ou brinde do cliente. Use SOMENTE quando ele pedir. "
            "Antes da ficha do pedido só anota (diga que vê o desconto quando a ficha estiver "
            "pronta). Depois da ficha libera o próximo degrau e devolve a ficha refeita "
            "(mensagem_ao_cliente, enviada pelo sistema); acima do teto, ou para brinde, o "
            "sistema passa a negociação ao vendedor e você só avisa o cliente. Nunca prometa "
            "desconto por conta própria nem invente valores."
        ),
        esquema_json=_objeto(
            {
                "pedido": {
                    "type": "string",
                    "enum": [p.value for p in PedidoCliente],
                    "description": (
                        "mais_desconto: o cliente quer pagar menos; brinde_ou_beneficio: ele "
                        "quer um brinde, acessório ou outro benefício (isso vai ao vendedor)."
                    ),
                },
                "motivo": _txt("O que o cliente pediu, em poucas palavras.", nulo=False),
            }
        ),
    ),
    DefinicaoFerramenta(
        nome="confirmar_pedido",
        descricao=(
            "Registra que o cliente CONFIRMOU a ficha do pedido (calcular_proposta devolve a "
            "ficha e o sistema a envia). Só funciona numa rodada posterior à da ficha, com o "
            "'sim' do cliente (sim, pode fechar, confirmo...) e a ficha inalterada; pergunta, "
            "pedido de desconto ou mudança não contam. Depois chame fechar_acordo. Se recusar, "
            "siga a instrução do erro."
        ),
        esquema_json=_objeto({}),
    ),
    DefinicaoFerramenta(
        nome="fechar_acordo",
        descricao=(
            "Fecha o acordo com o cliente. Chame só depois de confirmar_pedido (o cliente disse "
            "'sim' à ficha numa mensagem seguinte). O sistema só fecha com a ficha confirmada, "
            "proposta apresentada, ficha completa e forma aceita pela loja (senão devolve o que "
            "falta). Devolve a "
            "mensagem_ao_cliente pronta (valor final, endereço, horários e, no Pix, a chave e o "
            "favorecido), que o sistema envia como a resposta do turno; depois chame "
            f"chamar_vendedor com motivo '{MOTIVO_ACORDO_FECHADO}'. Nunca invente endereço, "
            "horário ou chave Pix. Se o "
            "cliente mudar algo depois, refaça a proposta e feche de novo."
        ),
        esquema_json=_objeto({}),
    ),
    DefinicaoFerramenta(
        nome="chamar_vendedor",
        descricao=(
            "Aciona um vendedor humano da loja. Use quando o cliente pedir para falar com uma "
            "pessoa, fizer uma reclamação, quando a situação fugir do que você pode resolver, "
            "para avaliação na loja, ou depois de fechar o acordo (motivo "
            f"'{MOTIVO_ACORDO_FECHADO}'). Não chame só porque o cliente quer fechar: conduza com "
            "fechar_acordo. Depois de chamar, avise o cliente que um vendedor continuará o "
            "atendimento."
        ),
        esquema_json=_objeto({"motivo": _txt("Motivo do acionamento, em uma frase.", nulo=False)}),
    ),
)


def _sem_acordo_velho(antes: EstadoAtendimento, depois: EstadoAtendimento) -> EstadoAtendimento:
    """Mudou a ficha, o desconto ou a proposta depois de fechar? O acordo antigo deixa de valer."""
    if depois.acordo is None or depois.acordo is not antes.acordo:
        return depois
    mudou = (
        depois.ficha != antes.ficha
        or depois.desconto != antes.desconto
        or depois.ultima_proposta != antes.ultima_proposta
    )
    return replace(depois, acordo=None) if mudou else depois


def _sem_confirmacao_velha(
    antes: EstadoAtendimento, depois: EstadoAtendimento
) -> EstadoAtendimento:
    """Mudou a ficha, o desconto ou a proposta sem refazer a ficha de confirmacao? O aceite cai."""
    if (
        depois.confirmacao is not antes.confirmacao
        or depois.pedido_confirmado != antes.pedido_confirmado
    ):
        return depois  # a propria ferramenta mexeu na confirmacao
    if depois.confirmacao is None and not depois.pedido_confirmado:
        return depois
    mudou = (
        depois.ficha != antes.ficha
        or depois.desconto != antes.desconto
        or depois.ultima_proposta != antes.ultima_proposta
    )
    return replace(depois, confirmacao=None, pedido_confirmado=False) if mudou else depois


def _resumir(conteudo: dict[str, Any]) -> str:
    texto = json.dumps(conteudo, ensure_ascii=False)
    return texto if len(texto) <= _RESUMO_MAX else texto[: _RESUMO_MAX - 1] + "…"


class CatalogoFerramentas:
    """Definicoes oferecidas ao LLM e execucao delas (sem excecao para erro do LLM)."""

    def __init__(self) -> None:
        self._handlers: dict[str, _Handler] = {
            "registrar_interesse": _registrar_interesse,
            "consultar_estoque": _consultar_estoque,
            "confirmar_item": _confirmar_item,
            "registrar_usado": _registrar_usado,
            "registrar_leitura_imagem": _registrar_leitura_imagem,
            "registrar_compra": _registrar_compra,
            "calcular_proposta": _calcular_proposta,
            "confirmar_pedido": _confirmar_pedido,
            "liberar_desconto": _liberar_desconto,
            "fechar_acordo": _fechar_acordo,
            "chamar_vendedor": _chamar_vendedor,
        }

    def definicoes(self) -> list[DefinicaoFerramenta]:
        return list(_DEFINICOES)

    async def executar(
        self,
        nome: str,
        entrada: dict[str, Any],
        estado: EstadoAtendimento,
        ctx: ContextoFerramentas,
    ) -> ResultadoFerramenta:
        conteudo, novo, erro = await self._rodar(nome, entrada, estado, ctx)
        evento = {
            "tipo": "ferramenta",
            "nome": nome,
            "entrada": entrada,
            "resultado_resumido": _resumir(conteudo),
            "erro": erro,
        }
        return ResultadoFerramenta(conteudo, novo, [evento], erro)

    async def _rodar(
        self,
        nome: str,
        entrada: dict[str, Any],
        estado: EstadoAtendimento,
        ctx: ContextoFerramentas,
    ) -> tuple[dict[str, Any], EstadoAtendimento, bool]:
        handler = self._handlers.get(nome)
        if handler is None:
            return {"erro": f"Ferramenta desconhecida: {nome}."}, estado, True
        if not isinstance(entrada, dict):
            return {"erro": "A entrada da ferramenta deve ser um objeto JSON."}, estado, True
        try:
            saida = await handler(entrada, estado, ctx)
            conteudo = await _com_formas_na_pergunta(saida, ctx)
        except ErroFerramenta as exc:
            return {"erro": str(exc), **exc.extras}, estado, True
        except EstoqueIndisponivel:
            return (
                {
                    "erro": "estoque indisponível",
                    "status": "estoque_indisponivel",
                    "mensagem": (
                        "Não consegui consultar o estoque agora. Avise o cliente, sem citar "
                        "valores, e tente de novo em instantes ou chame o vendedor."
                    ),
                },
                estado,
                True,
            )
        except LojaNaoEncontrada:
            return {"erro": "Loja não encontrada. Chame o vendedor."}, estado, True
        novo = _sem_confirmacao_velha(estado, saida.estado)
        return conteudo, _sem_acordo_velho(estado, novo), False
