"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { useToast } from "@/components/ui/toast"
import {
  api,
  assinarEventosLoja,
  mensagemDeErro,
  type CardLead,
  type DetalheLead,
  type EventoPainel,
} from "@/lib/api"

import {
  achatarConversas,
  aplicarDono,
  incorporarMensagem,
  mensagemDeEvento,
  type VendedorResumo,
} from "./regras"

export type Cliente = typeof api
export type Assinar = (
  lojaId: string,
  onEvento: (evento: EventoPainel) => void,
  opcoes?: { onErro?: () => void },
) => () => void

export type StatusCarga = "carregando" | "pronto" | "erro"

type Vendedor = VendedorResumo & { telefone: string | null }

/**
 * Estado da inbox: lista de conversas, conversa aberta (detalhe) e ações assumir, devolver e
 * responder. O cliente da API e a assinatura SSE entram por parâmetro para os testes.
 */
export function useInbox(
  lojaId: string,
  leadId: string | null,
  cliente: Cliente = api,
  assinar: Assinar = assinarEventosLoja,
) {
  const toast = useToast()
  const [colunas, setColunas] = useState<{ leads: CardLead[] }[]>([])
  const [atividade, setAtividade] = useState<Record<string, string>>({})
  const [statusLista, setStatusLista] = useState<StatusCarga>("carregando")
  const [vendedores, setVendedores] = useState<Vendedor[]>([])
  const [detalhe, setDetalhe] = useState<DetalheLead | null>(null)
  const [statusDetalhe, setStatusDetalhe] = useState<StatusCarga>("carregando")
  const [tempoRealOk, setTempoRealOk] = useState(true)
  const [ocupado, setOcupado] = useState(false)
  const [semCanal, setSemCanal] = useState<ReadonlySet<string>>(new Set())

  const conversasRef = useRef<CardLead[]>([])
  const vendedoresRef = useRef<Vendedor[]>([])
  const leadIdRef = useRef(leadId)
  const sequenciaLista = useRef(0)
  const sequenciaDetalhe = useRef(0)
  const sequenciaMensagem = useRef(0)
  const offline = useRef(false)

  const conversas = useMemo(() => achatarConversas(colunas, atividade), [colunas, atividade])

  useEffect(() => {
    conversasRef.current = conversas
    vendedoresRef.current = vendedores
    leadIdRef.current = leadId
  })

  const carregarLista = useCallback(
    (exibirErro: boolean) => {
      const minha = ++sequenciaLista.current
      cliente
        .GET("/lojas/{loja_id}/leads", { params: { path: { loja_id: lojaId } } })
        .then(({ data }) => {
          if (minha !== sequenciaLista.current) return
          if (data) {
            setColunas(data.etapas)
            setStatusLista("pronto")
          } else if (exibirErro) setStatusLista("erro")
        })
        .catch(() => {
          if (minha === sequenciaLista.current && exibirErro) setStatusLista("erro")
        })
    },
    [cliente, lojaId],
  )

  const carregarDetalhe = useCallback(
    (id: string, exibirErro: boolean) => {
      const minha = ++sequenciaDetalhe.current
      cliente
        .GET("/lojas/{loja_id}/leads/{lead_id}", { params: { path: { loja_id: lojaId, lead_id: id } } })
        .then(({ data }) => {
          if (minha !== sequenciaDetalhe.current) return
          if (data) {
            setDetalhe(data)
            setStatusDetalhe("pronto")
          } else if (exibirErro) setStatusDetalhe("erro")
        })
        .catch(() => {
          if (minha === sequenciaDetalhe.current && exibirErro) setStatusDetalhe("erro")
        })
    },
    [cliente, lojaId],
  )

  // Vendedores ativos (para "Atendendo como" e para o nome do dono).
  useEffect(() => {
    let ativo = true
    cliente
      .GET("/lojas/{loja_id}/config/vendedores", { params: { path: { loja_id: lojaId } } })
      .then(({ data }) => {
        if (ativo && data) setVendedores(data.vendedores)
      })
      .catch(() => {})
    return () => {
      ativo = false
    }
  }, [cliente, lojaId])

  // Conversa aberta.
  useEffect(() => {
    sequenciaDetalhe.current++
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDetalhe(null)
    if (!leadId) return
    setStatusDetalhe("carregando")
    carregarDetalhe(leadId, true)
  }, [leadId, carregarDetalhe])

  // Lista + tempo real.
  useEffect(() => {
    carregarLista(true)
    const fechar = assinar(
      lojaId,
      (evento) => {
        const voltou = offline.current
        offline.current = false
        setTempoRealOk(true)
        if (voltou) {
          carregarLista(false)
          if (leadIdRef.current) carregarDetalhe(leadIdRef.current, false)
        }
        aplicarEvento(evento)
      },
      {
        onErro: () => {
          offline.current = true
          setTempoRealOk(false)
        },
      },
    )
    const contador = sequenciaLista
    return () => {
      contador.current++
      fechar()
    }

    function aplicarEvento(evento: EventoPainel) {
      const atual = leadIdRef.current === evento.lead_id
      const atualizarCard = (fn: (c: CardLead) => CardLead) => {
        setColunas((cs) => cs.map((col) => ({ ...col, leads: col.leads.map((l) => (l.id === evento.lead_id ? fn(l) : l)) })))
        setDetalhe((d) => (d && d.card.id === evento.lead_id ? { ...d, card: fn(d.card) } : d))
      }

      if (evento.evento === "MensagemNova") {
        setAtividade((a) => ({ ...a, [evento.lead_id]: evento.em }))
        if (!conversasRef.current.some((c) => c.id === evento.lead_id)) carregarLista(false)
        const nova = mensagemDeEvento(evento, ++sequenciaMensagem.current)
        setDetalhe((d) =>
          d && d.card.id === evento.lead_id ? { ...d, mensagens: incorporarMensagem(d.mensagens, nova) } : d,
        )
      } else if (evento.evento === "DonoMudou") {
        if (!conversasRef.current.some((c) => c.id === evento.lead_id)) carregarLista(false)
        atualizarCard((c) => aplicarDono(c, evento, vendedoresRef.current))
        if (atual) carregarDetalhe(evento.lead_id, false) // handoff e motivo podem ter mudado
      } else if (evento.evento === "EtapaMudou") {
        if (!conversasRef.current.some((c) => c.id === evento.lead_id)) carregarLista(false)
        atualizarCard((c) => ({ ...c, etapa: evento.para, etapa_desde: evento.em }))
      }
    }
  }, [lojaId, assinar, carregarLista, carregarDetalhe])

  const trocarCard = useCallback((novo: CardLead) => {
    setColunas((cs) => cs.map((col) => ({ ...col, leads: col.leads.map((l) => (l.id === novo.id ? novo : l)) })))
    setDetalhe((d) => (d && d.card.id === novo.id ? { ...d, card: novo } : d))
  }, [])

  const assumir = useCallback(
    async (vendedorId: string) => {
      if (!leadId) return
      setOcupado(true)
      try {
        const { data, error } = await cliente.POST("/lojas/{loja_id}/leads/{lead_id}/assumir", {
          params: { path: { loja_id: lojaId, lead_id: leadId } },
          body: { vendedor_id: vendedorId },
        })
        if (data) {
          trocarCard(data)
          carregarDetalhe(leadId, false)
        } else {
          toast.erro("Não foi possível assumir a conversa", { descricao: mensagemDeErro(error) })
          carregarDetalhe(leadId, false)
        }
      } catch {
        toast.erro("Não foi possível assumir a conversa", { descricao: "Falha de conexão com o servidor." })
      } finally {
        setOcupado(false)
      }
    },
    [cliente, lojaId, leadId, toast, trocarCard, carregarDetalhe],
  )

  const devolver = useCallback(async () => {
    if (!leadId) return
    setOcupado(true)
    try {
      const { data, error } = await cliente.POST("/lojas/{loja_id}/leads/{lead_id}/devolver", {
        params: { path: { loja_id: lojaId, lead_id: leadId } },
      })
      if (data) {
        trocarCard(data)
        carregarDetalhe(leadId, false)
      } else {
        toast.erro("Não foi possível devolver para a IA", { descricao: mensagemDeErro(error) })
        carregarDetalhe(leadId, false)
      }
    } catch {
      toast.erro("Não foi possível devolver para a IA", { descricao: "Falha de conexão com o servidor." })
    } finally {
      setOcupado(false)
    }
  }, [cliente, lojaId, leadId, toast, trocarCard, carregarDetalhe])

  /** Envia a resposta do vendedor. Devolve true se foi aceita (o campo pode ser limpo). */
  const enviar = useCallback(
    async (texto: string): Promise<boolean> => {
      if (!leadId) return false
      try {
        const { data, error } = await cliente.POST("/lojas/{loja_id}/leads/{lead_id}/mensagens", {
          params: { path: { loja_id: lojaId, lead_id: leadId } },
          body: { texto },
        })
        if (!data) {
          toast.erro("Não foi possível enviar a mensagem", { descricao: mensagemDeErro(error) })
          return false
        }
        const { mensagem, enviada } = data
        setDetalhe((d) => (d && d.card.id === leadId ? { ...d, mensagens: incorporarMensagem(d.mensagens, mensagem) } : d))
        setAtividade((a) => ({ ...a, [leadId]: mensagem.criada_em }))
        if (!enviada) setSemCanal((s) => new Set(s).add(mensagem.id))
        return true
      } catch {
        toast.erro("Não foi possível enviar a mensagem", { descricao: "Falha de conexão com o servidor." })
        return false
      }
    },
    [cliente, lojaId, leadId, toast],
  )

  const recarregar = useCallback(() => {
    setStatusLista("carregando")
    carregarLista(true)
    if (leadId) {
      setStatusDetalhe("carregando")
      carregarDetalhe(leadId, true)
    }
  }, [carregarLista, carregarDetalhe, leadId])

  return {
    conversas,
    statusLista,
    vendedores,
    detalhe,
    statusDetalhe,
    tempoRealOk,
    ocupado,
    semCanal,
    assumir,
    devolver,
    enviar,
    recarregar,
  }
}
