# Spec: Snapshots GEX Intraday

## Estado

- [x] Implementado

## Objetivo

Capturar el perfil completo de GEX 0DTE cada 10 minutos durante la sesión regular
(09:30–16:00 ET), persistirlo en disco y detectar desplazamientos significativos
de los niveles clave. El monitor Mancini integra este ciclo en su bucle de polling
existente sin necesidad de un proceso externo.

---

## Arquitectura

```
scripts/gex_intraday.py          ← módulo nuevo (lógica pura, sin I/O de monitor)
         ↑ llamado por
scripts/mancini/monitor.py       ← añade ciclo GEX al bucle principal
         ↓ escribe
outputs/gex_snapshots_YYYY-MM-DD.jsonl   ← un fichero por día, append
```

El módulo `gex_intraday.py` es independiente del monitor: puede ejecutarse también
desde CLI para depuración o para capturar un snapshot puntual manualmente.

---

## Formato del snapshot (JSONL)

Cada línea es un JSON completo:

```json
{
  "ts":                  "2026-04-29T09:45:00",
  "ts_et":               "2026-04-29T09:45:00-04:00",
  "spot":                5215.0,
  "net_gex_bn":          -1.23,
  "signal_gex":          "SHORT_GAMMA_SUAVE",
  "regime_text":         "Dealers SHORT gamma bajo 5200 — rebotes débiles, sin cobertura",
  "flip_level":          5200.0,
  "control_node":        5150.0,
  "chop_zone_low":       5195.0,
  "chop_zone_high":      5205.0,
  "put_wall":            5100.0,
  "call_wall":           5300.0,
  "gex_by_strike":       {"5100": -1.23, "5150": -0.87, "5200": 0.12},
  "gex_pct_by_strike":   {"5100": -100.0, "5150": -70.7, "5200": 9.8},
  "n_strikes":           45,
  "status":              "OK"
}
```

Claves de `gex_by_strike` y `gex_pct_by_strike`: strings del strike como entero
(`str(int(strike))`). Valores en billions para `gex_by_strike`, porcentaje para `gex_pct_by_strike`.

---

## 1. Módulo `scripts/gex_intraday.py`

### Constantes

```python
SNAPSHOT_PATH_TPL = "outputs/gex_snapshots_{date}.jsonl"  # {date} = YYYY-MM-DD
SESSION_START_ET  = (9, 30)   # hora, minuto ET — inicio captura
SESSION_END_ET    = (16, 0)   # hora, minuto ET — fin captura
GEX_SHIFT_ALERT_PTS = 10     # puntos — umbral para alerta de desplazamiento
```

### Función `take_gex_snapshot(client, spot) -> dict`

Equivalente al bloque 0DTE de `calc_net_gex()` pero adaptado a uso intraday.
Reutiliza `fetch_option_chain(days_ahead=0)` de `fetch_market_data.py` y
`calc_net_gex()` de `calculate_indicators.py`.

```python
def take_gex_snapshot(client, spot: float | None) -> dict:
    """
    Captura el perfil GEX 0DTE en el momento actual.

    Args:
        client: TastyTradeClient autenticado
        spot:   precio spot del SPX (float) o None para obtenerlo del cliente

    Returns:
        dict con todos los campos del formato snapshot (ver spec).
        En caso de error, status != "OK" y todos los campos numéricos son None.
    """
```

Internamente:
1. Si `spot` es None, llamar `client.get_equity_quote("$SPX.X")` para obtenerlo.
2. Llamar `fetch_option_chain(days_ahead=0)` usando el cliente.
3. Llamar `calc_net_gex(chain_0dte=chain, chain_multi=chain, spot=spot, fecha=today)`.
   (Para el snapshot intraday, la cadena 0DTE se usa para todo; el `net_gex_bn`
   será el GEX solo de hoy, no el multi-día. Esto es intencional: el snapshot
   mide la presión intraday, no el régimen estructural.)
4. Construir y retornar el dict del snapshot con timestamp ET.

### Función `save_snapshot(snapshot: dict, date: str | None = None) -> None`

```python
def save_snapshot(snapshot: dict, date: str | None = None) -> None:
    """
    Añade el snapshot al fichero JSONL del día.
    Crea el fichero si no existe.
    date: YYYY-MM-DD, por defecto la fecha de hoy.
    """
```

Usa `Path(SNAPSHOT_PATH_TPL.format(date=date or today)).open("a")` y escribe
una línea JSON con `json.dumps(snapshot, ensure_ascii=False) + "\n"`.

### Función `load_snapshots(date: str | None = None) -> list[dict]`

```python
def load_snapshots(date: str | None = None) -> list[dict]:
    """
    Carga todos los snapshots del día indicado.
    Retorna lista vacía si el fichero no existe o no hay líneas válidas.
    """
```

Lee el fichero JSONL línea a línea, ignora líneas malformadas con `try/except`.

### Función `detect_shift(prev: dict | None, curr: dict) -> dict | None`

```python
def detect_shift(prev: dict | None, curr: dict) -> dict | None:
    """
    Compara dos snapshots consecutivos y detecta desplazamientos significativos.

    Retorna un dict con los campos del shift, o None si no hay shift relevante.

    {
        "type":       str,    # "FLIP_SHIFT" | "CONTROL_NODE_SHIFT" | "BOTH"
        "flip_prev":  float | None,
        "flip_curr":  float | None,
        "cn_prev":    float | None,
        "cn_curr":    float | None,
        "spot":       float,
        "ts":         str,
    }
    """
```

Lógica:
```
flip_shift = prev y curr tienen flip_level distintos Y abs(curr_flip - prev_flip) >= GEX_SHIFT_ALERT_PTS
cn_shift   = prev y curr tienen control_node distintos Y abs(curr_cn - prev_cn) >= GEX_SHIFT_ALERT_PTS
             (incluyendo None → float o float → None como shift relevante si el régimen cambia)

si flip_shift y cn_shift → type = "BOTH"
si solo flip_shift       → type = "FLIP_SHIFT"
si solo cn_shift         → type = "CONTROL_NODE_SHIFT"
si ninguno               → retorna None
```

### Ejecución CLI

```python
if __name__ == "__main__":
    # Captura un snapshot inmediato y lo imprime (útil para debugging)
    snapshot = take_gex_snapshot(client=None, spot=None)
    print(json.dumps(snapshot, indent=2))
    save_snapshot(snapshot)
```

---

## 2. Integración en `scripts/mancini/monitor.py`

### Nuevas constantes

```python
GEX_POLL_INTERVAL_S = 600   # 10 minutos — igual que TWEET_POLL_INTERVAL_S
```

### Nuevo atributo en `ManciniMonitor.__init__`

```python
self._last_gex_snapshot: dict | None = None
self._last_gex_poll_ts:  float       = 0.0
```

### Nuevo método `_poll_gex(self, price: float) -> None`

```python
def _poll_gex(self, price: float) -> None:
    """
    Captura snapshot GEX intraday, lo persiste y detecta shifts.
    Llamado desde el bucle principal cuando toca el ciclo de 10 min.
    Solo activo durante la sesión regular (SESSION_START–SESSION_END ET).
    """
    from scripts.gex_intraday import take_gex_snapshot, save_snapshot, detect_shift

    now = _now_et()
    # Guard: solo durante sesión regular
    session_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    session_end   = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    if not (session_start <= now <= session_end):
        return

    snapshot = take_gex_snapshot(client=self._client, spot=price)
    if snapshot.get("status") != "OK":
        _log(f"GEX snapshot error: {snapshot.get('status')}")
        return

    save_snapshot(snapshot)

    shift = detect_shift(self._last_gex_snapshot, snapshot)
    if shift:
        _log(f"GEX shift detectado: {shift['type']}")
        notifier.notify_gex_shift(shift)

    self._last_gex_snapshot = snapshot
    _log(f"GEX snapshot OK — flip={snapshot.get('flip_level')} "
         f"CN={snapshot.get('control_node')} net={snapshot.get('net_gex_bn'):+.2f}B")
```

### Integración en el bucle principal `run()`

En el bucle `while True` del monitor, añadir el check de GEX junto al de tweets:

```python
# Ciclo GEX (cada 10 min, mismo intervalo que tweets)
now_ts = time.time()
if now_ts - self._last_gex_poll_ts >= GEX_POLL_INTERVAL_S:
    self._poll_gex(price)
    self._last_gex_poll_ts = now_ts
```

El GEX poll no bloquea el ciclo de precio (15s). Si `take_gex_snapshot` tarda más
de lo esperado, el bucle reanuda normalmente — el siguiente GEX poll se producirá
en el siguiente intervalo de 10 min.

---

## 3. Notificación de shift en `scripts/mancini/notifier.py`

### Nueva función `notify_gex_shift(shift: dict) -> None`

```python
def notify_gex_shift(shift: dict) -> None:
    """
    Envía alerta Telegram cuando el flip_level o control_node se desplazan > 10 pts.
    """
```

Formato del mensaje Telegram:

```
⚡ GEX Shift detectado

Tipo: FLIP_SHIFT
Flip: 5200 → 5185 (−15 pts)
CN:   5150 (sin cambio)
Spot: 5190 | 14:32 ET

Dealers SHORT gamma bajo 5185
```

El tipo puede ser `FLIP_SHIFT`, `CONTROL_NODE_SHIFT` o `BOTH`.
Solo se incluyen las líneas de los campos que cambiaron.

---

## 4. Almacenamiento y limpieza

- Los ficheros `outputs/gex_snapshots_YYYY-MM-DD.jsonl` se acumulan igual que los logs.
- No se sobreescriben entre ejecuciones del monitor (append-only).
- Limpieza manual: no automatizada. El usuario puede borrar ficheros viejos sin
  afectar al funcionamiento del sistema.
- No commitear `outputs/gex_snapshots_*.jsonl` (ya está en `.gitignore` por el patrón `outputs/`).

---

## 5. Tests

### `tests/test_gex_intraday.py`

```python
def test_save_and_load_snapshot(tmp_path):
    # Guardar snapshot → cargar → verificar que el contenido es idéntico
    ...

def test_load_snapshots_ignores_malformed_lines(tmp_path):
    # Fichero con una línea JSON válida + una malformada → carga solo la válida
    ...

def test_detect_shift_flip_above_threshold():
    prev = {"flip_level": 5200, "control_node": 5150, "spot": 5195}
    curr = {"flip_level": 5185, "control_node": 5150, "spot": 5190}  # flip cae 15 pts
    shift = detect_shift(prev, curr)
    assert shift["type"] == "FLIP_SHIFT"
    assert shift["flip_prev"] == 5200
    assert shift["flip_curr"] == 5185

def test_detect_shift_below_threshold_returns_none():
    prev = {"flip_level": 5200, "control_node": 5150, "spot": 5195}
    curr = {"flip_level": 5205, "control_node": 5150, "spot": 5200}  # flip sube 5 pts
    assert detect_shift(prev, curr) is None

def test_detect_shift_regime_change():
    # control_node era None (long gamma) → ahora es 5150 (short gamma)
    prev = {"flip_level": 5200, "control_node": None, "spot": 5210}
    curr = {"flip_level": 5200, "control_node": 5150, "spot": 5195}
    shift = detect_shift(prev, curr)
    assert shift is not None  # cambio de régimen siempre se alerta

def test_detect_shift_first_snapshot_no_alert():
    # Si no hay snapshot previo, no hay shift
    assert detect_shift(None, {"flip_level": 5200, "control_node": 5150}) is None
```

---

## Verificación

1. Ejecutar `uv run python scripts/gex_intraday.py` durante sesión — debe imprimir
   el snapshot y crear `outputs/gex_snapshots_YYYY-MM-DD.jsonl` con una línea JSON.
2. Ejecutar el monitor durante 20+ min — el fichero JSONL debe tener una línea cada ~10 min.
3. Verificar que si la cadena 0DTE devuelve error (`status != "OK"`), el monitor no falla
   y registra el error en log sin interrumpir el bucle de precio.
4. Simular shift: modificar manualmente `_last_gex_snapshot` con flip=5200 y forzar
   snapshot con flip=5185 → debe llegar alerta Telegram con tipo `FLIP_SHIFT`.
5. Verificar que fuera del horario de sesión (antes 9:30 o después 16:00 ET),
   `_poll_gex` retorna sin hacer ninguna llamada a la API.
