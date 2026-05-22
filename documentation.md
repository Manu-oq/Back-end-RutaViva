# Documentación Técnica Viva — Backend Ruta Viva

> ⚠️ **PRE-DEPLOY CHECKLIST — Cambiar antes de despliegue productivo:**
>
> 1. **CORS**: `allow_origins=["*"]` en `app/main.py` está así solo para desarrollo. Cambiar a dominios explícitos del frontend en producción.
> 2. **Credenciales DB**: Los defaults `admin/admin` en `config.py` y `docker-compose.yml` son para desarrollo local. Setear `POSTGRES_USER` y `POSTGRES_PASSWORD` con valores seguros en `.env` antes de desplegar.
>
> Estos dos puntos NO son blocking para desarrollo, pero SÍ deben cambiarse antes de cualquier exposición pública.

> Última actualización integral: **2026-05-22**
>
> Este documento es la memoria técnica acumulativa del backend. No está pensado como resumen ejecutivo corto, sino como una referencia detallada del estado real del sistema, de las decisiones ya tomadas y de los problemas ya resueltos.

---

## 1. Objetivo del documento
Este archivo existe para registrar de forma trazable y técnica:

- qué está construido hoy,
- cómo está organizado el backend,
- qué endpoints existen realmente,
- qué servicios externos participan,
- cómo está modelada y versionada la base de datos,
- qué decisiones de arquitectura ya quedaron fijadas,
- qué errores aparecieron y cómo se resolvieron,
- y qué vacíos o pendientes siguen abiertos.

La idea es que cualquier persona que entre al proyecto pueda responder, leyendo este documento y el código:

- qué hace el sistema hoy,
- en qué punto del roadmap se encuentra,
- cómo fluye una request desde FastAPI hasta PostgreSQL,
- cómo se integran OpenAI, DeepSeek, PostGIS y pgvector,
- y por qué Alembic, Docker y SQLAlchemy están configurados como están.

---

## 2. Reglas de mantenimiento de esta documentación
Este archivo debe actualizarse cuando ocurra cualquiera de estos eventos:

- creación de nuevos endpoints,
- cambio de proveedores externos,
- cambio de modelos de IA,
- modificaciones de esquema,
- nuevas migraciones,
- refactors relevantes de arquitectura,
- cambios de configuración crítica,
- incorporación o eliminación de dependencias,
- resolución de bugs importantes,
- o ajustes que alteren cómo se entiende el flujo del backend.

### Reglas concretas
1. No borrar historial técnico relevante.
2. No reemplazar un problema por su solución como si el problema nunca hubiera existido.
3. Registrar decisiones y también su motivación.
4. Especificar archivos modificados cuando el cambio sea importante.
5. Preferir precisión real del estado actual por encima de descripciones vagas.
6. Cuando un tema cambie de dirección técnica, dejar constancia del cambio.

---

## 3. Estado actual del backend

## 3.1 Estado general
El backend ya no está solo en fase de arranque. Actualmente dispone de:

- infraestructura reproducible con Docker para PostgreSQL + pgvector + PostGIS,
- aplicación FastAPI funcional,
- autenticación JWT operativa,
- acceso protegido a usuario autenticado,
- perfil turista editable,
- activación de perfil emprendedor,
- creación de POIs con embedding automático,
- listado, edición y eliminación de POIs propios de emprendedores,
- búsqueda geoespacial,
- búsqueda semántica/híbrida basada en embeddings OpenAI,
- generación de itinerarios con DeepSeek,
- persistencia de itinerarios e itinerarios por pasos,
- flujo conversacional de Ara con sesiones, mensajes, quick replies dinámicos y generación final bajo confirmación,
- ingesta masiva de POIs reales desde OpenStreetMap/Overpass,
- sistema de reviews con embeddings semánticos,
- creación de reviews con respuesta inmediata mediante `BackgroundTasks`,
- perfil dinámico de intereses del turista actualizado en segundo plano,
- búsqueda híbrida personalizada por perfil cuando existe usuario autenticado,
- generación de itinerarios consciente del clima mediante OpenWeatherMap,
- generación de itinerarios multi-día hasta 7 días con normalización de fechas, timezone Chile y metadata `day_index`/`day_date`/`day_label`,
- carga local de imágenes y servicio `/media/{filename}` protegido por JWT,
- favoritos/bookmarks de POIs para turistas,
- geocoding público para búsqueda de lugares,
- forecast público diario para frontend,
- edición de email/avatar/display name del usuario autenticado,
- métricas, ingresos placeholder, visitas y posts para emprendedores,
- telemetría por request con `X-Process-Time`,
- manejo global uniforme de errores para frontend,
- seeder idempotente de categorías base,
- índice vectorial HNSW para acelerar búsqueda semántica,
- migraciones Alembic operativas,
- y metadata ORM correctamente registrada para futuras autogeneraciones,
- diversificación automática de candidatos en Ara cuando el usuario ya completó una dimensión (evita loops de una sola categoría),
- reparación determinista de violaciones horarias y saturación categórica en itinerarios generados,
- validación de horarios de apertura con distinción de "día cerrado" vs "sin datos",
- sanitización mejorada de metalenguaje técnico y consejos delegados en respuestas del LLM,
- peso configurable del perfil semántico del usuario en búsqueda híbrida (`profile_weight`), reducido en generación de itinerarios nuevos para evitar contaminación de preferencias antiguas,
- endpoint de reseteo de perfil semántico (`DELETE /api/v1/users/me/tourist-profile/interests`),
- hot reload para desarrollo vía volume mount de código y `--reload` en uvicorn,
- deep copy de preferencias en rama `free_question` para evitar mutaciones accidentales en sesión,
- limpieza automática de `candidate_poi_ids` y `replacement_context` post-generación y post-reemplazo,
- refactorización arquitectónica profunda: endpoints delgados (thin handlers), lógica en services, constantes extraídas,
- 70 tests unitarios funcionales (`test_rut`, `test_security`, `test_poi_metadata_extractor`) con `conftest.py` y `pyproject.toml`,
- JWT con claims `iat`, `jti`, `iss` (issuer `"ruta-viva"`) y validación de issuer en `deps.py`,
- access token: 1 hora (era 7 días). Refresh token: 7 días vía `create_refresh_token()`,
- rate limiting en login: 5 requests/minuto con `slowapi` (configurado en `app/core/rate_limit.py`),
- `BaseRepository` con `_commit_or_rollback()` compartido por los 7 repositorios,
- `repositories/utils.py` con `get_category_ids`, `get_category_ids_batch` (elimina N+1) y `build_poi_response_from_row`,
- `review_enrichment_service.py` extraído de `review_repository.py`: embeddings y perfil dinámico ahora son servicio,
- 7 CheckConstraints en status/role/source, 6 constraints de integridad (confidence_score, step_order, departure>arrival, radius>0, end>=start, full_name VARCHAR(255)),
- Review: `UniqueConstraint(tourist_id, poi_id)` + migración `f6a7b8c9d0e1`,
- timestamps: `updated_at` en `User`, `created_at`+`updated_at` en `Itinerary`, `EntrepreneurProfile`, `TouristProfile`, `POI`,
- schema validations: password min=8, text_content min=1 max=5000, RUT pattern, lat/lon range, query max=500,
- Post CRUD deduplicado en `entrepreneur_repository`,
- `geo_service.py` implementado con `distance_meters()` (Haversine),
- `http_client.py`: pool de conexiones compartido para httpx (`get_client` singleton),
- `exceptions.py`: jerarquía `AppError` → `NotFoundError`, `PermissionError`, `ValidationError`, `ExternalServiceError`,
- `time_utils.py`: `to_chile_timezone()` centralizado, `CHILE_TZ` y `UTC_TZ`,
- `rate_limit.py`: limiter de slowapi con `get_remote_address`,
- constantes extraídas: `ara_constants.py` (458 líneas de términos, patterns, food terms, dimensiones) e `itinerary_constants.py` (categories, terms, time config),
- eliminación de imports privados entre endpoints (cross-endpoint function imports eliminados),
- `datetime.utcnow()` → `datetime.now(timezone.utc)` en 3 sitios,
- naives datetime tratados como UTC (no Chile) en 10+ sitios,
- N+1 eliminado: `get_category_ids_batch()` para búsquedas,
- `recalculate_confidence`: 4→1 query. `get_metrics`: 5→1 query,
- `get_review_summary_by_poi`: SQL `AVG/COUNT/FILTER` en vez de Python,
- weather cache con `TTLCache` 30 min (cachetools),
- `get_embeddings_batch()` en `embedding_service.py` para futuras optimizaciones,
- migración `088edfdc10c4` con checks, constraints, timestamps y validations de la Fase 4.

## 3.2 Funcionalidades ya implementadas y operativas
### Refactorización arquitectónica (Fases 1-4)
- `ara.py`: de 2043 líneas a ~200 líneas (-90%). Handlers delgados, lógica delegada a services.
- `itineraries.py`: de 1281 líneas a ~413 líneas (-68%). Handlers delgados, lógica en `itinerary_generation_service.py` e `itinerary_weather_service.py`.
- `ara_service.py`: de 1707 líneas a ~186 líneas (-89%). Fachada delgada con 5 sub-módulos + orquestador.
- 20+ módulos nuevos creados durante la refactorización (ver sección 6.3).
- Se eliminaron imports privados entre endpoints (cross-endpoint function imports).
- Constantes extraídas a `ara_constants.py` (458 líneas) e `itinerary_constants.py`.

### Seguridad JWT mejorada
- JWT claims ahora incluyen `iat` (issued at), `jti` (unique token ID), `iss` (`"ruta-viva"`).
- `TokenPayload` en `schemas/token.py` con `sub`, `iat`, `jti`, `iss`.
- `RefreshTokenRequest` schema para refresh de tokens.
- `create_refresh_token()` con expiración de 7 días (10080 minutos).
- Access token reducido de 7 días a 1 hora (60 minutos).
- Validación de issuer en `deps.py`: tokens sin `iss == "ruta-viva"` son rechazados.

### Rate limiting
- `slowapi` integrado en `app/core/rate_limit.py`.
- Login protegido: máximo 5 requests/minuto por IP.
- Configuración por defecto con `get_remote_address` como key function.

### Tests unitarios
- 70 tests en `tests/unit/`: `test_rut` (19), `test_security` (10), `test_poi_metadata_extractor` (40).
- `conftest.py` con fixtures `async_client`, `db_session`, `auth_headers`.
- `pyproject.toml` con `asyncio_mode = "auto"` para pytest-asyncio.
- Integración pendiente: aún no hay tests end-to-end ni de repositorios.

### Data integrity (Fase 4)
- 7 CheckConstraints en campos de status/role/source (pois.verification_status, pois.access_type, itineraries.status, entrepreneur_profiles.verification_status, ara_sessions.status, ara_messages.role, poi_visits.source).
- 6 constraints de integridad: confidence_score BETWEEN 0-1, step_order>0, departure>arrival, radius>0, end>=start, full_name VARCHAR(255).
- Review: UniqueConstraint(tourist_id, poi_id) previene reviews duplicadas.
- Schema validations: password min=8, text_content min=1 max=5000, RUT pattern, lat/lon range, query max=500.
- Timestamps: updated_at en User; created_at+updated_at en Itinerary, EntrepreneurProfile, TouristProfile, POI.

### Performance y calidad
- N+1 eliminado en búsquedas con `get_category_ids_batch()`.
- `recalculate_confidence`: 4 queries → 1 query.
- `get_metrics`: 5 queries → 1 query.
- `get_review_summary_by_poi`: SQL AVG/COUNT/FILTER en vez de cargar y calcular en Python.
- httpx.AsyncClient compartido vía `http_client.py` (connection pooling).
- weather cache con `TTLCache` 30 min (cachetools).
- `get_embeddings_batch()` disponible en `embedding_service.py`.
- `datetime.utcnow()` → `datetime.now(timezone.utc)` en 3 sitios.
- Naive datetime tratado como UTC (no Chile) en 10+ sitios.

### Itinerarios y servicios
- `itinerary_generation_service.py` (~830 líneas): toda la lógica de generación, validación, sanitización y persistencia.
- `itinerary_weather_service.py`: lógica de clima por paso, forecast diario, cache TTL.
- `poi_search_service.py` (~362 líneas): búsqueda de POIs con geocoding, normalización de mensaje y detección de destinos.
- `review_enrichment_service.py`: enriquecimiento de reviews (embedding + perfil dinámico) extraído de repository.

### Ara descompuesta (modular)
- `ara_service.py` ahora es fachada delgada (~186 líneas).
- `ara_message_normalizer.py`: normalización/limpieza de mensajes del usuario.
- `ara_turn_classifier.py`: clasificación de intención (amplia, específica, free_question, candidate_selection).
- `ara_preference_merger.py`: merge de preferencias y dimensiones completadas.
- `ara_trip_draft_builder.py`: construcción del draft de itinerario desde preferencias.
- `ara_response_builder.py`: formateo de respuestas y quick replies.
- `ara_conversation_orchestrator.py`: orquestación del flujo conversacional y generación.
- `ara_chat_service.py`: servicio de chat con DeepSeek para Ara.

### Infraestructura transversal
- `BaseRepository` con `_commit_or_rollback()` compartido por los 7 repositorios.
- `repositories/utils.py`: `get_category_ids`, `get_category_ids_batch`, `build_poi_response_from_row`.
- `core/exceptions.py`: `AppError` → `NotFoundError`, `PermissionError`, `ValidationError`, `ExternalServiceError`.
- `core/time_utils.py`: `CHILE_TZ`, `UTC_TZ`, `to_chile_timezone()`.
- `core/http_client.py`: pool compartido de `httpx.AsyncClient` con límites de conexión.
- `core/rate_limit.py`: `Limiter` de slowapi configurado.
- `core/ara_constants.py`: 458 líneas de términos, patterns, comida, dimensiones, destinos.
- `core/itinerary_constants.py`: categorías, términos, config horaria para itinerarios.
- `geo_service.py`: `distance_meters()` con fórmula Haversine.
- `docker-compose.yml` levanta PostgreSQL en contenedor.
- `Dockerfile.db` extiende la imagen de `ankane/pgvector` y agrega paquetes de PostGIS.
- `scripts/init_db.sql` se monta como script de inicialización.
- la app FastAPI se ejecuta sobre SQLAlchemy async + `asyncpg`.

### API base
- `GET /health` comprueba que la API puede ejecutar `SELECT 1` contra la base.
- toda la API funcional está versionada bajo `settings.api_v1_prefix`, hoy `/api/v1`.

### Autenticación y usuario
- `POST /api/v1/auth/register` crea usuario turista.
- `POST /api/v1/auth/login` emite JWT bearer.
- `GET /api/v1/users/me` retorna el usuario autenticado con perfiles turista/emprendedor cuando existen.
- `PUT /api/v1/users/me/tourist-profile` actualiza preferencias reales del turista.
- `POST /api/v1/users/me/entrepreneur-profile` activa perfil emprendedor.
- la autenticación usa `HTTPBearer` + validación JWT con `python-jose`.

### POIs
- `POST /api/v1/pois/` crea POIs autenticados.
- `GET /api/v1/pois/mine` lista POIs del emprendedor autenticado.
- `PUT /api/v1/pois/{poi_id}` edita POIs propios y recalcula embedding si cambia nombre/descripción.
- `DELETE /api/v1/pois/{poi_id}` elimina POIs propios.
- `PATCH /api/v1/pois/{poi_id}/media` asocia URLs de imagen a `POI.multimedia_urls`.
- en la creación se genera automáticamente `description_embedding` con OpenAI.
- `GET /api/v1/pois/search` hace búsqueda geográfica por radio.
- `GET /api/v1/pois/semantic-search` hace búsqueda híbrida actual: filtro por radio + ranking semántico por cosine distance.
- `GET /api/v1/pois/{poi_id}` entrega el detalle serializado de un POI para pantallas frontend de detalle.
- `GET /api/v1/categories/` expone la taxonomía base sembrada de categorías.
- `GET /api/v1/pois/{poi_id}/posts` expone posts públicos de un POI sin autenticación.
- `POST /api/v1/pois/{poi_id}/visit` registra visitas públicas desde frontend sin autenticación.
- detección automática de duplicados en creación de POIs (cascada: geográfico → categoría → semántico).
- scoring de confianza (`confidence_score`) calculado al crear POI y recalculado automáticamente.
- estado de verificación (`verification_status`) para POIs (`pending`/`verified`/`flagged`) y emprendedores (`unverified`/`pending_review`/`verified`).
- rate limiting de creación de POIs (máximo 5/hora, 10/día por usuario).
- validación de RUT chileno (módulo 11) al activar perfil emprendedor con verificación automática.

### Reviews y perfil dinámico
- `POST /api/v1/reviews/` permite a turistas autenticados crear valoraciones.
- la respuesta HTTP de creación de review es inmediata: primero se guarda la reseña con `text_embedding=None`.
- luego FastAPI ejecuta una `BackgroundTasks` que genera el embedding OpenAI del texto.
- esa tarea en segundo plano actualiza `reviews.text_embedding` y `tourist_profiles.interests_embedding`.
- el perfil del turista se actualiza con media móvil exponencial.
- `GET /api/v1/reviews/poi/{poi_id}` permite ver reseñas de un POI específico.
- `GET /api/v1/reviews/poi/{poi_id}/summary` entrega promedio, total y distribución.
- `PUT /api/v1/reviews/{review_id}` y `DELETE /api/v1/reviews/{review_id}` permiten gestionar reviews propias.

### Itinerarios
- `POST /api/v1/itineraries/generate` genera un itinerario turístico con DeepSeek.
- `GET /api/v1/itineraries/` lista los itinerarios persistidos del turista autenticado.
- `GET /api/v1/itineraries/{itinerary_id}` devuelve un itinerario persistido por ID validando propiedad del turista.
- `GET /api/v1/itineraries/{itinerary_id}/pois` devuelve solo los POIs del itinerario activo para mapa filtrado.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/{step_id}` reemplaza POI o edita horarios/contexto de un paso.
- `DELETE /api/v1/itineraries/{itinerary_id}/steps/{step_id}` elimina un paso y reordena los restantes.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/reorder` reordena steps con `step_ids`.
- `DELETE /api/v1/itineraries/{itinerary_id}` elimina un itinerario completo del historial del turista.
- cada `ItineraryStepResponse` incluye `poi_nombre`, `poi_descripcion`, `day_index`, `day_date` y `day_label`.
- el endpoint de generación:
  - recibe consulta de usuario + coordenadas + radio + `start_date`/`end_date`,
  - trata `start_date` y `end_date` del payload como fuente de verdad por encima de fechas escritas en lenguaje natural,
  - genera embedding de la query con OpenAI,
  - recupera POIs relevantes con `POIRepository.search_hybrid`,
  - filtra oficinas/servicios de información y alojamientos cuando no fueron pedidos explícitamente,
  - consulta OpenWeatherMap mediante `weather_service.get_forecast`,
  - envía POIs + pronóstico climático + guía de horarios a DeepSeek bajo un prompt estricto,
  - instruye al LLM a priorizar actividades indoor cuando hay lluvia y outdoor cuando el clima es favorable,
  - exige horarios dentro del rango oficial del viaje y con zona horaria de Chile,
  - valida el JSON devuelto,
  - verifica que el LLM no inventó POIs fuera del contexto,
  - rechaza pasos fuera de fecha, huecos grandes, alojamientos usados como paradas absurdas y servicios de información usados como atractivos,
  - sanitiza consejos inútiles que delegan recomendaciones a recepción/CONAF/terceros,
  - persiste `Itinerary` e `ItineraryStep`,
  - y devuelve el itinerario completo guardado.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/{step_id}/reschedule` permite modificar horario y duración de un paso, desplazando pasos subsecuentes del mismo día.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/reorder-with-times` reordena pasos con asignación automática de horarios (inicio 9:00 AM, gaps de 15 min, preserva duraciones).
- `GET /api/v1/itineraries/{itinerary_id}/weather` expone pronóstico por día y coordenadas únicas de POIs del itinerario, cacheando por coordenadas redondeadas + fecha.
- inyección de clima por paso: tras sanitización, el backend inyecta `ai_context.weather` con `{description, temperature_c, precipitation_probability}` del forecast diario.

### Ara conversacional
- `POST /api/v1/ara/sessions` crea una sesión conversacional desde el input rápido o desde acciones contextuales.
- `POST /api/v1/ara/sessions/{session_id}/messages` agrega mensajes, avanza el estado conversacional y puede ejecutar reemplazo de step.
- `GET /api/v1/ara/sessions/{session_id}/messages` recupera historial del chat.
- `POST /api/v1/ara/sessions/{session_id}/generate-itinerary` genera el itinerario final desde el contexto refinado (síncrono).
- `POST /api/v1/ara/sessions/{session_id}/generate-itinerary/async` inicia generación en background (respuesta 202, polling vía `/generation-status`).
- `GET /api/v1/ara/sessions/{session_id}/generation-status` consulta el estado de la generación asíncrona.
- Ara no genera el itinerario completo en el primer mensaje: primero detecta intención, devuelve respuesta natural y quick replies dinámicos.
- los quick replies cambian según intención amplia/específica y backend envía el chip `Hazlo todo tú`.
- si el mensaje incluye `itinerary_id` y `step_id`, Ara interpreta flujo de "Cambiar lugar", sugiere alternativas reales y permite reemplazar la parada.
- cuando el usuario completa una dimensión (ej: gastronomía), Ara diversifica automáticamente los candidatos y quick replies para evitar loops de una sola categoría.
## 3.3 Funcionalidades presentes pero aún incompletas
- `app/services/rag_service.py` fue eliminado; el pipeline RAG formal sigue pendiente.
- 70 tests unitarios funcionales (`test_rut`, `test_security`, `test_poi_metadata_extractor`). Faltan tests de integración, de repositorios y E2E.
- no hay autorización fina por roles más allá de checks puntuales.
- no existe aún pipeline RAG completo de ingesta, chunking, retrieval y respuesta final.
- no hay tracing distribuido ni dashboard formal de observabilidad, pero sí existe telemetría básica por request con logs y `X-Process-Time`.

---

## 4. Stack técnico actual y decisiones vigentes

## 4.1 API / framework web
- **FastAPI** como framework HTTP.
- validación y serialización basadas en **Pydantic**.
- documentación OpenAPI/Swagger automática por FastAPI.

## 4.2 Persistencia
- **PostgreSQL** como motor relacional principal.
- **SQLAlchemy 2.0** en estilo moderno (`DeclarativeBase`, `Mapped[...]`, `mapped_column(...)`).
- **asyncpg** como driver async real.
- **Alembic** para versionado del esquema.

## 4.3 Extensiones de base de datos
- **PostGIS** para modelado y consulta geoespacial.
- **pgvector** para columnas vectoriales y búsqueda semántica.

### Nuevas columnas y constraints (2026-05-20 / 2026-05-21)
- `entrepreneur_posts`: `poi_id` FK NOT NULL, `is_pinned` bool, `scheduled_at` DateTime nullable, `sort_order` Integer default 0.
- `pois`: `verification_status` String(20) default "pending", `confidence_score` Float default 0.0.
- `entrepreneur_profiles`: `rut` String(12) nullable unique, `verification_status` String(20) default "unverified".
- `poi_visits`: tabla nueva para tracking de visitas a POIs.

## 4.4 IA / proveedores externos
### Embeddings
- proveedor único actual: **OpenAI**.
- cliente usado: `AsyncOpenAI`.
- modelo de embeddings: **`text-embedding-3-small`**.
- dimensionalidad adoptada: **1536**.

### Generación de itinerarios
- proveedor de chat actual: **DeepSeek**.
- integración hecha usando `AsyncOpenAI` con `base_url=settings.deepseek_base_url`.
- modelo usado: **`deepseek-chat`**.

### Clima para itinerarios
- proveedor actual: **OpenWeatherMap**.
- endpoint usado: `/data/2.5/forecast`.
- cliente HTTP async: **httpx**.
- configuración: `OPENWEATHER_API_KEY` cargada como `settings.openweather_api_key`.
- salida interna: string compacto para LLM, por ejemplo `Viernes 01: Lluvia ligera, 12°C, probabilidad de lluvia 70%.`
- uso: antes de generar itinerario se obtiene el pronóstico con las coordenadas del usuario y se incorpora al prompt de DeepSeek.

### Decisión ya tomada
Se eliminó el soporte a Gemini como proveedor de embeddings.

Implicancias:
- `embedding_service.py` quedó simplificado y unificado.
- `OPENAI_API_KEY` es el único secreto necesario para embeddings.
- se removieron configuraciones y dependencias de Gemini.
- la dimensión de `POI.description_embedding` quedó fijada a 1536 para asegurar integridad con OpenAI.

---

## 5. Estructura actual del proyecto

```text
Back-end-TT/
├── README.md
├── documentation.md
├── estudio.md
├── .env.example
├── ruta_viva/
│   ├── alembic.ini
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── Dockerfile.db
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── .gitignore
│   ├── scripts/
│   │   ├── init_db.sql
│   │   ├── create_vector_indices.py
│   │   ├── import_osm_data.py
│   │   ├── recategorize_pois.py
│   │   └── seed_categories.py
│   ├── migrations/
│   │   ├── README
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 13e4146989e2_initial_schema_with_dynamic_vector_.py
│   │       ├── 82d1bcc33432_fix_poi_description_embedding_openai_1536.py
│   │       ├── 9f4a1b2c3d4e_add_poi_visit_rules_and_extended_categories.py
│   │       ├── a1b2c3d4e5f6_add_frontend_sync_features.py
│   │       ├── b2c3d4e5f6a7_add_ara_conversation_sessions.py
│   │       ├── c3d4e5f6a7b8_add_poi_posts_and_analytics_fields.py
│   │       ├── d4e5f6a7b8c9_add_entrepreneur_post_sort_order.py
│   │       ├── e5f6a7b8c9d0_add_verification_confidence_and_rut_fields.py
│   │       ├── f6a7b8c9d0e1_add_unique_constraint_review_tourist_poi.py
│   │       └── 088edfdc10c4_add_constraints_timestamps_and_.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   └── unit/
│   │       ├── __init__.py
│   │       ├── test_rut.py
│   │       ├── test_security.py
│   │       └── test_poi_metadata_extractor.py
│   └── app/
│       ├── main.py
│       ├── api/
│       │   ├── deps.py
│       │   └── v1/
│       │       ├── api.py
│       │       └── endpoints/
│       │           ├── ara.py
│       │           ├── auth.py
│       │           ├── bookmarks.py
│       │           ├── categories.py
│       │           ├── entrepreneur.py
│       │           ├── geocoding.py
│       │           ├── itineraries.py
│       │           ├── media.py
│       │           ├── pois.py
│       │           ├── reviews.py
│       │           ├── users.py
│       │           └── weather.py
│       ├── core/
│       │   ├── ara_constants.py
│       │   ├── config.py
│       │   ├── exceptions.py
│       │   ├── http_client.py
│       │   ├── itinerary_constants.py
│       │   ├── rate_limit.py
│       │   ├── rut.py
│       │   ├── security.py
│       │   └── time_utils.py
│       ├── db/
│       │   ├── base.py
│       │   ├── models.py
│       │   └── session.py
│       ├── models/
│       │   ├── ara_message.py
│       │   ├── ara_session.py
│       │   ├── bookmark.py
│       │   ├── category.py
│       │   ├── entrepreneur_profile.py
│       │   ├── entrepreneur_post.py
│       │   ├── itinerary.py
│       │   ├── itinerary_step.py
│       │   ├── poi.py
│       │   ├── poi_category.py
│       │   ├── poi_visit.py
│       │   ├── review.py
│       │   ├── tourist_profile.py
│       │   └── user.py
│       ├── repositories/
│       │   ├── ara_repository.py
│       │   ├── base.py
│       │   ├── bookmark_repository.py
│       │   ├── entrepreneur_repository.py
│       │   ├── itinerary_repository.py
│       │   ├── poi_repository.py
│       │   ├── review_repository.py
│       │   ├── user_repository.py
│       │   └── utils.py
│       ├── schemas/
│       │   ├── ara.py
│       │   ├── bookmark.py
│       │   ├── category.py
│       │   ├── entrepreneur.py
│       │   ├── entrepreneur_profile.py
│       │   ├── geocoding.py
│       │   ├── itinerary.py
│       │   ├── poi.py
│       │   ├── review.py
│       │   ├── token.py
│       │   ├── tourist_profile.py
│       │   ├── user.py
│       │   └── weather.py
│       └── services/
│           ├── ara_chat_service.py
│           ├── ara_conversation_orchestrator.py
│           ├── ara_message_normalizer.py
│           ├── ara_preference_merger.py
│           ├── ara_response_builder.py
│           ├── ara_service.py
│           ├── ara_trip_draft_builder.py
│           ├── ara_turn_classifier.py
│           ├── embedding_service.py
│           ├── geo_service.py
│           ├── geocoding_service.py
│           ├── image_service.py
│           ├── itinerary_generation_service.py
│           ├── itinerary_weather_service.py
│           ├── llm_service.py
│           ├── poi_metadata_extractor.py
│           ├── poi_search_service.py
│           ├── review_enrichment_service.py
│           └── weather_service.py
└── fastapi/
    └── ... entorno virtual local previo ...
```

---

## 6. Arquitectura aplicada actualmente

## 6.1 Capas y responsabilidades
### `app/api/`
Responsable de la frontera HTTP:
- definición de rutas,
- parsing de requests,
- inyección de dependencias,
- respuestas HTTP,
- códigos de estado,
- errores de validación o autorización.

Desde la refactorización de la Fase 1, los endpoints son **thin handlers**: delegan toda la lógica de negocio en services y repositories. No contienen lógica de dominio, solo orquestan la request/response.

### `app/core/`
Responsable de infraestructura transversal:
- configuración vía settings,
- seguridad JWT con claims `iat`/`jti`/`iss`,
- hashing de passwords,
- rate limiting (slowapi),
- constantes de dominio (`ara_constants.py`, `itinerary_constants.py`),
- utilidades de tiempo (`time_utils.py`),
- excepciones jerárquicas (`exceptions.py`),
- pool compartido de HTTP client (`http_client.py`).

### `app/db/`
Responsable de infraestructura de persistencia:
- `Base` del ORM,
- registro de metadata,
- engine async,
- sesión por request,
- imports de modelos para descubrimiento global.

### `app/models/`
Responsable de la representación ORM persistente:
- tablas,
- columnas,
- relaciones,
- constraints reflejadas desde el modelo.

### `app/schemas/`
Responsable de contratos externos e internos validados:
- payloads de entrada,
- respuestas serializadas,
- estructuras intermedias para IA/itinerarios.

### `app/repositories/`
Responsable del acceso a datos:
- consultas,
- escritura,
- flush/commit/rollback vía `BaseRepository._commit_or_rollback()`,
- rehidratación a schemas de salida,
- utilidades compartidas en `utils.py` (`get_category_ids_batch`, `build_poi_response_from_row`).

### `app/services/`
Responsable de integraciones externas y lógica de negocio:
- embeddings OpenAI,
- generación de itinerarios con DeepSeek (`itinerary_generation_service.py`),
- clima para itinerarios (`itinerary_weather_service.py`),
- búsqueda de POIs con geocoding (`poi_search_service.py`),
- enriquecimiento de reviews (`review_enrichment_service.py`),
- servicios modulares de Ara (`ara_message_normalizer`, `ara_turn_classifier`, `ara_preference_merger`, `ara_trip_draft_builder`, `ara_response_builder`, `ara_conversation_orchestrator`, `ara_chat_service`),
- distancia Haversine (`geo_service.py`).
- `rag_service.py` ya no existe; el futuro pipeline RAG debe implementarse como servicio nuevo si se retoma.

## 6.2 Estado real de la separación
La separación de capas está consolidada tras la refactorización de la Fase 1. Actualmente:
- los endpoints son **thin handlers** que solo parsean request, delegan a services/repositories y devuelven response,
- la lógica de negocio vive en services dedicados, no duplicada en endpoints,
- los repositories heredan de `BaseRepository` y comparten utilidades en `utils.py`,
- las constantes de dominio están centralizadas en `core/ara_constants.py` e `itinerary_constants.py`,
- se eliminaron los imports privados entre endpoints (cross-endpoint function imports),
- ra.py pasó de 2043 a ~200 líneas, itineraries.py de 1281 a ~413, ara_service.py de 1707 a ~186.

Esta es la forma madura de la arquitectura: endpoints delgados, services con lógica real, repositories para persistencia, core para transversales.

---

## 6.3 Módulos de servicio descompuestos (refactorización Fase 1)

La refactorización consistió en extraer la lógica de los monolitos (ara.py, itineraries.py, ara_service.py) en módulos con responsabilidad única:

### Ara — servicios modulares
| Archivo | Responsabilidad |
|---------|----------------|
| `ara_service.py` (~186 líneas) | Fachada delgada: recibe request, delega al orquestador |
| `ara_conversation_orchestrator.py` | Orquestación del flujo conversacional y generación |
| `ara_message_normalizer.py` | Normalización/limpieza de mensajes del usuario (typos, acentos) |
| `ara_turn_classifier.py` | Clasificación de intención (amplia, específica, free_question, candidate_selection) |
| `ara_preference_merger.py` | Merge de preferencias y dimensiones completadas |
| `ara_trip_draft_builder.py` | Construcción del draft de itinerario desde preferencias |
| `ara_response_builder.py` | Formateo de respuestas textuales y quick replies |
| `ara_chat_service.py` | Servicio de chat con DeepSeek para Ara |
| `poi_search_service.py` (~362 líneas) | Búsqueda de POIs con geocoding, normalización y detección de destinos |

### Itinerarios — servicios extraídos
| Archivo | Responsabilidad |
|---------|----------------|
| `itinerary_generation_service.py` (~830 líneas) | Toda la lógica de generación, validación, sanitización y persistencia |
| `itinerary_weather_service.py` | Lógica de clima por paso, forecast diario, cache TTL |
| `itinerary_constants.py` | Constantes: categorías, términos, config horaria |

### Reviews — servicio extraído
| Archivo | Responsabilidad |
|---------|----------------|
| `review_enrichment_service.py` | Enriquecimiento: embedding + perfil dinámico (antes en repository) |

### Infraestructura transversal — nuevos módulos
| Archivo | Responsabilidad |
|---------|----------------|
| `repositories/base.py` | `BaseRepository` con `_commit_or_rollback()` compartido |
| `repositories/utils.py` | `get_category_ids`, `get_category_ids_batch`, `build_poi_response_from_row` |
| `core/exceptions.py` | Jerarquía: `AppError` → `NotFoundError`, `PermissionError`, `ValidationError`, `ExternalServiceError` |
| `core/time_utils.py` | `CHILE_TZ`, `UTC_TZ`, `to_chile_timezone()` |
| `core/http_client.py` | Pool compartido de `httpx.AsyncClient` con límites de conexión |
| `core/rate_limit.py` | `Limiter` de slowapi configurado |
| `core/ara_constants.py` | 458 líneas de términos, patterns, dimensiones y destinos |
| `core/itinerary_constants.py` | Categorías, términos, config horaria para itinerarios |
| `geo_service.py` | `distance_meters()` con fórmula Haversine |

---

## 7. Configuración central (`app/core/config.py`)

## 7.1 Variables actuales de settings
El backend expone actualmente estas configuraciones principales:

### App
- `app_name`
- `app_version`
- `api_v1_prefix`

### PostgreSQL
- `postgres_user`
- `postgres_password`
- `postgres_db`
- `postgres_host`
- `postgres_port`

### IA
- `openai_api_key`
- `deepseek_api_key`
- `deepseek_base_url`

### Seguridad JWT
- `secret_key`
- `algorithm`
- `access_token_expire_minutes` (default 60)
- `refresh_token_expire_minutes` (default 10080 = 7 días)

## 7.2 URI async
`settings.async_database_uri` construye la conexión con formato:

```text
postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>
```

## 7.3 Observaciones importantes
- se usa `SettingsConfigDict` con `.env`.
- `extra="ignore"` permite tolerar claves sobrantes en `.env`.
- `case_sensitive=False` facilita lectura de variables en distintos formatos.
- el proyecto ya no necesita claves de Gemini.

## 7.4 Variables mínimas esperables en `.env`
No se documentan secretos reales, pero conceptualmente hoy se esperan al menos:

> **SECRET_KEY es REQUERIDO.** No tiene valor por defecto. Si no se define en `.env`, Pydantic falla en startup con `ValidationError`. Las demas claves (OpenAI, DeepSeek, OpenWeather) son optativas y el sistema degrada gracefulmente cuando no estan presentes.

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=admin
POSTGRES_DB=rutaviva_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com

SECRET_KEY=...
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_MINUTES=10080
```

---

## 8. Seguridad y autenticación

## 8.1 Password hashing
`app/core/security.py` usa `passlib` con esquema:
- `bcrypt_sha256`

Esto implica que el sistema nunca persiste el password plano.

## 8.2 Login y emisión de JWT
El endpoint `POST /api/v1/auth/login`:
1. busca usuario por email,
2. verifica password contra `password_hash`,
3. si coincide, genera access token con `create_access_token(subject=str(user.id))`,
4. devuelve `Token(access_token=..., token_type="bearer", refresh_token=...)`.

### Claims del JWT
Cada token incluye:
- `sub`: UUID del usuario,
- `exp`: timestamp de expiración,
- `iat`: timestamp de emisión (`int(datetime.now(timezone.utc).timestamp())`),
- `jti`: UUID único por token (para futura revocación),
- `iss`: `"ruta-viva"` (issuer fijo).

### Expiración
- Access token: **60 minutos** (era 7 días / 10080 minutos).
- Refresh token: **7 días** (10080 minutos) vía `create_refresh_token()`.

### Rate limiting en login
- `POST /api/v1/auth/login`: máximo 5 requests/minuto por IP.
- Implementado con `slowapi` vía `app/core/rate_limit.py`.

## 8.3 Validación de usuario autenticado
La dependencia `get_current_user`:
1. recibe `HTTPAuthorizationCredentials` vía `HTTPBearer`,
2. decodifica JWT con `settings.secret_key` y `settings.algorithm`,
3. valida que `iss == "ruta-viva"` (issuer verificación),
4. extrae `sub`,
5. lo transforma a `UUID`,
6. carga el usuario desde base,
7. y devuelve la entidad `User` si todo es válido.

La dependencia `get_optional_current_user`:
- funciona igual pero retorna `None` en vez de lanzar 401,
- usada en endpoints con autenticación opcional (ej: búsqueda semántica personalizada).

## 8.4 Estado actual de autorización
Hay autenticación funcional, pero autorización fina aún parcial.

### Casos actuales
- `GET /users/me` solo exige usuario autenticado.
- `POST /pois/` exige usuario autenticado, pero no impone formalmente que deba ser emprendedor; si el usuario tiene `entrepreneur_profile`, se usa como `entrepreneur_id`, y si no, queda `None`.
- `POST /itineraries/generate` sí valida específicamente que `current_user.tourist_profile is not None`.
- `POST /api/v1/media/upload` ahora requiere usuario autenticado vía `Depends(get_current_user)` (anteriormente era público).

Esto muestra que la autorización por rol todavía está en etapa intermedia.

---

## 9. Sesión de base de datos y flujo async

## 9.1 Engine
`app/db/session.py` crea el engine async con:
- `create_async_engine(settings.async_database_uri, echo=False, pool_pre_ping=True)`

`pool_pre_ping=True` ayuda a mitigar conexiones muertas o recicladas inválidamente.

## 9.2 Session factory
Se usa:

- `async_sessionmaker`
- `class_=AsyncSession`
- `autoflush=False`
- `expire_on_commit=False`

### Implicaciones
- `autoflush=False`: el sistema no empuja cambios automáticamente en cualquier acceso; el control es más explícito.
- `expire_on_commit=False`: los objetos no se invalidan automáticamente después del commit, lo que simplifica ciertos flujos de retorno tras persistencia.

## 9.3 Dependency `get_db`
`get_db()` entrega una `AsyncSession` por request mediante `async with AsyncSessionLocal() as session`.

FastAPI resuelve esta dependencia en endpoints que la declaran con `Depends(get_db)`.

---

## 10. Metadata ORM y registro de modelos

## 10.1 Problema detectado
Se detectó un problema importante alrededor del registro global de modelos para Alembic.

La intención correcta era que Alembic viera todos los modelos en `Base.metadata`, pero una primera solución hizo que `app/db/base.py` importara modelos concretos. Eso produjo un ciclo circular:

1. Alembic cargaba `migrations/env.py`,
2. `env.py` importaba `app.db.models`,
3. `app.db.models` importaba modelos como `Bookmark`,
4. `Bookmark` importaba `Base` desde `app.db.base`,
5. y `base.py` intentaba volver a importar `Bookmark` antes de que terminara de inicializarse.

El síntoma fue:

```text
ImportError: cannot import name 'Bookmark' from partially initialized module
```

## 10.2 Solución aplicada
La solución correcta quedó así:

- `app/db/base.py` define únicamente `Base`.
- `app/db/models.py` importa todos los modelos concretos.
- `migrations/env.py` importa `app.db.models` antes de usar `Base.metadata`.

Esto evita ciclos y mantiene la metadata completa para Alembic.

## 10.3 Modelos registrados a través de `app/db/models.py`
`app/db/models.py` importa:

- `User`
- `TouristProfile`
- `EntrepreneurProfile`
- `Category`
- `POI`
- `POICategory`
- `Bookmark`
- `Review`
- `Itinerary`
- `ItineraryStep`
- `EntrepreneurPost`
- `POIVisit`
- `AraSession`
- `AraMessage`

Al importar ese módulo, todos esos modelos quedan cargados y sus tablas se incorporan a `Base.metadata`.

## 10.4 Decisión técnica corregida
`app/db/base.py` debe mantenerse mínimo:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

La regla práctica del proyecto queda así:

> `base.py` define la raíz declarativa; `models.py` registra los modelos concretos.

## 10.5 Estado actual
Actualmente:

- `migrations/env.py` importa `app.db.models`,
- luego usa `target_metadata = Base.metadata`,
- y `alembic upgrade head` ya corre sin el error circular.

Esto deja a Alembic y a la app con el modelo global correctamente visible sin romper la inicialización de Python.

---

## 11. Modelado de dominio y persistencia

## 11.1 Entidades principales
### `User`
Representa identidad base del sistema.
Campos relevantes:
- `id: UUID`
- `email`
- `password_hash`
- `is_active`
- `created_at`
- `updated_at` (agregado en Fase 4, server_default `now()`)

Relaciones:
- `tourist_profile` (1 a 1 opcional)
- `entrepreneur_profile` (1 a 1 opcional)

### `TouristProfile`
Extiende al usuario turista.
Campos relevantes:
- `user_id`
- `full_name`
- `interests_embedding: Vector(1536) | None`
- `has_own_transport`
- `system_preferences: JSONB | None`

Relaciones:
- `bookmarks`
- `reviews`
- `itineraries`

### `EntrepreneurProfile`
Extiende al usuario emprendedor.
Campos relevantes:
- `user_id`
- `rut: String(12) | None` (único, RUT chileno validado con módulo 11)
- `verification_status: String(20)` (default "unverified"; estados: "unverified", "pending_review", "verified")
- `admin_data: JSONB | None`

Relaciones:
- `pois`
- `posts`

### `EntrepreneurPost`
Contenido publicado por emprendedores asociado a sus POIs.
Campos relevantes:
- `id`
- `entrepreneur_id` → FK a `entrepreneur_profiles`
- `poi_id` → FK NOT NULL a `pois`
- `title`, `content`
- `image_url`
- `is_published`
- `is_pinned: bool` (default false)
- `sort_order: Integer` (default 0)
- `scheduled_at: DateTime | None`

Relaciones:
- `entrepreneur`
- `poi`

### `POIVisit`
Tracking de visitas a POIs.
Campos relevantes:
- `id`
- `poi_id` → FK a `pois`
- `visitor_id` → FK nullable a `users`
- `visited_at`

Relaciones:
- `poi`

### `Category`
Catálogo de categorías para POIs.
Campos:
- `id` entero autoincremental
- `name` único
- `icon_url`

### `POI`
Punto de interés principal del dominio turístico.
Campos relevantes:
- `id`
- `entrepreneur_id`
- `name`
- `description`
- `location: Geometry('POINT', srid=4326)`
- `description_embedding: Vector(1536)`
- `access_type`
- `contact_phone`
- `contact_email`
- `multimedia_urls: JSONB | None`
- `verification_status: String(20)` (default "pending"; estados: "pending", "verified", "flagged")
- `confidence_score: Float` (default 0.0; calculada automáticamente por señales: fotos, descripción, categorías, horarios, reviews, visitas, creador verificado)

Relaciones:
- `entrepreneur`
- `category_links`
- `bookmarks`
- `reviews`
- `itinerary_steps`
- `visits`
- `entrepreneur_posts`

### `POICategory`
Tabla puente many-to-many entre POIs y categorías.

### `Bookmark`
Marca de guardado entre turista y POI.
Constraint importante:
- `uq_bookmark_tourist_poi`

### `Review`
Review turística de POI.
Campos relevantes:
- `rating_stars` con `CHECK BETWEEN 1 AND 5`
- `text_embedding: Vector(1536) | None`

Constraint importante:
- `uq_reviews_tourist_poi` sobre (`tourist_id`, `poi_id`) — previene reviews duplicadas del mismo turista al mismo POI.

### `Itinerary`
Cabecera del itinerario generado o planificado.
Campos relevantes:
- `tourist_id`
- `title`
- `start_date`
- `end_date`
- `status`
- `created_at` (agregado en Fase 4)
- `updated_at` (agregado en Fase 4)

### `ItineraryStep`
Paso individual del itinerario.
Campos relevantes:
- `itinerary_id`
- `poi_id`
- `step_order`
- `arrival_time`
- `departure_time`
- `ai_context: JSONB | None`

Constraint importante:
- `uq_itinerary_steps_order` sobre (`itinerary_id`, `step_order`)

## 11.2 Relaciones de dominio importantes
- `users` → `tourist_profiles`: 1 a 1
- `users` → `entrepreneur_profiles`: 1 a 1
- `tourist_profiles` → `itineraries`: 1 a muchos
- `itineraries` → `itinerary_steps`: 1 a muchos
- `pois` → `itinerary_steps`: 1 a muchos
- `pois` ↔ `categories`: muchos a muchos vía `poi_categories`
- `tourist_profiles` ↔ `pois` por bookmarks y reviews

## 11.3 Tipos especiales del proyecto
### Espacial
- `Geometry('POINT', srid=4326)` para ubicación persistida de POIs.

### Vectorial
- `Vector(1536)` para:
  - `POI.description_embedding`
  - `TouristProfile.interests_embedding`
  - `Review.text_embedding`

### JSON
- `JSONB` para:
  - `EntrepreneurProfile.admin_data`
  - `TouristProfile.system_preferences`
  - `POI.multimedia_urls`
  - `ItineraryStep.ai_context`

---

## 12. Schemas Pydantic actuales

## 12.1 Auth y usuario
- `UserCreate`
- `UserResponse`
- `TouristProfileCreate`
- `TouristProfileResponse`
- `Token`
- `TokenPayload` (con `sub`, `iat`, `jti`, `iss`)
- `RefreshTokenRequest`
- `RegisterRequest` (declarado dentro de `auth.py`)
- `LoginRequest` (declarado dentro de `auth.py`)

## 12.2 POIs
- `POIBase`
- `POICreate`
- `POIResponse`

Características importantes:
- el contrato externo habla en español (`nombre`, `descripcion`, `tipo_acceso`, etc.),
- pero el ORM interno usa nombres en inglés (`name`, `description`, `access_type`, etc.),
- `POIResponse` expone `latitude` y `longitude` como floats derivados desde `POI.location`.

## 12.3 Itinerarios
- `GenerateItineraryRequest`
- `GeneratedItineraryStep`
- `GeneratedItinerary`
- `ItineraryStepResponse`
- `ItineraryResponse`

Observación importante:
`GeneratedItinerary` y `GeneratedItineraryStep` cumplen doble rol:
- contrato esperado desde el LLM,
- estructura intermedia validada antes de persistir en DB.

`ItineraryStepResponse` enriquece cada paso persistido con:
- `poi_nombre`
- `poi_descripcion`

Estos campos se derivan de la relación `ItineraryStep.poi` y existen para que el frontend pueda mostrar nombres reales de lugares sin hacer una request adicional por cada `poi_id`.

---

## 13. Repositorios actuales

## 13.1 `UserRepository`
Responsabilidades actuales:
- buscar usuario por ID,
- buscar usuario por email,
- crear usuario turista + perfil turista en una misma transacción.

### Punto importante
`create_tourist_user()`:
- crea `User`,
- hace `flush()` para obtener `user.id`,
- crea `TouristProfile`,
- hace `commit()`,
- `refresh(user)`,
- devuelve el usuario ya persistido.

## 13.2 `POIRepository`
Responsabilidades actuales:
- crear POIs,
- recuperar POIs cercanos,
- buscar POIs con ranking semántico,
- reconstruir `POIResponse` con `latitude`, `longitude` y `category_ids`.

### `create_poi()`
Aspectos clave:
- construye `POINT(longitude latitude)` con SRID 4326,
- persiste el embedding ya generado externamente,
- inserta filas en `poi_categories`,
- hace commit transaccional.

### `get_pois_nearby()`
Aspectos clave:
- usa `ST_SetSRID`, `ST_MakePoint`, `ST_DWithin` y `ST_Distance`,
- convierte `POI.location` a `Geography` para mediciones realistas en metros,
- ordena por distancia.

### `search_hybrid()`
Aspectos clave:
- usa el mismo filtro geográfico por radio,
- usa `POI.description_embedding.cosine_distance(query_embedding)`,
- ordena por `semantic_distance`,
- limita resultados.

### Nota importante sobre el nombre “hybrid”
En la implementación actual, “hybrid” significa:
- restricción geográfica espacial por radio,
- seguida de ranking semántico vectorial.

No existe todavía una fórmula explícita de score combinado ponderado entre distancia geográfica y similitud semántica.

## 13.3 `ItineraryRepository`
Responsabilidades actuales:
- persistir itinerarios generados,
- persistir pasos ordenados del itinerario,
- recargar el itinerario completo con `steps` usando `selectinload`.

### Decisiones importantes
- ordena los pasos por `step_order` antes de guardar,
- reenumera desde 1 al persistir,
- envuelve el proceso en transacción con commit/rollback,
- devuelve `ItineraryResponse` ya rehidratado desde DB.

---

## 14. Servicios externos actuales

## 14.1 `OpenAIEmbeddingService`
Archivo:
- `ruta_viva/app/services/embedding_service.py`

Responsabilidad:
- generar embeddings de texto para búsquedas semánticas y persistencia de POIs.

Características:
- usa `AsyncOpenAI(api_key=settings.openai_api_key)`
- modelo fijo: `text-embedding-3-small`
- método principal: `async def get_embedding(text: str) -> list[float]`
- expuesto por `get_embedding_service()` como singleton simple lazy

### Decisión técnica
Se evitó una factory compleja y se dejó una integración explícita, pequeña y mantenible.

## 14.2 `ItineraryGenerator`
Archivo:
- `ruta_viva/app/services/llm_service.py`

Responsabilidad:
- tomar una consulta de usuario y una lista de POIs de contexto,
- invocar DeepSeek,
- exigir JSON estructurado,
- validar el resultado contra `GeneratedItinerary`.

Características:
- usa `AsyncOpenAI` con `base_url=settings.deepseek_base_url`
- modelo fijo: `deepseek-chat`
- el prompt obliga a:
  - actuar como experto en La Araucanía,
  - no inventar lugares,
  - usar solo `poi_id` presentes en el contexto,
  - devolver solo JSON válido,
  - producir estructura compatible con `GeneratedItinerary`.

### Defensa por capas aplicada actualmente
1. prompt estricto,
2. `response_format={"type": "json_object"}`,
3. `json.loads(content)`,
4. `GeneratedItinerary.model_validate(parsed)`,
5. validación posterior en endpoint para asegurar que todos los `poi_id` pertenezcan al conjunto entregado.

---

## 15. Catálogo detallado de endpoints

## 15.1 `GET /health`
Archivo:
- `app/main.py`

Propósito:
- comprobar que la API está arriba y que la base responde.

Flujo:
1. FastAPI resuelve `db` con `get_db`.
2. se ejecuta `SELECT 1`.
3. si no falla, responde `{"status": "ok", "database": "up"}`.

## 15.2 `POST /api/v1/auth/register`
Archivo:
- `app/api/v1/endpoints/auth.py`

Body esperado:
- `user: UserCreate`
- `profile: TouristProfileCreate`

Flujo:
1. verifica si el email ya existe,
2. si existe devuelve `400 Email already registered`,
3. si no existe, crea `User` + `TouristProfile`,
4. devuelve `UserResponse`.

## 15.3 `POST /api/v1/auth/login`
Archivo:
- `app/api/v1/endpoints/auth.py`

Body esperado:
- `email`
- `password`

Flujo:
1. busca usuario por email,
2. verifica password hash,
3. si falla devuelve `401 Incorrect email or password`,
4. si pasa, retorna token bearer.



## 15.3.1 Perfil turista y emprendedor
Archivos:
- `app/api/v1/endpoints/users.py`
- `app/repositories/user_repository.py`

Endpoints:
- `GET /api/v1/users/me` devuelve usuario con `tourist_profile` y `entrepreneur_profile`.
- `PUT /api/v1/users/me/tourist-profile` actualiza `full_name`, `has_own_transport` y `system_preferences`.
- `POST /api/v1/users/me/entrepreneur-profile` crea/actualiza perfil emprendedor.
- `DELETE /api/v1/users/me/tourist-profile/interests` resetea `interests_embedding` a `None` (escape hatch para perfil semántico contaminado).

Uso principal:
- permitir que el frontend edite preferencias reales, active flujo emprendedor sin crear una cuenta separada, y reinicie el perfil semántico si reviews antiguas sesgan las recomendaciones.

## 15.4 `GET /api/v1/users/me`
Archivo:
- `app/api/v1/endpoints/users.py`

Flujo:
1. FastAPI resuelve `current_user` por dependencia,
2. endpoint serializa ese usuario en `UserResponse`.

## 15.5 `POST /api/v1/pois/`
Archivo:
- `app/api/v1/endpoints/pois.py`

Body esperado:
- `POICreate`

Flujo:
1. requiere usuario autenticado,
2. determina `entrepreneur_id` si existe `entrepreneur_profile`,
3. concatena `payload.nombre + payload.descripcion`,
4. obtiene embedding OpenAI,
5. llama `poi_repository.create_poi(...)`,
6. persiste POI + relaciones con categorías,
7. devuelve `POIResponse`.

### Nota importante
La creación de embedding ocurre **antes** de delegar al repositorio. El repositorio no sabe generar embeddings; solo persiste el vector que recibe.

## 15.6 `GET /api/v1/pois/search`
Archivo:
- `app/api/v1/endpoints/pois.py`

Query params:
- `lat`
- `lon`
- `radius` (default 5000)

Flujo:
1. no requiere autenticación,
2. delega a `get_pois_nearby()`,
3. retorna lista ordenada por distancia.

## 15.7 `GET /api/v1/pois/semantic-search`
Archivo:
- `app/api/v1/endpoints/pois.py`

Query params:
- `query`
- `lat`
- `lon`
- `radius`

Flujo:
1. genera embedding de la query con OpenAI,
2. llama a `search_hybrid()`,
3. filtra por radio y rankea por distancia semántica coseno,
4. devuelve POIs relevantes.

## 15.8 `GET /api/v1/pois/{poi_id}`
Archivo:
- `app/api/v1/endpoints/pois.py`

Path params:
- `poi_id`

Flujo:
1. no requiere autenticación,
2. busca el POI por UUID,
3. reconstruye `POIResponse` con `latitude`, `longitude` y `category_ids`,
4. devuelve `404 POI not found.` si el UUID no existe.

Uso principal:
- soportar la pantalla de detalle del frontend cuando el POI no está ya cargado en memoria desde el mapa.



## 15.8.1 `PATCH /api/v1/pois/{poi_id}/media`
Archivo:
- `app/api/v1/endpoints/pois.py`

Body esperado:
- `image_url`

Flujo:
1. exige usuario autenticado,
2. valida que el POI exista,
3. si el POI tiene `entrepreneur_id`, exige que coincida con el usuario actual,
4. agrega la URL a `multimedia_urls.gallery`,
5. usa la URL como `cover` si el POI no tenía portada,
6. devuelve el `POIResponse` actualizado.

Uso principal:
- asociar al POI la URL devuelta por `POST /api/v1/media/upload`.

## 15.8.2 `GET /api/v1/categories/`
Archivo:
- `app/api/v1/endpoints/categories.py`

Flujo:
1. no requiere autenticación,
2. lee `categories` ordenadas por ID,
3. devuelve `id`, `name` e `icon_url`.

Uso principal:
- reemplazar categorías hardcodeadas del frontend.



## 15.8.3 POIs propios de emprendedor
Archivo:
- `app/api/v1/endpoints/pois.py`

Endpoints:
- `GET /api/v1/pois/mine` lista POIs cuyo `entrepreneur_id` coincide con el usuario autenticado.
- `PUT /api/v1/pois/{poi_id}` edita campos principales, ubicación y categorías.
- `DELETE /api/v1/pois/{poi_id}` elimina el POI propio.

Reglas:
- requieren `entrepreneur_profile`,
- solo el dueño puede editar/eliminar,
- si cambia nombre o descripción se recalcula `description_embedding`.

## 15.9 `POST /api/v1/itineraries/generate`
Archivo:
- `app/api/v1/endpoints/itineraries.py`

Body esperado:
- `query`
- `lat`
- `lon`
- `radius`
- `start_date`
- `end_date`

Flujo completo:
1. exige usuario autenticado,
2. exige que el usuario tenga `tourist_profile`,
3. toma `start_date` y `end_date` del payload como fuente de verdad,
4. genera embedding de `payload.query`,
5. busca `context_pois` con `POIRepository.search_hybrid`,
6. si no hay POIs devuelve `404`,
7. filtra o relega POIs no deseados según intención explícita: información/CONAF y alojamientos,
8. consulta pronóstico climático,
9. enriquece la query con fechas oficiales, ubicación, radio, clima y guía horaria,
10. envía consulta y POIs a `ItineraryGenerator`,
11. valida el JSON generado con `GeneratedItinerary`,
12. normaliza horarios a `America/Santiago`,
13. comprueba que todos los `poi_id` estén dentro de `context_pois`,
14. rechaza pasos fuera de fecha, huecos grandes, alojamientos absurdos o uso no pedido de oficinas/servicios de información,
15. sanitiza consejos recursivos inútiles,
16. persiste `Itinerary` e `ItineraryStep`,
17. recarga pasos con su POI asociado,
18. retorna `ItineraryResponse` completo, incluyendo `poi_nombre`, `poi_descripcion`, `day_index`, `day_date` y `day_label` por paso.


## 15.9.1 `GET /api/v1/itineraries/`
Archivo:
- `app/api/v1/endpoints/itineraries.py`

Flujo:
1. exige usuario autenticado,
2. exige `tourist_profile`,
3. consulta `ItineraryRepository.list_itineraries_by_tourist(...)`,
4. filtra por `tourist_id=current_user.id`,
5. devuelve itinerarios con pasos ordenados y datos básicos del POI (`poi_nombre`, `poi_descripcion`).

Uso principal:
- alimentar el historial de itinerarios del frontend.

## 15.9.2 `GET /api/v1/itineraries/{itinerary_id}`
Archivo:
- `app/api/v1/endpoints/itineraries.py`

Flujo:
1. exige usuario autenticado,
2. exige `tourist_profile`,
3. busca por `itinerary_id` y `tourist_id=current_user.id`,
4. devuelve `404 Itinerary not found.` cuando no existe o no pertenece al usuario,
5. devuelve `ItineraryResponse` enriquecido cuando existe.

Uso principal:
- permitir que el frontend abra un detalle persistido por URL/ID sin depender del estado en memoria.

## 15.9.3 Endpoints de edición y mapa filtrado de itinerarios
Archivo:
- `app/api/v1/endpoints/itineraries.py`

Endpoints:
- `GET /api/v1/itineraries/{itinerary_id}/pois`: devuelve únicamente los POIs usados por el itinerario. Su objetivo principal es el mapa filtrado.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/{step_id}`: acepta `poi_id`, `arrival_time`, `departure_time` y/o `ai_context` para modificar un paso.
- `DELETE /api/v1/itineraries/{itinerary_id}/steps/{step_id}`: elimina un paso y reordena los restantes.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/reorder`: acepta `{"step_ids": ["..."]}` y exige contener todos los steps exactamente una vez.
- `DELETE /api/v1/itineraries/{itinerary_id}`: elimina el itinerario completo y responde `204 No Content`.

Reglas:
- todos requieren turista autenticado,
- todos validan propiedad por `tourist_id=current_user.id`,
- la eliminación completa se apoya en `ON DELETE CASCADE` para borrar steps.

## 15.9.4 Contrato de fechas, timezone y metadata por día
Archivo:
- `app/schemas/itinerary.py`
- `app/repositories/itinerary_repository.py`
- `app/api/v1/endpoints/itineraries.py`

Reglas actuales:
- `start_date` y `end_date` del payload son la fuente de verdad.
- Las fechas escritas en lenguaje natural dentro de `query` no deben sobreescribir el payload.
- DeepSeek recibe instrucción explícita de usar el rango oficial y no devolver UTC/Z.
- Backend normaliza horarios como hora civil de Chile (`America/Santiago`) antes de validar/persistir.
- Backend rechaza `arrival_time` o `departure_time` fuera de `[start_date, end_date]`.
- En viajes multi-día, backend exige distribución por días si hay suficientes steps, salvo intención explícita de descanso/traslado.

Cada step de respuesta puede incluir:
```json
{
  "day_index": 1,
  "day_date": "2026-05-18",
  "day_label": "Lunes 18"
}
```

Esto permite que frontend agrupe itinerarios por día sin derivar fechas desde UTC.

## 15.9.5 Ara conversacional
Archivos:
- `app/api/v1/endpoints/ara.py`
- `app/services/ara_service.py`
- `app/repositories/ara_repository.py`
- `app/models/ara_session.py`
- `app/models/ara_message.py`

Endpoints:
- `POST /api/v1/ara/sessions`
- `POST /api/v1/ara/sessions/{session_id}/messages`
- `GET /api/v1/ara/sessions/{session_id}/messages`
- `POST /api/v1/ara/sessions/{session_id}/generate-itinerary`

Flujo:
1. Home envía `initial_message` con coordenadas, radio y fechas.
2. Backend crea `AraSession` y guarda `AraMessage` del usuario.
3. Ara detecta intención amplia/específica (`gastronomia`, `naturaleza`, `cultura`, `descanso`, etc.).
4. Ara devuelve respuesta humana y quick replies dinámicos.
5. El itinerario final solo se genera cuando el usuario confirma o elige `Hazlo todo tú`.
6. `generate-itinerary` reutiliza el pipeline robusto de itinerarios: embeddings, búsqueda híbrida, clima, DeepSeek, validaciones y persistencia.

Flujo “Cambiar lugar”:
- si el mensaje contiene `itinerary_id` y `step_id`, Ara carga el itinerario, identifica el step actual, busca alternativas y devuelve chips `replace_step`.
- si frontend envía el value `usar poi <poi_id> para step <step_id>`, backend actualiza el step con `ItineraryRepository.update_step(...)`.

## 15.10 `POST /api/v1/reviews/`
Archivo:
- `app/api/v1/endpoints/reviews.py`

Body esperado:
- `ReviewCreate`

Campos:
- `poi_id`
- `rating_stars` entre 1 y 5
- `text_content`

Flujo completo:
1. exige usuario autenticado,
2. verifica que el usuario tenga `tourist_profile`,
3. valida que exista el POI reseñado,
4. persiste la review inmediatamente con `text_embedding=None`,
5. confirma transacción y devuelve `ReviewResponse`,
6. en `BackgroundTasks`, genera embedding del texto con OpenAI,
7. actualiza `reviews.text_embedding`,
8. actualiza `tourist_profiles.interests_embedding` con media móvil exponencial.

### Importancia técnica
Este endpoint es la primera feature donde una acción explícita del usuario modifica su representación semántica interna. La review no solo queda como contenido histórico; también se convierte en señal vectorial para personalización.

## 15.11 `GET /api/v1/reviews/poi/{poi_id}`
Archivo:
- `app/api/v1/endpoints/reviews.py`

Flujo:
1. recibe `poi_id` como path param,
2. consulta reviews asociadas a ese POI,
3. ordena por `created_at DESC`,
4. devuelve lista de `ReviewResponse`.

Este endpoint es público y sirve para visualizar la reputación/opiniones asociadas a un lugar.



## 15.11.1 `GET /api/v1/reviews/poi/{poi_id}/summary`
Archivo:
- `app/api/v1/endpoints/reviews.py`

Devuelve:
- `average_rating`
- `total_reviews`
- `rating_distribution`

## 15.11.2 `PUT /api/v1/reviews/{review_id}` y `DELETE /api/v1/reviews/{review_id}`
Archivo:
- `app/api/v1/endpoints/reviews.py`

Reglas:
- requieren turista autenticado,
- solo el dueño de la review puede editar/eliminar,
- al editar texto se reinicia `text_embedding` y se agenda enriquecimiento semántico en background.

## 15.12 Búsqueda semántica personalizada
Archivo:
- `app/repositories/poi_repository.py`
- `app/api/v1/endpoints/pois.py`

`GET /api/v1/pois/semantic-search` sigue siendo público, pero ahora soporta autenticación opcional.

Si no hay token o el usuario no tiene perfil turista, se comporta como antes:

```python
ranking_score = query_distance
```

Si hay usuario turista autenticado con `interests_embedding`, combina:

```python
ranking_score = (query_distance * 0.7) + (profile_distance * 0.3)
```

Donde:
- `query_distance` mide parecido entre el POI y la intención actual de búsqueda,
- `profile_distance` mide parecido entre el POI y el perfil histórico del turista.

Como son distancias, menor score significa mejor ranking.

## 15.13 Itinerarios con retrieval personalizado
Archivo:
- `app/api/v1/endpoints/itineraries.py`

El endpoint de itinerarios ya exigía usuario turista autenticado. Ahora, al llamar a `search_hybrid`, también pasa:

```python
user_interests_embedding=current_user.tourist_profile.interests_embedding
```

Esto significa que los POIs que entran como contexto para DeepSeek ya no dependen solo de la consulta puntual, sino también del perfil aprendido del turista. Por lo tanto, el grounding del itinerario queda personalizado.




## 15.14 Bookmarks de POIs
Archivos:
- `app/api/v1/endpoints/bookmarks.py`
- `app/repositories/bookmark_repository.py`

Endpoints:
- `GET /api/v1/bookmarks/` lista POIs favoritos del turista.
- `GET /api/v1/bookmarks/{poi_id}` devuelve estado booleano.
- `POST /api/v1/bookmarks/{poi_id}` guarda favorito idempotente.
- `DELETE /api/v1/bookmarks/{poi_id}` quita favorito.

Reglas:
- requieren turista autenticado,
- usan la restricción única `(tourist_id, poi_id)` como garantía de no duplicados.

## 15.15 Detección de duplicados y creación de POIs con verificación
Archivos:
- `app/api/v1/endpoints/pois.py`
- `app/repositories/poi_repository.py`
- `app/schemas/poi.py`

`POST /api/v1/pois/` ahora tiene dos respuestas posibles:
- `201 Created` → `POIResponse` (sin duplicados detectados, o `force_create=true`)
- `200 OK` → `POICreationCheck` (duplicados potenciales encontrados)

Query param `force_create=true` ignora duplicados y crea el POI directamente.

Sistema de detección de duplicados (3 pasos en cascada):
1. Geográfico: `ST_DWithin(50m)` busca candidatos a 50 metros.
2. Categoría: filtra candidatos que compartan al menos una categoría con el nuevo POI.
3. Semántico: rankea por `description_embedding.cosine_distance()`. Similitud ≥ 0.75 (distancia ≤ 0.25) → flag como potencial duplicado.

Schemas: `PotentialDuplicate(id, nombre, descripcion, latitude, longitude, category_ids, distance_meters, semantic_similarity)`, `POICreationCheck(potential_duplicates, pending_creation)`.

Rate limiting en creación: máximo 5 POIs/hora/usuario, 10 POIs/día/usuario. Excedido → `429 Too Many Requests`.

Cálculo de `confidence_score` en creación:
| Señal | Puntos |
|---|---|
| Tiene imagen (multimedia_urls con cover/gallery) | +0.2 |
| Descripción ≥ 50 chars | +0.15 |
| Descripción ≥ 20 chars | +0.05 |
| Tiene categoría | +0.1 |
| Tiene opening_hours_text | +0.1 |
| Tiene teléfono o email | +0.05 |
| Creado por emprendedor verificado | +0.2 |

Asignación de `verification_status` en creación:
| Creador | verification_status | Confianza inicial |
|---|---|---|
| OSM import (sin entrepreneur_id) | "verified" | 0.7 |
| Emprendedor verificado | "verified" | 0.5 + señales |
| Emprendedor no verificado | "pending" | 0.3 + señales |
| Turista (sin perfil emprendedor) | "pending" | 0.2 + señales |

Filtrado en búsquedas: `GET /pois/search` y `GET /pois/semantic-search` excluyen POIs con `verification_status = "flagged"`. `GET /pois/{poi_id}` no filtra — acceso directo siempre funciona.

## 15.16 Recalculación automática de confidence
Archivos:
- `app/repositories/poi_repository.py`

`POIRepository.recalculate_confidence(poi_id)` se dispara en:
- `PATCH /pois/{id}/media` (foto agregada → +0.2)
- `PUT /pois/{id}` (POI editado → recálculo por descripción, categorías, horarios)
- `POST /reviews/` (review creada → +0.02 por review, máximo 0.1)
- `POST /pois/{id}/visit` (visita registrada → +0.01 por visita, máximo 0.1)
- `POST /api/v1/entrepreneur/pois/{poi_id}/visit` (visita vía emprendedor)

Si un POI flagged alcanza score ≥ 0.4, se des-flaguea automáticamente a "pending".

## 15.17 Validación de RUT chileno
Archivos:
- `app/core/rut.py`
- `app/api/v1/endpoints/users.py`

`POST /api/v1/users/me/entrepreneur-profile` acepta RUT opcional:
- RUT válido (módulo 11) → `verification_status = "verified"` para el perfil emprendedor.
- RUT inválido → `422 Unprocessable Entity` con detalle "RUT inválido. Formato esperado: 12345678-9".
- Sin RUT → `verification_status = "unverified"`.
- RUT se almacena formateado (ej. "11111111-1") con constraint único.

## 15.18 Posts de emprendedor por POI
Archivos:
- `app/api/v1/endpoints/entrepreneur.py`
- `app/repositories/entrepreneur_repository.py`
- `app/schemas/entrepreneur.py`

Endpoints (todos requieren auth + verificación de ownership del POI):
- `POST /api/v1/entrepreneur/pois/{poi_id}/posts` — crea post asociado a un POI.
- `GET /api/v1/entrepreneur/pois/{poi_id}/posts` — lista posts del POI del emprendedor autenticado.
- `PATCH /api/v1/entrepreneur/pois/{poi_id}/posts/{post_id}` — edita post propio.
- `DELETE /api/v1/entrepreneur/pois/{poi_id}/posts/{post_id}` — elimina post propio.
- `PUT /api/v1/entrepreneur/pois/{poi_id}/posts/{post_id}/pin` — fija/desfija un post (`is_pinned`).
- `PUT /api/v1/entrepreneur/pois/{poi_id}/posts/reorder` — reordena posts con `PostPositionItem(post_id, sort_order)`.

Schemas: `EntrepreneurPostCreatePOI`, `EntrepreneurPostResponse` (incluye `poi_id`, `poi_name`, `is_pinned`, `scheduled_at`), `PinPostRequest`, `PostPositionItem`, `ReorderPostsRequest`.

## 15.19 Posts públicos de POI
Archivos:
- `app/api/v1/endpoints/pois.py`
- `app/repositories/entrepreneur_repository.py`
- `app/schemas/entrepreneur.py`

`GET /api/v1/pois/{poi_id}/posts` — endpoint público, sin autenticación. Retorna solo posts publicados (`is_published=True`), ordenados por `is_pinned DESC, sort_order ASC, created_at DESC`. Schema: `PublicEntrepreneurPostResponse` (id, title, content, image_url, is_published, is_pinned, scheduled_at, created_at, updated_at — sin entrepreneur_id ni poi_name).

## 15.20 Visitas, analíticas y actividad de POIs
Archivos:
- `app/api/v1/endpoints/entrepreneur.py`
- `app/api/v1/endpoints/pois.py`
- `app/repositories/entrepreneur_repository.py`
- `app/models/poi_visit.py`
- `app/schemas/entrepreneur.py`

Endpoints:
- `POST /api/v1/pois/{poi_id}/visit` — registro público de visita (no requiere auth). Schemas: `POIVisitCreate`, `POIVisitResponse`.
- `POST /api/v1/entrepreneur/pois/{poi_id}/visit` — registro de visita vía emprendedor, con recálculo de confidence.
- `GET /api/v1/entrepreneur/pois/{poi_id}/analytics` — analíticas del POI (auth, verifica ownership). Retorna `POIAnalyticsResponse` con `weekly_visits` (últimos 7 días), `monthly_growth` (crecimiento mes-a-mes en %).
- `GET /api/v1/entrepreneur/pois/{poi_id}/activity` — historial de actividad. Retorna lista `POIActivityItem`.
- `GET /api/v1/entrepreneur/me/metrics` — métricas agregadas del emprendedor autenticado.
- `GET /api/v1/entrepreneur/me/income` — placeholder estable de ingresos.

## 15.21 Gestión de itinerarios: reschedule, reorder con tiempos, clima por paso
Archivos:
- `app/api/v1/endpoints/itineraries.py`
- `app/repositories/itinerary_repository.py`
- `app/schemas/itinerary.py`
- `app/schemas/weather.py`
- `app/services/weather_service.py`

Endpoints (todos requieren turista autenticado y ownership del itinerario):
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/{step_id}/reschedule` — modifica `arrival_time` y `duration_minutes` de un paso, desplazando pasos subsecuentes del mismo día por el delta. Normaliza timezone a `America/Santiago`. Maneja tiempos `None`. Schema: `RescheduleStepRequest`.
- `PATCH /api/v1/itineraries/{itinerary_id}/steps/reorder-with-times` — reordena pasos con redistribución automática de horarios: cursor temporal desde 9:00 AM, gaps de 15 minutos, preserva duraciones. Patrón de dos fases (step_order negativo luego positivo). Schema: `ReorderStepsWithTimesRequest(steps: list[StepDayPosition])`.
- `GET /api/v1/itineraries/{itinerary_id}/weather` — retorna pronóstico por día para cada coordenada única de POI. Agrupa por `(rounded_lat, rounded_lon, date)` para cache y evita llamadas duplicadas a OWM. Usa `get_daily_forecast()` con API estructurada. Schema: `ItineraryStepWeatherResponse`.
- Inyección de clima en generación: tras `_sanitize_generated_itinerary_context`, el backend inyecta `ai_context.weather` por paso con `{description, temperature_c, precipitation_probability}` desde el forecast diario.
- Se agregó `from sqlalchemy import func as sql_func` en `itineraries.py` para funciones geoespaciales `ST_Y`/`ST_X`.
- Se agregó `format_forecast_summary` importado a `itineraries.py`.

## 16. Búsqueda geográfica y semántica

## 16.1 Geoespacial puro
La búsqueda cercana usa PostGIS con este razonamiento:
- el punto de referencia del usuario se construye con `ST_MakePoint(lon, lat)`,
- se declara con SRID 4326,
- se castea a `Geography` para usar metros reales,
- se filtra con `ST_DWithin`,
- y se mide con `ST_Distance`.

## 16.2 Semántico puro vs híbrido actual
El proyecto no hace hoy una búsqueda semántica global sin restricción espacial. En vez de eso, aplica una forma práctica de híbrido:

1. reduce el universo por cercanía geográfica,
2. calcula similitud vectorial sobre ese universo,
3. devuelve los más semánticamente cercanos dentro del radio.

## 16.3 Beneficio de este enfoque actual
Para turismo, esto evita un problema muy común: recuperar lugares semánticamente parecidos pero físicamente inviables por distancia.

---

## 17. IA aplicada actualmente en el backend

## 17.1 Embeddings
### Objetivo actual
Representar la descripción de un POI en un espacio vectorial para permitir retrieval semántico.

### Decisión tomada
Se estandarizó el sistema en OpenAI `text-embedding-3-small`.

### Razones de la decisión
- simplicidad de mantenimiento,
- proveedor único,
- coherencia dimensional,
- integración limpia con `AsyncOpenAI`,
- menor complejidad que sostener múltiples proveedores.

## 17.2 DeepSeek para itinerarios
### Objetivo actual
Usar un modelo generativo para transformar una intención de viaje y una lista de POIs relevantes en un itinerario estructurado y persistible.

### Restricciones de seguridad lógica
El backend no confía ciegamente en el LLM. El sistema aplica varias barreras:
- contexto limitado a POIs recuperados,
- prompt restrictivo,
- formato JSON requerido,
- validación Pydantic,
- control server-side de `poi_id` válidos,
- error si el modelo devuelve pasos vacíos.

### Resultado actual
El sistema ya genera y guarda itinerarios correctamente.


---

## 17.3 Reviews como señales semánticas de preferencia
La fase 3.5 incorporó reviews no solo como contenido social, sino como señales semánticas para perfilar al usuario.

Cuando un turista crea una review:

1. se guarda el rating estructurado,
2. se guarda el texto,
3. se genera embedding del texto,
4. se persiste ese embedding en `reviews.text_embedding`,
5. se actualiza `tourist_profiles.interests_embedding`.

Esto convierte cada review en una observación de intereses.

## 17.4 Matemática del perfil dinámico
La actualización del perfil usa una media móvil exponencial:

```python
nuevo_perfil = (perfil_actual * 0.9) + (embedding_review * 0.1)
```

Como los embeddings son vectores de 1536 dimensiones, la operación ocurre dimensión por dimensión:

```python
nuevo[i] = perfil_actual[i] * 0.9 + embedding_review[i] * 0.1
```

### Interpretación
- `0.9` conserva la mayor parte del historial del usuario.
- `0.1` incorpora suavemente la nueva señal.
- una sola review no cambia brutalmente el perfil.
- muchas reviews en una dirección semántica sí desplazan gradualmente el perfil.

Si el usuario no tiene `interests_embedding`, la primera review inicializa el perfil directamente con `embedding_review`.

## 17.5 Personalización de búsqueda e itinerarios
La búsqueda híbrida ahora puede usar dos señales:

1. señal explícita actual: lo que el usuario busca ahora,
2. señal histórica: lo que el usuario ha demostrado preferir mediante reviews.

La fórmula actual de ranking personalizado es:

```python
ranking_score = (query_distance * 0.7) + (profile_distance * 0.3)
```

Esto mantiene prioridad en la intención actual, pero permite que el historial module resultados.

En itinerarios, esta personalización afecta el conjunto de POIs enviado a DeepSeek, por lo que el LLM recibe un contexto más alineado al usuario.

## 17.6 Ingesta masiva OSM como base del contexto RAG
También se incorporó un script de ingesta masiva:

- `ruta_viva/scripts/import_osm_data.py`

Este script:
- consulta Overpass API,
- recupera POIs reales de La Araucanía,
- limpia nombres y descripciones,
- genera descripciones cuando OSM no trae una,
- mapea tags OSM a categorías internas,
- genera embeddings OpenAI,
- históricamente persistía POIs con `POIRepository.create_poi`; actualmente el import OSM inserta `POI` directo para conservar metadata rica,
- evita reimportar POIs OSM ya cargados,
- procesa por lotes,
- y aplica rate limiting.

Durante su estabilización se resolvieron dos problemas reales:

1. `406 Not Acceptable` de Overpass, corregido usando búsquedas por `ISO3166-2=CL-AR`, `wikidata=Q2170`, nombre y bounding box fallback.
2. secuencia autoincremental desfasada en `categories.id`, corregida creando categorías base con IDs explícitos y sincronizando la secuencia con `setval(...)`.

La ingesta ya permitió poblar la base con POIs reales, fortaleciendo el contexto disponible para búsqueda semántica, itinerarios y futuras capacidades RAG.


## 18. Alembic y migraciones

## 18.1 Configuración de `env.py`
`ruta_viva/migrations/env.py` está configurado para:
- usar `settings.async_database_uri`,
- cargar `Base.metadata`,
- trabajar en modo async,
- soportar objetos geoespaciales de GeoAlchemy2,
- comparar tipos (`compare_type=True`),
- integrar `pgvector` y `PostGIS` en el render/autogenerate.

## 18.2 Metadata objetivo
La metadata objetivo es:

```python
target_metadata = Base.metadata
```

Esto es crucial para que Alembic descubra correctamente el esquema actual.

## 18.3 Revisiones vigentes
### `13e4146989e2_initial_schema_with_dynamic_vector_.py`
Es la migración base vigente del proyecto actual. Aunque el nombre quedó histórico, hoy contiene ya elementos importantes del esquema real:
- tablas principales,
- `Vector(1536)` para embeddings,
- `Geometry('POINT', srid=4326)` para POIs,
- `itineraries` e `itinerary_steps`,
- constraints e índices relevantes.

### `82d1bcc33432_fix_poi_description_embedding_openai_1536.py`
Migración creada para fijar integridad del embedding de POIs a OpenAI 1536.

#### Qué hace exactamente
1. cuenta filas incompatibles en `pois` donde:
   - `description_embedding IS NULL`, o
   - `vector_dims(description_embedding) <> 1536`
2. si existen, lanza `RuntimeError` y obliga a backfill previo,
3. si no existen, altera el tipo a `vector(1536)`,
4. fija `nullable=False`.

#### Idea técnica importante
La migración no asume que todos los datos existentes ya son compatibles. Protege la integridad antes de cambiar el tipo.

### `c3d4e5f6a7b8_add_poi_posts_and_analytics_fields.py`
Migración que reestructura `entrepreneur_posts` para vincularlos a POIs:
1. elimina posts existentes (eran genéricos, sin POI),
2. agrega `poi_id` FK NOT NULL a `pois`,
3. agrega columnas `is_pinned` (bool, default false) y `scheduled_at` (DateTime nullable).

### `d4e5f6a7b8c9_add_entrepreneur_post_sort_order.py`
Migración que agrega `sort_order` (Integer, default 0) a `entrepreneur_posts` para reordenamiento persistente.

### `e5f6a7b8c9d0_add_verification_confidence_and_rut_fields.py`
Migración que implementa verificación y scoring:
1. agrega `verification_status` (String(20), default "pending") y `confidence_score` (Float, default 0.0) a `pois`,
2. agrega `rut` (String(12), nullable, unique) y `verification_status` (String(20), default "unverified") a `entrepreneur_profiles`,
3. crea constraint único en `entrepreneur_profiles.rut`,
4. actualiza POIs importados de OSM (`entrepreneur_id IS NULL`) a `verification_status = 'verified'` y `confidence_score = 0.7`.

## 18.4 Error real encontrado con Alembic
Se observó el error:

```text
Target database is not up to date.
```

### Causa
Se intentó ejecutar `alembic revision --autogenerate` antes de aplicar las migraciones pendientes.

### Resolución
Primero se aplicó:

```bash
alembic upgrade head
```

Luego una autogeneración adicional produjo una migración vacía porque el esquema ya estaba sincronizado.

### Lección práctica
`revision --autogenerate` no debe correr sobre una base atrasada respecto del historial de Alembic.

---

## 19. Docker e infraestructura local

## 19.1 Base de datos en contenedor
`docker-compose.yml` define un servicio `db` con:
- build desde `Dockerfile.db`,
- contenedor `rutaviva_db`,
- puerto `5432:5432`,
- volumen `postgres_data`,
- mount de `scripts/init_db.sql`,
- `healthcheck` con `pg_isready`.

## 19.2 Imagen custom de DB
`Dockerfile.db` parte desde:
- `ankane/pgvector:latest`

Luego instala:
- `postgresql-15-postgis-3`
- `postgresql-15-postgis-3-scripts`

Esto resuelve la necesidad simultánea de:
- soporte vectorial,
- soporte geoespacial.

## 19.3 Dependencias Python relevantes
`requirements.txt` incluye hoy:
- `fastapi`
- `uvicorn`
- `sqlalchemy>=2.0`
- `asyncpg`
- `alembic`
- `geoalchemy2`
- `pgvector`
- `openai`
- `pydantic`
- `pydantic-settings`
- `passlib[bcrypt]`
- `bcrypt==4.0.1`
- `email-validator`
- `python-jose[cryptography]`
- `python-multipart`

Observación importante:
- `google-genai` ya fue eliminado del proyecto.

---

## 20. Problemas técnicos detectados y resueltos recientemente

## 20.1 Proveedor de embeddings heterogéneo
### Problema
La capa de embeddings tenía residuos de Gemini y mayor complejidad de la necesaria.

### Solución
- se unificó todo en OpenAI,
- se limpió `embedding_service.py`,
- se eliminaron configuraciones y dependencia de Gemini,
- se fijó la dimensionalidad a 1536.

## 20.2 Integridad dimensional de embeddings
### Problema
Si el proveedor cambia o una columna queda sin dimensión fija, es posible persistir vectores incompatibles.

### Solución
- `POI.description_embedding` quedó como `Vector(1536)`,
- migración `82d1bcc33432` protege cambio de esquema y datos.

## 20.3 Autogenerate de Alembic sobre DB atrasada
### Problema
Apareció `Target database is not up to date`.

### Solución
Aplicar primero `upgrade head`, luego autogenerar si realmente hay cambios.

## 20.4 Descubrimiento de modelos por Alembic
### Problema
`Base.metadata` necesitaba todos los modelos cargados, pero importarlos directamente desde `app/db/base.py` produjo un ciclo circular.

### Solución
Dejar `app/db/base.py` solo con `Base`, registrar modelos desde `app/db/models.py` y mantener `target_metadata = Base.metadata` en `env.py`.

---

## 21. Limitaciones y pendientes reales del sistema

## 21.1 Testing
No hay suite automatizada aún.

Faltan al menos:
- tests de auth,
- tests de repositorios,
- tests de búsqueda geoespacial,
- tests del endpoint de itinerarios,
- mocks o tests de integración controlados para servicios externos.

## 21.2 Roles y permisos
No existe todavía una política formal y consistente de autorización por tipo de usuario en todos los endpoints.

## 21.3 Services de aplicación
Parte de la orquestación vive aún en endpoints. A futuro podría moverse más a services/casos de uso.

## 21.4 RAG completo
Aunque ya existe base fuerte para retrieval semántico y generación estructurada, aún falta:
- ingesta,
- segmentación,
- indexación de corpus adicional,
- ranking más rico,
- generación final de respuestas estilo RAG.

## 21.5 Ranking híbrido más sofisticado
`search_hybrid()` todavía no combina formalmente score espacial y score semántico en una sola fórmula. Hoy usa filtro espacial + orden semántico.

## 21.6 Validaciones adicionales
El endpoint de itinerarios aún podría endurecerse más con reglas como:
- `start_date <= end_date`,
- límites de cantidad de pasos,
- límites de tiempo entre pasos,
- validación más rica del contenido de `ai_context`.

---

## 22. Comandos de trabajo útiles en el estado actual

### Levantar DB
```bash
cd ruta_viva
docker compose up -d db
```

### Ejecutar migraciones
```bash
cd ruta_viva
../fastapi/bin/alembic upgrade head
```

### Levantar API
```bash
cd ruta_viva
../fastapi/bin/uvicorn app.main:app --reload
```

### Verificar health
```bash
curl http://127.0.0.1:8000/health
```

### Probar login / JWT / users me
Usar Swagger en `/docs` o requests manuales con bearer token.

### Probar búsqueda semántica
Llamar:
```text
GET /api/v1/pois/semantic-search?query=...&lat=...&lon=...&radius=...
```

### Probar generación de itinerario
Llamar:
```text
POST /api/v1/itineraries/generate
```
con body compatible con `GenerateItineraryRequest`.

---

## 23. Registro evolutivo por sesión

### [2026-04-18] Infraestructura inicial, modelos, migraciones y arranque FastAPI

#### Objetivo
- levantar la base del backend,
- modelar la base de datos,
- dejar operativa la conexión,
- completar el setup inicial.

#### Cambios realizados
- se validó/generó la estructura de carpetas principal,
- se creó `docker-compose.yml`,
- se creó `Dockerfile` de aplicación,
- se creó `requirements.txt`,
- se creó `init_db.sql`,
- se modeló el esquema con SQLAlchemy 2.0,
- se configuró Alembic async,
- se creó `Dockerfile.db` para soportar PostGIS + pgvector,
- se implementó `config.py`, `session.py` y `main.py`.

#### Archivos creados/modificados
- `ruta_viva/docker-compose.yml`
- `ruta_viva/Dockerfile`
- `ruta_viva/Dockerfile.db`
- `ruta_viva/requirements.txt`
- `ruta_viva/scripts/init_db.sql`
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/db/base.py`
- `ruta_viva/app/db/session.py`
- `ruta_viva/app/main.py`
- `ruta_viva/app/models/*.py`
- `ruta_viva/alembic.ini`
- `ruta_viva/migrations/env.py`
- base de migraciones iniciales

#### Decisiones técnicas
- usar FastAPI + SQLAlchemy 2.0 async,
- usar PostgreSQL con `pgvector` y `PostGIS`,
- usar UUID nativo PostgreSQL,
- usar `Geometry('POINT', srid=4326)` para ubicación,
- usar `Vector(1536)` para embeddings,
- usar `selectin` y `noload` en relaciones ORM,
- usar `pydantic-settings` para configuración.

#### Problemas encontrados
- Alembic tomó un placeholder inicial no válido,
- hubo conflictos de credenciales por volumen persistente,
- `vector` no estaba habilitado inicialmente,
- la imagen base no traía PostGIS,
- faltaban imports manuales en migraciones,
- el índice espacial fue duplicado por GeoAlchemy2 + Alembic.

#### Soluciones aplicadas
- corregir `alembic.ini` y `env.py`,
- recrear volumen Docker cuando fue necesario,
- verificar extensiones instaladas,
- crear imagen custom de DB,
- ajustar migraciones manualmente,
- eliminar duplicación del índice espacial.

#### Estado resultante
- base operativa,
- extensiones listas,
- app arrancando,
- persistencia async funcional.

---

### [2026-04-30] Autenticación base, usuarios y POIs funcionales

#### Objetivo
- consolidar el backend como API usable,
- agregar auth JWT,
- exponer rutas protegidas,
- permitir creación y búsqueda de POIs.

#### Cambios realizados
- se implementó registro de turista,
- se implementó login con JWT,
- se creó `get_current_user`,
- se agregó `GET /users/me`,
- se creó `POST /pois/`,
- se agregó `GET /pois/search`,
- se dejó operativa la base para trabajo geoespacial.

#### Archivos principales implicados
- `app/api/deps.py`
- `app/api/v1/endpoints/auth.py`
- `app/api/v1/endpoints/users.py`
- `app/api/v1/endpoints/pois.py`
- `app/core/security.py`
- `app/repositories/user_repository.py`
- `app/repositories/poi_repository.py`
- `app/schemas/user.py`
- `app/schemas/tourist_profile.py`
- `app/schemas/token.py`
- `app/schemas/poi.py`

#### Decisiones técnicas
- bearer token simple sobre JWT,
- dependencia compartida para usuario autenticado,
- creación de POIs protegida,
- búsqueda geográfica pública.

#### Estado resultante
- backend usable para auth + users + POIs.

---

### [2026-04-30] Unificación de embeddings en OpenAI y búsqueda semántica

#### Objetivo
- simplificar la capa de embeddings,
- eliminar Gemini,
- dejar búsqueda semántica consistente,
- asegurar integridad de dimensión vectorial.

#### Cambios realizados
- `app/services/embedding_service.py` se reescribió para usar solo OpenAI,
- se fijó el modelo `text-embedding-3-small`,
- se eliminó cualquier lógica multi-provider innecesaria,
- `POI.description_embedding` quedó fijado a `Vector(1536)`,
- `POST /pois/` genera embeddings antes de persistir,
- `GET /pois/semantic-search` genera embeddings de query y ejecuta búsqueda híbrida,
- se removieron restos de Gemini en config y dependencias,
- se creó migración específica para endurecer `description_embedding`.

#### Archivos creados/modificados
- `ruta_viva/app/services/embedding_service.py`
- `ruta_viva/app/models/poi.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/core/config.py`
- `ruta_viva/requirements.txt`
- `ruta_viva/migrations/versions/82d1bcc33432_fix_poi_description_embedding_openai_1536.py`
- eliminación de `app/services/openai_service.py` duplicado

#### Decisiones técnicas
- proveedor único de embeddings: OpenAI,
- dimensión fija: 1536,
- singleton simple para servicio de embeddings,
- búsqueda híbrida basada en radio + cosine distance.

#### Problemas encontrados
- DB podía quedar con migraciones pendientes antes de autogenerate,
- existía riesgo de embeddings incompatibles en filas antiguas,
- había configuración residual de Gemini.

#### Soluciones aplicadas
- aplicar `upgrade head` antes de autogenerar,
- agregar migración que valida dimensionalidad antes del cambio,
- limpiar proyecto de referencias a Gemini.

#### Estado resultante
- búsqueda semántica con OpenAI funcionando,
- integridad dimensional endurecida,
- proyecto simplificado.

---

### [2026-04-30] FASE 4 — Generación de itinerarios con DeepSeek

#### Objetivo
- usar retrieval sobre POIs para construir itinerarios turísticos,
- integrar un LLM generativo,
- persistir el resultado en tablas existentes de itinerario.

#### Cambios realizados
- se agregó configuración para DeepSeek,
- se creó `app/services/llm_service.py`,
- se creó `app/schemas/itinerary.py`,
- se creó `app/repositories/itinerary_repository.py`,
- se creó `app/api/v1/endpoints/itineraries.py`,
- se agregó el router de itinerarios a `app/api/v1/api.py`.

#### Archivos creados/modificados
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/services/llm_service.py`
- `ruta_viva/app/schemas/itinerary.py`
- `ruta_viva/app/repositories/itinerary_repository.py`
- `ruta_viva/app/api/v1/endpoints/itineraries.py`
- `ruta_viva/app/api/v1/api.py`

#### Decisiones técnicas
- reutilizar `AsyncOpenAI` para DeepSeek vía `base_url`,
- modelo `deepseek-chat`,
- prompt restrictivo para usar solo POIs del contexto,
- salida obligatoria en JSON,
- validación con Pydantic antes de persistir,
- verificación explícita server-side contra IDs válidos del contexto.

#### Problemas evitados o controlados
- alucinación de lugares inexistentes,
- invento de `poi_id` no recuperados,
- respuestas sin estructura,
- persistencia de pasos desordenados.

#### Estado resultante
- generación de itinerarios funcionando,
- persistencia en `itineraries` e `itinerary_steps` confirmada.

---

### [2026-04-30] Primer ajuste de metadata ORM para Alembic

#### Objetivo
- asegurar que Alembic pudiera detectar correctamente todo el esquema en futuras migraciones.

#### Cambios realizados
- se intentó registrar modelos para que `Base.metadata` quedara completo,
- se verificó compilación inicial.

#### Archivos modificados
- `ruta_viva/app/db/base.py`
- `ruta_viva/app/db/models.py`

#### Decisión técnica inicial
- se intentó importar modelos desde `base.py`, pero luego se descubrió que ese patrón generaba ciclos circulares.

#### Estado posterior
- esta decisión fue corregida definitivamente el 2026-05-02 separando raíz declarativa (`base.py`) y agregador de modelos (`models.py`).


---

### [2026-05-02] Ingesta masiva de POIs reales desde OpenStreetMap

#### Objetivo
- poblar la base con POIs reales de la Región de La Araucanía,
- aumentar el contexto disponible para búsqueda semántica, itinerarios y RAG.

#### Cambios realizados
- se agregó `requests` a `requirements.txt`,
- se creó `scripts/import_osm_data.py`,
- se implementó consulta Overpass para La Araucanía,
- se mapearon tags OSM a categorías internas,
- se generaron embeddings OpenAI para cada POI,
- originalmente se reutilizó `POIRepository.create_poi`; actualmente el script OSM inserta el modelo `POI` directo para conservar metadata OSM rica,
- se agregaron lotes, logs, manejo de errores y rate limiting.

#### Problemas encontrados
- Overpass rechazó la consulta inicial con `406 Not Acceptable`,
- algunos elementos OSM venían sin nombre o sin coordenadas útiles,
- la secuencia de `categories.id` estaba desfasada y produjo `duplicate key value violates unique constraint categories_pkey`.

#### Soluciones aplicadas
- consulta Overpass con fallbacks por `ISO3166-2=CL-AR`, `wikidata=Q2170`, nombre y bounding box,
- límite aplicado sobre POIs válidos procesables,
- categorías base con IDs explícitos,
- sincronización de secuencia PostgreSQL con `setval(...)`.

#### Estado resultante
- ingesta masiva exitosa,
- base poblada con POIs reales,
- contexto semántico más rico para el sistema.

---

### [2026-05-02] FASE 3.5 — Valoraciones y perfil dinámico del turista

#### Objetivo
- permitir que turistas creen reviews,
- convertir el texto de cada review en señal semántica,
- actualizar dinámicamente el perfil de intereses del usuario,
- personalizar búsqueda híbrida e itinerarios.

#### Cambios realizados
- se creó `app/schemas/review.py`,
- se creó `app/repositories/review_repository.py`,
- se creó `app/api/v1/endpoints/reviews.py`,
- se agregó router `/reviews`,
- se agregó autenticación opcional para búsqueda semántica pública personalizada,
- se modificó `POIRepository.search_hybrid`,
- se modificó el endpoint de itinerarios para pasar `interests_embedding`.

#### Decisiones técnicas
- cada review genera embedding con OpenAI,
- la review se guarda con `text_embedding`,
- el perfil se actualiza con `nuevo = actual * 0.9 + review * 0.1`,
- la búsqueda personalizada usa `70%` intención actual y `30%` perfil histórico,
- la primera review inicializa el perfil si aún no existe.

#### Estado resultante
- reviews funcionales,
- perfil semántico evolutivo del turista,
- búsqueda semántica personalizada si hay usuario logueado,
- itinerarios con retrieval personalizado.

---

### [2026-05-02] Corrección definitiva del patrón de metadata ORM para Alembic

#### Objetivo
- resolver el ciclo circular causado por importar modelos desde `app/db/base.py`.

#### Cambios realizados
- `app/db/base.py` quedó solo con la definición de `Base`,
- `app/db/models.py` quedó como agregador de modelos concretos,
- `migrations/env.py` sigue importando `app.db.models` antes de usar `Base.metadata`.

#### Problema encontrado
- `alembic upgrade head` fallaba con `ImportError: cannot import name 'Bookmark' from partially initialized module`.

#### Solución aplicada
- separar raíz declarativa (`base.py`) de registro de modelos (`models.py`).

#### Estado resultante
- `alembic upgrade head` vuelve a correr correctamente.


### [2026-05-02] Carga local de imágenes y servicio `/media`

#### Objetivo
- permitir subir imágenes sin contratar almacenamiento cloud en esta etapa,
- persistir archivos locales entre reinicios del contenedor,
- guardar URLs relativas en `POI.multimedia_urls`.

#### Cambios realizados
- se creó la carpeta `ruta_viva/media`,
- `app/main.py` expone `/media/{filename}` como endpoint autenticado con `FileResponse`,
- se creó `app/services/image_service.py`,
- se creó endpoint `POST /api/v1/media/upload`,
- se agregó router `media` a `app/api/v1/api.py`,
- `docker-compose.yml` monta `./media:/app/media` para persistencia.

#### Reglas implementadas
- solo se aceptan JPG y PNG,
- límite máximo de 5 MB,
- nombre único con `uuid4`,
- retorno de URL relativa como `/media/nombre_unico.jpg`.

#### Estado resultante
- el frontend puede subir imágenes localmente,
- las URLs generadas pueden guardarse en `multimedia_urls`,
- los archivos no se pierden al reiniciar el contenedor si se usa el volumen configurado.

---

### [2026-05-02] FASE 6 — Consciencia climática en itinerarios

#### Objetivo
- hacer que el itinerario no dependa solo de intención semántica y distancia,
- incorporar clima real como contexto de generación,
- evitar recomendar actividades al aire libre en momentos de lluvia cuando existan alternativas más protegidas.

#### Cambios realizados
- se agregó `httpx` a `requirements.txt`,
- se agregó `openweather_api_key` a `app/core/config.py`,
- se creó `app/services/weather_service.py`,
- `POST /api/v1/itineraries/generate` ahora consulta pronóstico antes de llamar a DeepSeek,
- `ItineraryGenerator.generate_itinerary` ahora recibe `weather_forecast`,
- el prompt de DeepSeek incluye reglas explícitas de clima.

#### Diseño del servicio de clima
`weather_service.get_forecast(lat, lon)`:

1. valida que exista `OPENWEATHER_API_KEY`,
2. llama a OpenWeatherMap `/data/2.5/forecast`,
3. usa `units=metric` y `lang=es`,
4. agrupa los bloques de 3 horas por día,
5. elige como resumen diario el bloque más cercano al mediodía,
6. calcula probabilidad máxima de lluvia del día,
7. devuelve un string compacto legible para IA.

#### Decisión técnica
El clima se pasa como contexto textual al LLM, no como regla rígida en SQL. Esto mantiene el backend flexible: la base recupera lugares y el LLM razona el orden del itinerario considerando clima, fechas e intención.

#### Estado resultante
- los itinerarios generados pueden mencionar en `ai_context.reason` por qué el clima influyó,
- actividades indoor se priorizan ante lluvia,
- actividades outdoor se favorecen cuando el pronóstico es despejado.

---

### [2026-05-02] Telemetría, seeder e ingesta OSM robustecida

#### Objetivo
- preparar el backend para mediciones de tesis y futura integración frontend,
- estabilizar datos base,
- hacer la ingesta masiva más resiliente para 10.000 registros.

#### Cambios realizados
- `app/main.py` incorporó middleware de telemetría con `time.perf_counter()`,
- cada respuesta incluye header `X-Process-Time`,
- los logs registran método, ruta, status code y tiempo en ms,
- `app/db/session.py` incorporó `BASE_CATEGORIES` e `init_db()`,
- `scripts/seed_categories.py` permite asegurar categorías base manualmente,
- el `lifespan` de FastAPI llama `init_db()` al iniciar,
- `scripts/import_osm_data.py` aumentó timeout Overpass a 300 segundos,
- la ingesta ahora usa checkpoint para omitir POIs OSM ya importados con embedding,
- la ingesta muestra ETA basado en progreso real.

#### Categorías base
- `1`: Naturaleza
- `2`: Gastronomía
- `3`: Turismo
- `4`: Alojamiento
- `5`: Cultura

#### Decisión técnica
`init_db()` usa insert idempotente con `ON CONFLICT` y luego sincroniza la secuencia con `setval(...)`. Esto evita errores por IDs manuales y permite ejecutar el seeder muchas veces sin duplicar datos.

#### Estado resultante
- se pueden medir latencias reales endpoint por endpoint,
- las categorías base quedan consistentes,
- la ingesta grande se puede retomar sin pagar nuevamente embeddings ya generados.

---

### [2026-05-02] Optimización vectorial, background tasks y exception handlers

#### Objetivo
- mejorar performance semántica,
- reducir latencia percibida al crear reviews,
- entregar errores limpios y consistentes para frontend.

#### Cambios realizados
- se creó `scripts/create_vector_indices.py`,
- se definió índice HNSW sobre `pois.description_embedding`,
- se usa `vector_cosine_ops` como métrica,
- `POST /api/v1/reviews/` ahora guarda la review inmediatamente,
- la generación del embedding de review y actualización del perfil se ejecuta en `BackgroundTasks`,
- `app/main.py` agregó handlers para `HTTPException`, `RequestValidationError` y `Exception`.

#### SQL del índice
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pois_description_embedding_hnsw
ON pois
USING hnsw (description_embedding vector_cosine_ops);
```

#### Por qué HNSW y no IVFFlat para este caso
HNSW es conveniente porque:

- no requiere fase previa de entrenamiento del índice,
- mantiene buen recall en búsqueda aproximada de vecinos más cercanos,
- funciona bien cuando los datos crecen incrementalmente,
- evita tener que calibrar listas/probes desde el inicio,
- se adapta mejor a un backend en evolución con ingesta OSM, POIs nuevos y reseñas.

IVFFlat puede funcionar bien en datasets enormes y más estáticos, pero requiere entrenamiento y ajuste más cuidadoso. Para Ruta Viva, HNSW es más robusto operacionalmente en esta etapa.

#### Formato global de errores
```json
{
  "error": "Tipo de Error",
  "detail": "Mensaje legible"
}
```

Los errores 401, 404 y 422 mantienen su status code correcto, pero ahora se devuelven con estructura más predecible para frontend.

#### Estado resultante
- búsqueda vectorial preparada para mayor volumen,
- reviews con mejor UX,
- frontend puede tratar errores de forma uniforme,
- la tesis puede medir latencia con mayor claridad.

---

### [2026-05-02] Endpoint de detalle de POI para integración frontend

#### Objetivo
- permitir que el frontend abra una pantalla de detalle de POI aunque el punto no esté en el estado local del mapa.

#### Cambios realizados
- se agregó `POIRepository.get_poi_by_id(...)`,
- se agregó `GET /api/v1/pois/{poi_id}`,
- se mantuvo el endpoint después de rutas estáticas como `/search` y `/semantic-search` para evitar conflictos de matching en FastAPI,
- se documentó el endpoint dentro del catálogo de rutas.

#### Estado resultante
- el frontend puede listar POIs con `/pois/search` o `/pois/semantic-search`,
- y puede recuperar el detalle directamente por UUID con `/pois/{poi_id}`.

---

### [2026-05-02] Enriquecimiento de itinerarios para frontend

#### Objetivo
- evitar que el frontend muestre solo UUIDs de POI en la pantalla de itinerario generado.

#### Cambios realizados
- `ItineraryStepResponse` incorporó `poi_nombre` y `poi_descripcion`,
- `ItineraryRepository.get_itinerary_by_id()` ahora usa `selectinload(Itinerary.steps).selectinload(ItineraryStep.poi)`,
- la respuesta se construye explícitamente para incluir datos básicos del POI asociado a cada paso.

#### Estado resultante
- `POST /api/v1/itineraries/generate` sigue persistiendo los mismos datos relacionales,
- pero la respuesta HTTP ya viene lista para UI narrativa con nombres reales de lugares.

---

### [2026-05-16] Ara conversacional, edición avanzada de itinerarios y contrato por día

#### Objetivo
- transformar la generación directa de itinerarios en una experiencia conversacional con Ara,
- permitir que frontend edite, elimine, reordene y filtre itinerarios,
- asegurar que fechas, timezone y agrupación por día sean consistentes para UI.

#### Cambios realizados
- Se agregaron `ara_sessions` y `ara_messages` con migración Alembic.
- Se creó `app/api/v1/endpoints/ara.py` con sesiones, mensajes, historial y generación final.
- Se creó `app/services/ara_service.py` para intención, preferencias, quick replies dinámicos y cambio de lugar.
- Se agregó `DELETE /api/v1/itineraries/{itinerary_id}`.
- Se agregaron endpoints para mapa filtrado, update/delete/reorder de steps.
- `ItineraryStepResponse` ahora incluye `day_index`, `day_date` y `day_label`.
- Backend normaliza horarios como `America/Santiago` y valida que estén dentro de `[start_date, end_date]`.
- El prompt de DeepSeek prioriza fechas del payload, no fechas escritas en lenguaje natural.
- Se endurecieron reglas contra oficinas/CONAF como parada principal, alojamientos usados como actividad turística, “hostel-hopping”, huecos grandes y consejos recursivos inútiles.
- Ara ahora evita metalenguaje visible, sincroniza mejor mensaje/chips y evita loops de respuestas iguales.

#### Estado resultante
- el frontend puede abrir chat Ara desde Home sin redirigir directo a resultado,
- puede renderizar quick replies enviados por backend,
- puede pedir generación final al confirmar,
- puede usar `day_index`/`day_date`/`day_label` para agrupar itinerarios por día,
- puede abrir “Cambiar lugar” contra Ara usando `itinerary_id` y `step_id`,
- y el backend rechaza o sanea itinerarios logísticamente absurdos antes de responder.

---

### [2026-05-16] Endpoints de sincronización frontend adicional

#### Objetivo
- cubrir necesidades de frontend para geocoding, clima público, perfil editable y módulo emprendedor.

#### Cambios realizados
- `GET /api/v1/geocoding/search` busca lugares por texto con sesgo opcional por lat/lon.
- `GET /api/v1/weather/forecast` devuelve forecast diario estructurado (`daily`) y resumen textual (`forecast`).
- `PATCH /api/v1/users/me` permite actualizar `email`, `avatar_url` y `display_name`.
- `POST /api/v1/pois/{poi_id}/visit` registra visitas desde frontend.
- `GET /api/v1/entrepreneur/me/metrics` entrega métricas agregadas.
- `GET /api/v1/entrepreneur/me/income` entrega placeholder estable de ingresos.
- CRUD de posts emprendedor bajo `/api/v1/entrepreneur/me/posts`.

#### Estado resultante
- frontend ya no necesita mocks para geocoding/clima/perfil/emprendedor básico,
- las métricas se pueden expandir sin romper contrato,
- y el backend mantiene respuestas flexibles pero con campos estables.

---

## 24. Estado final al cierre de esta actualización
Hoy el backend puede:

- autenticar usuarios,
- identificar al usuario actual,
- crear POIs con embedding automático,
- listar, editar y eliminar POIs propios de emprendedores,
- asociar imágenes persistentes a POIs,
- listar categorías base,
- actualizar perfil turista y activar perfil emprendedor,
- buscar POIs por cercanía,
- buscar POIs por intención semántica dentro de un radio,
- personalizar búsquedas semánticas con perfil dinámico cuando hay turista autenticado,
- crear reviews con confirmación inmediata y enriquecimiento semántico en background,
- editar/eliminar reviews propias y exponer resumen agregado por POI,
- actualizar el perfil de intereses del turista con cada review procesada,
- generar itinerarios con contexto recuperado, personalizado y consciente del clima,
- persistir itinerarios y pasos,
- listar itinerarios del turista autenticado,
- recuperar detalle de itinerario por ID validando propiedad,
- eliminar itinerarios completos del historial,
- editar, eliminar y reordenar pasos de itinerarios,
- entregar POIs de un itinerario para mapa filtrado,
- agrupar pasos por día mediante `day_index`, `day_date` y `day_label`,
- guardar y quitar POIs favoritos de turistas,
- subir imágenes locales y servirlas desde `/media`,
- medir latencia por request con `X-Process-Time`,
- entregar errores uniformes al frontend,
- asegurar categorías base de forma idempotente,
- usar índice HNSW para acelerar búsqueda vectorial,
- mantener su esquema versionado con Alembic sobre una metadata ORM correctamente registrada,
- importar masivamente POIs reales desde OpenStreetMap para enriquecer el contexto del sistema,
- diversificar automáticamente los candidatos conversacionales de Ara cuando una dimensión está completada, rompiendo loops de una sola categoría,
- validar y reparar determinísticamente violaciones de horarios de apertura en itinerarios generados,
- evitar saturación monocategórica en itinerarios con reparación automática y límites duros,
- sanitizar metalenguaje algorítmico y consejos delegados en las respuestas del LLM,
- resetear el perfil semántico del turista vía endpoint dedicado,
- usar peso configurable del perfil semántico en búsqueda híbrida, reducido en generación de nuevos itinerarios,
- limpiar automáticamente el estado de sesión al cambiar de fase conversacional (post-generación, post-reemplazo),
- y desarrollar con hot reload vía volume mount de código y `--reload`,

El backend también puede hoy (2026-05-21):
- detectar duplicados de POIs antes de crearlos (cascada: geográfico → categoría → semántico),
- asignar y recalcular automáticamente scores de confianza (`confidence_score`) basados en señales reales (fotos, descripciones, categorías, reviews, visitas, creador verificado),
- verificar POIs y emprendedores con estados (`pending`/`verified`/`flagged` para POIs, `unverified`/`pending_review`/`verified` para emprendedores),
- filtrar POIs flageados de búsquedas públicas manteniendo acceso directo por ID,
- validar RUT chileno (módulo 11) al activar perfil emprendedor,
- aplicar rate limiting en creación de POIs (5/hora, 10/día por usuario),
- gestionar posts de emprendedor vinculados a POIs con fijado (`is_pinned`), programado (`scheduled_at`) y orden persistente (`sort_order`),
- exponer posts públicos de POIs sin autenticación,
- registrar visitas a POIs con tracking público y para emprendedores,
- exponer analíticas de POIs (`weekly_visits`, `monthly_growth`) y actividad histórica,
- reprogramar pasos de itinerario con desplazamiento automático de pasos subsecuentes,
- reordenar pasos con asignación automática de horarios (cursor desde 9:00 AM, gaps de 15 min),
- consultar pronóstico climático por día y coordenadas de POI para pantalla de itinerario,
- e inyectar datos de clima estructurados por paso durante la generación de itinerarios.

La siguiente etapa natural del proyecto sería profundizar:
- autorización por roles,
- tests automatizados,
- services de aplicación más ricos,
- ranking híbrido más avanzado,
- validación cronológica en reordenamiento de pasos,
- moderación/paginación de reviews,
- métricas agregadas más avanzadas por POI,
- job queue persistente tipo Celery/RQ/Arq si las background tasks crecen,
- dashboard formal de observabilidad,
- y evolución hacia RAG completo.


---

### [2026-05-03] Endpoints de historial y detalle persistido de itinerarios

#### Objetivo
- soportar desde backend el historial de itinerarios del turista y la apertura de un detalle persistido por ID desde frontend.

#### Cambios realizados
- `GET /api/v1/itineraries/` lista itinerarios del turista autenticado.
- `GET /api/v1/itineraries/{itinerary_id}` devuelve detalle validando que pertenezca al usuario actual.
- `ItineraryRepository.get_itinerary_by_id(...)` acepta `tourist_id` opcional y retorna `None` si no existe o no pertenece al turista.
- se agregó `ItineraryRepository.list_itineraries_by_tourist(...)` con carga eager de pasos y POIs.
- la conversión a `ItineraryResponse` quedó centralizada en `_to_response(...)` para reutilizar enriquecimiento `poi_nombre`/`poi_descripcion`.

#### Estado resultante
- el frontend puede listar itinerarios guardados,
- puede abrir detalles por ID sin depender de memoria local,
- y las respuestas siguen protegidas por autenticación + propiedad del turista.


---

### [2026-05-03] Categorías, media persistente, reviews avanzadas y bookmarks

#### Objetivo
- habilitar el segundo bloque de 4 conexiones frontend-backend.

#### Cambios realizados
- se agregó `GET /api/v1/categories/` para exponer categorías base.
- se agregó `PATCH /api/v1/pois/{poi_id}/media` para persistir URLs de imagen en `POI.multimedia_urls`.
- se agregaron schemas y endpoints de resumen, edición y eliminación de reviews.
- se creó `BookmarkRepository` y endpoints `GET/POST/DELETE /api/v1/bookmarks`.
- `api_router` registra `categories` y `bookmarks`.

#### Estado resultante
- el frontend ya no necesita categorías hardcodeadas,
- las imágenes subidas pueden quedar asociadas a POIs,
- las reviews propias pueden gestionarse,
- y turistas pueden guardar POIs favoritos.


---

### [2026-05-03] Perfil editable, emprendedor y POIs propios

#### Objetivo
- exponer soporte backend para las 3 partes funcionales restantes del frontend.

#### Cambios realizados
- `UserResponse` ahora incluye `tourist_profile` y `entrepreneur_profile`.
- se agregó `TouristProfileUpdate` y `EntrepreneurProfileResponse/Create`.
- `PUT /users/me/tourist-profile` actualiza preferencias reales.
- `POST /users/me/entrepreneur-profile` activa perfil emprendedor.
- `GET /pois/mine` lista POIs propios.
- `PUT /pois/{poi_id}` edita POIs propios y recalcula embedding si corresponde.
- `DELETE /pois/{poi_id}` elimina POIs propios.

#### Estado resultante
- el frontend puede editar perfil turista, activar modo emprendedor y gestionar POIs propios.


### [2026-05-03] Limpieza de infraestructura y seguridad del backend

#### Objetivo
- endurecer la seguridad del backend antes de continuar con features,
- eliminar secretos hardcodeados del repositorio,
- corregir `.gitignore` para evitar filtraciones accidentales,
- proteger endpoints de upload que estaban públicos.

#### Cambios realizados
1. `.gitignore` reescrito completamente para ignorar `__pycache__/`, `*.pyc`, `.env`, `.venv/`, `venv/`, `fastapi/`, `media/`, `.direnv/`, `.vscode/`, `.idea/`, `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `build/`, `dist/`, `*.egg-info/`, `.DS_Store`.
2. `.env` eliminado del control de versiones (`git rm --cached`). Creado `.env.example` con placeholders seguros para todas las claves. El historial previo no se limpió (pendiente post-rotación de keys).
3. `config.py:20` — `secret_key` pasó de tener un valor hardcodeado a ser **requerido** (sin default). Si no se setea `SECRET_KEY` en `.env`, Pydantic falla en startup con `ValidationError`.
4. `POST /api/v1/media/upload` ahora requiere autenticación JWT (`Depends(get_current_user)`). Antes cualquier request podía subir archivos al servidor.
5. Se reorganizaron 14 commits del sprint en features: categories, pois CRUD, reviews complete, media auth, itineraries history, users profiles, bookmarks, scripts.

#### Archivos creados/modificados
- `ruta_viva/.gitignore`
- `ruta_viva/.env.example`
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/api/v1/endpoints/media.py`

#### Estado resultante
- backend más seguro: sin secretos en el repo, sin endpoint de upload público, sin `.env` versionado.
- `SECRET_KEY` es ahora un requisito explícito en startup (fail-fast si falta).


### [2026-05-18] Estabilización conversacional de Ara y robustez del motor de itinerarios

#### Objetivo
- resolver los bugs críticos de la experiencia conversacional con Ara,
- endurecer la generación de itinerarios contra violaciones horarias y saturación categórica,
- eliminar fugas de estado entre sesiones y preferencias fantasma,
- mejorar la calidad de las respuestas del LLM eliminando metalenguaje técnico,
- habilitar hot reload para desarrollo ágil.

#### Cambios realizados

**Fase 1 — Food Loop y Prompt Leakage (BUG-002, BUG-003)**
- `_maybe_diversify_candidate_pois` ahora diversifica cuando la categoría del intent primario ya está en `completed_dimensions`, rompiendo el ciclo infinito de comida.
- `_align_candidate_pois_with_intent` recibe `completed_dimensions` como parámetro y no filtra cuando el intent ya está completado.
- `FOOD_COMPLETION_TAGS` removió `"vista"` (no es exclusivo de gastronomía).
- `merge_preferences` solo marca `completed_dimensions` cuando `turn_type == "candidate_selection"`, no por mera mención de keywords.
- `build_refined_query` eliminó la duplicación del `trip_draft` en el prompt del LLM (iba dos veces). Se reemplazó por `Tags acumulados` y `Dimensiones completadas`.
- System prompt del LLM expandido con prohibición explícita de frases algorítmicas: "para mantener variedad", "evitar repetir", "alternativa para", "equilibrar la ruta", etc.
- `DELEGATED_RECOMMENDATION_TERMS` expandido con 9 patrones nuevos.
- `_replace_step_poi` y `_repair_duplicate_poi_steps` ahora generan reason contextualizado con nombre y descripción real del POI reemplazante, en vez del texto genérico anterior.
- `_sanitize_generated_itinerary_context` agregó detección de razones cortas provenientes de system repairs para sanitizarlas también.

**Fase 2 — Time-Window Violation y Category Saturation (BUG-004, BUG-005)**
- `parse_opening_hours_text` reescrito con `_split_opening_hours_segments`: divide el texto por `;`, `.` y por nombres de días consecutivos, parseando cada segmento independientemente para no mezclar horas de días distintos.
- Nueva función `_has_cerrado`. Días explícitamente cerrados retornan `[]` (lista vacía), distinguible de "sin datos" (día no presente en el dict).
- `_step_fits_opening_windows` reescrito: ahora distingue tres casos — sin datos (True), explícitamente cerrado (False), con ventanas (verifica arrival/departure dentro).
- Repair de time-window ahora permite reemplazos gastronómicos (removido `not _is_gastronomy(candidate)` del primer loop). Un restaurante mal agendado puede ser reemplazado por otro que sí abra en ese horario.
- Regla 11 del system prompt endurecida: "ANTES de asignar un POI a un slot horario, VERIFICÁ su opening_hours_text".
- Nueva función `_primary_category_id` con orden de prioridad determinista: gastronomía > alojamiento > naturaleza > cultura > fallback `category_ids[0]`. Reemplaza todos los usos de `poi.category_ids[0]` que no eran confiables.
- Repair de saturación ahora intenta fallback con cualquier POI diferente (incluso misma categoría) antes de eliminar el paso.
- `_normalize_to_chile_wall_time` mejorado: naive → asume Chile, timezone no-Chile → convierte con `astimezone`, ya en Chile → no-op.

**Fase 3 — Ghost Context Leak y Hot Reload (BUG-006, BUG-001)**
- `search_hybrid` en `POIRepository` ahora acepta `profile_weight` configurable (default 0.3). La fórmula: `(query * (1 - weight)) + (profile * weight)`.
- `_search_generation_context_with_fallbacks` usa `profile_weight=0.1` para priorizar la intención explícita del usuario sobre su historial semántico.
- `preferences = dict(previous_preferences)` → `copy.deepcopy(previous_preferences)` en la rama `free_question`. Los dicts anidados ya no se comparten con la sesión.
- `candidate_poi_ids` se limpia a `[]` post-generación del itinerario para no arrastrar POIs viejos.
- `replacement_context` se elimina de `preferences_data` tras ejecutar el reemplazo de un step.
- Nuevo endpoint `DELETE /api/v1/users/me/tourist-profile/interests` para resetear el perfil semántico del turista.
- `docker-compose.yml` agregó volume mount `./app:/app/app` y `command: uvicorn ... --reload` para hot reload en desarrollo. Sin el flag `-v` en `docker compose down`, los datos de PostgreSQL no se pierden.

#### Archivos creados/modificados
- `ruta_viva/app/api/v1/endpoints/ara.py`
- `ruta_viva/app/services/ara_service.py`
- `ruta_viva/app/services/llm_service.py`
- `ruta_viva/app/api/v1/endpoints/itineraries.py`
- `ruta_viva/app/services/poi_metadata_extractor.py`
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/repositories/user_repository.py`
- `ruta_viva/app/api/v1/endpoints/users.py`
- `ruta_viva/docker-compose.yml`

#### Estado resultante
- Ara ya no queda atrapada en loops de una sola categoría: cuando el usuario completa una dimensión (ej: gastronomía), el sistema diversifica automáticamente las tarjetas de candidatos y los quick replies.
- Los itinerarios generados respetan mejor los horarios de apertura, no agendan POIs cerrados y evitan saturación de una sola categoría en el día.
- Las respuestas del LLM ya no incluyen frases robóticas de planificador algorítmico; los mensajes de reparación usan datos reales del POI.
- El perfil semántico del usuario ya no contamina búsquedas de itinerarios nuevos (peso reducido a 0.1 en generación).
- El estado de sesión (replacement_context, candidate_poi_ids) se limpia correctamente al cambiar de fase conversacional.
- El frontend puede resetear el perfil semántico del turista vía endpoint dedicado.
- El desarrollo es más ágil: cambios en el código se reflejan sin rebuild del contenedor.


---

### [2026-05-20] Entrepreneur posts, analíticas, tracking de visitas y endpoints de medios

#### Objetivo
- extender el módulo emprendedor con contenido asociado a POIs,
- agregar tracking de visitas y analíticas,
- exponer endpoints públicos de visitas y métricas para frontend.

#### Cambios realizados
- `EntrepreneurPost` model: agregado `poi_id` (FK NOT NULL a `pois`), `is_pinned` (bool default false), `scheduled_at` (nullable DateTime), relación `poi`.
- `POI` model: agregada relación `entrepreneur_posts`.
- Migración `c3d4e5f6a7b8`: elimina posts existentes, agrega `poi_id` FK + `is_pinned` + `scheduled_at`.
- `schemas/entrepreneur.py` reescrito: agregados `EntrepreneurPostCreatePOI`, `PinPostRequest`, `POIAnalyticsResponse`, `POIActivityItem`; actualizado `EntrepreneurPostResponse` con `poi_id`, `poi_name`, `is_pinned`, `scheduled_at`.
- `repositories/entrepreneur_repository.py` reescrito: agregados `create_poi_post`, `list_poi_posts`, `update_poi_post`, `delete_poi_post`, `pin_poi_post`, `get_poi_analytics`, `get_poi_activity`, `record_poi_visit`.
- `endpoints/entrepreneur.py` reescrito: 7 nuevos endpoints de emprendedor + helper `_verify_poi_ownership`.
- Agregado `POST /api/v1/pois/{poi_id}/visit` — tracking público de visitas.
- Agregados `GET /api/v1/entrepreneur/me/metrics`, `GET /api/v1/entrepreneur/me/income`.
- Agregado modelo `POIVisit` y schemas `POIVisitCreate`/`POIVisitResponse`.
- Analytics de posts: `weekly_visits` (últimos 7 días), `monthly_growth` (% mes-a-mes).

#### Archivos creados/modificados
- `ruta_viva/app/models/entrepreneur_post.py`
- `ruta_viva/app/models/poi.py`
- `ruta_viva/app/models/poi_visit.py`
- `ruta_viva/app/schemas/entrepreneur.py`
- `ruta_viva/app/repositories/entrepreneur_repository.py`
- `ruta_viva/app/api/v1/endpoints/entrepreneur.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/migrations/versions/c3d4e5f6a7b8_add_poi_posts_and_analytics_fields.py`

#### Estado resultante
- posts de emprendedor vinculados a POIs con soporte de fijado, programación y ordenamiento,
- tracking de visitas públicos y vía emprendedor,
- analíticas y métricas para dashboard de emprendedor.


---

### [2026-05-21] Bug fixes: ara.py descripción y weather temperatura

#### Objetivo
- corregir dos bugs que causaban error 500 y datos de clima incorrectos.

#### Cambios realizados
**Bug 1 — `ara.py` línea ~1012**: `chosen_poi.description` causaba `AttributeError` porque `get_poi_by_id` retorna `POIResponse` (Pydantic con nombres de campo en español), no el modelo ORM. Corregido a `chosen_poi.descripcion`.

**Bug 2 — `weather_service.py` `_build_day_forecast`**: usaba la temperatura del bloque de 3 horas más cercano al mediodía, que podía ser 7°C mientras la máxima real era 16°C. Corregido para usar `max()` de todas las temperaturas diurnas (6:00-21:00). Agregado logging: INFO con lat, lon, item count, city name; DEBUG por día con temperaturas raw, max temp, descripción, precipitación.
- Agregado `get_daily_forecast()` estructurado e inyección de clima en generación de itinerarios (`ai_context.weather` por paso).

#### Archivos creados/modificados
- `ruta_viva/app/api/v1/endpoints/ara.py`
- `ruta_viva/app/services/weather_service.py`

#### Estado resultante
- Ara ya no lanza 500 al procesar descripciones de POIs obtenidos vía `get_poi_by_id`,
- pronóstico de temperatura usa máximas reales en vez de un solo bloque horario,
- logging de weather para debugging y monitoreo.


---

### [2026-05-21] Gestión de itinerarios: reschedule, reorder con tiempos, endpoint de clima

#### Objetivo
- agregar endpoints de gestión avanzada de itinerarios para frontend.

#### Cambios realizados
- Agregado schema `RescheduleStepRequest(arrival_time, duration_minutes)` en `app/schemas/itinerary.py`.
- Agregados schemas `StepDayPosition(step_id, day_index, position)` y `ReorderStepsWithTimesRequest(steps)`.
- Agregados schemas `ItineraryStepWeather` y `ItineraryStepWeatherResponse`.
- Agregado `reschedule_step()` en `ItineraryRepository`: desplaza pasos subsecuentes del mismo día por delta.
- Agregado `reorder_steps_with_times()` en `ItineraryRepository`: redistribuye horarios con gaps de 15 min, patrón de dos fases.
- Agregado `PATCH /{itinerary_id}/steps/{step_id}/reschedule` — modifica horario y duración.
- Agregado `PATCH /{itinerary_id}/steps/reorder-with-times` — reordena con asignación automática de tiempos.
- Agregado `GET /{itinerary_id}/weather` — forecast por coordenadas únicas de POI y día, cacheado.
- Reschedule normaliza timezone a `America/Santiago` y maneja tiempos `None`.
- Reorder usa cursor temporal desde 9:00 AM, preserva duraciones.
- Patrón de dos fases (step_order negativo luego positivo) reutilizado.
- Weather endpoint cachea por `(rounded_lat, rounded_lon, date)` para evitar llamadas duplicadas a OWM.
- Agregado `from sqlalchemy import func as sql_func` en `itineraries.py` para `ST_Y`/`ST_X`.
- Agregado `format_forecast_summary` import a `itineraries.py`.
- Inyección de clima en generación: tras sanitización, inyecta `ai_context.weather` por paso con `{description, temperature_c, precipitation_probability}`.

#### Archivos creados/modificados
- `ruta_viva/app/schemas/itinerary.py`
- `ruta_viva/app/schemas/weather.py`
- `ruta_viva/app/repositories/itinerary_repository.py`
- `ruta_viva/app/api/v1/endpoints/itineraries.py`
- `ruta_viva/app/services/weather_service.py`

#### Estado resultante
- frontend puede reprogramar pasos y reordenar con horarios automáticos sin depender de lógica de tiempo en cliente,
- endpoint de clima dedicado para pantalla de itinerario con cache inteligente,
- generación de itinerarios incluye datos de clima estructurados por paso.


---

### [2026-05-21] Posts públicos de POI y reordenamiento persistente de posts

#### Objetivo
- exponer posts de POI sin autenticación para frontend público,
- permitir reordenamiento persistente del orden de posts.

#### Cambios realizados
- Agregado schema `PublicEntrepreneurPostResponse` (id, title, content, image_url, is_published, is_pinned, scheduled_at, created_at, updated_at — sin entrepreneur_id ni poi_name).
- Agregado `list_published_poi_posts()` en `EntrepreneurRepository`: filtra `is_published=True`, ordena por `is_pinned DESC, sort_order ASC, created_at DESC`.
- Agregado `GET /api/v1/pois/{poi_id}/posts` — público, sin auth, retorna solo posts publicados.
- Agregado `sort_order` column (Integer, default 0) a modelo `EntrepreneurPost`.
- Agregados schemas `PostPositionItem` y `ReorderPostsRequest`.
- Agregado `reorder_poi_posts()` en `EntrepreneurRepository`: persiste orden por `sort_order`.
- Actualizados `list_poi_posts` y `list_published_poi_posts` para ordenar por `sort_order`.
- Agregado `PUT /api/v1/entrepreneur/pois/{poi_id}/posts/reorder` (auth, verifica ownership).
- Migración `d4e5f6a7b8c9`: agrega columna `sort_order` a `entrepreneur_posts`.

#### Archivos creados/modificados
- `ruta_viva/app/models/entrepreneur_post.py`
- `ruta_viva/app/schemas/entrepreneur.py`
- `ruta_viva/app/repositories/entrepreneur_repository.py`
- `ruta_viva/app/api/v1/endpoints/entrepreneur.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/migrations/versions/d4e5f6a7b8c9_add_entrepreneur_post_sort_order.py`

#### Estado resultante
- frontend puede mostrar posts de POIs sin requerir login,
- emprendedores pueden fijar posts y controlar el orden de visualización,
- reordenamiento persistente vía endpoint dedicado.


---

### [2026-05-21] Verificación de POIs, detección de duplicados, confidence scoring, validación de RUT y rate limiting

#### Objetivo
- combatir POIs falsos/troll mediante verificación, scoring de confianza y detección de duplicados,
- validar identidad de emprendedores con RUT chileno,
- proteger el sistema contra spam con rate limiting.

#### Cambios realizados

**Modelos:**
- `POI`: agregado `verification_status` (String(20), default "pending", server_default "pending") y `confidence_score` (Float, default 0.0, server_default "0.0").
- `EntrepreneurProfile`: agregado `rut` (String(12), nullable, unique) y `verification_status` (String(20), default "unverified", server_default "unverified").
- Estados de verificación POI: "pending", "verified", "flagged".
- Estados de verificación EntrepreneurProfile: "unverified", "pending_review", "verified".

**Schemas:**
- `POICreate`: `image_url` ahora requerido (no opcional). Middleware almacena cover+gallery desde esta URL.
- `POIResponse`: agregados `verification_status` (str, default "pending") y `confidence_score` (float, default 0.0).
- `PotentialDuplicate`: id, nombre, descripcion, latitude, longitude, category_ids, distance_meters, semantic_similarity.
- `POICreationCheck`: potential_duplicates, pending_creation.
- `EntrepreneurProfileCreate`: agregado campo `rut` opcional.
- `EntrepreneurProfileResponse`: agregado `verification_status`.

**Detección de duplicados (3 pasos en cascada):**
1. Geográfico: `ST_DWithin(50m)` encuentra candidatos en 50 metros.
2. Categoría: filtra candidatos que comparten al menos una categoría.
3. Semántico: rankea por `description_embedding.cosine_distance()`. Similitud ≥ 0.75 (distancia ≤ 0.25) → flag.

**Flujo de creación:**
- `POST /api/v1/pois/` → `201` si no hay duplicados o `force_create=true`, `200` con `POICreationCheck` si hay duplicados.
- `POST /api/v1/pois/?force_create=true` → ignora duplicados y crea igual.
- `image_url` obligatorio en `POICreate` — el upload debe ocurrir primero vía `POST /api/v1/media/upload`.

**Cálculo de confidence:**
| Señal | Puntos |
|---|---|
| Tiene imagen (multimedia_urls cover/gallery) | +0.2 |
| Descripción ≥ 50 chars | +0.15 |
| Descripción ≥ 20 chars | +0.05 |
| Tiene categoría | +0.1 |
| Tiene opening_hours_text | +0.1 |
| Tiene teléfono o email | +0.05 |
| Creado por emprendedor verificado | +0.2 |

**Asignación de verificación en creación:**
| Creador | verification_status | Confianza inicial |
|---|---|---|
| OSM import (sin entrepreneur_id) | "verified" | 0.7 |
| Emprendedor verificado | "verified" | 0.5 + señales |
| Emprendedor no verificado | "pending" | 0.3 + señales |
| Turista (sin perfil emprendedor) | "pending" | 0.2 + señales |

**Filtrado en búsquedas:**
- `GET /pois/search` y `GET /pois/semantic-search` excluyen POIs con `verification_status = "flagged"`.
- `GET /pois/{poi_id}` no filtra — acceso directo siempre funciona.

**Validación de RUT:**
- `app/core/rut.py`: valida RUT chileno con algoritmo módulo 11.
- Al crear perfil emprendedor, RUT válido → `verification_status = "verified"`.
- RUT inválido → `422` con mensaje descriptivo.
- Sin RUT → `verification_status = "unverified"`.
- RUT almacenado formateado con constraint único.

**Rate limiting:**
- Máximo 5 POIs por hora por usuario.
- Máximo 10 POIs por día por usuario.
- Excedido → `429 Too Many Requests`.

**Migración `e5f6a7b8c9d0`:**
- Agrega `verification_status` y `confidence_score` a `pois`.
- Agrega `rut` y `verification_status` a `entrepreneur_profiles`.
- Crea constraint único en `entrepreneur_profiles.rut`.
- Actualiza POIs importados de OSM (`entrepreneur_id IS NULL`) a `verification_status = 'verified'` y `confidence_score = 0.7`.

#### Archivos creados/modificados
- `ruta_viva/app/models/poi.py`
- `ruta_viva/app/models/entrepreneur_profile.py`
- `ruta_viva/app/schemas/poi.py`
- `ruta_viva/app/schemas/entrepreneur.py`
- `ruta_viva/app/schemas/entrepreneur_profile.py`
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/repositories/entrepreneur_repository.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/app/api/v1/endpoints/entrepreneur.py`
- `ruta_viva/app/api/v1/endpoints/users.py`
- `ruta_viva/app/core/rut.py`
- `ruta_viva/migrations/versions/e5f6a7b8c9d0_add_verification_confidence_and_rut_fields.py`

#### Estado resultante
- POIs falsos/troll pueden ser detectados como duplicados antes de crearse,
- confidence score cuantifica la calidad de cada POI con señales reales,
- emprendedores validados con RUT obtienen verificación automática,
- rate limiting previene abuso en creación masiva de POIs,
- POIs flageados no aparecen en búsquedas públicas pero siguen accesibles por ID,
- OSM imports heredan estado "verified" y score 0.7.


---

### [2026-05-21] Fase 2: Recalculación automática de confidence y filtrado en búsquedas

#### Objetivo
- hacer que los scores de confianza se actualicen automáticamente con señales reales del sistema,
- filtrar POIs flageados de resultados de búsqueda.

#### Cambios realizados
- Agregado `recalculate_confidence(poi_id)` a `POIRepository`: recalcula score desde fotos, descripción, categorías, reviews, visitas, verificación del creador, y opcionalmente des-flaguea POIs que alcancen ≥ 0.4.
- Confidence recalculation hooked en:
  - `PATCH /pois/{id}/media` (foto agregada → recalculado),
  - `PUT /pois/{id}` (POI editado → recalculado),
  - `POST /reviews/` (review creada → recalculado para ese POI),
  - `POST /pois/{id}/visit` (visita registrada en `pois.py` y `entrepreneur.py` → recalculado),
  - `POST /api/v1/entrepreneur/pois/{poi_id}/visit` → recalculado.
- Agregado filtro `verification_status != "flagged"` a queries `get_pois_nearby()` y `search_hybrid()`.
- `POICreationCheck` response type agregado a `POST /pois/` para detección de duplicados.

#### Archivos creados/modificados
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/app/api/v1/endpoints/entrepreneur.py`
- `ruta_viva/app/api/v1/endpoints/reviews.py`

#### Estado resultante
- scores de confianza evolucionan orgánicamente con la actividad del sistema,
- POIs que ganan suficientes señales positivas pueden salir del estado flagged automáticamente,
- búsquedas públicas no muestran POIs flageados, mejorando la calidad de resultados para usuarios.

---

### [2026-05-21] Fase 5: Consistencia, limpieza y Docker

#### Objetivo
Cerrar la fase de consistencia interna antes de conectar contratos con frontend: mantener JSON/API en inglés, reducir mapeos manuales, centralizar commits con rollback, eliminar duplicación en posts de emprendedor y robustecer Docker.

#### Cambios realizados
- **Schemas/API en inglés:** se mantiene la decisión de que los contratos JSON hablen en inglés (`name`, `description`, `latitude`, `longitude`, `category_ids`, etc.). La traducción queda a cargo del frontend.
- **Repositorio base:** `BaseRepository` conserva `_commit_or_rollback()` y agrega wrapper público `commit_or_rollback()` para servicios que controlan transacciones.
- **Posts de emprendedor deduplicados:** `EntrepreneurRepository.create_post`, `update_post` y `delete_post` ahora aceptan `poi_id` opcional y cubren tanto posts generales (`/me/posts`) como posts anidados por POI (`/pois/{poi_id}/posts`). Se eliminaron los métodos duplicados `create_poi_post`, `update_poi_post`, `delete_poi_post` del repositorio.
- **Respuesta de posts:** `EntrepreneurPost.poi_name` se expone como property del modelo para permitir `EntrepreneurPostResponse.model_validate(post)` con `from_attributes=True`, reduciendo mapeo manual en endpoints.
- **Rollback guard:** `bookmark_repository.delete_bookmark()` ahora ejecuta el `DELETE` dentro del bloque protegido para hacer rollback también si falla el execute, no solo el commit.
- **Consistencia booleana:** `list_published_poi_posts()` ya usa `.is_(True)` para `is_published`.
- **Utilidades ya centralizadas:** `repositories/utils.py` contiene `get_category_ids`, `get_category_ids_batch` y `build_poi_response_from_row`; `core/time_utils.py` contiene `to_chile_timezone`; `review_enrichment_service.py` contiene el background task de embeddings y la fórmula de decay `0.9/0.1`.
- **Docker:** `Dockerfile` pasa a multi-stage build, agrega healthcheck de API, mantiene runtime slim con usuario no root. `Dockerfile.db` deja de usar `latest` y queda pineado a `ankane/pgvector:v0.5.1`. `docker-compose.yml` agrega healthcheck al servicio `api`. Se agrega `.dockerignore` para reducir contexto y evitar copiar `.env`, caches, venvs y media.
- **Tests:** se agrega `tests/unit/test_repository_base.py` para cubrir commit exitoso y rollback en error de commit.

#### Contrato frontend relevante
- La opción adoptada es **Opción A**: schemas en inglés. Si el frontend venía enviando campos en español, debe migrar a los nombres en inglés del backend.
- Los endpoints públicos de posts mantienen rutas y estructura de respuesta, pero internamente pasan por un único método de repositorio.

#### Validación ejecutada
- `python -m compileall app tests/unit/test_repository_base.py` pasó correctamente.
- `docker compose config` validó correctamente la sintaxis de Compose.
- Smoke test directo con `../fastapi/bin/python` sobre `BaseRepository._commit_or_rollback()` pasó correctamente.
- `python -m pytest tests/unit/test_repository_base.py` no pudo ejecutarse en el Python del sistema por falta de `pytest_asyncio`.
- `../fastapi/bin/python -m pytest tests/unit/test_repository_base.py` tampoco pudo ejecutarse porque ese venv local no tiene `slowapi` instalado.

#### Archivos modificados/creados
- `ruta_viva/app/repositories/base.py`
- `ruta_viva/app/repositories/entrepreneur_repository.py`
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/repositories/user_repository.py`
- `ruta_viva/app/repositories/review_repository.py`
- `ruta_viva/app/repositories/bookmark_repository.py`
- `ruta_viva/app/repositories/itinerary_repository.py`
- `ruta_viva/app/api/v1/endpoints/entrepreneur.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/app/models/entrepreneur_post.py`
- `ruta_viva/Dockerfile`
- `ruta_viva/Dockerfile.db`
- `ruta_viva/docker-compose.yml`
- `ruta_viva/.dockerignore`
- `ruta_viva/tests/unit/test_repository_base.py`

---

### [2026-05-21] Fase 6: Limpieza final

#### Objetivo
Cerrar la limpieza de baja prioridad dejando menos deuda técnica antes de continuar con la conexión frontend y fases posteriores.

#### Cambios realizados
- `geo_service.py` se mantiene porque ya contiene `distance_meters()` y está siendo usado por `poi_search_service.py`.
- `rag_service.py` se elimina porque estaba vacío y no tenía imports activos.
- Schemas inline de auth movidos desde `api/v1/endpoints/auth.py` a `schemas/auth.py` (`RegisterRequest`, `LoginRequest`).
- `datetime.utcnow()` revisado: no quedan usos activos; el código usa `datetime.now(timezone.utc)` donde corresponde.
- Engine SQLAlchemy: `echo` pasa a ser configurable vía `DATABASE_ECHO` / `database_echo`, default `false`.
- `MEDIA_DIR.mkdir()` se mueve del import-time de `main.py` al `lifespan` de FastAPI.
- `/media/{filename}` deja de ser un mount estático público y pasa a endpoint autenticado con bearer token. La URL se mantiene igual para no romper valores guardados (`/media/<uuid>.jpg|png`), pero ahora requiere Authorization header.
- `candidate_poi_ids` de `AraSession` pasa de `JSONB` con strings a `ARRAY(UUID)`.
- `AraSession` deja de persistir `lat`/`lon` como floats separados y pasa a persistir `location` como PostGIS `POINT`. La API mantiene `lat`/`lon`; el cambio es interno.

#### Impacto frontend
- Las URLs de media siguen teniendo el mismo formato (`/media/{filename}`), pero ya no deberían usarse directo en `<img src>` si no hay forma de adjuntar token.
- Para imágenes protegidas, frontend debe hacer `fetch(url, { headers: { Authorization: 'Bearer ...' } })`, convertir a `Blob` y usar `URL.createObjectURL(blob)`.
- No cambia el contrato público de POIs, Ara, geocoding ni weather: se mantienen `lat`/`lon` y `latitude`/`longitude` en JSON/API.

#### Migración
- Nueva migración `a7b8c9d0e1f2_ara_location_and_candidate_uuid_array.py`:
  - crea `ara_sessions.location` como `Geometry(POINT, 4326)`,
  - migra datos desde `lat`/`lon`,
  - elimina columnas `lat` y `lon`,
  - convierte `candidate_poi_ids` desde JSONB array a `uuid[]`.

#### Archivos modificados/creados
- `ruta_viva/app/schemas/auth.py`
- `ruta_viva/app/api/v1/endpoints/auth.py`
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/db/session.py`
- `ruta_viva/app/main.py`
- `ruta_viva/app/models/ara_session.py`
- `ruta_viva/app/repositories/ara_repository.py`
- `ruta_viva/app/services/ara_conversation_orchestrator.py`
- `ruta_viva/app/services/rag_service.py` (eliminado)
- `ruta_viva/migrations/versions/a7b8c9d0e1f2_ara_location_and_candidate_uuid_array.py`
- `ruta_viva/.env.example`

---

### [2026-05-21] Corrección scripts de poblamiento post Fase 5/6

#### Objetivo
Dejar el pipeline de poblamiento compatible con los contratos en inglés, constraints actuales y mejoras de calidad necesarias para reconstruir la base de POIs después de un reset local.

#### Cambios realizados
- `scripts/import_osm_data.py` ya no usa `POICreate` con campos antiguos en español.
- `infer_access_type()` ahora devuelve valores válidos para DB: `public`, `restricted`, `private`.
- La creación de POIs OSM ahora usa inserción directa del modelo `POI` para preservar metadata rica de OpenStreetMap en `multimedia_urls` (`source`, `osm_type`, `osm_id`, `osm_url`, `osm_tags`, `website`, `image`, `wikipedia`).
- Si OSM trae `image`, se guarda además como `cover` y `gallery` en `multimedia_urls`.
- POIs OSM se crean/actualizan con `verification_status='verified'`.
- Se agrega `calculate_osm_confidence_score()` para inicializar `confidence_score` según categorías, descripción, horarios, contacto, website/wikipedia, imagen y penalización por `blocked_for_itinerary`.
- Las descripciones generadas desde OSM ahora incluyen más contexto semántico: sector/localidad, cocina, operador y clasificación OSM relevante cuando existe.
- `scripts/recategorize_pois.py` ahora mergea `visit_rules` en vez de reemplazarlas completas, para no perder metadata rica o flags de bloqueo generados por el import/enrichment.

#### Pipeline recomendado para reconstruir POIs
```bash
alembic upgrade head
python scripts/seed_categories.py
python scripts/import_osm_data.py --limit 3000 --batch-size 10
python scripts/recategorize_pois.py
python scripts/enrich_poi_metadata.py --limit 500 --refresh-embeddings
python scripts/create_vector_indices.py
python scripts/audit_poi_quality.py --limit 5000 --output poi_issues.jsonl
python scripts/apply_poi_quality_fixes.py poi_issues.jsonl --min-confidence 0.85
```

#### Validación ejecutada
- `python -m compileall scripts/import_osm_data.py scripts/recategorize_pois.py`
- Smoke test con `../fastapi/bin/python` de `build_place()` + `calculate_osm_confidence_score()`.

---

### [2026-05-22] Auditoría extrema — Ara conversacional e itinerarios

#### Objetivo
Revisar el flujo más importante del producto: desde que el frontend abre **Chat con Ara** hasta que el usuario termina con un itinerario creado, consultado, editado, reordenado, enriquecido con clima y eventualmente ajustado por Ara. Esta auditoría se hizo sobre el estado actual del código post Fase 5/6 y post cambios de base de datos.

#### Alcance auditado
- `POST /api/v1/ara/sessions`: inicio de conversación, detección de intención, preferencias, búsqueda de candidatos y quick replies.
- `POST /api/v1/ara/sessions/{session_id}/messages`: refinamientos, preguntas libres, selección de candidatos, reset de viaje y flujo de reemplazo de parada.
- `POST /api/v1/ara/sessions/{session_id}/generate-itinerary`: generación final síncrona desde el contexto conversacional.
- `POST /api/v1/ara/sessions/{session_id}/generate-itinerary/async` + `GET /generation-status`: generación asíncrona.
- `POST /api/v1/itineraries/generate`: generación directa sin conversación.
- `GET /api/v1/itineraries/`, `GET /{id}`, `GET /{id}/pois`: historial, detalle y mapa filtrado.
- `PATCH /api/v1/itineraries/{id}/steps/reorder`, `PATCH /steps/reorder-with-times`, `PATCH /steps/{step_id}`, `PATCH /steps/{step_id}/reschedule`, `DELETE /steps/{step_id}`, `DELETE /{id}`.
- `GET /api/v1/itineraries/{id}/weather`: clima por pasos del itinerario.
- Servicios principales: `ara_conversation_orchestrator.py`, `ara_chat_service.py`, `ara_turn_classifier.py`, `ara_preference_merger.py`, `ara_trip_draft_builder.py`, `ara_response_builder.py`, `itinerary_generation_service.py`, `itinerary_weather_service.py`, `poi_search_service.py`.

#### Foto real del flujo actual
1. Frontend inicia Ara con mensaje inicial, ubicación opcional, radio y fechas opcionales.
2. Backend normaliza fechas, analiza intención, extrae preferencias, construye `trip_draft`, resuelve centro de búsqueda y recupera candidatos POI.
3. Ara responde con texto natural, `quick_replies`, `candidate_pois`, `intent` y `preferences`.
4. En cada mensaje posterior, el backend clasifica el turno: selección de candidato, nueva ruta/reset, petición de generar, pregunta libre, reemplazo de parada o refinamiento general.
5. Para preguntas libres, Ara puede usar DeepSeek con contexto de candidatos o del itinerario activo, pero tiene fallback local si no hay API key o falla el proveedor.
6. Para generar itinerario desde Ara, el backend arma una consulta refinada, mezcla candidatos de sesión con búsqueda fresca, trae clima, llama a DeepSeek, valida/repara el resultado, persiste `Itinerary` + `ItineraryStep` y marca la sesión como completada.
7. Después de generado, frontend puede listar, abrir detalle, obtener POIs del mapa, reordenar, reprogramar, eliminar pasos, consultar clima y abrir Ara para cambiar un lugar puntual.

#### Matriz de hallazgos

| Severidad | Área | Hallazgo | Impacto | Recomendación |
|---|---|---|---|---|
| CRÍTICA | Ara/DB | El código usa estados de sesión que el constraint `ck_ara_sessions_status` no permite: `queued`, `ready_to_generate`, `suggesting_step_replacement`, `step_replaced`. El modelo solo permite `clarifying`, `searching`, `generating`, `completed`, `failed`. | Flujos clave pueden fallar con `IntegrityError` al commitear: generación async, confirmación de generación y cambio de lugar. | Unificar máquina de estados. Opción recomendada: migración + modelo para incluir estados reales usados por frontend, o mover estados UI a `preferences_data.conversation_mode` y dejar `status` solo para ciclo técnico. |
| CRÍTICA | Ara async | `generate-itinerary/async` setea `status="queued"`, estado no permitido por DB. | La generación en background probablemente falla antes de encolar la tarea. | Si se mantiene async, agregar `queued` al constraint o usar `generating` desde el inicio y metadata `generation_status=queued`. |
| ALTA | Ara cambio de lugar | El flujo de reemplazo actual cambia `poi_id` del step, pero no recalcula horario, duración, clima, distancia, ni valida si el nuevo POI abre en ese slot. | El usuario puede reemplazar por un lugar logísticamente malo o cerrado; el itinerario queda técnicamente actualizado pero no necesariamente correcto. | Crear servicio de reemplazo de step que valide apertura, categoría, clima, distancia y opcionalmente reprograme el bloque. |
| ALTA | Itinerarios | `reschedule_step()` sobrescribe `target.arrival_time` antes de calcular la duración antigua; al mover un paso puede calcular duración incorrecta y desplazar mal pasos siguientes. | Cambios de horario desde frontend pueden generar duraciones de 15 minutos por error o desplazamientos inesperados. | Guardar `old_arrival` y `old_departure` antes de mutar el step; recalcular duración con valores antiguos. |
| ALTA | Clima | `get_itinerary_step_weather()` consulta por coordenada, pero guarda resultados en `forecast_by_date` solo por fecha. Si un mismo día tiene POIs en microclimas distintos, el último forecast pisa al anterior y todos los steps del día reciben el mismo clima. | Clima por POI puede ser incorrecto, especialmente en La Araucanía donde costa, valle, lago y cordillera cambian mucho. | Indexar clima por `(step_id)` o `(rounded_lat, rounded_lon, date)` y mapear cada step a su forecast real. |
| ALTA | Calidad de ruta | No existe cálculo real de tiempo de traslado ni optimización geográfica de orden. El LLM ordena y backend valida horarios/categorías, pero no valida distancias consecutivas ni tiempos de viaje. | Itinerarios pueden verse bien en pantalla pero ser poco realistas en terreno. | Agregar capa logística: matriz simple de distancias Haversine + velocidad conservadora, y después OSRM/Google/ORS si se desea precisión. |
| ALTA | Código muerto | `api/v1/endpoints/itineraries.py` y `itinerary_generation_service.py` contienen bloques grandes inalcanzables después de `return`. | Confunde mantenimiento, duplica reglas mentales y puede esconder bugs al editar en el bloque equivocado. | Eliminar código muerto y dejar una única fuente de verdad para generación. |
| ALTA | Generación directa | `POST /itineraries/generate` usa `search_hybrid()` con `profile_weight` default `0.3`; Ara usa fallback de generación con `profile_weight=0.1`. | La generación directa puede seguir contaminándose más por perfil histórico que el flujo Ara. | Pasar explícitamente `profile_weight=0.1` en generación directa para alinear ambos flujos. |
| MEDIA | Frontend contract | `status` es `str` sin enum en schemas y `quick_replies.type` también es libre. | Frontend debe adivinar estados y tipos, aumentando fragilidad. | Definir enums documentados para `AraSessionStatus` y `AraQuickReplyType`; exponerlos en OpenAPI. |
| MEDIA | UX Ara | Las respuestas pueden mezclar texto conversacional, candidatos, quick replies y metadata grande. | La pantalla puede sentirse cargada y el usuario puede no saber cuál es la acción principal. | UI recomendada: una acción primaria visible por turno, máximo 3 chips principales, candidatos en carrusel colapsable, metadata solo para lógica interna. |
| MEDIA | POI recommendations | La calidad depende mucho de OSM/enrichment. Hay buenos filtros contra POIs logísticos, pero la recomendación aún no combina `confidence_score`, densidad por zona, diversidad y popularidad/reviews como ranking final explícito. | Ara puede recomendar lugares reales pero no necesariamente los mejores o más turísticos. | Crear score de recomendación final: similitud + distancia + confidence + diversidad + disponibilidad + señales sociales. |
| MEDIA | Multi-día | Hay reglas para cubrir días y variar categorías, pero no existe concepto fuerte de base por noche, check-in/check-out, traslados entre comunas ni día liviano de llegada/salida fuera del prompt. | Viajes de varios días pueden sentirse como lista de actividades, no como viaje real. | Formalizar `trip_draft` como contrato: base por noche, zonas por día, intensidad diaria y ventanas de traslado. |
| MEDIA | Media protegida | `candidate_pois.multimedia_urls` puede contener `/media/{filename}`, que ahora requiere JWT. | `<img src>` directo falla si no se adjunta token. | Frontend debe usar fetch con bearer token, Blob y `URL.createObjectURL`, o backend debe emitir signed URLs en una fase posterior. |
| MEDIA | Testing | No hay tests específicos para state machine de Ara, generación multi-día, reemplazo de step, clima por POI ni edición avanzada. | Cambios futuros pueden romper el flujo principal sin detección. | Agregar tests unitarios e integración con LLM/weather mockeados. |
| BAJA | Endpoints | `ara_service` se inyecta en endpoints de Ara pero no se usa en handlers. | Deuda menor y ruido conceptual. | Eliminar dependencias no usadas o conectar facade si realmente será la interfaz pública del dominio. |

#### Contrato actual relevante para frontend

**Inicio de chat**
```http
POST /api/v1/ara/sessions
Authorization: Bearer <token>
```
Body:
```json
{
  "initial_message": "Quiero una ruta familiar cerca de Pucón con naturaleza y comida rica",
  "lat": -39.282,
  "lon": -71.954,
  "radius": 5000,
  "start_date": "2026-05-23",
  "end_date": "2026-05-24",
  "metadata": null
}
```
Respuesta importante para UI:
- `session_id`: guardar para todos los mensajes siguientes.
- `status`: hoy es string y debe tratarse defensivamente por el mismatch detectado.
- `assistant_message.content`: burbuja principal de Ara.
- `quick_replies`: chips; `type="generate"` debe mostrarse como CTA fuerte.
- `candidate_pois`: tarjetas sugeridas; pueden venir vacías si Ara solo está aclarando o respondiendo una duda.
- `preferences` e `intent`: útiles para debug o UI avanzada, no deberían mostrarse completos al usuario.

**Enviar mensaje**
```http
POST /api/v1/ara/sessions/{session_id}/messages
```
Body:
```json
{ "message": "Prefiero algo con poca caminata y si llueve, bajo techo" }
```

**Generar itinerario desde Ara**
```http
POST /api/v1/ara/sessions/{session_id}/generate-itinerary
```
Body opcional:
```json
{ "final_instruction": "Hazlo tranquilo, con almuerzo y pocas caminatas" }
```

**Generación async**
```http
POST /api/v1/ara/sessions/{session_id}/generate-itinerary/async
GET  /api/v1/ara/sessions/{session_id}/generation-status
```
Advertencia: actualmente debe corregirse el estado `queued` antes de confiar en este flujo.

**Cambiar lugar desde Ara**
Se inicia una sesión Ara con metadata:
```json
{
  "initial_message": "Quiero cambiar este lugar por algo parecido pero más cerca",
  "lat": -39.282,
  "lon": -71.954,
  "radius": 5000,
  "metadata": {
    "intent": "change_itinerary_step",
    "itinerary_id": "<uuid>",
    "step_id": "<uuid>",
    "poi_name": "Nombre actual"
  }
}
```
Ara responde con alternativas y quick replies tipo `replace_step`. Al elegir, backend actualiza el step.

**Gestión post-generación**
- `GET /api/v1/itineraries/`: historial.
- `GET /api/v1/itineraries/{id}`: detalle agrupable por `day_index`, `day_date`, `day_label`.
- `GET /api/v1/itineraries/{id}/pois`: POIs para mapa filtrado.
- `PATCH /api/v1/itineraries/{id}/steps/reorder`: reordena todos los steps por UUID.
- `PATCH /api/v1/itineraries/{id}/steps/reorder-with-times`: reordena por día/posición y reasigna horarios desde 09:00 con gaps de 15 min.
- `PATCH /api/v1/itineraries/{id}/steps/{step_id}/reschedule`: cambia hora y desplaza pasos posteriores.
- `PATCH /api/v1/itineraries/{id}/steps/{step_id}`: cambia POI/horarios/contexto.
- `GET /api/v1/itineraries/{id}/weather`: clima por step; requiere corrección para clima por coordenada.

#### Cómo debería sentirse Ara en frontend
- Ara debe sentirse como una guía, no como un formulario largo.
- Cada turno debe tener una intención dominante: aclarar, mostrar opciones, confirmar generación, responder duda o editar itinerario.
- Mostrar máximo 2-3 chips principales y dejar el resto en “más opciones”.
- Las tarjetas POI deben ser apoyo visual, no la respuesta completa.
- En generación, mostrar progreso claro: preparando preferencias → buscando lugares → revisando clima → armando ruta → listo.
- Después de generar, Ara debería cambiar a modo copiloto del itinerario: explicar pasos, ajustar horarios, cambiar lugares, responder dudas y sugerir alternativas por clima.

#### Backlog recomendado

**Sprint inmediato — desbloqueo**
1. Corregir estados Ara vs constraint DB.
2. Corregir `reschedule_step()` para preservar duración real.
3. Corregir clima por step/coordenada.
4. Eliminar código muerto post-`return`.
5. Alinear `profile_weight=0.1` también en generación directa.

**Sprint producto — calidad de Ara/itinerarios**
1. Formalizar enums de status y quick replies.
2. Servicio de reemplazo de step con validación horaria/climática/logística.
3. Score final de recomendación POI con `confidence_score`, diversidad y disponibilidad.
4. Validación logística mínima por distancia/tiempo entre pasos.
5. UX contract para frontend: state machine visual y payload mínimo por pantalla.

**Sprint avanzado — diferenciador Ruta Viva**
1. Optimización de ruta por zonas/días.
2. Base por noche y traslados para multi-día.
3. Signed URLs o proxy controlado para media.
4. Observabilidad: eventos de Ara, latencia LLM, tasa de fallback, tasa de generación fallida, POIs descartados por validadores.
5. Tests de integración end-to-end con LLM/weather mockeados.

#### Estado resultante de la auditoría
Ara y los itinerarios tienen una base potente: estado persistente, preferencias acumuladas, búsqueda híbrida, grounding con POIs reales, clima, validaciones deterministas y edición post-generación. Sin embargo, el flujo principal aún es el punto más delicado del producto por tres razones: la máquina de estados no está alineada con DB, la logística real de viaje todavía es débil y el contrato frontend necesita formalizarse mejor. La prioridad ya no debería ser agregar más endpoints, sino estabilizar y hacer confiable la experiencia completa.

