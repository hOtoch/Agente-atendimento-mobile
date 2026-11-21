"""Leitura de imagem (foto do aparelho, print da saude da bateria).

O LLM com visao SO le a imagem e devolve a leitura estruturada (`registrar_leitura_imagem`).
Quem decide se ela vai para a ficha e este modulo: com confianca >= `LIMIAR_CONFIANCA` (e uma
troca ja confirmada) grava; senao devolve a pergunta de confirmacao que o agente faz ao cliente.
A confirmacao do cliente grava pela ferramenta `registrar_usado`, que ja existia.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.application.agente.conversa_portas import EntradaConversa
from app.application.canal import TipoMensagem
from app.application.llm import Bloco, BlocoImagem
from app.application.midia import ArmazenamentoMidia
from app.domain.ficha import Ficha
from app.domain.valores import ModeloAparelho

LIMIAR_CONFIANCA = 0.8
LIMITE_BYTES_IMAGEM = 5 * 1024 * 1024
"""Maximo que a API de visao aceita por imagem."""

_NOME_NA_URL = re.compile(r"/([^/?#]+)(?:[?#].*)?$")


class TipoImagem(StrEnum):
    PRINT_BATERIA = "print_bateria"
    FOTO_APARELHO = "foto_aparelho"
    OUTRO = "outro"


@dataclass(frozen=True, slots=True)
class LeituraImagem:
    """O que o LLM enxergou. `None` = nao aparece na imagem."""

    tipo: TipoImagem
    bateria_pct: int | None
    tela_danificada: bool | None
    traseira_danificada: bool | None
    carcaca_marcada: bool | None
    modelo: ModeloAparelho | None
    confianca: float


@dataclass(frozen=True, slots=True)
class DecisaoLeitura:
    ficha: Ficha
    gravado: bool
    campos: tuple[str, ...]
    """Campos da ficha que a leitura preencheu (ou preencheria, se `pergunta` existir)."""
    pergunta: str | None = None
    """Confirmacao a fazer ao cliente quando nada foi gravado."""


def _candidatos(ficha: Ficha, leitura: LeituraImagem) -> dict[str, Any]:
    """Campos que a leitura traz e que fazem sentido para o tipo de imagem."""
    if leitura.tipo is TipoImagem.OUTRO:
        return {}
    campos: dict[str, Any] = {}
    if leitura.tipo is TipoImagem.PRINT_BATERIA and leitura.bateria_pct is not None:
        campos["bateria_pct"] = leitura.bateria_pct
    if leitura.tipo is TipoImagem.FOTO_APARELHO:
        for nome in ("tela_danificada", "traseira_danificada", "carcaca_marcada"):
            valor = getattr(leitura, nome)
            if valor is not None:
                campos[nome] = valor
    if leitura.modelo is not None and ficha.usado.modelo is None:
        campos["modelo"] = leitura.modelo  # nunca sobrescreve o que o cliente ja disse
    return campos


def _descrever(campos: dict[str, Any]) -> str:
    partes: list[str] = []
    if "bateria_pct" in campos:
        partes.append(f"a saúde da bateria é {campos['bateria_pct']}%")
    if "modelo" in campos:
        partes.append(f"o aparelho é um {campos['modelo']}")
    for nome, sim, nao in (
        ("tela_danificada", "a tela tem danos", "a tela está sem danos"),
        ("traseira_danificada", "o vidro traseiro tem danos", "o vidro traseiro está sem danos"),
        ("carcaca_marcada", "a carcaça tem marcas", "a carcaça está sem marcas"),
    ):
        if nome in campos:
            partes.append(sim if campos[nome] else nao)
    return "; ".join(partes)


def decidir_leitura(
    ficha: Ficha, leitura: LeituraImagem, limiar: float = LIMIAR_CONFIANCA
) -> DecisaoLeitura:
    candidatos = _candidatos(ficha, leitura)
    campos = tuple(candidatos)
    if not candidatos:
        return DecisaoLeitura(ficha, False, ())
    if ficha.tem_troca is not True:
        # Nao ha troca confirmada: nao assume que a foto/print e do aparelho da troca.
        pergunta = (
            f"Pela imagem, parece que {_descrever(candidatos)}. "
            "Esse é o aparelho que você daria na troca?"
        )
        return DecisaoLeitura(ficha, False, campos, pergunta)
    if leitura.confianca < limiar:
        pergunta = f"Pela imagem, parece que {_descrever(candidatos)}. Está correto?"
        return DecisaoLeitura(ficha, False, campos, pergunta)
    return DecisaoLeitura(ficha.com_usado(**candidatos), True, campos)


# --- imagem do cliente -> bloco para o LLM ---------------------------------------------------


def nome_da_midia(midia_url: str | None) -> str | None:
    """Nome do arquivo em `.../midias/<nome>` (webchat e WhatsApp guardam assim)."""
    if not midia_url:
        return None
    achado = _NOME_NA_URL.search(midia_url)
    return achado.group(1) if achado else None


async def carregar_bloco_imagem(
    armazenamento: ArmazenamentoMidia, midia_url: str | None
) -> BlocoImagem | None:
    """A imagem como bloco do LLM; None se nao existe, nao e imagem ou passa do limite."""
    nome = nome_da_midia(midia_url)
    if nome is None:
        return None
    conteudo = await armazenamento.ler(nome)
    if conteudo is None or not conteudo.tipo_mime.startswith("image/"):
        return None
    if len(conteudo.dados) > LIMITE_BYTES_IMAGEM:
        return None
    return BlocoImagem(conteudo.tipo_mime, base64.b64encode(conteudo.dados).decode("ascii"))


async def anexar_imagens(
    entradas: Sequence[EntradaConversa],
    blocos_texto: Sequence[Bloco],
    armazenamento: ArmazenamentoMidia | None,
) -> list[Bloco]:
    """`blocos_texto[i]` e o bloco da `entradas[i]`; nas imagens legiveis ele ganha a imagem antes.

    Sem armazenamento ou com imagem ilegivel, o bloco de texto provisorio segue sozinho.
    """
    saida: list[Bloco] = []
    for entrada, bloco in zip(entradas, blocos_texto, strict=True):
        if armazenamento is not None and entrada.tipo is TipoMensagem.IMAGEM:
            imagem = await carregar_bloco_imagem(armazenamento, entrada.midia_url)
            if imagem is not None:
                saida.append(imagem)
        saida.append(bloco)
    return saida
