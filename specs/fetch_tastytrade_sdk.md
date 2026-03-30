# SPEC — FETCH: TastyTrade SDK Client

## Estado
[ ] En desarrollo

## Objetivo
Reemplazar el placeholder `mcp_bridge` en `fetch_es_quote()` por una llamada real
al SDK de Python de TastyTrade, de forma que el pipeline pueda obtener el precio
del futuro /ES de forma autónoma — sin que Claude esté activo.

## Contexto
El pipeline pre-market necesita el precio del ES en premarket para calcular el
Overnight Gap. Actualmente `fetch_es_quote()` devuelve siempre `MISSING_DATA`
porque el `mcp_bridge` no existe.

El MCP de TastyTrade es una integración para Claude (el agente). Los scripts Python
no pueden llamar herramientas MCP directamente. La solución es usar el SDK oficial
`tastytrade` (PyPI), que llama a la API REST/streaming del broker con credenciales
propias, sin pasar por Claude.

Este spec cubre también la base de autenticación que necesitarán futuras funciones
(option chain SPXW, gestión de órdenes desde Python si fuera necesario).

## Dependencias nuevas

```toml
# pyproject.toml
dependencies = [
    "pandas>=3.0.1",
    "yfinance>=1.2.0",
    "tastytrade>=9.0",      # SDK oficial TastyTrade
    "python-dotenv>=1.0",   # carga de credenciales desde .env
]
```

## Credenciales

Fichero `.env` en la raíz del proyecto (ya en `.gitignore`):

```env
TT_USERNAME=tu_usuario_tastytrade
TT_PASSWORD=tu_contraseña_tastytrade
```

No commitear nunca este fichero. El `.gitignore` ya lo excluye.

## Arquitectura

Se crea un módulo separado `scripts/tastytrade_client.py` que encapsula
autenticación y acceso al SDK. El resto del pipeline lo usa como dependencia.

```
scripts/
  tastytrade_client.py   ← NUEVO: autenticación + helpers de mercado
  fetch_market_data.py   ← MODIFICAR: fetch_es_quote() usa TastyTradeClient
```

## Módulo: scripts/tastytrade_client.py

### Clase `TastyTradeClient`

```python
class TastyTradeClient:
    def __init__(self):
        """
        Carga credenciales de .env e inicia sesión con TastyTrade.
        Lanza EnvironmentError si las credenciales no están configuradas.
        Lanza tastytrade.TastytradeError si la autenticación falla.
        """

    def get_future_quote(self, symbol: str) -> dict:
        """
        Devuelve el precio actual de un futuro.
        symbol: símbolo raíz como '/ES' — el cliente resuelve el contrato activo.

        Retorna:
            {
                "symbol":     str,    # contrato activo resuelto, ej. "/ESM5"
                "last":       float,  # último precio negociado
                "mark":       float,  # mid (bid+ask)/2, fallback si last es 0
                "bid":        float,
                "ask":        float,
                "status":     str,    # "OK" | "ERROR" | "MISSING_DATA"
            }
        """
```

### Resolución del contrato activo

`/ES` es el símbolo raíz. TastyTrade requiere el contrato con vencimiento
explícito (ej. `/ESM5` para junio 2025). El cliente debe:

1. Llamar a `Future.get_active_futures(session, ['/ES'])` para obtener el
   contrato front-month activo
2. Usar ese símbolo para suscribirse a la quote via `DXLinkStreamer`

### Precio a devolver

- Usar `last` si es > 0
- Fallback a `mark` = `(bid + ask) / 2` si `last` es 0 o None
  (ocurre fuera de horario de negociación activa)

## Modificación: fetch_es_quote() en fetch_market_data.py

Reemplazar el bloque `try/except ImportError` actual por:

```python
def fetch_es_quote() -> dict:
    result = {
        "es_premarket": None,
        "fecha": str(date.today()),
        "status": "MISSING_DATA",
    }
    try:
        from tastytrade_client import TastyTradeClient
        client = TastyTradeClient()
        quote = client.get_future_quote("/ES")
        if quote["status"] != "OK":
            result["status"] = quote["status"]
            return result
        price = quote["last"] or quote["mark"]
        if not price or price == 0:
            result["status"] = "ERROR"
            return result
        result["es_premarket"] = round(float(price), 2)
        result["status"] = "OK"
    except EnvironmentError:
        result["status"] = "MISSING_DATA"   # credenciales no configuradas
    except Exception:
        result["status"] = "ERROR"
    return result
```

## Casos de error a manejar

| Situación                              | status          | es_premarket |
|----------------------------------------|-----------------|--------------|
| Credenciales no en .env                | MISSING_DATA    | None         |
| Autenticación fallida (contraseña mal) | ERROR           | None         |
| Sin conexión / timeout                 | ERROR           | None         |
| Mercado cerrado, last=0 y mark válido  | OK              | mark price   |
| last=0 y mark=0                        | ERROR           | None         |
| Contrato activo no encontrado          | MISSING_DATA    | None         |
| Cualquier excepción no controlada      | ERROR           | None         |

En todos los casos el pipeline continúa sin interrumpirse.

## Estructura del output de get_future_quote()

```python
{
    "symbol":  str,    # contrato resuelto, ej. "/ESM5"
    "last":    float,  # último precio (0.0 si no hay trades recientes)
    "mark":    float,  # (bid + ask) / 2
    "bid":     float,
    "ask":     float,
    "status":  str,    # "OK" | "ERROR" | "MISSING_DATA"
}
```

## Ubicación del código

- Cliente   : scripts/tastytrade_client.py → clase `TastyTradeClient`
- Fetch     : scripts/fetch_market_data.py → `fetch_es_quote()` (modificar)
- Config    : .env (raíz del proyecto, no commitear)
- Deps      : pyproject.toml (añadir tastytrade y python-dotenv)
- Tests     : tests/test_tastytrade_client.py

## Tests a implementar

Los tests mockean `TastyTradeClient` — sin llamadas reales a TastyTrade.

| Test                              | Setup                                            | Output esperado                            |
|-----------------------------------|--------------------------------------------------|--------------------------------------------|
| Quote OK con last                 | mock get_future_quote → last=5100.0, mark=5100.5 | es_premarket=5100.0, status="OK"           |
| Quote OK sin last (usa mark)      | mock → last=0, mark=5100.5                       | es_premarket=5100.5, status="OK"           |
| Credenciales ausentes             | EnvironmentError en constructor                  | es_premarket=None, status="MISSING_DATA"   |
| Error de autenticación            | TastytradeError en constructor                   | es_premarket=None, status="ERROR"          |
| last=0 y mark=0                   | mock → last=0, mark=0                            | es_premarket=None, status="ERROR"          |
| get_future_quote status ERROR     | mock → status="ERROR"                            | es_premarket=None, status="ERROR"          |
| get_future_quote status MISSING   | mock → status="MISSING_DATA"                     | es_premarket=None, status="MISSING_DATA"   |

## Notas de implementación

- `TastyTradeClient` usa `python-dotenv` para cargar `.env` — no asumir que las
  variables ya están en el entorno
- La sesión de TastyTrade expira. No es necesario gestionar renovación en esta
  fase — si expira, el siguiente run crea una sesión nueva
- `DXLinkStreamer` es async; usar `asyncio.run()` para llamarlo desde código síncrono
- El contrato front-month cambia cada trimestre (mar/jun/sep/dic). `get_active_futures`
  devuelve siempre el correcto sin hardcodear el vencimiento

## Prompt de inicio para Claude Code
```
Lee specs/fetch_tastytrade_sdk.md completamente antes de escribir ningún código.

Implementa en este orden exacto:

1. Añade las dependencias al pyproject.toml:
   tastytrade>=9.0 y python-dotenv>=1.0
   Ejecuta: uv sync

2. Crea scripts/tastytrade_client.py con la clase TastyTradeClient:
   - __init__: carga .env con load_dotenv(), lee TT_USERNAME y TT_PASSWORD,
     lanza EnvironmentError si faltan, crea Session de tastytrade
   - get_future_quote(symbol): obtiene el contrato activo con
     Future.get_active_futures(), suscribe via DXLinkStreamer, devuelve el dict
     definido en el spec. Usa asyncio.run() para la parte async.

3. Modifica fetch_es_quote() en scripts/fetch_market_data.py
   según el código del spec (importa TastyTradeClient, llama get_future_quote).

4. Crea tests/test_tastytrade_client.py
   Mockea TastyTradeClient.get_future_quote en todos los casos de la tabla.
   No hacer llamadas reales a TastyTrade.

5. Ejecuta: uv run pytest tests/test_tastytrade_client.py -v
   Confirma que todos pasan.

No implementes nada fuera de lo descrito en el spec.
```
