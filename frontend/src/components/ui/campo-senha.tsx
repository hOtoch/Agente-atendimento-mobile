import { Campo } from "./campo"
import { Input } from "./input"

/** Campo de senha: `Campo` + `Input type="password"`, com o `autoComplete` certo para cada uso. */
export function CampoSenha({
  label,
  value,
  onChange,
  erro,
  dica,
  autoComplete = "current-password",
  className,
}: {
  label: string
  value: string
  onChange: (valor: string) => void
  erro?: string
  dica?: string
  autoComplete?: "current-password" | "new-password"
  className?: string
}) {
  return (
    <Campo label={label} erro={erro} dica={dica} className={className}>
      {(controle) => (
        <Input
          {...controle}
          type="password"
          value={value}
          autoComplete={autoComplete}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Campo>
  )
}
