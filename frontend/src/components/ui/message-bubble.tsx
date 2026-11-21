import { cn } from "@/lib/utils"

export type LadoMensagem = "cliente" | "atendente"
export type TipoMensagemBalao = "texto" | "imagem" | "audio"

type Props = {
  /** Quem escreveu a mensagem. */
  lado: LadoMensagem
  tipo: TipoMensagemBalao
  texto?: string | null
  midiaUrl?: string | null
  /** Texto falado no áudio (STT), mostrado abaixo do player. */
  transcricao?: string | null
  horario?: Date | string | null
  /** Nome exibido acima do conteúdo (ex.: "IA", "Carla"). */
  autor?: string
  /** Mensagem de falha exibida abaixo do conteúdo (cor `danger`). */
  erro?: string
  /**
   * Quem está olhando a conversa: as mensagens dele ficam à direita. Padrão `atendente`
   * (inbox do painel); o simulador de cliente usa `cliente`.
   */
  perspectiva?: LadoMensagem
  className?: string
}

const FORMATO_HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" })

function formatarHorario(horario: Date | string): string | null {
  const data = typeof horario === "string" ? new Date(horario) : horario
  return Number.isNaN(data.getTime()) ? null : FORMATO_HORA.format(data)
}

/** Balão de mensagem de conversa: texto, imagem ou áudio, com horário e lado. */
export function MessageBubble({
  lado,
  tipo,
  texto,
  midiaUrl,
  transcricao,
  horario,
  autor,
  erro,
  perspectiva = "atendente",
  className,
}: Props) {
  const propria = lado === perspectiva
  const hora = horario ? formatarHorario(horario) : null

  return (
    <div
      data-slot="message-bubble"
      data-testid="balao"
      data-alinhamento={propria ? "direita" : "esquerda"}
      className={cn("flex w-full min-w-0", propria ? "justify-end" : "justify-start", className)}
    >
      <div className={cn("flex max-w-[85%] min-w-0 flex-col gap-1", propria ? "items-end" : "items-start")}>
      <div
        className={cn(
          "flex min-w-0 flex-col gap-1 rounded-lg px-3 py-2 text-sm",
          propria
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm bg-muted text-foreground",
        )}
      >
        {autor ? <span className="text-xs font-medium opacity-80">{autor}</span> : null}
        {tipo === "imagem" && midiaUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- mídia vem da API, sem otimização do Next
          <img
            src={midiaUrl}
            alt="Imagem enviada"
            className="max-h-72 w-full rounded-md object-cover"
          />
        ) : null}
        {tipo === "audio" && midiaUrl ? (
          <audio controls src={midiaUrl} className="h-10 w-full max-w-64" />
        ) : null}
        {tipo === "audio" && transcricao ? (
          <p data-testid="transcricao" className="text-xs break-words whitespace-pre-wrap opacity-90">
            <span className="font-medium">Transcrição: </span>
            {transcricao}
          </p>
        ) : null}
        {texto ? <p className="break-words whitespace-pre-wrap">{texto}</p> : null}
        {hora ? <span className="self-end text-xs opacity-70">{hora}</span> : null}
      </div>
      {erro ? <span className="text-xs font-medium text-danger">{erro}</span> : null}
      </div>
    </div>
  )
}
