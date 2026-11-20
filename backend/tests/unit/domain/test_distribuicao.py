from decimal import Decimal
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.distribuicao import (
    Candidato,
    MotivoSemVendedor,
    SemVendedorDisponivel,
    escolher_vendedor,
)

D = Decimal


def uid(n: int) -> UUID:
    return UUID(int=n)


def cand(n: int, peso: str | int, *, ativo: bool = True, disponivel: bool = True) -> Candidato:
    return Candidato(id=uid(n), peso=D(peso), ativo=ativo, disponivel=disponivel)


def simular(candidatos: list[Candidato], n: int) -> dict[UUID, int]:
    contagem: dict[UUID, int] = {c.id: 0 for c in candidatos}
    for _ in range(n):
        escolhido = escolher_vendedor(candidatos, contagem)
        assert isinstance(escolhido, UUID)
        contagem[escolhido] += 1
    return contagem


def desvio_max_pp(candidatos: list[Candidato], contagem: dict[UUID, int]) -> Decimal:
    total = sum(contagem.values())
    soma = sum(c.peso for c in candidatos if c.ativo and c.disponivel)
    return max(
        abs(D(contagem[c.id]) / total * 100 - c.peso / soma * 100)
        for c in candidatos
        if c.ativo and c.disponivel
    )


def test_mil_leads_50_30_20_desvio_ate_1pp() -> None:
    candidatos = [cand(1, 50), cand(2, 30), cand(3, 20)]
    contagem = simular(candidatos, 1000)
    assert sum(contagem.values()) == 1000
    assert desvio_max_pp(candidatos, contagem) <= 1
    assert contagem == {uid(1): 500, uid(2): 300, uid(3): 200}


def test_primeiro_lead_vai_para_o_maior_peso() -> None:
    assert escolher_vendedor([cand(1, 20), cand(2, 50), cand(3, 30)], {}) == uid(2)


def test_empate_de_deficit_desempata_por_maior_peso_depois_id() -> None:
    # pesos iguais: menor id vence; contagens zeradas
    assert escolher_vendedor([cand(2, 50), cand(1, 50)], {}) == uid(1)
    # 60/40 com 3 e 2 atribuidos: os dois estao exatamente na meta (deficit 0, empate)
    # -> vence o maior peso, mesmo com id maior
    assert escolher_vendedor([cand(1, 40), cand(2, 60)], {uid(1): 2, uid(2): 3}) == uid(2)


def test_ordem_dos_candidatos_nao_importa() -> None:
    a = [cand(1, 50), cand(2, 30), cand(3, 20)]
    contagem = {uid(1): 3, uid(2): 1, uid(3): 0}
    assert escolher_vendedor(a, contagem) == escolher_vendedor(list(reversed(a)), contagem)


def test_inativo_nao_recebe_e_nao_entra_na_conta() -> None:
    candidatos = [cand(1, 50), cand(2, 50, ativo=False), cand(3, 50)]
    contagem = simular(candidatos, 100)
    assert contagem[uid(2)] == 0
    assert contagem[uid(1)] == contagem[uid(3)] == 50


def test_indisponivel_nao_recebe() -> None:
    candidatos = [cand(1, 50), cand(2, 50, disponivel=False)]
    assert simular(candidatos, 10)[uid(2)] == 0


def test_contagem_de_inativo_nao_entra_no_total() -> None:
    # o inativo ja recebeu 100 leads; isso nao deve distorcer a proporcao dos ativos
    candidatos = [cand(1, 50), cand(2, 50), cand(3, 50, ativo=False)]
    contagem = {uid(1): 1, uid(2): 0, uid(3): 100}
    assert escolher_vendedor(candidatos, contagem) == uid(2)


def test_pesos_sao_normalizados_entre_elegiveis() -> None:
    # 5 e 5 (soma 10) comportam-se como 50/50; inativo de 90 nao conta
    candidatos = [cand(1, 5), cand(2, 5), cand(3, 90, ativo=False)]
    contagem = simular(candidatos, 100)
    assert contagem[uid(1)] == contagem[uid(2)] == 50


def test_vendedor_novo_com_contagem_zero_e_ausente_do_mapa() -> None:
    candidatos = [cand(1, 50), cand(2, 50)]
    assert escolher_vendedor(candidatos, {uid(1): 10}) == uid(2)


def test_sem_candidatos() -> None:
    assert escolher_vendedor([], {}) == SemVendedorDisponivel(MotivoSemVendedor.SEM_CANDIDATOS)


def test_todos_inativos_ou_indisponiveis() -> None:
    r = escolher_vendedor([cand(1, 50, ativo=False), cand(2, 50, disponivel=False)], {})
    assert r == SemVendedorDisponivel(MotivoSemVendedor.NENHUM_ATIVO_DISPONIVEL)


def test_pesos_zerados_nao_recebem() -> None:
    assert escolher_vendedor([cand(1, 0), cand(2, 0)], {}) == SemVendedorDisponivel(
        MotivoSemVendedor.PESOS_ZERADOS
    )
    # peso 0 ao lado de peso positivo: nunca recebe
    assert simular([cand(1, 0), cand(2, 100)], 20)[uid(1)] == 0


def test_mudanca_de_peso_afeta_so_os_proximos() -> None:
    antes = [cand(1, 50), cand(2, 50)]
    contagem = simular(antes, 100)
    assert contagem == {uid(1): 50, uid(2): 50}
    # a historia fica; a partir de agora 80/20: o 1 deve receber mais ate alcancar a nova meta
    depois = [cand(1, 80), cand(2, 20)]
    for _ in range(100):
        e = escolher_vendedor(depois, contagem)
        assert isinstance(e, UUID)
        contagem[e] += 1
    assert contagem[uid(1)] > contagem[uid(2)]
    # os 100 primeiros nao foram reescritos
    assert contagem[uid(1)] + contagem[uid(2)] == 200


@st.composite
def pesos_somando_100(draw: st.DrawFn) -> list[int]:
    k = draw(st.integers(min_value=1, max_value=6))
    cortes = sorted(draw(st.lists(st.integers(1, 99), min_size=k - 1, max_size=k - 1, unique=True)))
    pontos = [0, *cortes, 100]
    return [b - a for a, b in zip(pontos, pontos[1:], strict=False)]


@settings(max_examples=60, deadline=None)
@given(pesos=pesos_somando_100())
def test_hypothesis_desvio_pequeno_com_n_grande(pesos: list[int]) -> None:
    candidatos = [cand(i + 1, p) for i, p in enumerate(pesos)]
    contagem = simular(candidatos, 1000)
    assert desvio_max_pp(candidatos, contagem) <= 1


@settings(max_examples=60, deadline=None)
@given(
    pesos=pesos_somando_100(),
    inativos=st.lists(st.booleans(), min_size=6, max_size=6),
)
def test_hypothesis_inativo_nunca_recebe(pesos: list[int], inativos: list[bool]) -> None:
    candidatos = [cand(i + 1, p, ativo=not inativos[i]) for i, p in enumerate(pesos)]
    contagem: dict[UUID, int] = {c.id: 0 for c in candidatos}
    for _ in range(200):
        e = escolher_vendedor(candidatos, contagem)
        if isinstance(e, SemVendedorDisponivel):
            assert not any(c.ativo for c in candidatos)
            return
        assert next(c for c in candidatos if c.id == e).ativo
        contagem[e] += 1
