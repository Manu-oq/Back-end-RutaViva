# Fase 1 — Fixes Críticos

## Tarea 1 — Fix N+1 en Reviews ✅ (1/3 completado)

**Archivo:** `app/repositories/review_repository.py`

### Edit 1 — Import (COMPLETADO)
```python
# Línea 7, ya agregado
from sqlalchemy.orm import selectinload
```

### Edit 2 — Query con selectinload (PENDIENTE)
```python
# Línea 66 — CAMBIAR:
stmt = select(Review).where(Review.poi_id == poi_id).order_by(Review.created_at.desc())

# POR:
stmt = (
    select(Review)
    .where(Review.poi_id == poi_id)
    .options(selectinload(Review.tourist))
    .order_by(Review.created_at.desc())
)
```

### Edit 3 — _build_review_response sin db.get (PENDIENTE)
```python
# Líneas 20-21 — CAMBIAR:
tourist_profile = await db.get(TouristProfile, review.tourist_id)
author_name = tourist_profile.full_name if tourist_profile else None

# POR:
author_name = review.tourist.full_name if review.tourist else None
```

**Impacto:** 20 reviews con tourist: 21 queries → 1 query.
**Import existente:** `TouristProfile` sigue siendo necesario en línea 10 (usado en `create_review` para validación).
**Relación:** `Review.tourist` ya existe en `app/models/review.py:46` con `lazy="selectin"`.

---

## Tarea 2 — EmbeddingCache Global con TTL

### 2a) `app/services/embedding_service.py` — Agregar cache global

Agregar después de la clase `EmbeddingCache` (después de línea 43):

```python
import time
import asyncio


class GlobalEmbeddingCache:
    """Cache de embeddings a nivel de proceso con TTL. Sobrevive entre requests."""

    def __init__(self, service: OpenAIEmbeddingService, ttl_seconds: int = 900) -> None:
        self._service = service
        self._cache: dict[str, tuple[float, list[float]]] = {}
        self._ttl = ttl_seconds
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_embedding(self, text: str) -> list[float]:
        now = time.monotonic()
        if text in self._cache:
            expires, emb = self._cache[text]
            if now < expires:
                return emb
        lock = self._locks.setdefault(text, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if text in self._cache:
                expires, emb = self._cache[text]
                if now < expires:
                    return emb
            emb = await self._service.get_embedding(text)
            self._cache[text] = (now + self._ttl, emb)
            self._locks.pop(text, None)
            return emb


_global_embedding_cache: GlobalEmbeddingCache | None = None


def get_global_embedding_cache() -> GlobalEmbeddingCache:
    global _global_embedding_cache
    if _global_embedding_cache is None:
        _global_embedding_cache = GlobalEmbeddingCache(OpenAIEmbeddingService())
    return _global_embedding_cache
```

### 2b) Modificar `EmbeddingCache` para delegar al global

```python
# Líneas 35-43 — REEMPLAZAR la clase EmbeddingCache:
class EmbeddingCache:
    """Cache request-scoped que delega al GlobalEmbeddingCache."""

    def __init__(self, service: OpenAIEmbeddingService) -> None:
        self._service = service
        self._local: dict[str, list[float]] = {}
        self._global = get_global_embedding_cache()

    async def get_embedding(self, text: str) -> list[float]:
        if text not in self._local:
            self._local[text] = await self._global.get_embedding(text)
        return self._local[text]
```

### 2c) `app/services/ara_v2/memory_service.py` — Agregar batch store

Agregar método `store_facts_batch`:

```python
async def store_facts_batch(
    self,
    db: AsyncSession,
    tourist_id: UUID,
    session_id: UUID,
    facts: list[dict[str, Any]],
) -> None:
    """Store multiple facts efficiently using batch embedding."""
    if not facts:
        return
    textos = [f.get("hecho", "") for f in facts]
    categorias = [f.get("categoria", "general") for f in facts]
    confianzas = [f.get("confianza", 0.5) for f in facts]
    embeddings = await self._embedding_service.get_embeddings_batch(textos)
    for texto, categoria, confianza, embedding in zip(textos, categorias, confianzas, embeddings):
        memory = ConversationMemory(
            tourist_id=tourist_id,
            session_id=session_id,
            hecho=texto,
            categoria=categoria,
            confianza=confianza,
            embedding=embedding,
        )
        db.add(memory)
    await db.flush()
```

### 2d) `app/services/ara_v2/conversation_processor.py` — Usar batch

Buscar el loop donde itera sobre `comprehension.actualizaciones_memoria` y llama `memory_service.store_fact()` individualmente (líneas ~83-99). Cambiar para usar `store_facts_batch`:

```python
# ANTES (loop individual):
for fact in comprehension.actualizaciones_memoria:
    await memory_service.store_fact(db=db, tourist_id=tourist_id, session_id=session.id, hecho=fact.hecho, ...)

# DESPUÉS (batch):
facts_list = [
    {"hecho": f.hecho, "categoria": f.categoria, "confianza": f.confianza_temporal}
    for f in comprehension.actualizaciones_memoria
]
await memory_service.store_facts_batch(db=db, tourist_id=tourist_id, session_id=session.id, facts=facts_list)
```

**Nota:** Verificar los nombres exactos de los campos en `ComprehensionMemoryFact` (schema de `actualizaciones_memoria`) antes de implementar.

---

## Tarea 3 — Eliminar duplicación + código muerto

### Contexto
El frontend confirmó que **solo usa SSE** (`POST /generate-itinerary/stream`). 
Ni sync (`POST /generate-itinerary`) ni async (`POST /generate-itinerary/async`) se usan.

### 3a) Eliminar código muerto

#### `app/api/v1/endpoints/ara.py`

**Import removals:**
- Eliminar `from app.services.ara_itinerary_generation import generate_itinerary_from_session` (línea 31)
- Eliminar `from app.services.ara_itinerary_generation import run_ara_itinerary_generation_job` (línea 33)
- Eliminar `from app.services.llm_service import ItineraryGenerator, get_itinerary_generator` (línea 37, verificar si se usa en SSE)
- Eliminar `AraGenerateItineraryAcceptedResponse` de línea 17 (si no se usa en otro lado)
- Eliminar `AraGenerationStatusResponse` de línea 19 (si no se usa en otro lado)
- Eliminar `BackgroundTasks` del import de fastapi línea 7

**Route removals:**
- Borrar `POST /generate-itinerary` (líneas 91-114)
- Borrar `POST /generate-itinerary/async` (líneas 146-195)  
- Borrar `GET /generation-status` (líneas 198-230)

**Import a mantener:**
- `from app.services.llm_service import ItineraryGenerator, get_itinerary_generator` — SSE lo usa (línea 128)

#### `app/services/ara_itinerary_generation.py`
Borrar archivo completo (410 líneas, ya nadie lo llama).

#### `app/schemas/ara.py`
Verificar si `AraGenerateItineraryAcceptedResponse` y `AraGenerationStatusResponse` se usan en otro lado. Si no, borrar.

### 3b) Extraer core común

Crear `app/services/ara_itinerary_core.py` con función principal:

```python
async def generate_itinerary_core(
    db,
    session,
    user,
    payload,
    embedding_service,
    llm_service,
    *,
    on_phase: Callable[[str], Awaitable[None]] | None = None,
) -> tuple:
```

**Fases:**
1. `"validating"` — validar tourist_profile, session, coordinates
2. `"searching"` — build_refined_query, selected_poi_ids, search, merge, filter
3. `"weather"` — get_forecast
4. `"generating"` — enriched_query, schedule_guidance, llm call
5. `"repairing"` — 6 repairs + validate + blacklist + sanitize
6. `"saving"` — create_generated_itinerary

**Repair pipeline completo:**
```
normalize_generated_itinerary_times
→ repair_invalid_poi_ids
→ repair_latest_start_times
→ repair_lodging_duplicates
→ repair_duplicate_poi_steps
→ repair_schedule_and_category_issues
→ validate_generated_itinerary_rules
→ filter_blacklisted_context_pois
→ sanitize_generated_itinerary_context
```

### 3c) Refactorizar wrappers

#### `ara_streaming_service.py:stream_itinerary_generation()`
Reducir de ~300 líneas a ~40 líneas. Llamar a `generate_itinerary_core()` con callback SSE.

#### `tool_orchestrator.py:_build_itinerary()`
Reducir de ~110 líneas a ~20 líneas. Llamar a `generate_itinerary_core()` sin callback.

---

## Verificación post-implementación
- 168/168 tests deben seguir pasando
- `docker compose down && docker compose up -d`
- Probar flujo completo: mensaje → buscar POIs → generar itinerario por SSE
