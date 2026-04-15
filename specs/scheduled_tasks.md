# Tareas programadas — Referencia completa

Documento de referencia para todas las tareas automáticas del sistema.
Cada sesión de Claude Code debe recrear estos crons al inicio.

---

## 1. Mancini Scan (diario, entre semana)

**Skill**: `/mancini-scan`
**Ventana**: 07:00–11:30 ET (13:00–17:30 CEST)
**Cadencia spec**: cada 10 min (ver nota abajo)

### Crons prácticos (3 disparos en momentos clave)

| Cron (CEST) | Hora ET | Propósito |
|---|---|---|
| `3 13 * * 1-5` | 07:03 ET | Captura plan inicial de Mancini |
| `3 14 * * 1-5` | 08:03 ET | Captura actualizaciones pre-apertura |
| `3 15 * * 1-5` | 09:03 ET | Última revisión antes de las 09:25 ET |

> **Nota**: el spec (`mancini_replicant.md`) define scan cada 10 min, pero cada
> invocación es un skill de Claude (costoso). 3 disparos cubren los momentos
> críticos. Si se migra a un script Python standalone, usar `*/10 13-17 * * 1-5`.

---

## 2. Mancini Monitor (diario, entre semana)

**Skill**: `/mancini-monitor`
**Ventana**: 08:00–16:00 ET (14:00–22:00 CEST)
**Cadencia**: una sola invocación (el monitor corre su propio loop de polling cada 60s)

| Cron (CEST) | Hora ET | Propósito |
|---|---|---|
| `7 14 * * 1-5` | 08:07 ET | Arranca monitor (auto-para a las 16:00 ET) |

**Prerequisito**: el scan debe haber cargado `outputs/mancini_plan.json` antes.
El cron de 14:07 se ejecuta 4 minutos después del scan de 14:03, dando margen
para que el plan esté listo.

---

## 3. Mancini Weekly Scan (fines de semana)

**Skill**: `/mancini-weekly-scan`
**Días**: sábado y domingo
**Hora**: 18:00 CEST (12:00 ET)

| Cron (CEST) | Días | Propósito |
|---|---|---|
| `3 18 * * 0,6` | sáb, dom | Captura "Big Picture View" semanal de Mancini |

> Mancini publica su visión semanal durante el fin de semana. Se ejecuta ambos
> días porque a veces publica el sábado y a veces el domingo.

---

## 4. SPX Premarket Analysis (entre semana)

**Skill**: `/premarket-analysis`
**Spec**: `specs/skill_premarket_analysis.md`

| Cron (ET) | Hora CEST | Propósito |
|---|---|---|
| `10 9 * * 1-5` | 15:10 CEST | Scorecard premarket (orientativo) |
| `15 10 * * 1-5` | 16:15 CEST | Scorecard open phase (decisión final) |

> Estos se crean con `mcp__scheduled-tasks__create_scheduled_task` usando
> timezone `America/New_York`. Ver spec para detalles.

---

## Resumen visual — Día entre semana (horario CEST)

```
13:00 ─── Ventana scan abierta ──────────────────────────────────────
13:03     /mancini-scan          ← plan inicial
14:00 ─── Ventana monitor abierta ───────────────────────────────────
14:03     /mancini-scan          ← actualización pre-apertura
14:07     /mancini-monitor       ← arranca polling /ES
15:03     /mancini-scan          ← última revisión
15:10     /premarket-analysis    ← scorecard premarket
15:30 ─── Apertura mercado (09:30 ET) ───────────────────────────────
16:15     /premarket-analysis    ← scorecard open (decisión)
17:30 ─── Fin ventana scan ──────────────────────────────────────────
22:00 ─── Fin ventana monitor ───────────────────────────────────────
```

## Resumen visual — Fin de semana (horario CEST)

```
18:03     /mancini-weekly-scan   ← Big Picture View semanal
```

---

## Limitaciones actuales

- **Session-only**: los crons de CronCreate solo viven mientras la sesión de
  Claude Code esté abierta. Si se cierra, hay que recrearlos.
- **Auto-expire**: los crons recurrentes se auto-eliminan tras 7 días.
- **No persistentes**: aunque se use `durable: true`, actualmente no se
  escriben a disco.

### Solución futura

Migrar los scans a scripts Python standalone invocados por el scheduler del
sistema operativo (Task Scheduler en Windows, cron en Linux) para eliminar
la dependencia de una sesión Claude activa.
