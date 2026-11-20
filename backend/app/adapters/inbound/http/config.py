"""Rotas REST da configuracao da loja e do checklist de onboarding."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.inbound.http import schemas_config as s
from app.application.config.casos_de_uso import CasosDeUsoConfig
from app.application.config.entradas import (
    EntradaLinhaEstoque,
    EntradaLinhaMapeamento,
    EntradaLinhaTroca,
    EntradaPreco,
    EntradaTaxa,
    EntradaVendedor,
)
from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
    VendedorLoja,
)
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.pagamento import (
    DescontoPix,
    DescontoPixNenhum,
    DescontoPixPercentual,
    DescontoPixValor,
    TabelaTaxas,
)
from app.domain.troca import SEM, DescontoTroca, LinhaTroca, TabelaTroca
from app.domain.valores import Dinheiro
from app.infra.dependencias import get_casos_config, get_session

router = APIRouter(tags=["config"])

Casos = Annotated[CasosDeUsoConfig, Depends(get_casos_config)]
Sessao = Annotated[AsyncSession, Depends(get_session)]


# --- dominio -> schema ------------------------------------------------------------------------


def _perfil_out(p: PerfilLoja) -> s.PerfilSchema:
    return s.PerfilSchema(
        nome_exibicao=p.nome_exibicao,
        tom_de_voz=p.tom_de_voz,
        endereco=p.endereco,
        horarios=dict(p.horarios),
        whatsapp_contato=p.whatsapp_contato,
    )


def _pix(d: DescontoPix) -> tuple[str, Decimal | None]:
    match d:
        case DescontoPixNenhum():
            return "nenhum", None
        case DescontoPixPercentual(percentual=p):
            return "percentual", p
        case DescontoPixValor(valor=v):
            return "valor", v.valor


def _preco_out(c: ConfigPreco) -> s.PrecoSchema:
    tipo, valor = _pix(c.regras.desconto_pix)
    pol: PoliticaDesconto = c.politica
    op: RegraOportunidadeUnica = c.oportunidade
    return s.PrecoSchema(
        max_parcelas=c.regras.max_parcelas,
        repassa_taxa=c.regras.repassa_taxa,
        desconto_pix_tipo=tipo,
        desconto_pix_valor=valor,
        aceita_entrada_mais_cartao=c.regras.aceita_entrada_mais_cartao,
        desconto_teto=pol.teto.valor,
        desconto_degrau=pol.degrau.valor,
        oportunidade_ativa=op.ativa,
        oportunidade_dias_minimos=op.dias_minimos,
        oportunidade_valor=op.valor.valor,
        oportunidade_conta_no_teto=op.conta_no_teto,
    )


def _taxas_out(t: TabelaTaxas) -> s.TaxasSchema:
    itens = sorted(t.taxas.items(), key=lambda kv: (str(kv[0][0]).zfill(2), kv[0][1].value))
    return s.TaxasSchema(
        taxas=[
            s.TaxaSchema(chave=chave, bandeira=bandeira.value, taxa_pct=pct)
            for (chave, bandeira), pct in itens
        ]
    )


def _desc(d: DescontoTroca) -> tuple[Decimal | None, bool]:
    if d is SEM:
        return None, True
    if not isinstance(d, Dinheiro):
        raise TypeError(f"desconto de troca inesperado: {d!r}")
    return d.valor, False


def _linha_troca_out(x: LinhaTroca) -> s.LinhaTrocaSchema:
    tela, tela_sem = _desc(x.desconto_tela)
    traseira, traseira_sem = _desc(x.desconto_traseira)
    carcaca, carcaca_sem = _desc(x.desconto_carcaca)
    bateria, bateria_sem = _desc(x.desconto_bateria)
    return s.LinhaTrocaSchema(
        marca=x.modelo.marca,
        modelo=x.modelo.nome,
        capacidade_gb=int(x.capacidade),
        valor_sem_detalhes=x.valor_sem_detalhes.valor,
        desconto_tela=tela,
        desconto_tela_sem=tela_sem,
        desconto_traseira=traseira,
        desconto_traseira_sem=traseira_sem,
        desconto_carcaca=carcaca,
        desconto_carcaca_sem=carcaca_sem,
        desconto_bateria=bateria,
        desconto_bateria_sem=bateria_sem,
        limite_bateria_pct=x.limite_bateria_pct,
    )


def _troca_out(t: TabelaTroca) -> s.TrocaSchema:
    return s.TrocaSchema(
        tabela_troca=[_linha_troca_out(x) for x in (*t.linhas_apple, *t.linhas_outras_marcas)]
    )


def _estoque_out(linhas: list[LinhaEstoqueLocal]) -> s.EstoqueSchema:
    return s.EstoqueSchema(
        estoque=[
            s.LinhaEstoqueSchema(
                sku=x.sku,
                marca=x.modelo.marca,
                modelo=x.modelo.nome,
                capacidade_gb=int(x.capacidade),
                cor=x.cor,
                condicao=x.condicao.value,
                preco_pix=x.preco_pix.valor,
                quantidade=x.quantidade,
                bateria_pct=x.bateria_pct,
            )
            for x in linhas
        ]
    )


def _mapeamento_out(linhas: list[LinhaMapeamentoSku]) -> s.MapeamentoSchema:
    return s.MapeamentoSchema(
        mapeamento_sku=[
            s.LinhaMapeamentoSchema(
                sku_externo=x.sku_externo,
                marca=x.modelo.marca,
                modelo=x.modelo.nome,
                capacidade_gb=int(x.capacidade),
                cor=x.cor,
                condicao=x.condicao.value,
            )
            for x in linhas
        ]
    )


def _vendedores_out(vendedores: list[VendedorLoja]) -> s.VendedoresSchema:
    return s.VendedoresSchema(
        vendedores=[
            s.VendedorSchema(
                id=v.id,
                nome=v.nome,
                telefone=v.telefone,
                peso_percentual=v.peso_percentual,
                ativo=v.ativo,
            )
            for v in vendedores
        ]
    )


# --- rotas ------------------------------------------------------------------------------------


@router.post("/lojas", status_code=status.HTTP_201_CREATED, response_model=s.LojaOut)
async def criar_loja(corpo: s.LojaIn, casos: Casos, sessao: Sessao) -> s.LojaOut:
    loja_id = await casos.criar_loja(corpo.nome)
    await sessao.commit()
    return s.LojaOut(id=loja_id, nome=corpo.nome.strip())


@router.get("/lojas/{loja_id}/config/perfil", response_model=s.PerfilSchema | None)
async def obter_perfil(loja_id: UUID, casos: Casos) -> s.PerfilSchema | None:
    perfil = await casos.obter_perfil(loja_id)
    return None if perfil is None else _perfil_out(perfil)


@router.put("/lojas/{loja_id}/config/perfil", response_model=s.PerfilSchema)
async def atualizar_perfil(
    loja_id: UUID, corpo: s.PerfilSchema, casos: Casos, sessao: Sessao
) -> s.PerfilSchema:
    perfil = await casos.atualizar_perfil(loja_id, PerfilLoja(**corpo.model_dump()))
    await sessao.commit()
    return _perfil_out(perfil)


@router.get("/lojas/{loja_id}/config/preco", response_model=s.PrecoSchema | None)
async def obter_preco(loja_id: UUID, casos: Casos) -> s.PrecoSchema | None:
    config = await casos.obter_preco(loja_id)
    return None if config is None else _preco_out(config)


@router.put("/lojas/{loja_id}/config/preco", response_model=s.PrecoSchema)
async def atualizar_preco(
    loja_id: UUID, corpo: s.PrecoSchema, casos: Casos, sessao: Sessao
) -> s.PrecoSchema:
    config = await casos.atualizar_preco(loja_id, EntradaPreco(**corpo.model_dump()))
    await sessao.commit()
    return _preco_out(config)


@router.get("/lojas/{loja_id}/config/taxas", response_model=s.TaxasSchema)
async def obter_taxas(loja_id: UUID, casos: Casos) -> s.TaxasSchema:
    return _taxas_out(await casos.obter_taxas(loja_id))


@router.put("/lojas/{loja_id}/config/taxas", response_model=s.TaxasSchema)
async def atualizar_taxas(
    loja_id: UUID, corpo: s.TaxasSchema, casos: Casos, sessao: Sessao
) -> s.TaxasSchema:
    taxas = await casos.atualizar_taxas(
        loja_id, [EntradaTaxa(**t.model_dump()) for t in corpo.taxas]
    )
    await sessao.commit()
    return _taxas_out(taxas)


@router.get("/lojas/{loja_id}/config/troca", response_model=s.TrocaSchema)
async def obter_troca(loja_id: UUID, casos: Casos) -> s.TrocaSchema:
    return _troca_out(await casos.obter_troca(loja_id))


@router.put("/lojas/{loja_id}/config/troca", response_model=s.TrocaSchema)
async def atualizar_troca(
    loja_id: UUID, corpo: s.TrocaSchema, casos: Casos, sessao: Sessao
) -> s.TrocaSchema:
    tabela = await casos.atualizar_troca(
        loja_id, [EntradaLinhaTroca(**x.model_dump()) for x in corpo.tabela_troca]
    )
    await sessao.commit()
    return _troca_out(tabela)


@router.get("/lojas/{loja_id}/config/estoque", response_model=s.EstoqueSchema)
async def obter_estoque(loja_id: UUID, casos: Casos) -> s.EstoqueSchema:
    return _estoque_out(await casos.obter_estoque(loja_id))


@router.put("/lojas/{loja_id}/config/estoque", response_model=s.EstoqueSchema)
async def atualizar_estoque(
    loja_id: UUID, corpo: s.EstoqueSchema, casos: Casos, sessao: Sessao
) -> s.EstoqueSchema:
    linhas = await casos.atualizar_estoque(
        loja_id, [EntradaLinhaEstoque(**x.model_dump()) for x in corpo.estoque]
    )
    await sessao.commit()
    return _estoque_out(linhas)


@router.get("/lojas/{loja_id}/config/mapeamento-sku", response_model=s.MapeamentoSchema)
async def obter_mapeamento(loja_id: UUID, casos: Casos) -> s.MapeamentoSchema:
    return _mapeamento_out(await casos.obter_mapeamento(loja_id))


@router.put("/lojas/{loja_id}/config/mapeamento-sku", response_model=s.MapeamentoSchema)
async def atualizar_mapeamento(
    loja_id: UUID, corpo: s.MapeamentoSchema, casos: Casos, sessao: Sessao
) -> s.MapeamentoSchema:
    linhas = await casos.atualizar_mapeamento(
        loja_id, [EntradaLinhaMapeamento(**x.model_dump()) for x in corpo.mapeamento_sku]
    )
    await sessao.commit()
    return _mapeamento_out(linhas)


@router.get("/lojas/{loja_id}/config/vendedores", response_model=s.VendedoresSchema)
async def obter_vendedores(loja_id: UUID, casos: Casos) -> s.VendedoresSchema:
    return _vendedores_out(await casos.obter_vendedores(loja_id))


@router.put("/lojas/{loja_id}/config/vendedores", response_model=s.VendedoresSchema)
async def atualizar_vendedores(
    loja_id: UUID, corpo: s.VendedoresIn, casos: Casos, sessao: Sessao
) -> s.VendedoresSchema:
    vendedores = await casos.atualizar_vendedores(
        loja_id, [EntradaVendedor(**v.model_dump()) for v in corpo.vendedores]
    )
    await sessao.commit()
    return _vendedores_out(vendedores)


@router.get("/lojas/{loja_id}/onboarding/checklist", response_model=s.ChecklistSchema)
async def checklist(loja_id: UUID, casos: Casos) -> s.ChecklistSchema:
    itens = await casos.checklist(loja_id)
    return s.ChecklistSchema(
        itens=[
            s.ItemChecklistSchema(
                chave=i.chave, rotulo_ptbr=i.rotulo_ptbr, completo=i.completo, detalhe=i.detalhe
            )
            for i in itens
        ]
    )
