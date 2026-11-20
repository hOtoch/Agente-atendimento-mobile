"""Tabela de troca (upgrade) da loja demo: iPhone 11 a 17 Pro Max.

Valor sem detalhes por capacidade (GB -> R$) e descontos por modelo
(tela, traseira, carcaca, bateria; `None` = SEM). Limite de bateria: 80%.
"""

from decimal import Decimal

from app.application.config.entradas import EntradaLinhaTroca

LIMITE_BATERIA_PCT = 80

# modelo -> {capacidade_gb: valor sem detalhes}
VALORES: dict[str, dict[int, int]] = {
    "iPhone 11": {64: 800, 128: 900, 256: 1050},
    "iPhone 11 Pro": {64: 1200, 256: 1450, 512: 1700},
    "iPhone 11 Pro Max": {64: 1400, 256: 1700, 512: 1950},
    "iPhone 12 mini": {64: 900, 128: 1000, 256: 1150},
    "iPhone 12": {64: 1150, 128: 1300, 256: 1500},
    "iPhone 12 Pro": {128: 1900, 256: 2150, 512: 2450},
    "iPhone 12 Pro Max": {128: 2200, 256: 2500, 512: 2800},
    "iPhone 13 mini": {128: 1500, 256: 1750, 512: 2050},
    "iPhone 13": {128: 1800, 256: 2050, 512: 2350},
    "iPhone 13 Pro": {128: 2500, 256: 2800, 512: 3100, 1024: 3500},
    "iPhone 13 Pro Max": {128: 2900, 256: 3200, 512: 3550, 1024: 3900},
    "iPhone 14": {128: 2200, 256: 2500, 512: 2850},
    "iPhone 14 Plus": {128: 2450, 256: 2750, 512: 3100},
    "iPhone 14 Pro": {128: 3200, 256: 3550, 512: 3900, 1024: 4300},
    "iPhone 14 Pro Max": {128: 3700, 256: 4100, 512: 4500, 1024: 4900},
    "iPhone 15": {128: 2650, 256: 2950, 512: 3300},
    "iPhone 15 Plus": {128: 2900, 256: 3200, 512: 3550},
    "iPhone 15 Pro": {128: 3900, 256: 4300, 512: 4700, 1024: 5150},
    "iPhone 15 Pro Max": {256: 4900, 512: 5350, 1024: 5800},
    "iPhone 16e": {128: 2600, 256: 2900, 512: 3300},
    "iPhone 16": {128: 3100, 256: 3450, 512: 3850},
    "iPhone 16 Plus": {128: 3400, 256: 3750, 512: 4150},
    "iPhone 16 Pro": {128: 4600, 256: 5000, 512: 5450, 1024: 5900},
    "iPhone 16 Pro Max": {256: 5600, 512: 6100, 1024: 6600},
    "iPhone 17": {256: 4300, 512: 4900},
    "iPhone Air": {256: 5000, 512: 5500, 1024: 6100},
    "iPhone 17 Pro": {256: 6000, 512: 6500, 1024: 7000},
    "iPhone 17 Pro Max": {256: 6600, 512: 7100, 1024: 7600},
}

# modelo -> (tela, traseira, carcaca, bateria); None = SEM (avaliacao na loja)
DESCONTOS: dict[str, tuple[int, int | None, int, int]] = {
    "iPhone 11": (250, None, 120, 100),
    "iPhone 11 Pro": (350, None, 150, 120),
    "iPhone 11 Pro Max": (400, None, 170, 130),
    "iPhone 12 mini": (300, 150, 120, 110),
    "iPhone 12": (350, 200, 150, 120),
    "iPhone 12 Pro": (500, 250, 200, 150),
    "iPhone 12 Pro Max": (550, 280, 220, 160),
    "iPhone 13 mini": (350, 200, 150, 130),
    "iPhone 13": (450, 250, 200, 150),
    "iPhone 13 Pro": (650, 300, 250, 170),
    "iPhone 13 Pro Max": (700, 320, 270, 180),
    "iPhone 14": (500, 280, 250, 160),
    "iPhone 14 Plus": (520, 300, 260, 170),
    "iPhone 14 Pro": (800, 350, 300, 190),
    "iPhone 14 Pro Max": (850, 380, 320, 200),
    "iPhone 15": (550, 300, 280, 180),
    "iPhone 15 Plus": (570, 320, 290, 185),
    "iPhone 15 Pro": (900, 400, 350, 200),
    "iPhone 15 Pro Max": (950, 420, 370, 210),
    "iPhone 16e": (500, 300, 250, 170),
    "iPhone 16": (600, None, 300, 190),  # linha do exemplo oficial
    "iPhone 16 Plus": (620, 340, 310, 195),
    "iPhone 16 Pro": (1000, 450, 400, 220),
    "iPhone 16 Pro Max": (1050, 470, 420, 230),
    "iPhone 17": (650, 350, 330, 200),
    "iPhone Air": (700, 380, 340, 200),
    "iPhone 17 Pro": (1100, 500, 450, 240),
    "iPhone 17 Pro Max": (1150, 520, 470, 250),
}


def _linhas() -> tuple[EntradaLinhaTroca, ...]:
    linhas: list[EntradaLinhaTroca] = []
    for modelo, capacidades in VALORES.items():
        tela, traseira, carcaca, bateria = DESCONTOS[modelo]
        for capacidade, valor in capacidades.items():
            linhas.append(
                EntradaLinhaTroca(
                    marca="Apple",
                    modelo=modelo,
                    capacidade_gb=capacidade,
                    valor_sem_detalhes=Decimal(valor),
                    desconto_tela=Decimal(tela),
                    desconto_tela_sem=False,
                    desconto_traseira=None if traseira is None else Decimal(traseira),
                    desconto_traseira_sem=traseira is None,
                    desconto_carcaca=Decimal(carcaca),
                    desconto_carcaca_sem=False,
                    desconto_bateria=Decimal(bateria),
                    desconto_bateria_sem=False,
                    limite_bateria_pct=LIMITE_BATERIA_PCT,
                )
            )
    return tuple(linhas)


TROCA: tuple[EntradaLinhaTroca, ...] = _linhas()
