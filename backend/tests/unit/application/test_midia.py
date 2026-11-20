"""ReceberMidia: valida tipo e tamanho e guarda via a porta ArmazenamentoMidia (fake em memoria)."""

import pytest

from app.application.midia import (
    ConteudoMidia,
    MidiaGrandeDemais,
    ReceberMidia,
    TipoMidiaNaoSuportado,
    normalizar_tipo,
)


class ArmazenamentoMemoria:
    def __init__(self) -> None:
        self.itens: dict[str, ConteudoMidia] = {}

    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        nome = f"m{len(self.itens)}"
        self.itens[nome] = ConteudoMidia(dados=dados, tipo_mime=tipo_mime)
        return nome

    async def ler(self, nome: str) -> ConteudoMidia | None:
        return self.itens.get(nome)


@pytest.mark.parametrize(
    "tipo",
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "audio/webm",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp4",
    ],
)
async def test_tipos_aceitos_sao_guardados(tipo: str) -> None:
    arm = ArmazenamentoMemoria()
    nome = await ReceberMidia(arm, limite_bytes=100)(b"abc", tipo)
    assert arm.itens[nome] == ConteudoMidia(dados=b"abc", tipo_mime=tipo)


async def test_parametros_do_content_type_sao_ignorados() -> None:
    arm = ArmazenamentoMemoria()
    nome = await ReceberMidia(arm, limite_bytes=100)(b"abc", "Audio/WebM;codecs=opus")
    assert arm.itens[nome].tipo_mime == "audio/webm"


@pytest.mark.parametrize("tipo", ["application/pdf", "text/html", "image/gif", "", "audio/x-wav"])
async def test_tipo_nao_suportado_e_recusado_sem_guardar(tipo: str) -> None:
    arm = ArmazenamentoMemoria()
    with pytest.raises(TipoMidiaNaoSuportado):
        await ReceberMidia(arm, limite_bytes=100)(b"abc", tipo)
    assert arm.itens == {}


async def test_acima_do_limite_e_recusado_sem_guardar() -> None:
    arm = ArmazenamentoMemoria()
    caso = ReceberMidia(arm, limite_bytes=3)
    with pytest.raises(MidiaGrandeDemais) as erro:
        await caso(b"abcd", "image/png")
    assert erro.value.limite_bytes == 3
    assert arm.itens == {}


async def test_exatamente_no_limite_passa() -> None:
    arm = ArmazenamentoMemoria()
    await ReceberMidia(arm, limite_bytes=3)(b"abc", "image/png")
    assert len(arm.itens) == 1


def test_normalizar_tipo() -> None:
    assert normalizar_tipo(" Image/PNG ; q=1") == "image/png"
