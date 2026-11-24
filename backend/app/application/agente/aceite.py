"""`parece_aceite`: o cliente aceitou a ficha de confirmacao? (funcao pura, sem IO)

Conservadora de proposito: na duvida devolve False e a IA pergunta de novo. Aceite e uma fala
curta com um marcador afirmativo (sim, isso, pode fechar, fechado, confirmo, ok, 👍...) que nao
e pergunta, nao nega e nao pede desconto, brinde ou mudanca.
"""

from __future__ import annotations

import re
import unicodedata

_MAX_PALAVRAS = 12
_EMOJIS = ("👍", "✅", "👌", "🤝", "🙌", "🤙", "💪")
_AFIRMATIVOS = re.compile(
    r"\b(sim|isso|pode|pode fechar|fechado|fechou|confirmo|confirmado|certo|correto|beleza|bora|"
    r"ok|okay|okey|perfeito|show|combinado|aceito|vamos|topo|positivo|tudo certo|ta bom|"
    r"esta bom|esta certo|isso mesmo)\b"
)
_NEGATIVOS = re.compile(r"\b(nao|nunca|jamais|errado|incorreto|ainda nao)\b")
_PEDIDOS = re.compile(
    r"desconto|descont|abat|brinde|capinha|pelicula|carregador|fone|de graca|negoci|"
    r"mais barato|abaix|baix|menos|caro|melhor preco|\bmas\b|porem|so que|so se|na verdade|"
    r"mudar|muda\b|alterar|trocar|outro|outra|parcel|\b\d{1,2} ?x\b|"
    r"quanto|qual|quais|como|quando|onde|cade|tem |tem$|da pra|posso|\be se\b|\bse for\b"
)


def _normalizar(fala: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", fala.lower()) if not unicodedata.combining(c)
    )
    return re.sub(r"[^\w\s?]", " ", sem_acento)


def parece_aceite(fala: str) -> bool:
    """True se a fala do cliente soa como aceite da ficha (sem acento e sem caixa)."""
    if "?" in fala or not fala.strip():
        return False
    texto = " ".join(_normalizar(fala).split())
    afirma = any(e in fala for e in _EMOJIS) or _AFIRMATIVOS.search(texto) is not None
    if not afirma:
        return False
    if len(texto.split()) > _MAX_PALAVRAS or "\n" in fala.strip():
        return False
    return _NEGATIVOS.search(texto) is None and _PEDIDOS.search(texto) is None
