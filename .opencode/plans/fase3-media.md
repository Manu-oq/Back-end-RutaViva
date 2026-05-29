# Fase 3 — Prioridad Media

168/168 tests deben pasar después de cada fix. `docker compose down && docker compose up -d` al final.

---

## Fix 12 — Credenciales de DB no hardcodeadas

**Archivo:** `docker-compose.yml`
**Líneas:** 36-37

### Cambio exacto

DE:
```yaml
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: admin
      POSTGRES_DB: rutaviva_db
```

A:
```yaml
      POSTGRES_USER: ${POSTGRES_USER:-admin}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-admin}
      POSTGRES_DB: ${POSTGRES_DB:-rutaviva_db}
```

**¿Qué hace?** Si las variables de entorno `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` existen, las usa. Si no, usa `admin/admin/rutaviva_db` como fallback. En desarrollo no cambia nada (no están definidas en .env para DB). En producción se sobreescriben.

**Nada más cambia en este archivo.**

**Rebuild:** `docker compose down && docker compose up -d`

---

## Fix 13 — Migrar bcrypt_sha256 a bcrypt

**Archivo:** `app/core/security.py`
**Línea:** 11

### Cambio exacto

DE:
```python
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
```

A:
```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

**¿Rompe contraseñas existentes?** NO. Passlib con `deprecated="auto"` puede verificar hashes viejos (`bcrypt_sha256`) y automáticamente los migra a `bcrypt` en el próximo login. Es transparente.

**Nada más cambia en este archivo.**

---

## Fix 16 — Eliminar refreshes N+1 en itinerary_repository

**Archivo:** `app/repositories/itinerary_repository.py`

### Contexto

Cada vez que se hace un commit de mutación (create, update step, add step, delete, reorder, reschedule), el código hace:

```python
await db.refresh(itinerary, ["steps"])       # 1 query
for step in itinerary.steps:
    await db.refresh(step, ["poi"])          # 1 query por step = N queries
return self._to_response(itinerary)
```

Para un itinerario de 10 steps: 11 queries solo para devolver la respuesta.

El método `get_itinerary_by_id` (línea 97-116) YA existe y hace lo mismo en 2 queries usando `selectinload(Itinerary.steps).selectinload(ItineraryStep.poi)`.

### Cambio exacto

Reemplazar el patrón de refresh en **8 ubicaciones**. En CADA una:

**DE:**
```python
        await db.refresh(itinerary, ["steps"])
        for step in itinerary.steps:
            await db.refresh(step, ["poi"])
        return self._to_response(itinerary)
```

**A:**
```python
        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)
```

### Ubicaciones exactas (8 en total)

| # | Método | Líneas a reemplazar | Nota |
|---|--------|---------------------|------|
| 1 | `create_generated_itinerary` | 83-86 | También necesita `tourist_id` como variable disponible |
| 2 | `update_step` | 252-255 | `tourist_id` ya es parámetro |
| 3 | `add_step` | 298-301 | `tourist_id` ya es parámetro |
| 4 | `update_status` | 318-321 | `s` → `step` (la variable se llama `s` en el loop, renombrar a `step` en la línea del DE) |
| 5 | `delete_step` | 366-369 | `step` es la variable del loop |
| 6 | `reorder_steps` | 402-405 | `step` es la variable del loop |
| 7 | `reschedule_step` | 468-471 | `step` es la variable del loop |
| 8 | `reorder_steps_with_times` | 565-568 | `step` (verificar nombre de variable en el loop) |

**IMPORTANTE:** En el DE de cada ubicación, respetar si la variable del loop se llama `step` o `s`. El patrón a buscar es exactamente 3 líneas:
1. `await db.refresh(itinerary, ["steps"])`
2. `for step in itinerary.steps:` (o `for s in itinerary.steps:`)
3. `    await db.refresh(step, ["poi"])` (o `    await db.refresh(s, ["poi"])`)
4. `return self._to_response(itinerary)`

Las 4 líneas se reemplazan por 1 sola:
```python
        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)
```

**Verificar que `tourist_id` esté disponible** en cada método. Todos los métodos reciben `tourist_id` como parámetro o lo tienen en una variable local. Revisar que `create_generated_itinerary` recibe `tourist_id` como parámetro.

**Nada más cambia en este archivo.**

---

## Orden de implementación

1. Fix 13 (bcrypt) — 1 línea, sin riesgo
2. Fix 12 (docker-compose creds) — 3 líneas
3. Fix 16 (N+1 refreshes) — 8 ubicaciones, 1 línea cada una

## Verificación final

- 168/168 tests passing
- `docker compose down && docker compose up -d`
- Verificar que login/logout sigan funcionando (bcrypt migration)
- Verificar que la DB levante con las credenciales por defecto (`admin/admin`)
- Verificar que los métodos del itinerary_repository sigan devolviendo `ItineraryResponse` con steps y POIs cargados
