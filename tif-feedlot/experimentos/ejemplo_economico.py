"""Ejemplo numérico FICTICIO de la comparación vender ahora vs. continuar h días.

Todos los valores son inventados para ilustrar la formulación; no representan
precios ni desempeños reales. Uso: python3 -I ejemplo_economico.py
"""
import numpy as np

W0 = 380.0            # kg PV por cabeza hoy (pesada con desbaste ya aplicado)
P = {0: 3000.0, 7: 3000.0, 14: 2985.0, 21: 2970.0}  # $/kg PV neto esperado según peso/fecha (escenario del usuario)
COMISION = 0.04       # fracción sobre el valor bruto
FLETE = 15000.0       # $/cabeza, igual si vende hoy o después (se cancela)
CMS = 9.8             # kg MS/día consumo esperado
C_MS = 250.0          # $/kg MS de la ración
C_OTROS = 700.0       # $/cabeza/día costos evitables (sanidad, personal variable, hotelería)
TASA_ANUAL = 0.30     # costo de oportunidad del capital inmovilizado en el animal
ADG = {7: 1.45, 14: 1.35, 21: 1.20}  # ganancia media prevista hasta el horizonte (kg/d)
SD_ADG = 0.20         # desvío de la predicción de ADG (de la validación del modelo)


def valor_neto(peso, precio):
    return peso * precio * (1 - COMISION) - FLETE


def delta(h, adg, precio_h):
    v0 = valor_neto(W0, P[0])
    vh = valor_neto(W0 + adg * h, precio_h)
    costo_alim = CMS * C_MS * h
    costo_otros = C_OTROS * h
    costo_capital = v0 * TASA_ANUAL * h / 365
    return v0, vh, costo_alim, costo_otros, costo_capital, vh - v0 - costo_alim - costo_otros - costo_capital


def adg_equilibrio(h, precio_h):
    """ADG mínima para que continuar h días no pierda contra vender hoy."""
    lo, hi = 0.0, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if delta(h, mid, precio_h)[-1] < 0 else (lo, mid)
    return (lo + hi) / 2


rng = np.random.default_rng(0)
print(f"Valor neto de vender hoy: {valor_neto(W0, P[0]):,.0f} $/cab")
for h in (7, 14, 21):
    v0, vh, ca, co, cc, d = delta(h, ADG[h], P[h])
    sims = np.array([delta(h, a, P[h])[-1] for a in rng.normal(ADG[h], SD_ADG, 10000)])
    print(f"h={h:2d} d | peso esp {W0+ADG[h]*h:6.1f} kg | valor {vh:,.0f} | alim {ca:,.0f} | otros {co:,.0f} "
          f"| capital {cc:,.0f} | Δ esperado {d:+,.0f} $/cab | P(Δ>0)={np.mean(sims>0):.2f} "
          f"| ADG equilibrio {adg_equilibrio(h, P[h]):.2f} kg/d")
# margen 'diario' ingenuo: valor de la ganancia diaria vs costo diario, ignorando cambio de precio y capital
ingenuo = ADG[14] * P[0] - CMS * C_MS - C_OTROS
print(f"Margen diario ingenuo (h=14, sin capital ni cambio de precio): {ingenuo:+,.0f} $/cab/d")
