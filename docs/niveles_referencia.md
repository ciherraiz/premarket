# Niveles de Referencia — Glosario

Referencia de los niveles técnicos y GEX utilizados en las notificaciones del sistema.

---

## Niveles GEX (Gamma Exposure)

Calculados en tiempo real a partir de la cadena de opciones SPXW 0DTE.

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **FLIP** | Gamma Flip Level | Precio donde los dealers pasan de largo a corto gamma. **Por encima:** el mercado tiende a estabilizarse (dealers cubren movimientos). **Por debajo:** los movimientos se amplifican. Nivel más importante del perfil GEX. |
| **CALL WALL** | Call Wall | Strike con mayor concentración de GEX positivo. Los dealers venden delta al acercarse el precio → actúa como **resistencia**. |
| **PUT WALL** | Put Wall | Strike con mayor concentración de GEX negativo. Los dealers compran delta al acercarse el precio → actúa como **soporte**. |
| **CN** | Control Node | Strike de máxima exposición gamma negativa. En régimen SHORT gamma es el nivel de mayor presión bajista. Coincide frecuentemente con el Put Wall. |

---

## Niveles del Día Anterior (Prior Day)

Calculados al cierre de la sesión regular anterior.

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **PDH** | Prior Day High | Máximo del día anterior. Resistencia frecuente en apertura. |
| **PDL** | Prior Day Low | Mínimo del día anterior. Soporte frecuente en apertura. |
| **PDC** | Prior Day Close | Cierre del día anterior. Referencia de equilibrio para el gap de apertura. |

---

## Pivots Diarios

Calculados a partir de PDH, PDL y PDC. Miden zonas de extensión respecto al equilibrio del día anterior.

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **PP_D** | Pivot Point diario | Precio de equilibrio de referencia. Por encima → sesgo alcista intradía. Por debajo → sesgo bajista. |
| **R1_D** | Resistance 1 diaria | Primera extensión alcista sobre el pivot. Objetivo natural en días alcistas. |
| **R2_D** | Resistance 2 diaria | Segunda extensión alcista. Objetivo en días de momentum fuerte. |
| **S1_D** | Support 1 diaria | Primera extensión bajista bajo el pivot. Objetivo natural en días bajistas. |
| **S2_D** | Support 2 diaria | Segunda extensión bajista. Objetivo en días de momentum bajista fuerte. |

---

## Niveles Semanales (Prior Week)

Calculados al cierre de la semana anterior. Más fiables que los diarios para niveles de ruptura y zonas de reversión.

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **PWH** | Prior Week High | Máximo de la semana anterior. Resistencia de alta relevancia. |
| **PWL** | Prior Week Low | Mínimo de la semana anterior. Soporte de alta relevancia. |
| **PWC** | Prior Week Close | Cierre de la semana anterior. Referencia para el sesgo semanal. |
| **PP_W** | Pivot Point semanal | Equilibrio de la semana. Usado como filtro de sesgo direccional. |
| **R1_W** | Resistance 1 semanal | Primera extensión alcista semanal. |
| **S1_W** | Support 1 semanal | Primera extensión bajista semanal. |

---

## Niveles Mensuales (Prior Month)

Calculados al cierre del mes anterior. Relevantes principalmente como zonas de control macro.

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **PMH** | Prior Month High | Máximo del mes anterior. Resistencia macro. |
| **PMC** | Prior Month Close | Cierre del mes anterior. Referencia de sesgo mensual. |
| **PML** | Prior Month Low | Mínimo del mes anterior. Soporte macro. |

---

## Niveles Overnight Globex

Calculados de la sesión nocturna de futuros /ES (18:00 ET del día anterior → 09:29 ET de hoy).

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **ONH** | Overnight High | Máximo de la sesión nocturna. Resistencia clave en los primeros 30 minutos de sesión regular. Una ruptura confirma momentum alcista. |
| **ONL** | Overnight Low | Mínimo de la sesión nocturna. Soporte clave en apertura. Una ruptura confirma momentum bajista. |

---

## Round Numbers

| Label | Nombre completo | Significado operacional |
|---|---|---|
| **RND_7200** | Número redondo | Múltiplos de 25 puntos (7000, 7025, 7050…). Visibles para todos los participantes, actúan como imán de precio y zonas de acumulación de órdenes. Su relevancia aumenta cuando coinciden con niveles GEX o técnicos. |

---

## Régimen GEX

El régimen determina el **comportamiento esperado del mercado**, no la dirección.

| Signal | Significado |
|---|---|
| **LONG_GAMMA_FUERTE** | Dealers LONG gamma fuerte. El mercado tiende a mean-reversion. Movimientos contenidos, rebotes comprados y caídas vendidas. Rango estrecho probable. |
| **LONG_GAMMA_SUAVE** | Dealers LONG gamma moderado. Tendencia a estabilizarse pero con algo más de volatilidad que el caso fuerte. |
| **SHORT_GAMMA_SUAVE** | Dealers SHORT gamma moderado. Movimientos algo amplificados. Rebotes débiles, sin cobertura intensa. |
| **SHORT_GAMMA_FUERTE** | Dealers SHORT gamma fuerte. Movimientos tendenciales y amplificados en ambas direcciones. Caídas se aceleran, rebotes no son confiables. |
