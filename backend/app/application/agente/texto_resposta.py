"""Limpeza deterministica do texto do modelo antes de ir ao cliente.

O modelo as vezes devolve a mesma frase duas vezes na mesma resposta (visto com gpt-4.1-mini).
Aqui o codigo tira a repeticao: o texto inteiro dobrado e linhas iguais seguidas.
"""

from __future__ import annotations

import re


def _metade_repetida(texto: str) -> str | None:
    """`X X` (separado por espaco/quebra) -> `X`; None se o texto nao e uma repeticao."""
    for n in range(2, 4):
        partes = re.split(r"\s+", texto)
        if len(partes) % n:
            continue
        tamanho = len(partes) // n
        blocos = [" ".join(partes[i * tamanho : (i + 1) * tamanho]) for i in range(n)]
        if len(set(blocos)) == 1:
            return blocos[0]
    return None


def sem_repeticao(texto: str) -> str:
    """Remove o texto dobrado e linhas iguais seguidas (mesmo com linha em branco no meio)."""
    linhas: list[str] = []
    ultima: str | None = None
    for linha in texto.split("\n"):
        conteudo = linha.strip()
        if conteudo and conteudo == ultima:
            while linhas and not linhas[-1].strip():
                linhas.pop()
            continue
        linhas.append(linha)
        if conteudo:
            ultima = conteudo
    limpo = "\n".join(linhas).strip()
    unica = _metade_repetida(limpo)
    return limpo if unica is None else unica


def uma_pergunta(texto: str) -> str:
    """Uma pergunta por mensagem: depois da primeira linha com pergunta, linhas com `?` saem.

    O modelo as vezes reescreve a mesma pergunta numa segunda linha (ou emenda outra pergunta).
    O que vem antes da primeira pergunta e as linhas sem pergunta depois dela ficam.
    """
    linhas = texto.split("\n")
    primeira = next((i for i, linha in enumerate(linhas) if "?" in linha), None)
    if primeira is None:
        return texto
    resto = [linha for linha in linhas[primeira + 1 :] if "?" not in linha]
    if len(resto) == len(linhas) - primeira - 1:
        return texto
    limpo = "\n".join([*linhas[: primeira + 1], *resto])
    return re.sub(r"\n{3,}", "\n\n", limpo).strip()
