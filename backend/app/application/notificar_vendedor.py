"""Gancho do handoff: distribui o lead, atribui o vendedor como dono e o avisa no WhatsApp.

Fluxo de `NotificarVendedorNoHandoff.handoff_solicitado` (chamado depois que a conversa ficou
"aguardando vendedor"):

1. Numa transacao PROPRIA e curta (`abrir`): `DistribuirLead` escolhe o vendedor pela proporcao
   da loja e `definir_dono` o torna dono da conversa; o commit libera a trava da loja.
2. So depois da transacao fechada: publica `DonoMudou` (card e inbox mostram quem atende) e envia
   o resumo + link do painel ao WhatsApp do vendedor. Nunca ha chamada HTTP segurando a trava.

Toda falha aqui e tipada e nao fatal: sem vendedor disponivel o lead segue "aguardando
vendedor"; vendedor sem telefone ou WhatsApp fora do ar nao desfazem a atribuicao.
Nada de valor monetario e decidido aqui: o texto so formata o que o resumo ja trouxe.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.application.canal import Canal
from app.application.distribuir_lead import DistribuirLead, ListaVendedores
from app.application.handoff import ResumoHandoff
from app.application.painel.eventos import EventoDonoMudou
from app.application.painel.portas import DONO_VENDEDOR, RepositorioPainel
from app.application.painel.publicador import PublicadorPainel, publicar_sem_falhar
from app.application.whatsapp import RegistroEnviadas, WhatsAppGateway
from app.domain.distribuicao import SemVendedorDisponivel

log = logging.getLogger(__name__)

_DDI_BRASIL = "55"
_CENTAVOS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ServicosDaDistribuicao:
    """O que a transacao do gancho precisa, todos sobre a MESMA sessao."""

    distribuir: DistribuirLead
    repo: RepositorioPainel
    vendedores: ListaVendedores


AbrirServicos = Callable[[], AbstractAsyncContextManager[ServicosDaDistribuicao]]
"""Abre uma transacao: commita ao sair com sucesso, faz rollback se levantar excecao."""


def formatar_brl(valor: Decimal) -> str:
    arredondado = valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP)
    americano = f"{arredondado:,.2f}"
    return "R$ " + americano.replace(",", "_").replace(".", ",").replace("_", ".")


def numero_whatsapp(telefone: str | None) -> str | None:
    """So digitos com DDI (assume Brasil para numero com DDD e sem DDI); None se nao der."""
    digitos = re.sub(r"\D", "", telefone or "")
    if len(digitos) in (10, 11):
        return _DDI_BRASIL + digitos
    return digitos if len(digitos) >= 12 else None


def montar_mensagem_vendedor(
    *,
    lead_id: UUID,
    lead_nome: str | None,
    lead_telefone: str,
    canal: Canal,
    resumo: ResumoHandoff,
    url_painel: str,
) -> str:
    linhas = ["Novo cliente esperando atendimento.", ""]
    linhas.append(f"Cliente: {lead_nome or 'sem nome'}")
    contato = re.sub(r"\D", "", lead_telefone)
    if canal is Canal.WHATSAPP and contato:
        linhas.append(f"Contato: +{contato}")
    linhas.append(f"Motivo: {resumo.motivo}")
    linhas.extend(_linhas_do_resumo(resumo))
    linhas += ["", f"Abrir no painel: {url_painel.rstrip('/')}/conversas?lead={lead_id}"]
    return "\n".join(linhas)


def _linhas_do_resumo(resumo: ResumoHandoff) -> list[str]:
    """Corpo do aviso (do aparelho as observacoes); so formata o que o resumo ja trouxe."""
    linhas: list[str] = []
    if resumo.aparelho_desejado:
        detalhes = [resumo.aparelho_desejado] + ([resumo.cor] if resumo.cor else [])
        sku = f" (SKU {resumo.sku})" if resumo.sku else ""
        linhas.append("Aparelho: " + ", ".join(detalhes) + sku)
    linhas.extend(_linhas_da_troca(resumo))
    linhas.extend(_linhas_da_proposta(resumo))
    if resumo.forma_pagamento:
        linhas.append(f"Pagamento: {resumo.forma_pagamento}")
    if resumo.data_prevista:
        linhas.append(f"Data prevista: {resumo.data_prevista:%d/%m/%Y}")
    if resumo.pendencias:
        linhas.append("Pendências: " + ", ".join(resumo.pendencias))
    if resumo.ultimas_mensagens_cliente:
        linhas.append("Últimas mensagens do cliente:")
        linhas.extend(f'- "{fala}"' for fala in resumo.ultimas_mensagens_cliente)
    if resumo.observacoes:
        linhas.append(f"Observações: {resumo.observacoes}")
    return linhas


def _linhas_da_troca(resumo: ResumoHandoff) -> list[str]:
    if not resumo.troca:
        return []
    texto = resumo.troca + (f" ({resumo.troca_condicao})" if resumo.troca_condicao else "")
    if resumo.valor_troca:
        texto += f" - avaliada em {formatar_brl(resumo.valor_troca)}"
    elif resumo.troca_status == "avaliacao_na_loja":
        texto += " - avaliação na loja"
    return [f"Troca: {texto}"]


def _linhas_da_proposta(resumo: ResumoHandoff) -> list[str]:
    if not (resumo.proposta or resumo.valor_proposta is not None):
        return []
    total = f"total {_valor(resumo.valor_proposta)}" if resumo.valor_proposta is not None else None
    partes = [p for p in (resumo.proposta, total) if p]
    texto = " - ".join(partes)
    if resumo.parcelas and resumo.valor_parcela is not None:
        texto += f" ({resumo.parcelas}x de {formatar_brl(resumo.valor_parcela)})"
    linhas = [f"Proposta: {texto}"]
    if resumo.valor_aparelho is not None:
        valores = [
            ("aparelho", resumo.valor_aparelho),
            ("troca", resumo.valor_troca),
            ("desconto", resumo.desconto),
        ]
        linhas.append(
            "Valores: " + ", ".join(f"{r} {formatar_brl(v)}" for r, v in valores if v is not None)
        )
    return linhas


def _valor(valor: Decimal | None) -> str | None:
    return None if valor is None else formatar_brl(valor)


class NotificarVendedorNoHandoff:
    """Implementa `AoSolicitarHandoff`."""

    def __init__(
        self,
        *,
        abrir: AbrirServicos,
        gateway: WhatsAppGateway,
        registro: RegistroEnviadas,
        publicador: PublicadorPainel,
        url_painel: str,
    ) -> None:
        self._abrir = abrir
        self._gateway = gateway
        self._registro = registro
        self._publicador = publicador
        self._url_painel = url_painel

    async def handoff_solicitado(self, loja_id: UUID, lead_id: UUID, resumo: ResumoHandoff) -> None:
        async with self._abrir() as s:
            lead = await s.repo.obter_lead(loja_id, lead_id)
            if lead is None:
                log.warning("handoff do lead %s: lead nao encontrado na loja %s", lead_id, loja_id)
                return
            if lead.dono == DONO_VENDEDOR and lead.vendedor_id is not None:
                log.info("handoff do lead %s: ja esta com o vendedor %s", lead_id, lead.vendedor_id)
                return
            escolha = await s.distribuir.executar(loja_id, lead_id)
            if isinstance(escolha, SemVendedorDisponivel):
                log.warning(
                    "handoff do lead %s sem vendedor disponivel (%s): fica aguardando vendedor",
                    lead_id,
                    escolha.motivo,
                )
                return
            dono = f"{DONO_VENDEDOR}:{escolha}"
            await s.repo.definir_dono(
                loja_id,
                lead_id,
                DONO_VENDEDOR,
                escolha,
                {"dono": dono, "vendedor_id": str(escolha), "origem": "distribuicao"},
            )
            vendedor = next(
                (v for v in await s.vendedores.listar(loja_id) if v.id == escolha), None
            )
        # transacao fechada (trava da loja liberada): daqui em diante pode haver rede
        await publicar_sem_falhar(
            self._publicador,
            loja_id,
            EventoDonoMudou(lead_id=lead_id, dono=dono, vendedor_id=escolha, em=resumo.gerado_em),
        )
        numero = numero_whatsapp(vendedor.telefone if vendedor else None)
        if numero is None:
            log.warning(
                "vendedor %s sem telefone valido: lead %s nao foi avisado", escolha, lead_id
            )
            return
        texto = montar_mensagem_vendedor(
            lead_id=lead_id,
            lead_nome=lead.nome,
            lead_telefone=lead.telefone,
            canal=lead.canal,
            resumo=resumo,
            url_painel=self._url_painel,
        )
        try:
            id_whatsapp = await self._gateway.enviar_texto(loja_id, numero, texto)
            if id_whatsapp is not None:
                await self._registro.registrar(loja_id, id_whatsapp)
        except Exception:
            log.warning(
                "aviso ao vendedor %s sobre o lead %s nao foi enviado",
                escolha,
                lead_id,
                exc_info=True,
            )
