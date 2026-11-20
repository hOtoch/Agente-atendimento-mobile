"""Executor em modo fake de ponta a ponta: agente roteirizado + ferramentas e loja demo reais."""

from __future__ import annotations

import json
from pathlib import Path

from evals import rodar
from evals.cenarios import CENARIOS, CONTROLES
from evals.conversa import rodar_cenario_fake
from evals.roteiros import ROTEIROS_FAKE


async def test_exemplo_oficial_chega_na_troca_de_2310() -> None:
    cenario = next(c for c in CENARIOS if c.id == "exemplo_oficial")
    r = await rodar_cenario_fake(cenario)
    assert r.aprovado, [c for c in r.checagens if not c.passou]
    textos = " ".join(m.texto for m in r.transcricao.mensagens_agente)
    assert "R$ 2.310,00" in textos
    assert r.transcricao.etapa_final == "interesse_qualificado"


async def test_controle_com_violacao_proposital_e_pego() -> None:
    controle = CONTROLES[0]
    r = await rodar_cenario_fake(controle)
    assert not r.aprovado
    reprovadas = {c.nome for c in r.checagens if c.aplicavel and not c.passou}
    assert "sem_valor_antes_da_proposta" in reprovadas


async def test_cenarios_roteirizados_reais_passam() -> None:
    for cenario in CENARIOS:
        if cenario.id not in ROTEIROS_FAKE:
            continue
        r = await rodar_cenario_fake(cenario)
        assert r.aprovado, (cenario.id, [c for c in r.checagens if c.aplicavel and not c.passou])


def test_cli_fake_gera_relatorio_md_e_json(tmp_path: Path) -> None:
    codigo = rodar.main(["--modo", "fake", "--saida", str(tmp_path), "--data", "2026-11-20"])
    assert codigo == 0
    md = tmp_path / "2026-11-20-fake-fake.md"
    js = tmp_path / "2026-11-20-fake-fake.json"
    assert md.exists() and js.exists()
    texto = md.read_text(encoding="utf-8")
    assert "Taxa de aprovação" in texto
    assert "controle_preco_sem_ficha" in texto
    assert "Transcrições" in texto
    dados = json.loads(js.read_text(encoding="utf-8"))
    assert dados["modo"] == "fake"
    por_id = {c["id"]: c for c in dados["cenarios"]}
    assert por_id["controle_preco_sem_ficha"]["aprovado"] is False
    assert por_id["controle_preco_sem_ficha"]["deve_reprovar"] is True
    assert por_id["exemplo_oficial"]["aprovado"] is True
    assert "custo" in dados and "tokens_medios" in dados and "taxa_aprovacao" in dados


def test_cli_cenario_desconhecido(tmp_path: Path) -> None:
    assert rodar.main(["--modo", "fake", "--cenarios", "nao_existe", "--saida", str(tmp_path)]) == 2
