# Pre-Market Analysis — Contexto del Proyecto

## Qué es este proyecto
Sistema de análisis pre-apertura para opciones 0DTE del SPX.
Calcula varios indicadores combinados en dos scores (direccional + volatilidad)
para determinar estrategia y strikes antes de las 09:25 ET.

## Stack técnico
- Python con uv para gestión de paquetes
- TastyTrade SDK — wrapper en `scripts/tastytrade_client.py`
  - Quotes de futuros (/ES) y equity ($SPX.X) via API REST
  - Greeks (gamma, IV) y cadena de opciones SPXW via DXLink websocket
  - Credenciales en `.env`: `TASTYTRADE_USERNAME`, `TASTYTRADE_PASSWORD`
- Datos externos: yfinance (VIX9D, VIX, VXV/VIX3M, VVIX, SPX OHLCV, ES cierre)

## Arquitectura del pipeline

```
scripts/tastytrade_client.py  (SDK wrapper — TastyTrade API + DXLink)
         ↓
scripts/fetch_market_data.py  →  outputs/data.json
         ↓
scripts/calculate_indicators.py  →  outputs/indicators.json
         ↓
scripts/generate_scorecard.py  →  terminal

scripts/run.py  ←  punto de entrada único (orquesta los tres pasos)
```

## Indicadores implementados

**D-Score** (direccional, rango aprox. −10 a +10):

| ID     | Indicador        | Peso   | Función                  |
|--------|------------------|--------|--------------------------|
| IND-01 | VIX/VXV Slope    | ±2     | `calc_vix_vxv_slope`     |
| IND-02 | VIX9D/VIX Ratio  | ±2     | `calc_vix9d_vix_ratio`   |
| IND-03 | Net GEX          | ±3     | `calc_net_gex`           |
| IND-04 | Flip Level       | ±2     | `calc_net_gex`           |
| IND-05 | Overnight Gap    | ±1     | `calc_overnight_gap`     |

**V-Score** (volatilidad, rango aprox. −2 a +5):

| ID     | Indicador        | Peso   | Función                  |
|--------|------------------|--------|--------------------------|
| IND-06 | IV Rank (IVR)    | ±3     | `calc_ivr`               |
| IND-07 | ATR Ratio        | ±2     | `calc_atr_ratio`         |

## Flujo de trabajo estándar

Cuando se pida "ejecutar el análisis" o "scorecard de hoy":

```
uv run python scripts/run.py
```

Esto ejecuta en secuencia: fetch → calcular indicadores → imprimir scorecard.

## Convenciones
- Iterar siempre sobre `specs/` antes de modificar código
- Los outputs en `outputs/` se sobreescriben cada ejecución
- Los logs en `logs/` se acumulan (un fichero JSON por día)
- Constantes configurables (umbrales GEX, etc.) al inicio de `calculate_indicators.py`
- Correr `uv run pytest` antes de commitear
- No commitear: `CLAUDE.local.md`, `outputs/`, `logs/`, `.env`

## Git
- Repositorio: https://github.com/ciherraiz/premarket
- Rama principal: main
- Commits en español, formato convencional: `feat:`, `fix:`, `chore:`
- Cada funcionalidad nueva pasa por `specs/` antes de implementarse

## Estado actual
- [X] Paso 1: estructura creada
- [X] Paso 2: scripts implementados (todos los indicadores D-Score y V-Score)
- [X] Paso 3: SDK TastyTrade integrado (`tastytrade_client.py`)
- [ ] Paso 4: primer test en vivo con datos reales
- [ ] Paso 5: calibración de umbrales GEX con datos reales
