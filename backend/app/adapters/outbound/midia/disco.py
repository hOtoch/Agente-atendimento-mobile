"""Armazenamento de midia em disco local (`MIDIA_DIR`)."""

import asyncio
import re
import uuid
from pathlib import Path

from app.application.midia import ConteudoMidia

_EXTENSAO_POR_TIPO = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
}
_TIPO_POR_EXTENSAO = {ext: tipo for tipo, ext in _EXTENSAO_POR_TIPO.items()}
_NOME = re.compile(r"[0-9a-f]{32}\.([a-z0-9]+)")


class ArmazenamentoMidiaDisco:
    """Implementa `ArmazenamentoMidia`. Nomes gerados (`uuid4().hex.ext`): nada vem do cliente."""

    def __init__(self, diretorio: str | Path) -> None:
        self._dir = Path(diretorio)

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        nome = f"{uuid.uuid4().hex}.{_EXTENSAO_POR_TIPO[tipo_mime]}"

        def _gravar() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / nome).write_bytes(dados)

        await asyncio.to_thread(_gravar)
        return nome

    async def ler(self, nome: str) -> ConteudoMidia | None:
        achado = _NOME.fullmatch(nome)
        if achado is None or achado.group(1) not in _TIPO_POR_EXTENSAO:
            return None
        caminho = self._dir / nome

        def _ler() -> bytes | None:
            try:
                return caminho.read_bytes()
            except FileNotFoundError:
                return None

        dados = await asyncio.to_thread(_ler)
        if dados is None:
            return None
        return ConteudoMidia(dados=dados, tipo_mime=_TIPO_POR_EXTENSAO[achado.group(1)])
