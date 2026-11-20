"""Perfil da Loja Demo Celulares (tudo ficticio)."""

from app.application.config.modelos import PerfilLoja

NOME_LOJA = "Loja Demo Celulares"

PERFIL = PerfilLoja(
    nome_exibicao=NOME_LOJA,
    tom_de_voz=(
        "Amigável e direto: fala como um vendedor de bairro atencioso, sem enrolação, "
        "sem gírias pesadas, e sempre deixa claro o próximo passo."
    ),
    endereco="Rua das Palmeiras, 123, Centro, Cidade Exemplo - UF, CEP 00000-000",
    horarios={
        "seg": "09:00-18:00",
        "ter": "09:00-18:00",
        "qua": "09:00-18:00",
        "qui": "09:00-18:00",
        "sex": "09:00-18:00",
        "sab": "09:00-14:00",
    },
    whatsapp_contato="+55 11 90000-0000",
)
