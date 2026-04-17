# Plan Chart — Visualización gráfica del plan Mancini

## Objetivo

Generar una imagen (PNG) que muestre visualmente la situación actual del
plan Mancini: niveles clave, targets, precio actual de /ES, estado de los
detectores y trade activo. Enviarla a Telegram en momentos clave para que
el trader vea de un vistazo dónde está el precio respecto al plan.

## Problema actual

Las notificaciones de Telegram son texto plano con números. Para evaluar
la situación hay que reconstruir mentalmente la posición del precio
respecto a los niveles. Un gráfico lo hace instantáneo.

---

## Diseño del gráfico

### Layout: eje vertical de precio

El gráfico es un eje vertical de precio con líneas horizontales anotadas.
No es un gráfico temporal (no hay eje X de tiempo), sino un **mapa de
niveles** con el precio actual como referencia.

```
 ┌────────────────────────────────────────────────────────┐
 │                                                        │
 │  7200 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 5       │
 │  7188 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 4       │
 │  7177 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 3 ✓     │
 │  7154 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 2 ✓     │
 │  7131 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 1 ✓     │
 │                                                        │
 │  ▶ 7112 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ES actual       │
 │                                                        │
 │  7058 ══════════════════════════════  VIGILANDO         │
 │                                       Nivel clave      │
 │                                       upper            │
 │                                                        │
 │  6950 ══════════════════════════════  BREAKDOWN         │
 │                                       Nivel clave      │
 │                                       lower             │
 │                                       -3 pts bajo nivel│
 │                                                        │
 │  6920 ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  Target 1 ↓     │
 │                                                        │
 └────────────────────────────────────────────────────────┘
   Mancini Plan | 2026-04-17 | 12:32 ET
```

### Elementos del gráfico

**1. Precio actual /ES**
- Línea horizontal gruesa con triángulo `▶` a la izquierda
- Etiqueta: precio numérico + "ES actual"
- Color: azul

**2. Niveles clave (key_level_upper, key_level_lower)**
- Línea horizontal doble (gruesa, prominente)
- Color: según estado (ver abajo)
- Etiqueta a la derecha con estado del detector en texto claro:

| Estado detector | Texto en etiqueta | Color línea |
|---|---|---|
| WATCHING | `VIGILANDO — esperando breakdown` | gris |
| BREAKDOWN | `BREAKDOWN — X pts bajo nivel` | naranja |
| RECOVERY | `RECUPERANDO — X polls confirmando` | amarillo |
| SIGNAL | `SEÑAL CONFIRMADA` | verde |
| ACTIVE | `TRADE ACTIVO` | verde |
| DONE | `COMPLETADO` | gris claro |
| EXPIRED | `EXPIRADO` | gris claro |

**3. Targets**
- Líneas horizontales punteadas finas
- Etiqueta: "Target N" con `✓` si alcanzado
- Targets alcanzados: color gris atenuado
- Targets pendientes: color verde (upper) o rojo (lower)

**4. Trade activo (si existe)**
- Línea de entry: verde, etiqueta "Entry XXXX"
- Línea de stop actual: roja, etiqueta "Stop XXXX"
- Zona sombreada semitransparente entre entry y stop (riesgo)
- Texto informativo junto al nivel clave:
  ```
  Trade LONG: entry 7060
  Stop: 7131 (breakeven en T1)
  Targets hit: 2/5
  ```

**5. Chop zone (si existe)**
- Banda sombreada amarilla semitransparente entre los dos precios
- Etiqueta: "Chop zone"

**6. Título y metadata**
- Parte inferior: `Mancini Plan | YYYY-MM-DD | HH:MM ET`

### Estilo visual

- Fondo oscuro (estilo "dark") — legible en Telegram con tema oscuro y claro
- Fuente monoespaciada para alineación
- Tamaño: 800x600 px (buena resolución en Telegram sin ser excesivo)
- Márgenes generosos a la derecha para las etiquetas de texto

---

## Módulo: `scripts/mancini/chart.py`

### Función principal

```python
def generate_plan_chart(
    plan: DailyPlan,
    es_price: float,
    detectors: list[FailedBreakdownDetector],
    trade: Trade | None = None,
    timestamp_et: str = "",
) -> bytes:
    """Genera PNG del plan Mancini con precio actual.

    Args:
        plan: plan del día con niveles y targets
        es_price: precio actual de /ES
        detectors: lista de detectores con su estado
        trade: trade activo (None si no hay)
        timestamp_et: hora ET para el título

    Returns:
        Bytes del PNG generado.
    """
```

### Lógica de rendering

```python
import io
import matplotlib
matplotlib.use("Agg")  # backend sin GUI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def generate_plan_chart(...) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 6))

    # Estilo oscuro
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # Recopilar todos los niveles para calcular rango del eje Y
    levels = []
    if plan.key_level_upper is not None:
        levels.append(plan.key_level_upper)
    if plan.key_level_lower is not None:
        levels.append(plan.key_level_lower)
    levels.extend(plan.targets_upper)
    levels.extend(plan.targets_lower)
    levels.append(es_price)
    if trade:
        levels.extend([trade.entry_price, trade.stop_price])

    y_min = min(levels) - 15
    y_max = max(levels) + 15

    ax.set_ylim(y_min, y_max)
    ax.set_xlim(0, 1)
    ax.set_xticks([])  # sin eje X

    # 1. Dibujar targets
    for i, target in enumerate(plan.targets_upper):
        hit = trade and trade.targets_hit > i
        color = "#555555" if hit else "#4ecca3"
        label = f"Target {i+1} ✓" if hit else f"Target {i+1}"
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=0.7)
        ax.text(0.72, target, f"{target:.0f}  {label}",
                color=color, fontsize=9, va="center",
                fontfamily="monospace")

    for i, target in enumerate(plan.targets_lower):
        color = "#e74c3c"
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=0.7)
        ax.text(0.72, target, f"{target:.0f}  Target {i+1} ↓",
                color=color, fontsize=9, va="center",
                fontfamily="monospace")

    # 2. Dibujar niveles clave con estado del detector
    for detector in detectors:
        color, status_text = _detector_style(detector)
        ax.axhline(y=detector.level, color=color, linewidth=2.5, alpha=0.9)
        side_label = "upper" if detector.side == "upper" else "lower"
        ax.text(0.72, detector.level,
                f"{detector.level:.0f}  Nivel {side_label}\n"
                f"         {status_text}",
                color=color, fontsize=9, va="center",
                fontweight="bold", fontfamily="monospace")

    # 3. Chop zone
    if plan.chop_zone:
        ax.axhspan(plan.chop_zone[0], plan.chop_zone[1],
                   color="#f1c40f", alpha=0.1)
        mid = (plan.chop_zone[0] + plan.chop_zone[1]) / 2
        ax.text(0.05, mid, "Chop zone", color="#f1c40f",
                fontsize=9, alpha=0.7, fontfamily="monospace")

    # 4. Trade activo
    if trade:
        # Entry
        ax.axhline(y=trade.entry_price, color="#2ecc71",
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.entry_price,
                f"▶ Entry {trade.entry_price:.0f}",
                color="#2ecc71", fontsize=9, fontweight="bold",
                fontfamily="monospace")
        # Stop
        ax.axhline(y=trade.stop_price, color="#e74c3c",
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.stop_price,
                f"✖ Stop {trade.stop_price:.0f}",
                color="#e74c3c", fontsize=9, fontweight="bold",
                fontfamily="monospace")
        # Zona de riesgo
        ax.axhspan(min(trade.entry_price, trade.stop_price),
                   max(trade.entry_price, trade.stop_price),
                   color="#e74c3c", alpha=0.08)

    # 5. Precio actual
    ax.axhline(y=es_price, color="#3498db", linewidth=3, alpha=0.9)
    ax.text(0.02, es_price,
            f"▶ ES {es_price:.2f}",
            color="#3498db", fontsize=11, fontweight="bold",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e",
                      edgecolor="#3498db", alpha=0.9))

    # 6. Título
    fecha = plan.fecha
    ax.set_title(f"Mancini Plan  |  {fecha}  |  {timestamp_et}",
                 color="white", fontsize=11, fontfamily="monospace",
                 pad=10)

    # Estilo del eje Y
    ax.tick_params(axis="y", colors="white", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_color("#555555")

    plt.tight_layout()

    # Exportar a bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _detector_style(detector) -> tuple[str, str]:
    """Retorna (color, texto_estado) para un detector."""
    match detector.state.value:
        case "WATCHING":
            return "#888888", "VIGILANDO — esperando breakdown"
        case "BREAKDOWN":
            depth = ""
            if detector.breakdown_low is not None:
                pts = abs(detector.level - detector.breakdown_low)
                depth = f" ({pts:.0f} pts bajo nivel)"
            return "#e67e22", f"BREAKDOWN{depth}"
        case "RECOVERY":
            polls = getattr(detector, "acceptance_count", "?")
            return "#f1c40f", f"RECUPERANDO — {polls} polls confirmando"
        case "SIGNAL":
            return "#2ecc71", "SEÑAL CONFIRMADA"
        case "ACTIVE":
            return "#2ecc71", "TRADE ACTIVO"
        case "DONE":
            return "#555555", "COMPLETADO"
        case "EXPIRED":
            return "#555555", "EXPIRADO"
        case _:
            return "#888888", detector.state.value
```

---

## Envío a Telegram

### Nuevo método en `scripts/notify_telegram.py`

```python
TELEGRAM_PHOTO_API = "https://api.telegram.org/bot{token}/sendPhoto"

def send_telegram_photo(photo_bytes: bytes, caption: str = "") -> bool:
    """Envía imagen PNG a Telegram."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = TELEGRAM_PHOTO_API.format(token=token)
    files = {"photo": ("plan_chart.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption

    resp = httpx.post(url, data=data, files=files, timeout=15)
    return resp.is_success
```

### Nuevo método en `scripts/mancini/notifier.py`

```python
def notify_plan_chart(plan, es_price, detectors, trade=None) -> bool:
    """Genera y envía gráfico del plan a Telegram."""
    from scripts.mancini.chart import generate_plan_chart

    timestamp_et = _now_et().strftime("%H:%M ET")
    png_bytes = generate_plan_chart(
        plan=plan,
        es_price=es_price,
        detectors=detectors,
        trade=trade,
        timestamp_et=timestamp_et,
    )
    return send_telegram_photo(png_bytes, caption=f"📊 Plan Mancini | {plan.fecha}")
```

---

## Integración en monitor.py

### Cuándo generar y enviar

```python
# En _scan_for_plan(), tras crear el plan:
notifier.notify_plan_chart(self.plan, price, self.detectors)

# En _handle_transition(), al detectar BREAKDOWN:
elif t.to_state == State.BREAKDOWN:
    ...
    price = ...
    notifier.notify_plan_chart(self.plan, price, self.detectors,
                                self.trade_manager.active_trade())

# En _handle_transition(), al abrir trade (SIGNAL):
elif t.to_state == State.SIGNAL:
    ...
    notifier.notify_plan_chart(self.plan, price, self.detectors, trade)

# En _handle_trade_event(), al alcanzar target:
if event["type"] == "TARGET_HIT":
    ...
    notifier.notify_plan_chart(self.plan, event["price"], self.detectors,
                                self._find_trade(event["trade_id"]))

# En check_intraday_updates(), tras ajuste que modifica niveles:
if adj.adjustment_type in ("LEVEL_UPDATE", "TARGET_UPDATE", "INVALIDATION"):
    price = self.poll_es()
    if price:
        notifier.notify_plan_chart(self.plan, price, self.detectors,
                                    self.trade_manager.active_trade())
```

### Resumen de eventos que generan gráfico

| Evento | ¿Chart? | Razón |
|---|---|---|
| Plan creado | ✅ | Situación inicial del día |
| BREAKDOWN detectado | ✅ | Acción importante, ver contexto |
| SIGNAL / trade abierto | ✅ | Momento clave, ver entry/stop/targets |
| TARGET_HIT | ✅ | Trailing stop movido |
| LEVEL_UPDATE intraday | ✅ | Niveles cambiaron |
| TARGET_UPDATE intraday | ✅ | Targets cambiaron |
| INVALIDATION intraday | ✅ | Detectores desactivados |
| BIAS_SHIFT | ❌ | No cambia niveles visuales |
| CONTEXT_UPDATE | ❌ | Solo informativo |
| Tick normal sin evento | ❌ | Demasiado frecuente |
| Cierre de sesión | ❌ | No aporta valor visual |

---

## Dependencias

- `matplotlib` — ya en el proyecto (usado por `analyze_predictability.py`)
- No se necesitan dependencias nuevas

---

## Módulos afectados

### Nuevos
- `scripts/mancini/chart.py` — generación del gráfico

### Modificados
- `scripts/notify_telegram.py` — añadir `send_telegram_photo()`
- `scripts/mancini/notifier.py` — añadir `notify_plan_chart()`
- `scripts/mancini/monitor.py` — llamar a `notify_plan_chart()` en eventos clave

---

## Tests

### test_chart.py
- `test_generate_chart_basic`: plan con niveles + precio → PNG válido (bytes no vacíos, header PNG)
- `test_generate_chart_with_trade`: plan + trade activo → PNG incluye entry/stop
- `test_generate_chart_with_targets_hit`: targets alcanzados se marcan ✓
- `test_generate_chart_no_detectors`: plan sin detectores → no falla
- `test_generate_chart_chop_zone`: plan con chop zone → no falla
- `test_generate_chart_detector_states`: cada estado genera texto correcto
- `test_generate_chart_only_upper_level`: plan con solo key_level_upper → no falla
- `test_generate_chart_returns_valid_png`: los primeros bytes son `\x89PNG`

### test_notify_telegram_photo.py
- `test_send_photo_success`: mock httpx → True
- `test_send_photo_no_credentials`: sin token → False
- `test_send_photo_with_caption`: caption incluido en la request
