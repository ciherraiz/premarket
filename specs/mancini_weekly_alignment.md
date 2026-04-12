# Weekly Alignment — Integración del Big Picture View en el monitor

## Objetivo

Usar el plan semanal (Big Picture View) como filtro de convicción para los trades
diarios. Los trades alineados con el sesgo semanal se operan normalmente; los trades
contra el sesgo se operan con restricciones o se descartan.

## Concepto de Alignment

```
ALIGNED     — trade va en dirección del sesgo semanal → operar normal
NEUTRAL     — no hay plan semanal o sesgo indeterminado → operar normal
MISALIGNED  — trade contra el sesgo semanal → restricciones
```

### Cálculo del sesgo semanal

A partir del `notes` del weekly plan (donde Haiku incluye "alcista"/"bajista"/"neutral"):
- Si notes contiene "alcista" → sesgo = BULLISH
- Si notes contiene "bajista" → sesgo = BEARISH
- Otro caso → sesgo = NEUTRAL

Alternativa robusta: si `key_level_upper` y `targets_upper` existen pero
`targets_lower` está vacío → BULLISH. Y viceversa.

### Cálculo de alignment por trade

| Sesgo semanal | Dirección trade | Alignment |
|---------------|----------------|-----------|
| BULLISH       | LONG           | ALIGNED   |
| BULLISH       | SHORT          | MISALIGNED|
| BEARISH       | SHORT          | ALIGNED   |
| BEARISH       | LONG           | MISALIGNED|
| NEUTRAL       | cualquiera     | NEUTRAL   |

## Comportamiento por alignment

### ALIGNED / NEUTRAL → operar normal
- Entry normal
- Target 1 parcial 50%, runner a Target 2+
- Sin restricciones

### MISALIGNED → restricciones
- Solo operar Target 1 (cerrar 100% en T1, sin runner)
- Log en trade: `alignment: "MISALIGNED"`
- Alerta Telegram incluye warning: "⚠️ Contra sesgo semanal"

## Targets extendidos con weekly

Si el trade es ALIGNED y el plan semanal tiene targets por encima de los
targets diarios, el runner puede usar el target semanal más cercano como
Target 2+ alternativo.

Lógica:
1. Targets base = `daily_plan.targets_upper`
2. Si ALIGNED y weekly tiene targets > último target diario:
   - Añadir el primer weekly target que supere el último daily target
3. Esto permite que el runner tenga más recorrido en días alineados

## Validación de niveles clave

Si el `key_level_lower` del plan diario coincide con un nivel del weekly
(diferencia < 3 pts), loguear como "nivel confluente" — esto es información
para el usuario, no cambia la lógica de trading automáticamente.

## Módulos afectados

### config.py
Sin cambios estructurales. Se usa `load_weekly()` existente.

### monitor.py

Cambios:
1. `load_state()` — cargar también `mancini_weekly.json` como `self.weekly`
2. Nuevo método `_calc_weekly_bias()` → "BULLISH" | "BEARISH" | "NEUTRAL"
3. Nuevo método `_calc_alignment(direction)` → "ALIGNED" | "NEUTRAL" | "MISALIGNED"
4. `_handle_transition()` al abrir trade:
   - Calcular alignment
   - Si MISALIGNED → pasar `runner_mode=False` al trade
   - Incluir alignment en logs y alertas
5. `_get_targets_for_level()`:
   - Si ALIGNED → enriquecer con targets semanales
6. `run()` — mostrar sesgo semanal al arrancar

### trade_manager.py

Cambios:
1. `open_trade()` — nuevo param opcional `runner_mode: bool = True`
   - Si `runner_mode=False`, solo incluir Target 1 en targets (forzar cierre en T1)
2. Campo `alignment` en Trade dataclass (para logging)

### notifier.py

Cambios:
1. `notify_signal()` — incluir alignment info si MISALIGNED
2. Nuevo formato: "⚠️ Contra sesgo semanal — solo T1"

### logger.py
Sin cambios. El campo `alignment` se guarda automáticamente via `trade.to_dict()`.

## Tests

- `test_calc_weekly_bias`: BULLISH/BEARISH/NEUTRAL desde notes y targets
- `test_calc_alignment`: matriz sesgo × dirección
- `test_misaligned_trade_only_t1`: trade MISALIGNED cierra 100% en T1
- `test_aligned_trade_extended_targets`: targets semanales añadidos al runner
- `test_no_weekly_plan_neutral`: sin plan semanal → NEUTRAL → operar normal
- `test_alignment_in_notification`: alerta incluye warning si MISALIGNED
