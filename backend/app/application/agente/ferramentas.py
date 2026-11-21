"""Ferramentas do agente. O LLM conversa e chama estas funcoes; o CODIGO decide.

A trava de preco vive em `calcular_proposta`: com a ficha incompleta ela devolve so as
pendencias (nunca um valor). `consultar_estoque` nunca devolve preco. O estado e imutavel:
cada execucao devolve um novo `EstadoAtendimento`; persistir e registrar eventos fica com o
orquestrador.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from app.application.agente.contexto import ContextoFerramentas, ErroFerramenta
from app.application.agente.estado import EstadoAtendimento
from app.application.agente.proposta import FRASE_OBRIGATORIA, montar_proposta
from app.application.config.modelos import LojaNaoEncontrada
from app.application.estoque import EstoqueIndisponivel
from app.application.llm import DefinicaoFerramenta
from app.domain.desconto import TetoAtingido, liberar_proximo
from app.domain.estoque import ItemEstoque
from app.domain.ficha import Ficha, Pendencia, TipoPagamento, UsadoInformado, pendencias
from app.domain.valores import Bandeira, Capacidade, Dinheiro, ModeloAparelho

__all__ = [
    "FRASE_OBRIGATORIA",
    "CatalogoFerramentas",
    "ContextoFerramentas",
    "ResultadoFerramenta",
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
    _P.APARELHO_MODELO: ("modelo do aparelho desejado", "Qual iPhone você está procurando?"),
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
    _P.USADO_CAMERA: ("funcionamento da câmera do usado", "A câmera funciona normalmente?"),
    _P.USADO_OUTROS_DEFEITOS: (
        "outros defeitos do usado",
        "Ele tem algum outro defeito, como Face ID, alto-falante ou botões?",
    ),
    _P.USADO_PECA_TROCADA: (
        "peça já trocada no usado",
        "Alguma peça dele já foi trocada ou reparada?",
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


async def _modelos_em_estoque(ctx: ContextoFerramentas) -> list[str]:
    try:
        linhas = await ctx.config.obter_estoque(ctx.loja_id)
    except LojaNaoEncontrada:
        return []
    vistos: dict[str, None] = {}
    for linha in linhas:
        if linha.quantidade > 0:
            vistos[linha.modelo.nome] = None
    return list(vistos)


async def _modelo_da_loja(texto: str, ctx: ContextoFerramentas) -> ModeloAparelho:
    """Modelo conhecido (iPhone); senao, erro que diz o que a loja vende."""
    try:
        modelo = ModeloAparelho.de(texto)
    except ValueError:
        modelo = None
    if modelo is not None and modelo.conhecido:
        return modelo
    em_estoque = await _modelos_em_estoque(ctx)
    extra = (
        " Modelos no estoque agora: " + ", ".join(em_estoque) + "."
        if em_estoque
        else " Consulte o estoque com consultar_estoque para ver as opções."
    )
    raise ErroFerramenta(
        f"Não reconheci '{texto}'. A loja trabalha com iPhone.{extra}",
        modelos_no_estoque=em_estoque,
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
    if item.bateria_pct is not None:
        opcao["bateria_pct"] = item.bateria_pct
    if item.desatualizado:
        opcao["dados_desatualizados"] = True
    return opcao


def _aplicar_interesse(
    ficha: Ficha, modelo: ModeloAparelho, capacidade: Capacidade | None, cor: str | None
) -> tuple[Ficha, bool]:
    """Atualiza o interesse; se algo mudou, a confirmacao do item cai. Devolve (ficha, mudou)."""
    atual = ficha.interesse
    mesmo_modelo = atual.modelo == modelo
    nova_cap = capacidade or (atual.capacidade if mesmo_modelo else None)
    nova_cor = cor or (atual.cor if mesmo_modelo else None)
    mudou = (modelo, nova_cap, nova_cor) != (atual.modelo, atual.capacidade, atual.cor)
    campos: dict[str, Any] = {"modelo": modelo, "capacidade": nova_cap, "cor": nova_cor}
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
    ficha, mudou = _aplicar_interesse(estado.ficha, modelo, capacidade, cor)
    novo = replace(estado, ficha=ficha, estoque_consultado=estado.estoque_consultado and not mudou)
    conteudo: dict[str, Any] = {"status": "ok", **_situacao(ficha)}
    if novo.ficha.interesse.sku_estoque_confirmado is None:
        conteudo["proximo_passo"] = "Chame consultar_estoque para ver as opções disponíveis."
    return _Saida(conteudo, novo)


async def _consultar_estoque(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    modelo = await _modelo_da_loja(_texto_obrigatorio(entrada, "modelo"), ctx)
    capacidade = _capacidade_opcional(entrada)
    cor = _texto_opcional(entrada, "cor")
    atual = estado.ficha.interesse
    if atual.modelo == modelo:
        capacidade = capacidade or atual.capacidade
        cor = cor or atual.cor

    itens = await ctx.estoque.buscar(ctx.loja_id, modelo, capacidade, cor)

    ficha, _ = _aplicar_interesse(estado.ficha, modelo, capacidade, cor)
    confirmado = ficha.interesse.sku_estoque_confirmado
    if confirmado is not None and confirmado not in {i.sku for i in itens}:
        ficha = ficha.com_interesse(sku_estoque_confirmado=None)
    unico = len(itens) == 1
    if unico:
        i = itens[0]
        ficha = ficha.com_interesse(
            capacidade=i.capacidade, cor=i.cor, sku_estoque_confirmado=i.sku
        )

    conteudo: dict[str, Any] = {
        "status": "ok",
        "opcoes": [_opcao(i) for i in itens[:_MAX_OPCOES]],
        "total_opcoes": len(itens),
        "confirmado": ficha.interesse.sku_estoque_confirmado is not None,
    }
    if not itens:
        conteudo["mensagem"] = "Não há unidades disponíveis com esses critérios."
    elif unico:
        conteudo["sku_confirmado"] = itens[0].sku
        conteudo["mensagem"] = (
            "Só existe uma opção compatível e ela já foi confirmada; confirme com o cliente."
        )
    else:
        conteudo["mensagem"] = (
            "Há mais de uma opção: pergunte ao cliente qual prefere "
            "(capacidade, cor ou condição) e use confirmar_item com o sku escolhido."
        )
    return _Saida(conteudo, replace(estado, ficha=ficha, estoque_consultado=True))


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
    return _Saida(conteudo, replace(estado, ficha=ficha, estoque_consultado=True))


async def _registrar_usado(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    tem_troca = entrada.get("tem_troca")
    if not isinstance(tem_troca, bool):
        raise ErroFerramenta("O campo 'tem_troca' é obrigatório (verdadeiro ou falso).")
    if not tem_troca:
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
    return _Saida({"status": "ok", **_situacao(ficha)}, replace(estado, ficha=ficha))


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


async def _calcular_proposta(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    if pendencias(estado.ficha):
        return _Saida(_bloqueio(estado.ficha), estado)
    conteudo = await montar_proposta(ctx, estado)
    return _Saida(conteudo, replace(estado, proposta_apresentada=True, ultima_proposta=conteudo))


async def _liberar_desconto(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    _texto_obrigatorio(entrada, "motivo")
    if not estado.proposta_apresentada or pendencias(estado.ficha):
        return _Saida(
            {
                "bloqueado": True,
                "mensagem": (
                    "Só é possível negociar desconto depois de apresentar a proposta ao "
                    "cliente (use calcular_proposta com a ficha completa)."
                ),
            },
            estado,
        )
    preco = await ctx.config.obter_preco(ctx.loja_id)
    if preco is None:
        raise ErroFerramenta("A loja ainda não definiu as regras de preço. Chame o vendedor.")

    liberacao = liberar_proximo(preco.politica, estado.desconto)
    if isinstance(liberacao, TetoAtingido):
        proposta = await montar_proposta(ctx, estado)
        conteudo = {
            "status": "ok",
            "teto_atingido": True,
            "mensagem": (
                "Não há mais desconto a liberar: este já é o melhor preço que a loja pode fazer."
            ),
            "proposta": proposta,
        }
        return _Saida(conteudo, replace(estado, ultima_proposta=proposta))

    novo_desconto, total = liberacao
    novo = replace(estado, desconto=novo_desconto)
    proposta = await montar_proposta(ctx, novo)  # se falhar, nada foi liberado
    conteudo = {
        "status": "ok",
        "teto_atingido": False,
        "desconto_liberado_agora": str(total - estado.desconto.liberado),
        "mensagem": "Desconto liberado e proposta recalculada. Apresente os valores novos.",
        "proposta": proposta,
    }
    return _Saida(conteudo, replace(novo, ultima_proposta=proposta))


async def _chamar_vendedor(
    entrada: dict[str, Any], estado: EstadoAtendimento, ctx: ContextoFerramentas
) -> _Saida:
    motivo = _texto_obrigatorio(entrada, "motivo")
    if estado.handoff_solicitado:
        return _Saida(
            {"status": "ok", "mensagem": "O vendedor já foi acionado e vai continuar a conversa."},
            estado,
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

_DEFINICOES: tuple[DefinicaoFerramenta, ...] = (
    DefinicaoFerramenta(
        nome="registrar_interesse",
        descricao=(
            "Registra na ficha o aparelho que o cliente quer comprar. Chame assim que o cliente "
            "disser o modelo (capacidade e cor quando souber; use null no que ainda não foi dito). "
            "Só aceita iPhone; se o modelo não for conhecido devolve erro com os modelos "
            "do estoque. "
            "Depois chame consultar_estoque."
        ),
        esquema_json=_objeto(
            {
                "modelo": _txt("Modelo do iPhone desejado, ex.: 'iPhone 16 Pro'.", nulo=False),
                "capacidade": _txt("Capacidade, ex.: '128GB'; null se não informada."),
                "cor": _txt("Cor desejada; null se não informada."),
            }
        ),
        estrita=False,
    ),
    DefinicaoFerramenta(
        nome="consultar_estoque",
        descricao=(
            "Consulta no estoque as opções disponíveis do modelo (sku, capacidade, cor, condição e "
            "bateria do seminovo). NUNCA devolve valores: para falar de dinheiro use "
            "calcular_proposta. Se houver exatamente uma opção compatível ela já é confirmada; "
            "se houver várias, pergunte ao cliente qual prefere e use confirmar_item. Se o estoque "
            "estiver fora do ar, avise o cliente e tente de novo depois."
        ),
        esquema_json=_objeto(
            {
                "modelo": _txt("Modelo do iPhone, ex.: 'iPhone 15'.", nulo=False),
                "capacidade": _txt("Capacidade para filtrar, ex.: '256GB'; null para todas."),
                "cor": _txt("Cor para filtrar; null para todas."),
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
            "troca (tem_troca=false). Pode ser chamada várias vezes, conforme o cliente responde: "
            "preencha só o que foi dito e use null no resto (null não apaga o que já foi "
            "registrado). outros_defeitos: lista vazia = nenhum defeito; null = ainda não "
            "perguntado. bateria_pct é a saúde da bateria de 0 a 100."
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
                "camera_ok": _bool("A câmera funciona normalmente?"),
                "outros_defeitos": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Outros defeitos (Face ID, alto-falante...); lista vazia se nenhum; "
                        "null se ainda não perguntado."
                    ),
                },
                "peca_trocada": _bool("Alguma peça já foi trocada/reparada?"),
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
            "Libera o próximo degrau de desconto e recalcula a proposta. Use SOMENTE quando o "
            "cliente pedir desconto, e só depois de ter apresentado a proposta; antes disso "
            "devolve "
            "bloqueado. Quando o teto da loja é atingido informa que é o melhor preço. Nunca "
            "prometa desconto por conta própria nem invente valores. Deixe claro ao cliente o "
            "que é "
            "desconto negociado e o que é oportunidade única."
        ),
        esquema_json=_objeto({"motivo": _txt("Por que o desconto foi pedido.", nulo=False)}),
    ),
    DefinicaoFerramenta(
        nome="chamar_vendedor",
        descricao=(
            "Aciona um vendedor humano da loja. Use quando o cliente quiser fechar a compra, pedir "
            "para falar com uma pessoa, ou quando a situação fugir do que você pode resolver. "
            "Depois de chamar, avise o cliente que um vendedor continuará o atendimento."
        ),
        esquema_json=_objeto({"motivo": _txt("Motivo do acionamento, em uma frase.", nulo=False)}),
    ),
)


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
            "registrar_compra": _registrar_compra,
            "calcular_proposta": _calcular_proposta,
            "liberar_desconto": _liberar_desconto,
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
        return saida.conteudo, saida.estado, False
