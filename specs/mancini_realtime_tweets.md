# Spec: Tweet fetcher en tiempo real — SearchTimeline

## Problema

`tweet_fetcher.py` usa el endpoint GraphQL `UserTweets` (GET) que tiene un cache
de ~1 hora en X. Esto hace que tweets nuevos de Mancini no aparezcan hasta mucho
después de ser publicados, haciendo inservible el scan automático para trading.

Ejemplo real (14 abril 2026): Mancini publicó un tweet a las 11:03 ET con targets
actualizados. El scan a las 11:47 ET no lo detectó — la API seguía devolviendo
tweets de las 10:04 ET como los más recientes.

Problema adicional: los hashes de los endpoints GraphQL de X (`queryId`) rotan
periódicamente con cada despliegue del frontend. El hash hardcodeado
`E3opETHurmVJflFsUBVuUQ` ya estaba obsoleto (el actual es otro). Si se hardcodea
el nuevo, volverá a romperse.

## Solución

### 1. Reemplazar UserTweets por SearchTimeline

Usar el endpoint `SearchTimeline` via **POST** con query `from:AdamMancini4`.
Este endpoint devuelve resultados del índice de búsqueda de X, que se actualiza
en tiempo real (segundos, no horas).

Diferencias clave vs UserTweets:

| Aspecto         | UserTweets (actual)     | SearchTimeline (nuevo)       |
|-----------------|-------------------------|------------------------------|
| Método HTTP     | GET                     | POST                         |
| Latencia        | ~1 hora (cache)         | Segundos (real-time)         |
| Input           | userId                  | rawQuery (`from:user`)       |
| Requiere userId | Sí (2 llamadas)        | No (1 llamada)               |

Estructura de la request POST:
```json
{
  "variables": {
    "rawQuery": "from:AdamMancini4",
    "count": 20,
    "querySource": "typed_query",
    "product": "Latest"
  },
  "features": { ... },
  "fieldToggles": { ... }
}
```

Estructura de la respuesta (misma que UserTweets para los entries):
```
data.search_by_raw_query.search_timeline.timeline.instructions[]
  → entries[] → content.itemContent.tweet_results.result.legacy.full_text
```

### 2. Auto-descubrimiento de hashes GraphQL

Los `queryId` de X rotan sin previo aviso. En vez de hardcodear, descubrirlos
en runtime:

1. `GET https://x.com` → extraer URLs de JS bundles del HTML
   (patrón: `https://abs.twimg.com/responsive-web/client-web*.js`)
2. Descargar cada bundle y buscar el patrón:
   `queryId:"<hash>",operationName:"SearchTimeline"`
3. Cachear el hash en memoria durante la vida del proceso

Fallback: si no se puede descubrir (x.com caído, cambio de estructura del JS),
lanzar `RuntimeError` con mensaje claro.

### 3. Features requeridas

SearchTimeline requiere un set de features más amplio que UserTweets (37 features
vs las 16 originales). Incluye features de Grok, cashtags, video screen, etc.
Se extraen de los mismos JS bundles y se hardcodean como dict porque cambian
con poca frecuencia (a diferencia de los hashes que rotan con cada deploy).

El `fieldToggles` también es requerido:
```json
{
  "withArticleRichContentState": true,
  "withArticlePlainText": false,
  "withGrokAnalyze": false,
  "withDisallowedReplyControls": false
}
```

## Cambios en ficheros

### `scripts/mancini/tweet_fetcher.py`

- **Eliminar**: `_get_user_id()`, `_get_user_tweets()`, `USER_FEATURES`, `TWEET_FEATURES`
- **Añadir**: `_discover_graphql_hash(operation)` — auto-discovery desde JS bundles
- **Añadir**: `_search_tweets(client, query, count)` — POST a SearchTimeline
- **Añadir**: `SEARCH_FEATURES`, `SEARCH_FIELD_TOGGLES` — features requeridas
- **Añadir**: `_hash_cache: dict` — cache en memoria de hashes descubiertos
- **Modificar**: `fetch_mancini_tweets()` → usa `_search_tweets()` en vez de
  `_get_user_id()` + `_get_user_tweets()`
- **Modificar**: `fetch_mancini_weekend_tweets()` → ídem

### `tests/test_mancini_tweet_fetcher.py`

- Actualizar mocks para reflejar la nueva estructura (POST en vez de GET,
  respuesta con `search_by_raw_query` en vez de `user.result.timeline_v2`)
- Añadir test para `_discover_graphql_hash()` (mock de httpx)
- Mantener tests de `_load_cookies`, `_build_client`, `_parse_x_datetime`

### `specs/mancini_replicant.md`

- Actualizar sección 7 (tweet_fetcher) para reflejar SearchTimeline + auto-discovery

## Verificación

1. `uv run pytest tests/test_mancini_tweet_fetcher.py` — todos los tests pasan
2. `uv run python scripts/mancini/tweet_fetcher.py` — devuelve tweets recientes
   de hoy (incluyendo los publicados en los últimos minutos)
3. Comparar timestamps del tweet más reciente devuelto vs hora actual — debe ser
   < 5 minutos si Mancini ha posteado recientemente
