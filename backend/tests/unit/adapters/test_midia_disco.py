"""ArmazenamentoMidiaDisco: grava em disco com nome gerado e impede path traversal."""

from pathlib import Path

import pytest

from app.adapters.outbound.midia.disco import ArmazenamentoMidiaDisco
from app.application.midia import ConteudoMidia


async def test_salva_e_le_de_volta_com_o_tipo(tmp_path: Path) -> None:
    arm = ArmazenamentoMidiaDisco(tmp_path)
    nome = await arm.salvar(b"\x89PNG", "image/png")
    assert nome.endswith(".png")
    assert (tmp_path / nome).read_bytes() == b"\x89PNG"
    assert await arm.ler(nome) == ConteudoMidia(dados=b"\x89PNG", tipo_mime="image/png")


async def test_cria_o_diretorio_se_nao_existir(tmp_path: Path) -> None:
    destino = tmp_path / "a" / "b"
    nome = await ArmazenamentoMidiaDisco(destino).salvar(b"x", "audio/webm")
    assert (destino / nome).exists()


async def test_nomes_sao_unicos(tmp_path: Path) -> None:
    arm = ArmazenamentoMidiaDisco(tmp_path)
    assert await arm.salvar(b"1", "audio/ogg") != await arm.salvar(b"1", "audio/ogg")


@pytest.mark.parametrize(
    "nome", ["../segredo.png", "..%2fx.png", "/etc/passwd", "a/b.png", "inexistente.png", "x.exe"]
)
async def test_nome_invalido_ou_inexistente_devolve_none(tmp_path: Path, nome: str) -> None:
    (tmp_path.parent / "segredo.png").write_bytes(b"x")
    assert await ArmazenamentoMidiaDisco(tmp_path).ler(nome) is None
