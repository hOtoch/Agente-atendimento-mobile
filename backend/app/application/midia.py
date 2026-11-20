"""Midia enviada pelo cliente (imagem/audio): porta de armazenamento e caso de uso de recebimento.

So guarda e devolve o arquivo; o processamento (visao/STT) fica para o M6.
"""

from dataclasses import dataclass
from typing import Protocol

TIPOS_ACEITOS: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "audio/webm",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp4",
    }
)


@dataclass(frozen=True, slots=True)
class ConteudoMidia:
    dados: bytes
    tipo_mime: str


class ArmazenamentoMidia(Protocol):
    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        """Guarda o arquivo e devolve o nome gerado (unico)."""
        ...

    async def ler(self, nome: str) -> ConteudoMidia | None:
        """Devolve o arquivo ou None se o nome nao existir (ou for invalido)."""
        ...


class TipoMidiaNaoSuportado(Exception):
    def __init__(self, tipo_mime: str) -> None:
        super().__init__(f"tipo de midia nao suportado: {tipo_mime!r}")
        self.tipo_mime = tipo_mime


class MidiaGrandeDemais(Exception):
    def __init__(self, limite_bytes: int) -> None:
        super().__init__(f"midia acima do limite de {limite_bytes} bytes")
        self.limite_bytes = limite_bytes


class MidiaNaoEncontrada(Exception):
    def __init__(self, nome: str) -> None:
        super().__init__(f"midia nao encontrada: {nome!r}")
        self.nome = nome


def normalizar_tipo(content_type: str) -> str:
    """`Audio/WebM;codecs=opus` -> `audio/webm`."""
    return content_type.split(";", 1)[0].strip().lower()


class ReceberMidia:
    def __init__(self, armazenamento: ArmazenamentoMidia, limite_bytes: int) -> None:
        self._armazenamento = armazenamento
        self.limite_bytes = limite_bytes

    async def __call__(self, dados: bytes, content_type: str) -> str:
        tipo = normalizar_tipo(content_type)
        if tipo not in TIPOS_ACEITOS:
            raise TipoMidiaNaoSuportado(tipo)
        if len(dados) > self.limite_bytes:
            raise MidiaGrandeDemais(self.limite_bytes)
        return await self._armazenamento.salvar(dados, tipo)
