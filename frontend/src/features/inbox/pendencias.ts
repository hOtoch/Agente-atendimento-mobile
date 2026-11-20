/**
 * Rótulos das pendências da ficha (espelham `Pendencia` em backend/app/domain/ficha.py; a API
 * devolve os nomes em minúsculas).
 */
const ROTULOS: Record<string, string> = {
  aparelho_modelo: "Modelo do aparelho desejado",
  aparelho_capacidade: "Capacidade do aparelho desejado",
  estoque_confirmado: "Confirmar o item no estoque",
  tem_troca: "Saber se há aparelho para troca",
  usado_modelo: "Modelo do aparelho usado",
  usado_capacidade: "Capacidade do aparelho usado",
  usado_tela: "Estado da tela do usado",
  usado_traseira: "Estado da traseira do usado",
  usado_carcaca: "Estado da carcaça do usado",
  usado_bateria: "Saúde da bateria do usado",
  usado_camera: "Câmera do usado",
  usado_outros_defeitos: "Outros defeitos do usado",
  usado_peca_trocada: "Peça trocada no usado",
  data_compra: "Data prevista da compra",
  pagamento_tipo: "Forma de pagamento",
  pagamento_parcelas: "Número de parcelas",
  pagamento_bandeira: "Bandeira do cartão",
  pagamento_entrada: "Valor da entrada",
}

export function rotuloPendencia(codigo: string): string {
  const rotulo = ROTULOS[codigo]
  if (rotulo) return rotulo
  const texto = codigo.replace(/_/g, " ")
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

export function rotulosDasPendencias(codigos: string[]): string[] {
  return codigos.map(rotuloPendencia)
}
