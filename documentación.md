# Documentación Técnica — Backend Ruta Viva

> Última actualización integral: **2026-05-27**
>
> Este documento describe la arquitectura, decisiones técnicas, flujos de datos y contratos del backend de Ruta Viva. Está dirigido a desarrolladores que necesitan entender, mantener o extender el sistema.

---

## 1. Stack tecnológico

| Componente | Tecnología | Versión/Detalle |
|------------|-----------|-----------------|
| Lenguaje | Python | 3.13 |
| Framework web | FastAPI | 0.115+ |
| ORM | SQLAlchemy | 2.0 (async) |
| Driver DB | asyncpg | — |
| Base de datos | PostgreSQL | 16 (Docker) |
| Extensiones DB | pgvector, PostGIS | — |
| Migraciones | Alembic | — |
| Validación | Pydantic v2 | — |
| Hashing | Passlib + bcrypt | — |
| JWT | python-jose | — |
| Rate Limiting | slowapi | — |
| LLM Embeddings | OpenAI text-embedding-3-small | 1536 dimensiones |
| LLM Chat | OpenAI GPT-4o-mini | Comprensión conversacional |
| LLM Generation | DeepSeek | Generación de itinerarios |
| Clima | OpenWeatherMap | One Call API 3.0 |
| Geocoding | Nominatim (OSM) | Forward geocoding |
| Contenedores | Docker + Docker Compose | — |
| Tests | pytest | asyncio_mode=auto |

---

## 2. Arquitectura general

### 2.1 Patrón de capas

```
┌─────────────────────────────────────────────────────────┐
│  api/v1/endpoints/     ← Handlers HTTP delgados         │
│  (reciben request, delegan a services, devuelven)       │
├─────────────────────────────────────────────────────────┤
│  services/             ← Lógica de negocio + IA         │
│  (orquestan flujos, integran APIs externas)             │
├─────────────────────────────────────────────────────────┤
│  repositories/         ← Acceso a datos                 │
│  (queries SQLAlchemy, N+1 prevention, eager loading)    │
├─────────────────────────────────────────────────────────┤
│  models/               ← Entidades ORM                  │
│  (tablas, relaciones, constraints)                      │
├─────────────────────────────────────────────────────────┤
│  schemas/              ← Contratos Pydantic             │
│  (request/response validation, serialización)           │
├─────────────────────────────────────────────────────────┤
│  core/                 ← Infraestructura transversal    │
│  (config, security, exceptions, rate_limit, timezone)   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Principios de diseño

1. **Endpoints delgados**: Reciben request, validan con Pydantic, delegan a services, devuelven response. Sin lógica de negocio inline. Máximo ~50 líneas por handler.
2. **Services con responsabilidad única**: Cada service hace una cosa. Si crece demasiado, se parte en sub-módulos.
3. **Repositories con eager loading explícito**: Toda query que expone relaciones usa `.options(selectinload(...))`. Nunca se confía en lazy loading.
4. **Excepciones de dominio**: Los services lanzan `AppError` o `PermissionError`. Solo `main.py` sabe de HTTP status codes.
5. **Settings tipados**: Toda configuración externa pasa por `Settings` de Pydantic, con defaults seguros y validación.
6. **Async end-to-end**: Desde el handler HTTP hasta la query SQL, todo es async. No hay bloqueos de thread pool.

---

## 3. Estructura del proyecto

```
ruta_viva/
├── app/
│   ├── main.py                    # FastAPI app, middleware, exception handlers, lifespan
│   ├── api/
│   │   ├── deps.py                # Dependencies: get_current_user, get_db, get_optional_current_user
│   │   └── v1/
│   │       ├── api.py             # Router aggregation
│   │       └── endpoints/
│   │           ├── ara.py         # Ara sessions, messages, SSE streaming
│   │           ├── auth.py        # Register, login, refresh, logout
│   │           ├── users.py       # Profile CRUD
│   │           ├── pois.py        # POI CRUD, search, semantic-search
│   │           ├── reviews.py     # Review CRUD, summaries
│   │           ├── bookmarks.py   # Bookmark CRUD
│   │           ├── itineraries.py # Itinerary CRUD, steps, weather, share, export
│   │           ├── entrepreneur.py # Entrepreneur metrics, analytics, posts
│   │           ├── categories.py  # Category listing
│   │           ├── geocoding.py   # Forward geocoding
│   │           ├── weather.py     # Weather forecast
│   │           └── media.py       # Image upload/serve
│   ├── core/
│   │   ├── config.py              # Settings (Pydantic BaseSettings)
│   │   ├── security.py            # JWT creation/validation, password hashing
│   │   ├── exceptions.py          # AppError, PermissionError
│   │   ├── rate_limit.py          # slowapi Limiter instance
│   │   ├── time_utils.py          # to_chile_timezone()
│   │   └── http_client.py         # httpx.AsyncClient connection pool
│   ├── db/
│   │   ├── base.py                # SQLAlchemy DeclarativeBase
│   │   ├── models.py              # Model imports (for Alembic metadata)
│   │   └── session.py             # AsyncSession factory, init_db()
│   ├── models/
│   │   ├── user.py                # User, TouristProfile, EntrepreneurProfile
│   │   ├── category.py            # Category
│   │   ├── poi.py                 # POI, POICategory (bridge)
│   │   ├── review.py              # Review
│   │   ├── bookmark.py            # Bookmark
│   │   ├── itinerary.py           # Itinerary, ItineraryStep
│   │   ├── ara_session.py         # AraSession, AraMessage
│   │   ├── conversation_memory.py # ConversationMemory
│   │   ├── entrepreneur_post.py   # EntrepreneurPost
│   │   └── poi_visit.py           # POIVisit
│   ├── repositories/
│   │   ├── base.py                # BaseRepository (CRUD genérico)
│   │   ├── utils.py               # get_category_ids_batch(), build_poi_response_from_row()
│   │   ├── user_repository.py
│   │   ├── poi_repository.py
│   │   ├── review_repository.py
│   │   ├── bookmark_repository.py
│   │   ├── itinerary_repository.py
│   │   ├── entrepreneur_repository.py
│   │   └── ara_repository.py
│   ├── schemas/
│   │   ├── user.py, token.py, poi.py, review.py, bookmark.py
│   │   ├── itinerary.py, category.py, geocoding.py, weather.py
│   │   ├── ara.py, ara_comprehension.py
│   │   └── entrepreneur.py
│   └── services/
│       ├── embedding_service.py   # OpenAIEmbeddingService + GlobalEmbeddingCache
│       ├── llm_service.py         # ItineraryGenerator (DeepSeek)
│       ├── geo_service.py         # distance_meters() Haversine
│       ├── geocoding_service.py   # Nominatim search
│       ├── weather_service.py     # OpenWeatherMap + TTLCache
│       ├── poi_search_service.py  # search_candidate_pois()
│       ├── review_enrichment_service.py
│       ├── ara_streaming_service.py    # SSE wrapper around core pipeline
│       ├── ara_itinerary_core.py       # Unified itinerary generation pipeline
│       ├── itinerary_generation_service.py
│       ├── itinerary_weather_service.py
│       ├── ara_trip_draft_builder.py   # Trip draft construction (remaining functions)
│       └── ara_v2/
│           ├── conversation_processor.py  # Conversation orchestration
│           ├── tool_orchestrator.py       # Tool execution + delegation
│           ├── comprehender.py            # LLM comprehension (GPT-4o-mini)
│           ├── comprehension_fallback.py  # Rule-based fallback
│           ├── response_generator.py      # Response building + quick replies
│           ├── answer_service.py          # POI question answering
│           ├── prompt_manager.py          # System prompt builders
│           ├── memory_service.py          # Conversation memory + embeddings
│           ├── category_mapping.py        # Category name ↔ intent mapping
│           ├── geocoding_service.py       # Destination geocoding
│           └── utils.py                   # get_gpt_mini_client()
├── tests/
│   ├── conftest.py                # Fixtures: async_client, db_session, auth_headers
│   ├── unit/
│   │   └── ara_v2/
│   │       ├── test_prompt_manager.py
│   │       ├── test_comprehender.py
│   │       ├── test_memory_service.py
│   │       ├── test_response_generator.py
│   │       ├── test_tool_orchestrator.py
│   │       └── test_conversation_processor.py
│   ├── test_rut.py, test_security.py, test_poi_metadata_extractor.py
├── migrations/
│   ├── env.py                    # Alembic environment
│   └── versions/                 # Migration scripts
├── scripts/
│   ├── init_db.sql               # Database bootstrap
│   ├── import_osm_data.py        # OSM bulk import
│   ├── seed_categories.py        # Category seeder
│   └── create_vector_indices.py  # HNSW index creation
├── docker-compose.yml
├── Dockerfile.db
├── requirements.txt
├── pyproject.toml
└── .env
```

---

## 4. API REST — Catálogo completo de endpoints

**Base URL:** `/api/v1`

### 4.1 Auth (`/api/v1/auth`)

| Método | Ruta | Auth | Rate Limit | Descripción |
|--------|------|------|------------|-------------|
| POST | `/register` | No | — | Registro de turista |
| POST | `/login` | No | 5/min | Login, retorna JWT access + refresh |
| POST | `/refresh` | No | — | Refresh token → nuevo par |
| POST | `/logout` | Bearer | — | Revoca access token por jti |

**Formato JWT:**
```json
{
  "sub": "<user_id>",
  "iat": 1716840000,
  "jti": "<uuid>",
  "iss": "ruta-viva",
  "exp": 1716843600
}
```

- `sub`: UUID del usuario
- `jti`: JWT ID único para blacklist en logout
- `iss`: "ruta-viva" (validado en `deps.py`)
- `exp`: 1 hora para access token, 7 días para refresh token

### 4.2 Users (`/api/v1/users`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/me` | Sí | Perfil del usuario autenticado |
| PATCH | `/me` | Sí | Editar email, avatar, display_name |
| PUT | `/me/tourist-profile` | Sí | Actualizar perfil turista (intereses, comida, actividad) |
| POST | `/me/entrepreneur-profile` | Sí | Activar perfil emprendedor (RUT, negocio, descripción) |

### 4.3 POIs (`/api/v1/pois`)

| Método | Ruta | Auth | Rate Limit | Descripción |
|--------|------|------|------------|-------------|
| POST | `/` | Sí | 5/h + 10/d | Crear POI con embedding y geometría |
| GET | `/mine` | Sí | — | POIs propios del emprendedor |
| GET | `/search` | No | 30/min | Búsqueda geoespacial por radio |
| GET | `/semantic-search` | Opcional | 10/min | Búsqueda híbrida semántica + geo |
| GET | `/{poi_id}` | No | — | Detalle de POI |
| GET | `/{poi_id}/posts` | No | — | Posts públicos del POI |
| POST | `/{poi_id}/visit` | Opcional | — | Registrar visita |
| PATCH | `/{poi_id}/media` | Sí | — | Agregar imagen al POI |
| PUT | `/{poi_id}` | Sí | — | Actualizar POI (owner only) |
| DELETE | `/{poi_id}` | Sí | — | Eliminar POI (owner only) |

**Búsqueda semántica personalizada:** Si el usuario está autenticado y tiene `interests_embedding`, el ranking combina:
```
score = (query_distance * 0.7) + (profile_distance * 0.3)   # Búsqueda normal
score = (query_distance * 0.9) + (profile_distance * 0.1)   # Dentro de generación de itinerario
```

### 4.4 Reviews (`/api/v1/reviews`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/` | Sí | Crear review (embedding en background) |
| GET | `/poi/{poi_id}` | No | Reviews de un POI (con author_name por selectinload) |
| GET | `/poi/{poi_id}/summary` | No | Agregado: count, avg, distribución |
| PUT | `/{review_id}` | Sí | Editar review propia |
| DELETE | `/{review_id}` | Sí | Eliminar review propia |

**Flujo de perfil dinámico:**
```
nuevo_perfil = (perfil_actual * 0.9) + (embedding_review * 0.1)
```
- 90% conserva historial, 10% incorpora nueva review
- Actualización dimensión por dimensión
- Reviews sin embedding (error OpenAI) no actualizan perfil pero la review se guarda igual

### 4.5 Itineraries (`/api/v1/itineraries`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | Sí | Listar itinerarios propios (paginado) |
| POST | `/generate` | Sí | Generar itinerario con LLM + clima |
| GET | `/{itinerary_id}` | Sí | Obtener itinerario con steps y POIs (selectinload) |
| DELETE | `/{itinerary_id}` | Sí | Eliminar itinerario |
| GET | `/{itinerary_id}/pois` | Sí | POIs del itinerario |
| POST | `/{itinerary_id}/steps` | Sí | Agregar step |
| PATCH | `/{itinerary_id}/steps/{step_id}` | Sí | Actualizar step |
| DELETE | `/{itinerary_id}/steps/{step_id}` | Sí | Eliminar step |
| PATCH | `/{itinerary_id}/steps/reorder` | Sí | Reordenar steps |
| PATCH | `/{itinerary_id}/steps/reorder-with-times` | Sí | Reordenar con horarios |
| PATCH | `/{itinerary_id}/steps/{step_id}/reschedule` | Sí | Reprogramar step |
| PATCH | `/{itinerary_id}/status` | Sí | Cambiar estado |
| GET | `/{itinerary_id}/weather` | Sí | Pronóstico para steps |
| GET | `/{itinerary_id}/export` | Sí | Exportar datos |
| POST | `/{itinerary_id}/share` | Sí | Generar link público |
| DELETE | `/{itinerary_id}/share` | Sí | Revocar link público |
| POST | `/{itinerary_id}/steps/{step_id}/visit` | Sí | Marcar step visitado |
| GET | `/{itinerary_id}/visits` | Sí | Visitas del itinerario |

**Pipeline de generación de itinerario (7 fases):**
```
Validating → Query Building → POI Searching → Weather → LLM Generation → Repair → Save
```

**Pipeline de reparación post-LLM (7 pasos):**
```
normalize_times → repair_invalid_ids → repair_start_times → repair_lodging_duplicates
→ repair_duplicate_steps → repair_schedule_category → validate_rules → sanitize_context
```

### 4.6 Ara — Asistente conversacional (`/api/v1/ara`)

| Método | Ruta | Auth | Rate Limit | Descripción |
|--------|------|------|------------|-------------|
| POST | `/sessions` | Sí | 5/min | Crear sesión conversacional |
| POST | `/sessions/{session_id}/messages` | Sí | 10/min | Enviar mensaje |
| GET | `/sessions/{session_id}/messages` | Sí | — | Obtener historial |
| POST | `/sessions/{session_id}/generate-itinerary/stream` | Sí | 3/min | **SSE streaming** de generación |

**Formato SSE:**
```
event: status
data: {"phase": "searching", "message": "Buscando lugares..."}

event: warning
data: {"message": "Encontré pocos puntos de interés...", "poi_count": 3}

event: status
data: {"phase": "generating", "message": "Armando tu itinerario con IA..."}

event: result
data: {"itinerary_id": "...", "steps": [...], ...}
```

**Contrato frontend:**
- Solo se usa SSE streaming. No existen rutas sync ni async.
- El evento `warning` debe manejarse para informar al usuario de resultados limitados.
- `AraGenerateItineraryResponse` se recibe como JSON dentro del stream, no como response body HTTP.

### 4.7 Otros endpoints

**Entrepreneur (`/api/v1/entrepreneur`):**
- `GET /me/metrics` — Métricas del dashboard
- `GET /me/income` — Ingresos (stub)
- `GET /me/posts`, `POST /me/posts`, `PATCH /me/posts/{id}`, `DELETE /me/posts/{id}`
- `GET /pois/{poi_id}/analytics` — Analytics detallado (3 queries: visits con FILTER, reviews, bookmarks)
- `GET /pois/{poi_id}/activity` — Feed de actividad (con selectinload en bookmarks)
- CRUD de posts por POI, reorder, pin/unpin

**Geocoding (`/api/v1/geocoding`):**
- `GET /search?q=...&lat=...&lon=...` — Nominatim forward geocoding

**Weather (`/api/v1/weather`):**
- `GET /forecast?lat=...&lon=...&start=...&end=...` — OpenWeatherMap daily forecast (cache TTLCache 30min)

**Media (`/api/v1/media`):**
- `POST /upload` — Subir imagen (JPG/PNG, max 5MB, nombres UUID4)

**Root level:**
- `GET /health` — Health check con `SELECT 1`
- `GET /share/{public_id}` — Itinerario compartido público (sin auth)
- `GET /media/{filename}` — Servir archivo (JWT requerido, path traversal protection)

---

## 5. Modelo de datos

### 5.1 Diagrama de entidades principales

```
User (1) ──────< TouristProfile (1)
  │                │
  │                ├──< Review (N) ──────> POI (1)
  │                ├──< Bookmark (N) ────> POI (1)
  │                ├──< Itinerary (N)
  │                │     └──< ItineraryStep (N) ──> POI (1)
  │                ├──< AraSession (N)
  │                │     └──< AraMessage (N)
  │                ├──< ConversationMemory (N)
  │                └──< POIVisit (N) ───> POI (1)
  │
  └──< EntrepreneurProfile (1)
         └──< POI (N)
               ├──< POICategory (N) ──> Category (1)
               └──< EntrepreneurPost (N)
```

### 5.2 Constraints de integridad

**Check constraints (7):**
- `reviews.rating_stars`: 1-5
- `users.role`: 'tourist' | 'entrepreneur'
- `itineraries.status`: 'draft' | 'active' | 'completed' | 'archived'
- `ara_sessions.status`: 'clarifying' | 'searching' | 'generating' | 'completed' | 'failed'
- `ara_sessions.conversation_mode`: 'exploring' | 'refining' | 'ready_to_generate' | 'generated' | 'editing' | 'replacing_step'
- `pois.source`: 'manual' | 'osm' | 'ai_generated'
- `entrepreneur_posts.status`: 'draft' | 'published' | 'archived'

**Unique constraints:**
- `uq_bookmark_tourist_poi`: un turista no puede bookmarked el mismo POI dos veces
- `uq_review_tourist_poi`: un turista no puede reseñar el mismo POI dos veces (crea o actualiza)
- `uq_itinerary_steps_order`: step_order único dentro de un itinerary

**Domain constraints:**
- `confidence_score`: 0.0 a 1.0
- `step_order > 0`
- `departure_time < arrival_time` en steps
- `radius > 0`
- `end_date >= start_date`
- `full_name VARCHAR(255)`
- `description_embedding` fijado a `Vector(1536)` en PostgreSQL

### 5.3 Estrategias de eager loading por entidad

| Entidad | Relación | Estrategia | Dónde se aplica |
|---------|----------|------------|-----------------|
| Review | → tourist | `selectinload` | `review_repository.get_reviews_by_poi`, `create_review`, `update_review` |
| Bookmark | → tourist | `selectinload` | `entrepreneur_repository.get_poi_activity` |
| Itinerary | → steps | `selectinload` anidado | `itinerary_repository.get_itinerary_by_id` y 8 métodos que lo usan |
| ItineraryStep | → poi | `selectinload` anidado | Misma query que arriba (two-level eager loading) |

**Regla:** Todo método de repositorio que expone relaciones en su respuesta DEBE usar `.options(selectinload(...))`. Nunca se confía en `lazy="selectin"` del modelo porque el lazy loading puede ser inhibido por el contexto de ejecución.

---

## 6. Servicios de IA

### 6.1 Embedding Service

**Archivo:** `app/services/embedding_service.py`

**Arquitectura de 3 niveles:**

```
EmbeddingCache (request-scoped)
  → delega a GlobalEmbeddingCache (process-scoped, TTL 900s)
    → delega a OpenAIEmbeddingService (API calls)
```

**GlobalEmbeddingCache:**
- TTL: 900 segundos (15 minutos)
- Thread-safety: `asyncio.Lock` por clave
- Patrón: double-checked locking
- Sin evicción (aceptable para text-embedding-3-small)
- Almacena: `{text: (expiry_timestamp, embedding_list)}`

**EmbeddingCache:**
- Request-scoped, wrapper del global
- Cache local para deduplicación intra-request
- Misma interfaz `get_embedding(text: str) -> list[float]`

**Batch embeddings:**
- `get_embeddings_batch(texts: list[str]) -> list[list[float]]`
- Una sola llamada a API para N textos
- OpenAI soporta hasta 2048 inputs por batch

### 6.2 LLM Service (DeepSeek)

**Archivo:** `app/services/llm_service.py`

**Modelo:** DeepSeek (via `AsyncOpenAI` con `base_url=https://api.deepseek.com`)

**Timeout:** 90 segundos

**Función principal:** `generate_itinerary(query, context_pois, weather) -> GeneratedItinerary`

**Validación post-LLM:**
1. Parseo JSON de la respuesta
2. Validación Pydantic con `GeneratedItinerary`
3. Verificación de `poi_id` contra contexto
4. Normalización de timezone
5. Pipeline de reparación (7 pasos)

**Retry:** Reintenta 1 vez en caso de error de parseo o timeout. Usa `with_retry()` con backoff exponencial.

### 6.3 Comprehension Service (GPT-4o-mini)

**Archivo:** `app/services/ara_v2/comprehender.py`

**Modelo:** GPT-4o-mini (via `AsyncOpenAI`)

**Timeout:** 10 segundos

**Función:** `comprehend(user_message, session_context) -> ComprehensionResult`

**Fallback:** Si el LLM falla (timeout, API error, parse error), usa `comprehension_fallback.py` con reglas deterministas basadas en keywords y patrones.

**Estructura de `ComprehensionResult`:**
```python
class ComprehensionResult(BaseModel):
    intenciones: list[AraIntent]         # Qué quiere hacer el usuario
    entidades: list[AraEntity]           # POIs, lugares, categorías mencionadas
    preferencias: AraPreferenceSummary   # Preferencias inferidas
    actualizaciones_memoria: list[MemoryFact]  # Hechos nuevos para guardar
```

### 6.4 Pipeline unificado de itinerarios

**Archivo:** `app/services/ara_itinerary_core.py`

**Función central:** `generate_itinerary_core(session, payload, db, user, embedding_service, llm_service, candidate_pois?, weather_forecast?, on_phase?) -> (itinerary, context_pois, generation_payload)`

**Callback pattern:**
```python
async def on_phase(name: str, extra: dict | None) -> None:
    # SSE: push event to queue
    # Tool orchestrator: logger.info(...)
    # Direct call: None (no callback)
```

**7 fases secuenciales:**

1. **Validating** — Verifica perfil turista, resuelve coordenadas (GPS o geocoded)
2. **Query Building** — Construye query refinada con `build_refined_query()`
3. **POI Searching** — Dos paths:
   - **Pre-fetched** (conversación): usa POIs pasados por el caller
   - **Full search** (SSE): merge de session context + user-selected + semantic search
4. **Weather** — Fetch forecast si no se pasó pre-calculado
5. **LLM Generation** — `llm_service.generate_itinerary()` con query + POIs + clima
6. **Repair** — 7 pasos de validación/corrección post-LLM
7. **Save** — Persiste via `itinerary_repository.create_generated_itinerary()`, linkea a sesión

**Llamado por:**
- `ara_streaming_service.py` — Con callback SSE
- `tool_orchestrator.py` — Con callback logging
- `itinerary_generation_service.py` — Directo (sin callback)

---

## 7. Rate Limiting

### 7.1 Configuración

**Librería:** slowapi (basada en `limits`)

**Key function:** `get_remote_address` (por IP)

**Binding:** `app.state.limiter = limiter` en `main.py`

### 7.2 Límites por endpoint

| Endpoint | Límite | Tipo | Justificación |
|----------|--------|------|---------------|
| `POST /auth/login` | 5/min | slowapi | Anti brute-force |
| `POST /ara/sessions` | 5/min | slowapi | Control de creación de sesiones |
| `POST /ara/sessions/{id}/messages` | 10/min | slowapi | Protección del flujo conversacional |
| `POST /ara/sessions/{id}/generate-itinerary/stream` | 3/min | slowapi | Generación es costosa (LLM + embeddings + clima) |
| `GET /pois/search` | 30/min | slowapi | PostGIS query, relativamente barata |
| `GET /pois/semantic-search` | 10/min | slowapi | Incluye llamada a OpenAI embeddings |
| `POST /pois/` | 5/hora + 10/día | Custom DB | Anti-spam de creación de POIs |

### 7.3 Handler de error 429

```json
{
  "error": "RateLimitExceeded",
  "detail": "Has enviado muchos mensajes muy rápido. Espera un momento y vuelve a intentarlo."
}
```

---

## 8. Seguridad

### 8.1 Password hashing

**Algoritmo:** bcrypt (puro, no `bcrypt_sha256`)

**Librería:** Passlib con `CryptContext(schemes=["bcrypt"], deprecated="auto")`

**Migración transparente:** Hashes viejos (`bcrypt_sha256`) se verifican correctamente y Passlib los re-hashea automáticamente al siguiente login. No se requiere migración masiva.

### 8.2 JWT

**Access token:** 1 hora de expiración
**Refresh token:** 7 días de expiración

**Claims:**
- `sub`: user UUID
- `iat`: issued at
- `jti`: JWT ID (UUID4, único)
- `iss`: "ruta-viva"

**Validación de issuer:** `deps.py` verifica que `payload["iss"] == "ruta-viva"`. Rechaza tokens de otros emisores.

### 8.3 Logout

El endpoint `POST /auth/logout` agrega el `jti` a una blacklist en memoria. Los tokens revocados se rechazan en `get_current_user`. **Limitación:** La blacklist no persiste entre reinicios del servidor. Para producción se necesita Redis.

### 8.4 Protección de archivos

- `/media/{filename}` requiere JWT válido
- Protección contra path traversal: se valida que `filename` no contenga `..` ni `/`
- Solo se sirven extensiones `.jpg`, `.jpeg`, `.png`

### 8.5 CORS

**Configuración actual:** `allow_origins=["*"]` (wildcard)

**Riesgo:** Cualquier origen puede hacer requests. En producción debe restringirse a los dominios del frontend.

---

## 9. Infraestructura

### 9.1 Docker Compose

**Servicios:**
- `db`: PostgreSQL 16 + pgvector + PostGIS
- `api`: FastAPI con uvicorn, hot reload vía volume mount

**Variables de entorno (db):**
```yaml
POSTGRES_USER: ${POSTGRES_USER:-admin}
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-admin}
POSTGRES_DB: ${POSTGRES_DB:-rutaviva_db}
```

**Volume mounts (api):**
- `./app:/app/app` — Hot reload de código
- `./media:/app/media` — Imágenes persistidas

### 9.2 Health check

- `GET /health`: verifica conectividad DB con `SELECT 1`
- Docker healthcheck: `pg_isready -U admin -d rutaviva_db` (NOTA: hardcodeado, no usa variables de entorno)

### 9.3 Índices de base de datos

- **HNSW** en `pois.description_embedding` para búsqueda vectorial rápida
- **GiST** en `pois.location` para búsqueda geoespacial
- **B-tree** en foreign keys (implícitos por SQLAlchemy)
- **Unique** en `bookmarks(tourist_id, poi_id)` y `reviews(tourist_id, poi_id)`

### 9.4 Telemetría

**Middleware `telemetry_middleware`:**
- Mide tiempo de cada request con `time.perf_counter()`
- Header: `X-Process-Time: 0.450123`
- Log: `POST /api/v1/pois/search - 200 OK - 450ms`
- Excluye `/health` para no contaminar logs

---

## 10. Tests

### 10.1 Estructura

```
tests/
├── conftest.py              # Fixtures compartidos
├── test_rut.py              # 19 tests de validación RUT
├── test_security.py         # 10 tests de JWT y hashing
├── test_poi_metadata_extractor.py  # 40 tests
└── unit/
    └── ara_v2/
        ├── test_prompt_manager.py         # 8 tests (comprehension + generation prompts)
        ├── test_comprehender.py           # ~30 tests (LLM + fallback)
        ├── test_memory_service.py         # ~20 tests (store_fact, store_facts_batch)
        ├── test_response_generator.py     # ~20 tests
        ├── test_tool_orchestrator.py      # ~15 tests
        └── test_conversation_processor.py # ~20 tests
```

### 10.2 Fixtures principales

```python
# conftest.py
@pytest.fixture
async def async_client():
    # TestClient para FastAPI con async

@pytest.fixture
async def db_session():
    # AsyncSession para tests con rollback automático

@pytest.fixture
async def auth_headers(db_session):
    # Headers con Bearer token para usuario de prueba
```

### 10.3 Comando para ejecutar

```bash
cd ruta_viva && python -m pytest -x -q
```

**Resultado actual:** 164/164 tests passing

### 10.4 Configuración

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 11. Flujos de datos detallados

### 11.1 Flujo de registro y login

```
POST /auth/register
  → UserCreate (Pydantic)
  → user_repository.create_user()
    → security.get_password_hash(password)  # bcrypt
    → INSERT INTO users
    → INSERT INTO tourist_profiles
  → commit
  → UserResponse

POST /auth/login
  → LoginRequest (Pydantic)
  → user_repository.get_by_email()
  → security.verify_password(plain, hashed)
  → security.create_access_token(user_id)
  → security.create_refresh_token(user_id)
  → TokenResponse(access_token, refresh_token)
```

### 11.2 Flujo de búsqueda semántica

```
GET /pois/semantic-search?query=X&lat=Y&lon=Z&radius=R
  → query_embedding = embedding_service.get_embedding(query)
  → poi_repository.search_hybrid(
      lat, lon, radius, query_embedding,
      profile_weight=0.3,          # 0.1 si viene de generación de itinerario
      interests_embedding=profile  # Solo si usuario autenticado
    )
  → SQL: SELECT *, cosine_distance(description_embedding, query) AS dist
         FROM pois
         WHERE ST_DWithin(location, ref_point, radius)
         ORDER BY dist
  → list[POIResponse]
```

### 11.3 Flujo de conversación Ara

```
POST /ara/sessions  (con initial_query="Villarrica")
  → crea AraSession(status="clarifying", conversation_mode="exploring")
  → AraSessionResponse

POST /ara/sessions/{id}/messages  (con content="busco restaurantes vegetarianos")
  → conversation_processor.handle_message_v2()
    → PASO 1: Persiste user message
    → PASO 2: comprehension = comprehender.comprehend(msg, context)
        → GPT-4o-mini analiza intención, entidades, preferencias
        → Si falla: fallback_comprehend() rule-based
    → PASO 3: Actualiza trip_draft con preferencias inferidas
    → PASO 4: memory_service.store_facts_batch(hechos)
        → Embedding batch → INSERT INTO conversation_memories
    → PASO 5: tool_orchestrator.execute(db, user, comprehension, session)
        → Si build_itinerary + fechas + ready_to_generate:
            → status="respond", response="Generando en segundo plano..."
            → Frontend llama a SSE streaming
        → Si search_pois:
            → Busca candidatos, diversifica, retorna quick replies
        → Si answer_question:
            → answer_service responde pregunta sobre POI
    → PASO 6: Persiste assistant message
  → AraMessagesResponse
```

### 11.4 Flujo de generación SSE

```
POST /ara/sessions/{id}/generate-itinerary/stream
  → Response: text/event-stream
  → stream_itinerary_generation()
    → Crea asyncio.Queue para eventos
    → Lanza generate_itinerary_core() en asyncio.Task
      → on_phase callback pushea a la queue
      → Fase 1-7 se ejecutan secuencialmente
    → Loop SSE:
      → event_queue.get() con timeout
      → Yield "event: status\ndata: {json}\n\n"
      → Si timeout y task done, drena queue restante
      → Si CancelledError, marca itinerario como abandoned
```

---

## 12. Configuración (Settings)

**Archivo:** `app/core/config.py`

**Fuentes:** `.env` file > environment variables > defaults

### Settings activas:

| Setting | Default | Uso |
|---------|---------|-----|
| `app_name` | "Ruta Viva" | Título OpenAPI |
| `app_version` | "0.1.0" | Versión OpenAPI |
| `api_v1_prefix` | "/api/v1" | Prefijo de rutas |
| `postgres_user` | "admin" | Usuario DB |
| `postgres_password` | "admin" | Password DB |
| `postgres_db` | "rutaviva_db" | Nombre DB |
| `postgres_host` | "localhost" | Host DB |
| `postgres_port` | 5432 | Puerto DB |
| `database_echo` | False | SQL echo |
| `openai_api_key` | None | API key OpenAI |
| `openai_gpt_mini_model` | "gpt-4o-mini" | Modelo de comprensión |
| `gpt_mini_timeout_seconds` | 10.0 | Timeout GPT-4o-mini |
| `deepseek_api_key` | None | API key DeepSeek |
| `deepseek_base_url` | "https://api.deepseek.com" | Endpoint DeepSeek |
| `deepseek_timeout_seconds` | 90.0 | Timeout DeepSeek |
| `ara_chat_timeout_seconds` | 8.0 | Timeout chat Ara |
| `openweather_api_key` | None | API key OpenWeatherMap |
| `secret_key` | (requerido) | Clave JWT |
| `algorithm` | "HS256" | Algoritmo JWT |
| `access_token_expire_minutes` | 60 | Expiración access token |
| `refresh_token_expire_minutes` | 10080 | Expiración refresh token (7 días) |

### Settings eliminadas (auditoría Fase 5):

| Setting | Razón de eliminación |
|---------|---------------------|
| `llm_retry_max_attempts: int = 2` | Nunca referenciado; el retry usa constantes locales |
| `llm_retry_base_delay: float = 1.0` | Nunca referenciado |
| `llm_retry_max_delay: float = 10.0` | Nunca referenciado |
| `ara_default_language: str = "es"` | Nunca referenciado; idioma definido en prompts y catalog |

---

## 13. Deuda técnica conocida

### 13.1 Crítica (bloquea producción)

| Item | Impacto | Plan |
|------|---------|------|
| CORS wildcard | Seguridad: cualquier origen puede llamar a la API | Coordinar con frontend los dominios de producción |
| Token blacklist en memoria | Los tokens revocados vuelven a ser válidos después de reinicio | Implementar Redis para blacklist persistente |

### 13.2 Alta (afecta rendimiento/escalabilidad)

| Item | Impacto | Plan |
|------|---------|------|
| `itinerary_generation_service.py` (997 líneas) | Mantenibilidad: archivo grande, difícil de testear | Refactorizar en sub-módulos cuando se toque funcionalidad |
| `ara_conversation_orchestrator.py` (~1500 líneas) | Mantenibilidad: archivo más grande del proyecto | Partir en use-cases independientes |
| Healthcheck DB hardcodeado | Si se cambian credenciales, el healthcheck Docker falla | Usar variables de entorno en el healthcheck |

### 13.3 Media (mejora de producto)

| Item | Impacto | Plan |
|------|---------|------|
| Sin tiempos de traslado reales | Itinerarios no optimizan orden geográfico | Integrar OSRM o Google Distance Matrix |
| Clima agrupado por fecha | Microclimas distintos en La Araucanía pueden pisarse | Clima por coordenada de POI, no por fecha |
| Sin pipeline RAG formal | Sin memoria a largo plazo de documentos externos | Diseñar e implementar `rag_service.py` |

### 13.4 Baja (pulido)

| Item | Plan |
|------|------|
| `GlobalEmbeddingCache` sin evicción de memoria | Agregar LRU eviction si el uso de memoria crece |
| Sin observabilidad (tracing distribuido) | Evaluar OpenTelemetry cuando haya múltiples servicios |
| Sin tests de integración con DB real | Agregar test DB con Docker en CI |

---

## 14. Comandos útiles

### Desarrollo

```bash
# Entorno virtual
cd ruta_viva
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Base de datos
docker compose up -d db

# API con hot reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# API + DB
docker compose up -d
```

### Tests

```bash
cd ruta_viva
python -m pytest -x -q              # Todos los tests
python -m pytest tests/unit/ara_v2/ -x -q  # Solo tests Ara v2
python -m pytest -x -q -k "test_comprehension"  # Por keyword
```

### Base de datos

```bash
# Migraciones
cd ruta_viva
alembic upgrade head               # Aplicar migraciones
alembic revision --autogenerate -m "descripción"  # Crear migración
alembic downgrade -1               # Revertir última

# Seed
python scripts/seed_categories.py  # Categorías base (idempotente)
python scripts/create_vector_indices.py  # Índice HNSW

# Import OSM
python scripts/import_osm_data.py  # Importar POIs de OpenStreetMap
```

### Docker

```bash
docker compose up -d               # Levantar todo
docker compose down                # Bajar todo
docker compose logs -f api         # Logs de la API
docker compose exec db psql -U admin -d rutaviva_db  # Consola SQL
```

---

## 15. Guía de contribución

### 15.1 Antes de hacer cambios

1. Leer `estudio.md` para entender la arquitectura y decisiones previas.
2. Revisar la sección "Deuda técnica conocida" de este documento.
3. Si el cambio es sustancial, seguir el flujo SDD: proposal → spec → design → tasks → apply.

### 15.2 Durante el desarrollo

1. **Endpoints delgados**: Si un handler supera 50 líneas, extraer lógica a un service.
2. **Eager loading explícito**: Todo repositorio que expone relaciones debe usar `selectinload`.
3. **Excepciones de dominio**: Usar `AppError` y `PermissionError`, no `HTTPException`.
4. **Settings tipados**: Toda configuración externa va en `Settings`.
5. **Tests**: Mínimo un test por endpoint nuevo o bug fix.

### 15.3 Antes de commit

1. `python -m pytest -x -q` — Todos los tests deben pasar.
2. Revisar `git diff` para asegurar que no hay secrets, debug prints ni código comentado.
3. Commit messages en inglés, formato conventional commits.

### 15.4 No hacer

- No commitear secrets (`.env`, API keys reales).
- No agregar imports no usados.
- No crear excepciones de dominio "por si acaso" que nunca se lanzan.
- No duplicar lógica de generación de itinerarios; todo debe pasar por `generate_itinerary_core()`.
- No confiar en lazy loading de SQLAlchemy; siempre usar `selectinload` explícito en repositorios.

---

## 16. Archivos eliminados en la auditoría (2026-05-27)

| Archivo | Líneas | Reemplazado por |
|---------|--------|-----------------|
| `app/services/ara_chat_service.py` | 269 | `ara_v2/response_generator.py` + `ara_v2/answer_service.py` |
| `app/services/ara_itinerary_generation.py` | 401 | `app/services/ara_itinerary_core.py` |

## 17. Referencias rápidas

### 17.1 Dónde encontrar...

| Pregunta | Archivo |
|----------|---------|
| ¿Cómo se crea un JWT? | `app/core/security.py` |
| ¿Cómo se valida un JWT? | `app/api/deps.py → get_current_user()` |
| ¿Cómo se genera un embedding? | `app/services/embedding_service.py` |
| ¿Cómo se genera un itinerario? | `app/services/ara_itinerary_core.py → generate_itinerary_core()` |
| ¿Cómo se streamea por SSE? | `app/services/ara_streaming_service.py` |
| ¿Cómo se clasifica la intención del usuario? | `app/services/ara_v2/comprehender.py` |
| ¿Cómo se ejecutan las herramientas de Ara? | `app/services/ara_v2/tool_orchestrator.py` |
| ¿Cómo se repara un itinerario post-LLM? | `app/services/ara_itinerary_core.py` (fase 6) |
| ¿Cómo se configura rate limiting? | `app/core/rate_limit.py` + `app/main.py` |
| ¿Cómo se convierte a hora chilena? | `app/core/time_utils.py → to_chile_timezone()` |
| ¿Cómo se calcula distancia entre coordenadas? | `app/services/geo_service.py → distance_meters()` |
| ¿Dónde está el catálogo de mensajes de Ara? | `app/services/ara_v2/response_generator.py` (AraMessages) |
