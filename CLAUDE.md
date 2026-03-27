# Pre-Market Analysis — Contexto del Proyecto

## Qué es este proyecto
Sistema de análisis pre-apertura para opciones 0DTE del SPX.
Calcula varios indicadores combinados en dos scores (direccional + volatilidad)
para determinar estrategia y strikes antes de las 09:25 ET.

## Stack técnico
- Python con uv para gestión de paquetes
- TastyTrade MCP conectado (herramientas: get_quotes, get_option_chain, etc.)
- Datos externos: yfinance (VIX/VXV/VVIX), SqueezeMetrics (DIX)

## Arquitectura del pipeline
fetch_market_data.py → data.json → calculate_indicators.py → indicators.json → generate_scorecard.py

## Flujo de trabajo estándar
Cuando se pida "ejecutar el análisis" o "scorecard de hoy":
1. Llamar a las herramientas MCP para obtener chain SPXW 0DTE y quotes ES + SPX
2. Ejecutar los tres scripts en secuencia
3. Mostrar el scorecard en terminal
4. Guardar en logs/ con fecha

## Convenciones
- Iterar siempre sobre specs/ antes de modificar código
- Los outputs en /outputs/ se sobreescriben cada día
- Los logs/ se acumulan (un fichero JSON por día)
- No commitear CLAUDE.local.md ni outputs/ ni logs/

## MCP disponible
TastyTrade conectado. Herramientas principales:
- get_quotes: símbolos SPX y /ES
- get_option_chain: símbolo SPXW, expiry = fecha de hoy

## Git
- Repositorio: https://github.com/ciherraiz/premarket
- Rama principal: main
- No commitear: outputs/, logs/, CLAUDE.local.md, .env
- Commits en español, formato convencional: feat:, fix:, chore:
- Cada funcionalidad nueva pasa por specs/ antes de implementarse

## Estado actual
[X] Paso 1: estructura creada
[ ] Paso 2: scripts migrados desde skill
[ ] Paso 3: bridge MCP implementado
[ ] Paso 4: primer test en vivo