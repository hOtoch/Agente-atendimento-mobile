"""Repositorios Postgres da configuracao da loja (linhas <-> objetos de dominio).

SEM (tabela de troca): coluna `desconto_<x>` NULL + `desconto_<x>_sem` = true.
"igual" (taxas): linha com `taxa_pct` NULL. Ambos voltam identicos ao que foi gravado.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.outbound.db.models import (
    EstoqueLocalRow,
    Loja,
    MapeamentoSkuRow,
    PerfilLojaRow,
    RegrasPrecoRow,
    TaxaRow,
    TrocaRow,
    Vendedor,
)
from app.application.config.entradas import EntradaVendedor
from app.application.config.modelos import (
    ConfigPreco,
    LinhaEstoqueLocal,
    LinhaMapeamentoSku,
    PerfilLoja,
    VendedorLoja,
)
from app.domain.bandeira import Bandeira
from app.domain.desconto import PoliticaDesconto, RegraOportunidadeUnica
from app.domain.estoque import Condicao
from app.domain.pagamento import (
    DEBITO,
    ChaveTaxa,
    DescontoPix,
    DescontoPixNenhum,
    DescontoPixPercentual,
    DescontoPixValor,
    RegrasPreco,
    TabelaTaxas,
)
from app.domain.troca import SEM, DescontoTroca, LinhaTroca, TabelaTroca
from app.domain.valores import Capacidade, Dinheiro, ModeloAparelho

_MARCA_APPLE = "Apple"


class RepositorioLojasSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def criar(self, nome: str) -> uuid.UUID:
        loja = Loja(nome=nome)
        self._s.add(loja)
        await self._s.flush()
        return loja.id

    async def existe(self, loja_id: uuid.UUID) -> bool:
        return (await self._s.get(Loja, loja_id)) is not None


# --- config (perfil, preco, taxas, troca) -----------------------------------------------------


def _pix_para_colunas(d: DescontoPix) -> tuple[str, Decimal | None]:
    match d:
        case DescontoPixNenhum():
            return "nenhum", None
        case DescontoPixPercentual(percentual=p):
            return "percentual", p
        case DescontoPixValor(valor=v):
            return "valor", v.valor


def _pix_de_colunas(tipo: str, valor: Decimal | None) -> DescontoPix:
    if tipo == "percentual" and valor is not None:
        return DescontoPixPercentual(valor)
    if tipo == "valor" and valor is not None:
        return DescontoPixValor(Dinheiro(valor))
    return DescontoPixNenhum()


def _chave_de_texto(chave: str) -> ChaveTaxa:
    return DEBITO if chave == DEBITO else int(chave)


def _desc_para_colunas(d: DescontoTroca) -> tuple[Decimal | None, bool]:
    if d is SEM:
        return None, True
    assert isinstance(d, Dinheiro)
    return d.valor, False


def _desc_de_colunas(valor: Decimal | None, sem: bool) -> DescontoTroca:
    if sem or valor is None:
        return SEM
    return Dinheiro(valor)


def _linha_troca_para_row(loja_id: uuid.UUID, posicao: int, linha: LinhaTroca) -> TrocaRow:
    tela, tela_sem = _desc_para_colunas(linha.desconto_tela)
    traseira, traseira_sem = _desc_para_colunas(linha.desconto_traseira)
    carcaca, carcaca_sem = _desc_para_colunas(linha.desconto_carcaca)
    bateria, bateria_sem = _desc_para_colunas(linha.desconto_bateria)
    return TrocaRow(
        loja_id=loja_id,
        posicao=posicao,
        marca=linha.modelo.marca,
        modelo=linha.modelo.nome,
        capacidade_gb=int(linha.capacidade),
        valor_sem_detalhes=linha.valor_sem_detalhes.valor,
        desconto_tela=tela,
        desconto_tela_sem=tela_sem,
        desconto_traseira=traseira,
        desconto_traseira_sem=traseira_sem,
        desconto_carcaca=carcaca,
        desconto_carcaca_sem=carcaca_sem,
        desconto_bateria=bateria,
        desconto_bateria_sem=bateria_sem,
        limite_bateria_pct=linha.limite_bateria_pct,
    )


def _row_para_linha_troca(r: TrocaRow) -> LinhaTroca:
    return LinhaTroca(
        modelo=ModeloAparelho.de(r.modelo, r.marca),
        capacidade=Capacidade(r.capacidade_gb),
        valor_sem_detalhes=Dinheiro(r.valor_sem_detalhes),
        desconto_tela=_desc_de_colunas(r.desconto_tela, r.desconto_tela_sem),
        desconto_traseira=_desc_de_colunas(r.desconto_traseira, r.desconto_traseira_sem),
        desconto_carcaca=_desc_de_colunas(r.desconto_carcaca, r.desconto_carcaca_sem),
        desconto_bateria=_desc_de_colunas(r.desconto_bateria, r.desconto_bateria_sem),
        limite_bateria_pct=r.limite_bateria_pct,
    )


class RepositorioConfigLojaSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def obter_perfil(self, loja_id: uuid.UUID) -> PerfilLoja | None:
        r = await self._s.get(PerfilLojaRow, loja_id, populate_existing=True)
        if r is None:
            return None
        return PerfilLoja(
            nome_exibicao=r.nome_exibicao,
            tom_de_voz=r.tom_de_voz,
            endereco=r.endereco,
            horarios={str(k): str(v) for k, v in r.horarios.items()},
            whatsapp_contato=r.whatsapp_contato,
            responder_em_audio=r.responder_em_audio,
        )

    async def salvar_perfil(self, loja_id: uuid.UUID, perfil: PerfilLoja) -> None:
        r = await self._s.get(PerfilLojaRow, loja_id)
        if r is None:
            r = PerfilLojaRow(loja_id=loja_id)
            self._s.add(r)
        r.nome_exibicao = perfil.nome_exibicao
        r.tom_de_voz = perfil.tom_de_voz
        r.endereco = perfil.endereco
        r.horarios = dict(perfil.horarios)
        r.whatsapp_contato = perfil.whatsapp_contato
        r.responder_em_audio = perfil.responder_em_audio
        await self._s.flush()

    async def obter_config_preco(self, loja_id: uuid.UUID) -> ConfigPreco | None:
        r = await self._s.get(RegrasPrecoRow, loja_id, populate_existing=True)
        if r is None:
            return None
        return ConfigPreco(
            RegrasPreco(
                max_parcelas=r.max_parcelas,
                repassa_taxa=r.repassa_taxa,
                desconto_pix=_pix_de_colunas(r.desconto_pix_tipo, r.desconto_pix_valor),
                aceita_entrada_mais_cartao=r.aceita_entrada_mais_cartao,
            ),
            PoliticaDesconto(teto=Dinheiro(r.desconto_teto), degrau=Dinheiro(r.desconto_degrau)),
            RegraOportunidadeUnica(
                ativa=r.oportunidade_ativa,
                dias_minimos=r.oportunidade_dias_minimos,
                valor=Dinheiro(r.oportunidade_valor),
                conta_no_teto=r.oportunidade_conta_no_teto,
            ),
        )

    async def salvar_config_preco(self, loja_id: uuid.UUID, config: ConfigPreco) -> None:
        r = await self._s.get(RegrasPrecoRow, loja_id)
        if r is None:
            r = RegrasPrecoRow(loja_id=loja_id)
            self._s.add(r)
        tipo, valor = _pix_para_colunas(config.regras.desconto_pix)
        r.max_parcelas = config.regras.max_parcelas
        r.repassa_taxa = config.regras.repassa_taxa
        r.desconto_pix_tipo = tipo
        r.desconto_pix_valor = valor
        r.aceita_entrada_mais_cartao = config.regras.aceita_entrada_mais_cartao
        r.desconto_teto = config.politica.teto.valor
        r.desconto_degrau = config.politica.degrau.valor
        r.oportunidade_ativa = config.oportunidade.ativa
        r.oportunidade_dias_minimos = config.oportunidade.dias_minimos
        r.oportunidade_valor = config.oportunidade.valor.valor
        r.oportunidade_conta_no_teto = config.oportunidade.conta_no_teto
        await self._s.flush()

    async def obter_taxas(self, loja_id: uuid.UUID) -> TabelaTaxas:
        rows = (
            await self._s.execute(
                select(TaxaRow)
                .where(TaxaRow.loja_id == loja_id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return TabelaTaxas(
            {(_chave_de_texto(r.chave), Bandeira(r.bandeira)): r.taxa_pct for r in rows}
        )

    async def salvar_taxas(self, loja_id: uuid.UUID, taxas: TabelaTaxas) -> None:
        await self._s.execute(delete(TaxaRow).where(TaxaRow.loja_id == loja_id))
        self._s.add_all(
            TaxaRow(loja_id=loja_id, chave=str(chave), bandeira=bandeira.value, taxa_pct=pct)
            for (chave, bandeira), pct in taxas.taxas.items()
        )
        await self._s.flush()

    async def obter_tabela_troca(self, loja_id: uuid.UUID) -> TabelaTroca:
        rows = (
            await self._s.execute(
                select(TrocaRow)
                .where(TrocaRow.loja_id == loja_id)
                .order_by(TrocaRow.posicao)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        apple: list[LinhaTroca] = []
        outras: list[LinhaTroca] = []
        for r in rows:
            (apple if r.marca == _MARCA_APPLE else outras).append(_row_para_linha_troca(r))
        return TabelaTroca(linhas_apple=tuple(apple), linhas_outras_marcas=tuple(outras))

    async def salvar_tabela_troca(self, loja_id: uuid.UUID, tabela: TabelaTroca) -> None:
        await self._s.execute(delete(TrocaRow).where(TrocaRow.loja_id == loja_id))
        linhas = [*tabela.linhas_apple, *tabela.linhas_outras_marcas]
        self._s.add_all(_linha_troca_para_row(loja_id, i, linha) for i, linha in enumerate(linhas))
        await self._s.flush()


# --- estoque local e mapeamento ---------------------------------------------------------------


class RepositorioEstoqueLocalSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def listar(self, loja_id: uuid.UUID) -> list[LinhaEstoqueLocal]:
        rows = (
            await self._s.execute(
                select(EstoqueLocalRow)
                .where(EstoqueLocalRow.loja_id == loja_id)
                .order_by(EstoqueLocalRow.posicao)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [
            LinhaEstoqueLocal(
                sku=r.sku,
                modelo=ModeloAparelho.de(r.modelo, r.marca),
                capacidade=Capacidade(r.capacidade_gb),
                cor=r.cor,
                condicao=Condicao(r.condicao),
                preco_pix=Dinheiro(r.preco_pix),
                quantidade=r.quantidade,
                bateria_pct=r.bateria_pct,
                erp_produto_id=r.erp_produto_id,
            )
            for r in rows
        ]

    async def substituir(self, loja_id: uuid.UUID, linhas: Sequence[LinhaEstoqueLocal]) -> None:
        # serializa trocas concorrentes do estoque da loja (cron x "sincronizar agora" x planilha):
        # a segunda espera o commit da primeira em vez de bater na constraint loja_sku
        await self._s.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"estoque_local:{loja_id}", 0)))
        )
        await self._s.execute(delete(EstoqueLocalRow).where(EstoqueLocalRow.loja_id == loja_id))
        self._s.add_all(
            EstoqueLocalRow(
                loja_id=loja_id,
                posicao=i,
                sku=x.sku,
                modelo=x.modelo.nome,
                marca=x.modelo.marca,
                capacidade_gb=int(x.capacidade),
                cor=x.cor,
                condicao=x.condicao.value,
                preco_pix=x.preco_pix.valor,
                quantidade=x.quantidade,
                bateria_pct=x.bateria_pct,
                erp_produto_id=x.erp_produto_id,
            )
            for i, x in enumerate(linhas)
        )
        await self._s.flush()


class RepositorioMapeamentoSkuSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def listar(self, loja_id: uuid.UUID) -> list[LinhaMapeamentoSku]:
        rows = (
            await self._s.execute(
                select(MapeamentoSkuRow)
                .where(MapeamentoSkuRow.loja_id == loja_id)
                .order_by(MapeamentoSkuRow.posicao)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [
            LinhaMapeamentoSku(
                sku_externo=r.sku_externo,
                modelo=ModeloAparelho.de(r.modelo, r.marca),
                capacidade=Capacidade(r.capacidade_gb),
                cor=r.cor,
                condicao=Condicao(r.condicao),
            )
            for r in rows
        ]

    async def substituir(self, loja_id: uuid.UUID, linhas: Sequence[LinhaMapeamentoSku]) -> None:
        await self._s.execute(delete(MapeamentoSkuRow).where(MapeamentoSkuRow.loja_id == loja_id))
        self._s.add_all(
            MapeamentoSkuRow(
                loja_id=loja_id,
                posicao=i,
                sku_externo=x.sku_externo,
                modelo=x.modelo.nome,
                marca=x.modelo.marca,
                capacidade_gb=int(x.capacidade),
                cor=x.cor,
                condicao=x.condicao.value,
            )
            for i, x in enumerate(linhas)
        )
        await self._s.flush()


class LeitorVendedoresSql:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def pesos_ativos(self, loja_id: uuid.UUID) -> list[Decimal]:
        rows = await self._s.execute(
            select(Vendedor.peso_percentual).where(
                Vendedor.loja_id == loja_id, Vendedor.ativo.is_(True)
            )
        )
        return [p for (p,) in rows]


def _vendedor_de_row(r: Vendedor) -> VendedorLoja:
    return VendedorLoja(r.id, r.nome, r.telefone, r.peso_percentual, r.ativo, r.codigo_erp)


class RepositorioVendedoresSql(LeitorVendedoresSql):
    async def listar(self, loja_id: uuid.UUID) -> list[VendedorLoja]:
        rows = (
            await self._s.execute(
                select(Vendedor)
                .where(Vendedor.loja_id == loja_id)
                .order_by(Vendedor.criado_em, Vendedor.nome, Vendedor.id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [_vendedor_de_row(r) for r in rows]

    async def substituir(
        self, loja_id: uuid.UUID, entradas: Sequence[EntradaVendedor]
    ) -> list[VendedorLoja]:
        existentes = {
            r.id: r
            for r in (
                await self._s.execute(
                    select(Vendedor)
                    .where(Vendedor.loja_id == loja_id)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        }
        mantidos: set[uuid.UUID] = set()
        base = datetime.now(UTC)
        for i, e in enumerate(entradas):
            row = existentes.get(e.id) if e.id is not None else None
            if row is None:
                # criado_em crescente preserva a ordem da lista
                row = Vendedor(loja_id=loja_id, criado_em=base + timedelta(microseconds=i))
                self._s.add(row)
            row.nome = e.nome.strip()
            row.telefone = (e.telefone or "").strip() or None
            row.peso_percentual = e.peso_percentual
            row.ativo = e.ativo
            await self._s.flush()
            mantidos.add(row.id)
        # ausentes saem da distribuicao, sem apagar: leads e conversas referenciam o vendedor
        for vid, row in existentes.items():
            if vid not in mantidos:
                row.ativo = False
        await self._s.flush()
        return await self.listar(loja_id)

    async def criar_do_erp(self, loja_id: uuid.UUID, codigo_erp: str, nome: str) -> VendedorLoja:
        row = Vendedor(
            loja_id=loja_id,
            nome=nome.strip(),
            codigo_erp=codigo_erp,
            peso_percentual=Decimal(0),
            ativo=True,
            criado_em=datetime.now(UTC),
        )
        self._s.add(row)
        await self._s.flush()
        return _vendedor_de_row(row)

    async def atualizar_do_erp(
        self, loja_id: uuid.UUID, vendedor_id: uuid.UUID, *, nome: str, ativo: bool
    ) -> None:
        row = (
            await self._s.execute(
                select(Vendedor)
                .where(Vendedor.id == vendedor_id, Vendedor.loja_id == loja_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.nome = nome.strip()
        row.ativo = ativo
        await self._s.flush()
