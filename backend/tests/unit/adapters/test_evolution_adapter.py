"""EvolutionAdapter (CanalPort do WhatsApp) sobre um gateway falso."""

from __future__ import annotations

import base64
from uuid import UUID

import pytest

from app.adapters.outbound.canal.enviadas import RegistroEnviadasMemoria
from app.adapters.outbound.canal.evolution import EvolutionAdapter
from app.application.canal import Canal, CanalPort, MensagemSaida, TipoMensagem
from app.application.midia import ConteudoMidia

LOJA = UUID("00000000-0000-4000-8000-00000000de30")
NUMERO = "5511987654321"


class GatewayFalso:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"ID{self._n}"

    async def enviar_texto(self, loja_id: UUID, numero: str, texto: str) -> str | None:
        self.chamadas.append(("texto", (loja_id, numero, texto), {}))
        return self._id()

    async def enviar_audio(self, loja_id: UUID, numero: str, audio: str) -> str | None:
        self.chamadas.append(("audio", (loja_id, numero, audio), {}))
        return self._id()

    async def enviar_imagem(
        self,
        loja_id: UUID,
        numero: str,
        imagem: str,
        legenda: str | None = None,
        tipo_mime: str = "image/jpeg",
    ) -> str | None:
        self.chamadas.append(
            ("imagem", (loja_id, numero, imagem), {"legenda": legenda, "tipo_mime": tipo_mime})
        )
        return self._id()

    async def digitando(self, loja_id: UUID, numero: str, duracao_ms: int = 1500) -> None:
        self.chamadas.append(("digitando", (loja_id, numero), {"duracao_ms": duracao_ms}))


class ArmazenamentoFalso:
    async def salvar(self, dados: bytes, tipo_mime: str) -> str:
        raise NotImplementedError

    async def ler(self, nome: str) -> ConteudoMidia | None:
        if nome == "a" * 32 + ".png":
            return ConteudoMidia(b"pngbytes", "image/png")
        return None


def _msg(
    tipo: TipoMensagem, texto: str | None = None, midia_url: str | None = None
) -> MensagemSaida:
    return MensagemSaida(
        loja_id=LOJA,
        canal=Canal.WHATSAPP,
        destinatario=NUMERO,
        tipo=tipo,
        texto=texto,
        midia_url=midia_url,
    )


@pytest.fixture
def gateway() -> GatewayFalso:
    return GatewayFalso()


@pytest.fixture
def registro() -> RegistroEnviadasMemoria:
    return RegistroEnviadasMemoria()


@pytest.fixture
def adapter(gateway: GatewayFalso, registro: RegistroEnviadasMemoria) -> EvolutionAdapter:
    return EvolutionAdapter(
        gateway,
        registro,
        armazenamento=ArmazenamentoFalso(),
        base_midia="http://api.local",
    )


def test_implementa_canal_port(adapter: EvolutionAdapter) -> None:
    canal: CanalPort = adapter
    assert canal is adapter


async def test_envia_texto_e_registra_o_id_para_ignorar_o_eco(
    adapter: EvolutionAdapter, gateway: GatewayFalso, registro: RegistroEnviadasMemoria
) -> None:
    await adapter.enviar(_msg(TipoMensagem.TEXTO, "Oi!"))
    assert gateway.chamadas == [("texto", (LOJA, NUMERO, "Oi!"), {})]
    assert await registro.foi_enviada(LOJA, "ID1")


async def test_envia_audio_por_url_externa(
    adapter: EvolutionAdapter, gateway: GatewayFalso
) -> None:
    await adapter.enviar(_msg(TipoMensagem.AUDIO, midia_url="https://cdn.exemplo.com/a.ogg"))
    assert gateway.chamadas == [("audio", (LOJA, NUMERO, "https://cdn.exemplo.com/a.ogg"), {})]


async def test_envia_imagem_nossa_como_base64_com_legenda(
    adapter: EvolutionAdapter, gateway: GatewayFalso
) -> None:
    url = f"http://api.local/midias/{'a' * 32}.png"
    await adapter.enviar(_msg(TipoMensagem.IMAGEM, "Olha esse", url))
    (nome, args, extra) = gateway.chamadas[0]
    assert nome == "imagem"
    assert args[2] == base64.b64encode(b"pngbytes").decode()
    assert extra == {"legenda": "Olha esse", "tipo_mime": "image/png"}


async def test_imagem_nossa_que_sumiu_do_disco_cai_na_url(
    adapter: EvolutionAdapter, gateway: GatewayFalso
) -> None:
    url = f"http://api.local/midias/{'b' * 32}.png"
    await adapter.enviar(_msg(TipoMensagem.IMAGEM, None, url))
    assert gateway.chamadas[0][1][2] == url


@pytest.mark.parametrize(
    "msg",
    [_msg(TipoMensagem.TEXTO, None), _msg(TipoMensagem.AUDIO), _msg(TipoMensagem.IMAGEM)],
)
async def test_mensagem_sem_conteudo_e_erro(adapter: EvolutionAdapter, msg: MensagemSaida) -> None:
    with pytest.raises(ValueError):
        await adapter.enviar(msg)


async def test_indicador_de_digitando(adapter: EvolutionAdapter, gateway: GatewayFalso) -> None:
    await adapter.digitando(LOJA, NUMERO)
    assert gateway.chamadas[0][0] == "digitando"
    assert gateway.chamadas[0][1] == (LOJA, NUMERO)
