# Spec: Workflow Combined Scorecard

## Estado
[Development]

## Propósito

Definir el formato y la lógica del scorecard combinado que fusiona las señales
premarket con los indicadores open-phase para producir la decisión de trading.

---

## Cuándo se imprime

Solo se imprime cuando `--phase open` ha corrido y ambas fases tienen datos.
La función `print_combined_scorecard(premarket, open_phase)` recibe los dos
dicts de indicadores ya calculados.

El scorecard premarket standalone (`print_scorecard`) sigue siendo válido
para una ejecución premarket sin open phase.

---

## Estructura del scorecard combinado

```
==============================================================
  SCORECARD COMBINADO — 2026-03-31  [ventana: 30 min]
==============================================================

  [PRE-MARKET — D-SCORE]
  Indicador            Valor                      Score  Signal
  ------------------------------------------------------------
  VIX/VXV Slope        VIX=16.05  VXV=18.30       +1    CONTANGO_SUAVE
  VIX9D/VIX Ratio      VIX9D=13.42  VIX=16.05     +2    CONTANGO_FUERTE
  Overnight Gap        Gap=+0.19%                  +1    GAP_ALCISTA
  Net GEX              GEX=+6.75B                  +1    LONG_GAMMA_SUAVE
  Flip Level           Flip=5200  Spot=5195         +2    SOBRE_FLIP
  ------------------------------------------------------------
  D-Score premarket:  +7

  [PRE-MARKET — V-SCORE]
  Indicador            Valor                      Score  Signal
  ------------------------------------------------------------
  IV Rank (IVR)        VIX=16.05  IVR=34.85%       +1    PRIMA_NORMAL
  ATR Ratio            ATR_ratio=0.8861             +1    CONTRACCION_SUAVE
  ------------------------------------------------------------
  V-Score premarket:  +2

  [OPEN PHASE — D-SCORE]  (09:30–10:00 ET)
  Indicador            Valor                      Score  Signal
  ------------------------------------------------------------
  <ind_open_d_1>       ...                         +X    SEÑAL
  <ind_open_d_2>       ...                         +X    SEÑAL
  ------------------------------------------------------------
  D-Score open:  +X

  [OPEN PHASE — V-SCORE]  (09:30–10:00 ET)
  Indicador            Valor                      Score  Signal
  ------------------------------------------------------------
  <ind_open_v_1>       ...                         +X    SEÑAL
  ------------------------------------------------------------
  V-Score open:  +X

==============================================================
  DECISIÓN FINAL
  D-Score total:  +X   (premarket +7  |  open +X)
  V-Score total:  +X   (premarket +2  |  open +X)

  Régimen:   TENDENCIA ALCISTA / RANGO / EXPANSIÓN / ...
  Estrategia: <descripción de la estrategia recomendada>
==============================================================
```

---

## Lógica de combinación de scores

### D-Score total

```
d_score_total = d_score_premarket + d_score_open
```

Suma directa. Los pesos relativos están en los indicadores individuales.

### V-Score total

```
v_score_total = v_score_premarket + v_score_open
```

### Rangos esperados (orientativos, antes de calibrar open-phase)

| Score | Rango premarket | Rango open | Rango total |
|---|---|---|---|
| D-Score | −10 a +10 | TBD | TBD |
| V-Score | −2 a +5 | TBD | TBD |

Los rangos exactos del open phase se definen en los specs `ind_open_*.md`.

---

## Lógica de régimen y estrategia

La interpretación del scorecard combinado (régimen + estrategia) se define
en una tabla de decisión que relaciona rangos de D-Score total y V-Score total
con acciones concretas (tipo de spread, strikes, ancho). Esta tabla se
elaborará tras calibrar los primeros indicadores open-phase con datos reales.

**Placeholder** hasta disponer de calibración:

| D-Score total | V-Score total | Régimen | Estrategia |
|---|---|---|---|
| ≥ +5 | ≥ +3 | Tendencia alcista + vol alta | Call spread OTM agresivo |
| ≥ +5 | < +3 | Tendencia alcista + vol baja | Call spread OTM conservador |
| −4 a +4 | ≥ +3 | Rango + vol alta | Iron condor amplio |
| −4 a +4 | < +3 | Rango + vol baja | Iron condor estrecho |
| ≤ −5 | ≥ +3 | Tendencia bajista + vol alta | Put spread OTM agresivo |
| ≤ −5 | < +3 | Tendencia bajista + vol baja | Put spread OTM conservador |

---

## Implementación en generate_scorecard.py

```python
def print_scorecard(indicators: dict, phase: str = "premarket") -> None:
    """
    Imprime el scorecard de una sola fase.
    Compatible con dicts planos (tests legacy) y namespaced.
    """
    data = indicators.get(phase, indicators)  # fallback a dict plano
    # ... lógica actual, sin cambios de fondo


def print_combined_scorecard(
    premarket: dict,
    open_phase: dict,
    window_minutes: int = 30,
) -> None:
    """
    Imprime el scorecard combinado con ambas fases y la decisión final.
    premarket: dict plano de indicadores premarket (ya extraído del namespace)
    open_phase: dict plano de indicadores open phase
    """
```

### Retrocompatibilidad

- `print_scorecard(indicators)` sin `phase` → comportamiento actual exacto
- Tests existentes que llaman `print_scorecard(flat_dict)` siguen funcionando
- La nueva función `print_combined_scorecard` es aditiva, no rompe nada existente

---

## Verificación

Tras implementar los indicadores open-phase:

```bash
# Ejecutar premarket primero
uv run python scripts/run.py --phase premarket

# Ejecutar open phase (a las 10:15 ET para ventana de 30 min)
uv run python scripts/run.py --phase open --window 30
```

El scorecard combinado debe mostrar:
1. Todos los indicadores premarket con sus scores (igual que el scorecard premarket)
2. Los indicadores open-phase con sus scores
3. D-Score total y V-Score total como suma de ambas fases
4. Régimen y estrategia en la sección DECISIÓN FINAL
