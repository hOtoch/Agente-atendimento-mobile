from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.config.entradas import EntradaVendedor
from app.application.config.memoria import MemoriaVendedores
from app.application.distribuicao_memoria import MemoriaAtribuicoes
from app.application.distribuir_lead import DistribuirLead, LeadNaoEncontrado
from app.domain.distribuicao import MotivoSemVendedor, SemVendedorDisponivel

D = Decimal


def entrada(vid: UUID | None, nome: str, peso: str, *, ativo: bool = True) -> EntradaVendedor:
    return EntradaVendedor(id=vid, nome=nome, telefone=None, peso_percentual=D(peso), ativo=ativo)


class Cenario:
    def __init__(self) -> None:
        self.loja = uuid4()
        self.vendedores = MemoriaVendedores()
        self.atribuicoes = MemoriaAtribuicoes()
        self.caso = DistribuirLead(self.vendedores, self.atribuicoes)

    async def configurar(self, *entradas: EntradaVendedor) -> list[UUID]:
        lista = await self.vendedores.substituir(self.loja, entradas)
        return [v.id for v in lista]

    def novo_lead(self) -> UUID:
        return self.atribuicoes.criar_lead(self.loja)


async def test_distribui_conforme_os_pesos() -> None:
    c = Cenario()
    a, b = await c.configurar(entrada(None, "A", "75"), entrada(None, "B", "25"))
    for _ in range(100):
        r = await c.caso.executar(c.loja, c.novo_lead())
        assert isinstance(r, UUID)
    cont = c.atribuicoes.contagem(c.loja)
    assert cont == {a: 75, b: 25}


async def test_grava_o_vendedor_no_lead() -> None:
    c = Cenario()
    (a,) = await c.configurar(entrada(None, "A", "100"))
    lead = c.novo_lead()
    assert await c.caso.executar(c.loja, lead) == a
    assert c.atribuicoes.vendedor_do_lead(lead) == a


async def test_inativo_nao_recebe() -> None:
    c = Cenario()
    a, b = await c.configurar(entrada(None, "A", "50"), entrada(None, "B", "50", ativo=False))
    for _ in range(20):
        assert await c.caso.executar(c.loja, c.novo_lead()) == a
    assert b not in c.atribuicoes.contagem(c.loja)


async def test_sem_vendedor_disponivel_devolve_resultado_tipado() -> None:
    c = Cenario()
    lead = c.novo_lead()
    r = await c.caso.executar(c.loja, lead)
    assert r == SemVendedorDisponivel(MotivoSemVendedor.SEM_CANDIDATOS)
    assert c.atribuicoes.vendedor_do_lead(lead) is None

    await c.configurar(entrada(None, "A", "50", ativo=False))
    r = await c.caso.executar(c.loja, lead)
    assert r == SemVendedorDisponivel(MotivoSemVendedor.NENHUM_ATIVO_DISPONIVEL)


async def test_idempotente_lead_com_vendedor_mantem() -> None:
    c = Cenario()
    await c.configurar(entrada(None, "A", "50"), entrada(None, "B", "50"))
    lead = c.novo_lead()
    primeiro = await c.caso.executar(c.loja, lead)
    for _ in range(5):
        assert await c.caso.executar(c.loja, lead) == primeiro
    assert sum(c.atribuicoes.contagem(c.loja).values()) == 1


async def test_lead_ja_atribuido_mantem_mesmo_com_vendedor_inativo_depois() -> None:
    c = Cenario()
    a, b = await c.configurar(entrada(None, "A", "100"), entrada(None, "B", "0"))
    lead = c.novo_lead()
    assert await c.caso.executar(c.loja, lead) == a
    await c.configurar(entrada(a, "A", "100", ativo=False), entrada(b, "B", "100"))
    assert await c.caso.executar(c.loja, lead) == a


async def test_mudanca_de_peso_afeta_so_os_proximos() -> None:
    c = Cenario()
    a, b = await c.configurar(entrada(None, "A", "50"), entrada(None, "B", "50"))
    leads_antes = [c.novo_lead() for _ in range(100)]
    for lead in leads_antes:
        await c.caso.executar(c.loja, lead)
    atribuicao_antes = {lead: c.atribuicoes.vendedor_do_lead(lead) for lead in leads_antes}

    await c.configurar(entrada(a, "A", "90"), entrada(b, "B", "10"))
    for _ in range(100):
        await c.caso.executar(c.loja, c.novo_lead())

    # historico intacto
    assert {lead: c.atribuicoes.vendedor_do_lead(lead) for lead in leads_antes} == atribuicao_antes
    # os 100 novos seguem o novo peso: 90/10 sobre o total de 200 -> A=180, B=20? nao:
    # o deficit corrige a meta global, entao A recebe todos os novos ate alcancar
    cont = c.atribuicoes.contagem(c.loja)
    assert cont[a] > cont[b]
    assert cont[a] + cont[b] == 200


async def test_pesos_sao_lidos_a_cada_chamada() -> None:
    c = Cenario()
    a, b = await c.configurar(entrada(None, "A", "100"), entrada(None, "B", "0"))
    assert await c.caso.executar(c.loja, c.novo_lead()) == a
    await c.configurar(entrada(a, "A", "0"), entrada(b, "B", "100"))
    assert await c.caso.executar(c.loja, c.novo_lead()) == b


async def test_lead_inexistente() -> None:
    c = Cenario()
    await c.configurar(entrada(None, "A", "100"))
    with pytest.raises(LeadNaoEncontrado):
        await c.caso.executar(c.loja, uuid4())


async def test_trava_da_loja_e_tomada_antes_de_ler() -> None:
    c = Cenario()
    await c.configurar(entrada(None, "A", "100"))
    await c.caso.executar(c.loja, c.novo_lead())
    assert c.atribuicoes.lojas_travadas == [c.loja]
