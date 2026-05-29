# Fase 2 — Prioridad Alta

168/168 tests deben pasar después de cada fix. `docker compose down && docker compose up -d` para aplicar.

---

## Fix 1 — Consolidar 6 COUNT queries de analytics en 2

**Archivo:** `app/repositories/entrepreneur_repository.py`
**Método:** `get_poi_analytics` (líneas 232-292)

### Cambio exacto

Borrar TODAS las líneas 232-292 del método `get_poi_analytics` y reemplazar por:

**Paso 1 — Agregar import de `case`** (junto a los imports existentes de sqlalchemy, alrededor de línea 5-10):
```python
from sqlalchemy import and_, case, func, select
```

**Paso 2 — Reemplazar el cuerpo del método (líneas 233-292)** por este código exacto:

```python
    async def get_poi_analytics(self, db: AsyncSession, poi_id: UUID) -> POIAnalyticsResponse:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = this_month_start - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Query 1 — todas las métricas de visits en una sola consulta con FILTER
        visits_stmt = select(
            func.count().label("total_visits"),
            func.count().filter(POIVisit.created_at >= week_ago).label("weekly_visits"),
            func.count().filter(POIVisit.created_at >= this_month_start).label("this_month_visits"),
            func.count().filter(
                and_(POIVisit.created_at >= last_month_start, POIVisit.created_at <= last_month_end)
            ).label("last_month_visits"),
        ).where(POIVisit.poi_id == poi_id)
        visits_result = (await db.execute(visits_stmt)).one()

        # Query 2 — reviews y bookmarks
        reviews_stmt = select(
            func.count(Review.id).label("reviews_count"),
            func.coalesce(func.avg(Review.rating_stars), 0.0).label("avg_rating"),
        ).where(Review.poi_id == poi_id)
        reviews_result = (await db.execute(reviews_stmt)).one()

        favorites_count = await db.scalar(
            select(func.count()).select_from(Bookmark).where(Bookmark.poi_id == poi_id)
        )

        lm = int(visits_result.last_month_visits or 0)
        tm = int(visits_result.this_month_visits or 0)
        if lm == 0:
            monthly_growth = 1.0 if tm > 0 else 0.0
        else:
            monthly_growth = (tm - lm) / lm

        return POIAnalyticsResponse(
            visits_count=int(visits_result.total_visits or 0),
            favorites_count=int(favorites_count or 0),
            reviews_count=int(reviews_result.reviews_count or 0),
            avg_rating=float(reviews_result.avg_rating) if reviews_result.avg_rating is not None else 0.0,
            weekly_visits=int(visits_result.weekly_visits or 0),
            monthly_growth=round(monthly_growth, 4),
        )
```

**NO cambiar** el return type, las variables, ni los nombres de los campos. El método sigue devolviendo exactamente el mismo `POIAnalyticsResponse` con los mismos 6 campos.

**Verificar que los imports ya existen en el archivo:**
- `datetime`, `timedelta`, `timezone` (deben estar en los imports de arriba)
- `POIVisit`, `Bookmark`, `Review` (imports de modelos)
- `POIAnalyticsResponse` (import de schema)

**Resultado:** 6 queries → 3 queries (2 para visits+reviews agrupadas, 1 para bookmarks que es tabla distinta). Misma data, misma respuesta.

---

## Fix 2 — N+1 en bookmark.tourist.full_name en get_poi_activity

**Archivo:** `app/repositories/entrepreneur_repository.py`
**Método:** `get_poi_activity` (líneas 294-346)

### Cambio exacto

**Paso 1 — Agregar import** (si no existe, junto a los imports de sqlalchemy):
```python
from sqlalchemy.orm import selectinload
```

**Paso 2 — Cambiar SOLO la query de bookmarks (línea 308-309).**

DE:
```python
        bookmarks = await db.execute(
            select(Bookmark).where(Bookmark.poi_id == poi_id).order_by(Bookmark.created_at.desc()).limit(limit)
        )
```
A:
```python
        bookmarks = await db.execute(
            select(Bookmark)
            .where(Bookmark.poi_id == poi_id)
            .options(selectinload(Bookmark.tourist))
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
        )
```

**Nada más cambia.** Las otras 3 queries (reviews, posts, visits) se dejan exactamente igual. El sort en Python y el truncate `[:limit]` no se tocan.

**Por qué solo esto:** `bookmark.tourist.full_name` en línea 312 disparaba una query extra por cada bookmark. Con `selectinload(Bookmark.tourist)`, todos los tourist_profiles se cargan en UNA sola query. Las otras queries (reviews, posts, visits) no tienen este problema porque sus datos vienen directo.

---

## Fix 3 — Rate limiting en endpoints públicos de POIs

**Archivo:** `app/api/v1/endpoints/pois.py`

### Cambio exacto

**Paso 1 — Agregar import de limiter** (junto a los imports existentes, alrededor de línea 10-15):
```python
from app.core.rate_limit import limiter
```

**Paso 2 — Agregar decorador en `search_nearby_pois` (línea 208).**

DE:
```python
@router.get("/search", response_model=list[POIResponse])
async def search_nearby_pois(
```
A:
```python
@router.get("/search", response_model=list[POIResponse])
@limiter.limit("30/minute")
async def search_nearby_pois(
```

**Paso 3 — Agregar decorador en `semantic_search_pois` (línea 233).**

DE:
```python
@router.get("/semantic-search", response_model=list[POIResponse])
async def semantic_search_pois(
```
A:
```python
@router.get("/semantic-search", response_model=list[POIResponse])
@limiter.limit("10/minute")
async def semantic_search_pois(
```

**IMPORTANTE:** El decorador `@limiter.limit` va DEBAJO de `@router.get`. El orden correcto es:
```python
@router.get("/semantic-search", ...)
@limiter.limit("10/minute")
async def semantic_search_pois(...):
```

**Por qué 10/min para semantic-search y 30/min para search:**
- semantic-search gasta tokens OpenAI (embedding), más restrictivo
- search solo consulta PostgreSQL (geospatial), menos restrictivo

**La respuesta 429 ya está configurada** en `main.py:132-140` con mensaje en español. No hay que tocar nada más.

---

## Orden de implementación
1. Fix 2 (selectinload) — el más simple, 1 línea
2. Fix 1 (6 COUNT → 3 queries) — requiere reescribir el cuerpo del método
3. Fix 3 (rate limiting) — 2 decoradores + 1 import

## Verificación final
- 168/168 tests passing
- `docker compose down && docker compose up -d`
- Verificar que `get_poi_analytics` devuelva exactamente los mismos 6 campos que antes
- Verificar que `get_poi_activity` siga funcionando (especialmente los bookmarks con tourist_name)
