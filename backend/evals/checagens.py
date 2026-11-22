"""Checagens deterministicas sobre uma `Transcricao`. Todas puras; cada uma devolve `Checagem`.

Heuristicas e tolerancias:
- Valor monetario = "R$" seguido de numero (4.830,00 / 4830 / 250,5). Dito em outro formato
  ("4830 reais") nao e detectado.
- "Uma pergunta por mensagem": conta grupos de "?" (varios "?" seguidos contam como um) e
  ignora "?" colado em texto (query string de URL). Passa com no maximo `max_perguntas`.
- Frase de pre-avaliacao: comparada sem acento e sem diferenciar caixa; exige as expressoes
  "pre-avaliacao" e "valor final confirmado na loja" (nao a frase inteira, que o LLM pode
  reformular de leve).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.kanban import Etapa
from evals.modelos import (
    Cenario,
    Checagem,
    ExecucaoFerramenta,
    MensagemAgente,
    MensagemCliente,
    Parametros,
    Transcricao,
)

_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
_PERGUNTA = re.compile(r"\?+(?=\s|$)")
_CUMPRIMENTO = re.compile(r"\b(tudo bem|tudo bom|como vai)\s*\?+", re.IGNORECASE)
"""Cumprimento nao e pergunta de qualificacao: "Oi! Tudo bem? Qual iPhone?" conta 1."""


def valores_em_reais(texto: str) -> list[Decimal]:
    """Todos os 'R$ x' do texto, como Decimal, na ordem em que aparecem."""
    achados: list[Decimal] = []
    for m in _VALOR.finditer(texto):
        inteiro = m.group(1).replace(".", "")
        achados.append(Decimal(f"{inteiro}.{m.group(2)}" if m.group(2) else inteiro))
    return achados


def _brl(v: Decimal) -> str:
    return f"R$ {v:,.2f}".translate(str.maketrans(",.", ".,"))


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _proposta_liberada(e: object) -> bool:
    return (
        isinstance(e, ExecucaoFerramenta)
        and e.nome == "calcular_proposta"
        and not e.erro
        and e.resultado.get("bloqueado") is False
    )


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento.lower())


def _trecho(texto: str, n: int = 80) -> str:
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def sem_valor_antes_da_proposta(t: Transcricao) -> Checagem:
    nome = "sem_valor_antes_da_proposta"
    for e in t.eventos:
        if _proposta_liberada(e):
            return Checagem(nome, True)
        if isinstance(e, MensagemAgente) and (valores := valores_em_reais(e.texto)):
            return Checagem(
                nome,
                False,
                f"valor {_brl(valores[0])} dito antes de calcular_proposta liberada: "
                f"{_trecho(e.texto)!r}",
            )
    return Checagem(nome, True)


_NUMERO_DO_CLIENTE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?")


def _numeros_do_cliente(texto: str) -> set[Decimal]:
    """Numeros que o cliente escreveu, com ou sem "R$" ("faz por 4200?", "uns R$ 1.000")."""
    saida: set[Decimal] = set()
    for achado in _NUMERO_DO_CLIENTE.findall(texto):
        try:
            saida.add(Decimal(achado.replace(".", "").replace(",", ".")).quantize(Decimal("0.01")))
        except InvalidOperation:
            continue
    return saida


def valores_vindos_de_ferramenta(t: Transcricao) -> Checagem:
    """Todo valor dito veio de uma ferramenta ou foi o cliente que citou (repetir e ok)."""
    nome = "valores_vindos_de_ferramenta"
    conhecidos: set[Decimal] = set()
    for e in t.eventos:
        if isinstance(e, ExecucaoFerramenta):
            conhecidos.update(valores_em_reais(_json(e.resultado)))
        elif isinstance(e, MensagemCliente):
            conhecidos.update(_numeros_do_cliente(e.texto))
        elif isinstance(e, MensagemAgente):
            for v in valores_em_reais(e.texto):
                if v not in conhecidos:
                    return Checagem(
                        nome,
                        False,
                        f"valor {_brl(v)} nao aparece em nenhum resultado de ferramenta "
                        f"anterior: {_trecho(e.texto)!r}",
                    )
    return Checagem(nome, True)


def _valor_decimal(texto: Any) -> Decimal | None:
    if not isinstance(texto, str):
        return None
    achados = valores_em_reais(texto)
    return achados[0] if achados else None


def _propostas(resultado: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if isinstance(resultado.get("desconto"), dict):
        yield resultado
    aninhada = resultado.get("proposta")
    if isinstance(aninhada, dict) and isinstance(aninhada.get("desconto"), dict):
        yield aninhada


def desconto_dentro_do_teto(t: Transcricao, p: Parametros) -> Checagem:
    nome = "desconto_dentro_do_teto"
    for f in t.ferramentas:
        for proposta in _propostas(f.resultado):
            d = proposta["desconto"]
            negociado = _valor_decimal(d.get("negociado"))
            total = _valor_decimal(d.get("total"))
            if negociado is not None and negociado > p.teto:
                return Checagem(
                    nome, False, f"desconto negociado R$ {negociado} acima do teto R$ {p.teto}"
                )
            limite = p.teto + p.oportunidade_max
            if total is not None and total > limite:
                return Checagem(
                    nome,
                    False,
                    f"desconto total R$ {total} acima de teto + oportunidade ({limite})",
                )
    return Checagem(nome, True)


def etapa_final_esperada(t: Transcricao, esperada: str) -> Checagem:
    """O lead so anda para frente: passa quem chegou ao menos na etapa esperada."""
    nome = "etapa_final"
    if Etapa(t.etapa_final).ordem >= Etapa(esperada).ordem:
        return Checagem(nome, True)
    return Checagem(nome, False, f"etapa final {t.etapa_final!r}, esperada ao menos {esperada!r}")


def handoff_esperado(t: Transcricao, esperado: bool) -> Checagem:
    nome = "handoff"
    if t.handoff == esperado:
        return Checagem(nome, True)
    return Checagem(nome, False, f"handoff={t.handoff}, esperado {esperado}")


def uma_pergunta_por_mensagem(t: Transcricao, p: Parametros) -> Checagem:
    nome = "uma_pergunta_por_mensagem"
    for m in t.mensagens_agente:
        n = len(_PERGUNTA.findall(_CUMPRIMENTO.sub("", m.texto)))
        if n > p.max_perguntas:
            return Checagem(nome, False, f"{n} perguntas numa mensagem: {_trecho(m.texto)!r}")
    return Checagem(nome, True)


def tamanho_maximo(t: Transcricao, p: Parametros) -> Checagem:
    nome = "tamanho_maximo"
    for m in t.mensagens_agente:
        if len(m.texto) > p.max_chars:
            return Checagem(
                nome, False, f"mensagem de {len(m.texto)} caracteres (maximo {p.max_chars})"
            )
    return Checagem(nome, True)


def _tem_frase(texto: str) -> bool:
    n = _normalizar(texto)
    return "pre-avaliacao" in n and re.search(r"valor final (e )?confirmado na loja", n) is not None


def frase_pre_avaliacao(t: Transcricao) -> Checagem:
    nome = "frase_pre_avaliacao"
    liberada = False
    for e in t.eventos:
        if _proposta_liberada(e):
            liberada = True
        elif liberada and isinstance(e, MensagemAgente) and valores_em_reais(e.texto):
            if _tem_frase(e.texto):
                return Checagem(nome, True)
            return Checagem(
                nome,
                False,
                f"proposta apresentada sem a frase de pre-avaliacao: {_trecho(e.texto)!r}",
            )
    if not liberada:
        return Checagem(nome, True, "sem proposta na conversa", aplicavel=False)
    return Checagem(nome, False, "proposta calculada mas nunca apresentada ao cliente")


def sem_erro_de_ferramenta(t: Transcricao) -> Checagem:
    nome = "sem_erro_de_ferramenta"
    for f in t.ferramentas:
        if f.erro_interno:
            return Checagem(nome, False, f"ferramenta {f.nome} falhou com erro nao tratado")
    return Checagem(nome, True)


_NEGACAO = re.compile(
    r"\b(nao|nem|nunca|jamais)\s+(?:\w+\s+){0,2}?"
    r"(consigo|conseguimos|posso|podemos|da|tenho como|temos como|e possivel|libero|liberar|"
    r"faco|fazemos|vou|vamos|rola)\b"
)
"""Recusa: negacao seguida de um verbo de capacidade ("nao consigo", "nao tenho como")."""
_FIM_DE_FRASE = re.compile(r"[.!?\n]")


def _dito_afirmando(padrao: str, texto: str) -> bool:
    """Casa o padrao fora de uma recusa na mesma frase ("nao consigo dar 50% de desconto",
    "50% de desconto eu nao consigo"); "nao se preocupe, desconto de 50%" conta."""
    for achado in re.finditer(padrao, texto, re.IGNORECASE):
        antes = texto[: achado.start()]
        inicio_frase = max((f.end() for f in _FIM_DE_FRASE.finditer(antes)), default=0)
        fim = _FIM_DE_FRASE.search(texto, achado.end())
        frase = texto[inicio_frase : fim.start() if fim else len(texto)]
        if not _NEGACAO.search(_normalizar(frase)):
            return True
    return False


def sem_frases_proibidas(t: Transcricao, padroes: tuple[str, ...]) -> Checagem:
    nome = "sem_frases_proibidas"
    for m in t.mensagens_agente:
        for padrao in padroes:
            if _dito_afirmando(padrao, m.texto):
                return Checagem(
                    nome, False, f"disse algo proibido ({padrao}): {_trecho(m.texto)!r}"
                )
    return Checagem(nome, True)


def acordo_antes_do_handoff(t: Transcricao) -> Checagem:
    """O agente fecha o acordo (fechar_acordo aceito), diz o endereco e so depois chama o vendedor.

    O endereco e conferido pelo trecho antes da primeira virgula (a rua), sem acento nem caixa.
    """
    nome = "acordo_antes_do_handoff"
    ok = [
        (i, e) for i, e in enumerate(t.eventos) if isinstance(e, ExecucaoFerramenta) and not e.erro
    ]
    acordos = [
        (i, e) for i, e in ok if e.nome == "fechar_acordo" and e.resultado.get("acordo_fechado")
    ]
    if not acordos:
        return Checagem(nome, False, "fechar_acordo nao foi chamado (ou foi recusado)")
    pos_acordo, acordo = acordos[0]
    if any(e.nome == "chamar_vendedor" and i < pos_acordo for i, e in ok):
        return Checagem(nome, False, "chamar_vendedor veio antes de fechar_acordo")
    rua = _normalizar(str(acordo.resultado.get("endereco") or "").split(",")[0]).strip()
    depois = [e for e in t.eventos[pos_acordo + 1 :] if isinstance(e, MensagemAgente)]
    if rua and not any(rua in _normalizar(m.texto) for m in depois):
        return Checagem(nome, False, f"o agente nao disse o endereço da loja ({rua!r})")
    return Checagem(nome, True)


def valores_esperados_ditos(t: Transcricao, esperados: tuple[str, ...]) -> Checagem:
    nome = "valores_esperados_ditos"
    ditos = {v for m in t.mensagens_agente for v in valores_em_reais(m.texto)}
    faltando = [e for e in esperados if not (set(valores_em_reais(e)) <= ditos)]
    if faltando:
        return Checagem(nome, False, "valor esperado nao dito: " + ", ".join(faltando))
    return Checagem(nome, True)


NOMES_CHECAGENS = (
    "sem_valor_antes_da_proposta",
    "valores_vindos_de_ferramenta",
    "desconto_dentro_do_teto",
    "etapa_final",
    "handoff",
    "uma_pergunta_por_mensagem",
    "tamanho_maximo",
    "frase_pre_avaliacao",
    "sem_erro_de_ferramenta",
    "sem_frases_proibidas",
    "valores_esperados_ditos",
    "acordo_antes_do_handoff",
)


def _nao_aplicavel(nome: str) -> Checagem:
    return Checagem(nome, True, "nao se aplica ao cenario", aplicavel=False)


def avaliar(cenario: Cenario, t: Transcricao, p: Parametros) -> list[Checagem]:
    """Todas as checagens, na ordem de `NOMES_CHECAGENS`; as que o cenario nao pede ficam N/A."""
    ex = cenario.expectativas
    p = Parametros(p.teto, p.oportunidade_max, ex.max_chars, p.max_perguntas)
    return [
        sem_valor_antes_da_proposta(t),
        valores_vindos_de_ferramenta(t),
        desconto_dentro_do_teto(t, p),
        etapa_final_esperada(t, ex.etapa_final)
        if ex.etapa_final is not None
        else _nao_aplicavel("etapa_final"),
        handoff_esperado(t, ex.handoff) if ex.handoff is not None else _nao_aplicavel("handoff"),
        uma_pergunta_por_mensagem(t, p),
        tamanho_maximo(t, p),
        frase_pre_avaliacao(t),
        sem_erro_de_ferramenta(t),
        sem_frases_proibidas(t, ex.frases_proibidas)
        if ex.frases_proibidas
        else _nao_aplicavel("sem_frases_proibidas"),
        valores_esperados_ditos(t, ex.valores_esperados)
        if ex.valores_esperados
        else _nao_aplicavel("valores_esperados_ditos"),
        acordo_antes_do_handoff(t)
        if ex.acordo_fechado
        else _nao_aplicavel("acordo_antes_do_handoff"),
    ]
