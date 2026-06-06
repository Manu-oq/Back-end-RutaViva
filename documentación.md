# Documentación Técnica — Backend Ruta Viva

> Última actualización: **2026-06-05**  
> Última actualización de refactorización: **2026-06-03** (Fases 1-2 completadas)
>
> Documento técnico exhaustivo del backend de Ruta Viva. Cubre cada archivo del codebase, cada endpoint, cada modelo y cada flujo de datos. Dirigido a desarrolladores que necesitan entender, mantener o extender el sistema.

---

## Tabla de Contenidos

1. [Stack Tecnológico](#1-stack-tecnológico)
2. [Arquitectura General](#2-arquitectura-general)
3. [Estructura del Proyecto](#3-estructura-del-proyecto)
4. [API REST — Catálogo Completo de Endpoints](#4-api-rest--catálogo-completo-de-endpoints)
5. [Modelo de Datos](#5-modelo-de-datos)
6. [Servicios de IA](#6-servicios-de-ia)
7. [Rate Limiting](#7-rate-limiting)
8. [Seguridad](#8-seguridad)
9. [Infraestructura](#9-infraestructura)
10. [Tests](#10-tests)
11. [Flujos de Datos Detallados](#11-flujos-de-datos-detallados)
12. [Configuración (Settings)](#12-configuración-settings)
13. [Deuda Técnica Conocida](#13-deuda-técnica-conocida)
14. [Comandos Útiles](#14-comandos-útiles)
15. [Guía de Contribución](#15-guía-de-contribución)
16. [Referencias Rápidas](#16-referencias-rápidas)
17. [Ara v2 — Asistente Conversacional](#17-ara-v2--asistente-conversacional)

---

## 1. Stack Tecnológico

| Componente | Tecnología | Versión / Detalle |
|------------|-----------|-------------------|
| Lenguaje | Python | 3.13 |
| Framework web | FastAPI | 0.115+ |
| ORM | SQLAlchemy | 2.0 (async) |
| Driver DB | asyncpg | — |
| Base de datos | PostgreSQL | 16 (Docker) |
| Extensiones DB | pgvector, PostGIS | — |
| Migraciones | Alembic | — |
| Validación | Pydantic v2 | — |
| Hashing de contraseñas | Passlib + bcrypt (puro) | Soporte transparente bcrypt_sha256→bcrypt |
| JWT | python-jose | HS256 |
| Rate Limiting | slowapi | Basado en `limits` |
| LLM Embeddings | OpenAI text-embedding-3-small | 1536 dimensiones |
| LLM Comprensión | OpenAI GPT-4o-mini | Comprensión conversacional Ara v2 |
| LLM Generación | DeepSeek (deepseek-chat) | Generación de itinerarios |
| Clima | OpenWeatherMap | Forecast API 2.5, cache TTLCache 30 min |
| Geocoding HTTP | Nominatim (OSM) | Forward geocoding |
| Geocoding LLM | GPT-4o-mini | Geocodificación de destinos en Ara |
| Contenedores | Docker + Docker Compose | PostgreSQL + API |
| Tests | pytest | asyncio_mode=auto |
| Telemetría | Middleware propio | X-Process-Time header |
| HTTP Client | httpx.AsyncClient | Connection pooling compartido |

---

## 2. Arquitectura General

### 2.1 Patrón de Capas

```
┌──────────────────────────────────────────────────────────┐
│  api/v1/endpoints/     ← Handlers HTTP delgados          │
│  (reciben request, validan Pydantic, delegan, responden)  │
├──────────────────────────────────────────────────────────┤
│  services/             ← Lógica de negocio + IA          │
│  (orquestan flujos, integran APIs externas)              │
├──────────────────────────────────────────────────────────┤
│  repositories/         ← Acceso a datos                  │
│  (queries SQLAlchemy, selectinload, N+1 prevention)      │
├──────────────────────────────────────────────────────────┤
│  models/               ← Entidades ORM                   │
│  (tablas, relaciones, constraints, columnas)             │
├──────────────────────────────────────────────────────────┤
│  schemas/              ← Contratos Pydantic              │
│  (request/response validation, serialización)            │
├──────────────────────────────────────────────────────────┤
│  core/                 ← Infraestructura transversal     │
│  (config, security, exceptions, rate_limit, timezone)    │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Principios de Diseño

1. **Endpoints delgados**: Reciben request, validan con Pydantic, delegan a services, devuelven response. Sin lógica de negocio inline. Máximo ~50 líneas por handler.
2. **Services con responsabilidad única**: Cada service hace una cosa. Si crece demasiado, se parte en sub-módulos (ej: `ara_v2/` con 9 módulos).
3. **Repositories con eager loading explícito**: Toda query que expone relaciones usa `.options(selectinload(...))`. Nunca se confía en `lazy="selectin"`.
4. **Excepciones de dominio**: Los services lanzan `AppError`, `PermissionError`, `ConflictError`. Solo `main.py` sabe de HTTP status codes.
5. **Settings tipados**: Toda configuración externa pasa por `Settings` de Pydantic, con defaults seguros y alias de entorno (AliasChoices).
6. **Async end-to-end**: Desde el handler HTTP hasta la query SQL, todo es async. No hay bloqueos de thread pool. Una excepción menor: `asyncio.to_thread` para escritura de archivos de imagen.

### 2.3 Estructura de Archivos del Proyecto

Todos los paths son relativos a `ruta_viva/`. Se listan **todos** los archivos fuente del proyecto, organizados por capa y excluyendo `__pycache__/`, `.pyc`, y `fastapi/` (virtualenv local).

```
ruta_viva/
│
├── app/                                 # Código fuente de la aplicación
│   ├── main.py                         # (193 líneas) FastAPI app, CORS, middleware, exception handlers, lifespan, /health, /media/{filename}
│   │
│   ├── api/                            # Capa HTTP
│   │   ├── deps.py                     # (91 líneas) Dependencies: get_current_user, get_optional_current_user
│   │   └── v1/
│   │       ├── api.py                  # (31 líneas) Router aggregation: incluye los 12 routers
│   │       └── endpoints/
│   │           ├── ara.py              # (139 líneas) Ara: sesiones, mensajes, intent, SSE streaming
│   │           ├── auth.py             # (128 líneas) Register, login, refresh, logout con rate limit
│   │           ├── bookmarks.py        # (69 líneas) Bookmark CRUD
│   │           ├── categories.py       # (16 líneas) Listado de categorías
│   │           ├── entrepreneur.py     # (240 líneas) Dashboard emprendedor, métricas, posts, analytics
│   │           ├── geocoding.py        # (24 líneas) Forward geocoding con Nominatim
│   │           ├── itineraries.py      # (497 líneas) CRUD itinerarios, steps, weather, share, export, visitas
│   │           ├── media.py            # (17 líneas) Upload de imágenes
│   │           ├── pois.py             # (420 líneas) POI CRUD, búsqueda geoespacial, semántica, visitas
│   │           ├── reviews.py          # (164 líneas) Review CRUD, summaries
│   │           ├── shared.py           # (27 líneas) GET /share/{public_id} — itinerario público compartido
│   │           ├── users.py            # (84 líneas) Perfil CRUD, edición, reset de intereses
│   │           └── weather.py          # (44 líneas) Weather forecast público
│   │
│   ├── core/                           # Infraestructura transversal
│   │   ├── ara_constants.py            # (546 líneas) Catálogo central: food/nature/culture/adventure terms, KNOWN_DESTINATION_NAMES,
│   │   │                               #   TYPO_REPLACEMENTS, DIMENSION_TRACKING, DESTINATION_REQUEST_PATTERN, EXPAND_DESTINATION_TERMS,
│   │   │                               #   KNOWN_DESTINATION_CENTERS, SURPRISE_ROUTE_TERMS, GENERATE_TERMS, LODGING_TERMS,
│   │   │                               #   GASTRONOMY/NATURE/CULTURE_CATEGORY_IDS, STRICT_DESTINATION_SOURCES, FOOD_COMPLETION_TAGS, etc.
│   │   ├── ara_messages.py             # (424 líneas) Catálogo AraMessages: respuestas de asistente en español, sistema bilingüe
│   │   │                               #   (greeting, no_destination, found_places, itinerary_ready, replacement_found, etc.)
│   │   ├── config.py                   # (65 líneas) Settings Pydantic con AliasChoices, async_database_uri property
│   │   ├── exceptions.py              # (25 líneas) Jerarquía: AppError → PermissionError, ConflictError, ItineraryNotEditableError
│   │   ├── http_client.py             # (24 líneas) Pool de httpx.AsyncClient con singleton por nombre
│   │   ├── itinerary_constants.py     # (102 líneas) Términos de alojamiento, transporte, servicio, repetición, día de descanso
│   │   ├── llm_retry.py               # (43 líneas) with_retry() con backoff exponencial, max_retries=2, base_delay=1.0, max_delay=10.0
│   │   ├── rate_limit.py              # (5 líneas) slowapi Limiter con get_remote_address
│   │   ├── rut.py                     # (36 líneas) validate_rut() módulo 11 chileno, format_rut()
│   │   ├── security.py                # (61 líneas) JWT: create_access_token, create_refresh_token, verify_password, get_password_hash
│   │   ├── time_utils.py              # (15 líneas) to_chile_timezone(), CHILE_TZ = America/Santiago
│   │   └── token_blacklist.py         # (49 líneas) TTLCache-based token revocation por jti, maxsize=10000
│   │
│   ├── db/                             # Configuración de base de datos
│   │   ├── base.py                    # (5 líneas) SQLAlchemy DeclarativeBase
│   │   ├── models.py                  # (33 líneas) Import de todos los modelos para Alembic metadata
│   │   └── session.py                 # (87 líneas) AsyncSession factory, init_db() idempotente con PostGIS+pgvector extensions
│   │                                  #   y BASE_CATEGORIES (15 categorías con IDs fijos)
│   │
│   ├── models/                         # Entidades ORM (16 archivos, uno por entidad)
│   │   ├── __init__.py                # (5 líneas) Vacío
│   │   ├── user.py                    # (56 líneas) User: email, password_hash, role, display_name, avatar_url, timestamps
│   │   ├── tourist_profile.py         # (45 líneas) TouristProfile: full_name, interests_embedding Vector(1536), has_own_transport, system_preferences
│   │   ├── entrepreneur_profile.py    # (45 líneas) EntrepreneurProfile: rut, business_name, description, verification_status, admin_data
│   │   ├── poi.py                     # (76 líneas) POI: name, description, description_embedding Vector(1536), location Geometry(POINT,4326),
│   │   │                              #   address, contact_info, multimedia_urls, source, verification_status, categories, timestamps
│   │   ├── poi_category.py            # (32 líneas) POICategory: bridge table POI↔Category
│   │   ├── category.py                # (31 líneas) Category: id, name, icon_url, parent_id (self-referential)
│   │   ├── review.py                  # (47 líneas) Review: rating_stars (1-5), text_content, embedding Vector(1536), tourist_id, poi_id
│   │   │                              #   UniqueConstraint(tourist_id, poi_id)
│   │   ├── bookmark.py                # (40 líneas) Bookmark: tourist_id, poi_id, UniqueConstraint(tourist_id, poi_id)
│   │   ├── itinerary.py               # (55 líneas) Itinerary: title, status, start_date, end_date, public_id, steps
│   │   ├── itinerary_step.py          # (53 líneas) ItineraryStep: step_order, poi_id, arrival_time, departure_time, ai_context, visited
│   │   ├── ara_session.py             # (102 líneas) AraSession: status (9 valores), initial_query, location Geometry, radius, dates,
│   │   │                              #   intent_data, preferences_data, candidate_poi_ids UUID[], generated_itinerary_id, version
│   │   ├── ara_message.py             # (39 líneas) AraMessage: role (user|assistant|system), content, quick_replies JSONB, metadata JSONB
│   │   ├── conversation_memory.py     # (40 líneas) ConversationMemory: hecho, categoria, confianza, embedding Vector(1536), contexto, expires_at
│   │   ├── entrepreneur_post.py       # (54 líneas) EntrepreneurPost: title, content, status, sort_order, pinned, poi_id
│   │   └── poi_visit.py               # (47 líneas) POIVisit: tourist_id, poi_id, visited_at, source, note
│   │
│   ├── repositories/                   # Acceso a datos (9 archivos)
│   │   ├── base.py                    # (16 líneas) BaseRepository con _commit_or_rollback() genérico
│   │   ├── user_repository.py         # (158 líneas) UserRepository: get_by_email, get_by_id, create_tourist_user, create_entrepreneur_profile, update
│   │   ├── poi_repository.py          # (485 líneas) POIRepository: create, get_by_id, search_geo, search_hybrid, get_pois_by_ids, get_by_owner
│   │   ├── review_repository.py       # (159 líneas) ReviewRepository: create, get_by_poi, get_summary (SQL AVG/COUNT/FILTER), update, delete
│   │   ├── bookmark_repository.py     # (106 líneas) BookmarkRepository: create, list, delete
│   │   ├── itinerary_repository.py    # (884 líneas) ItineraryRepository: CRUD itinerario+steps, share, export, visitas, create_generated_itinerary
│   │   ├── entrepreneur_repository.py # (352 líneas) EntrepreneurRepository: metrics (1 query), analytics (3 queries), posts CRUD, activity feed
│   │   ├── ara_repository.py          # (179 líneas) AraRepository: sessions CRUD, messages CRUD, update_session_context, commit_or_rollback
│   │   └── utils.py                   # (106 líneas) get_category_ids_batch() (anti N+1), build_poi_response_from_row()
│   │
│   ├── schemas/                        # Contratos Pydantic v2 (18 archivos)
│   │   ├── auth.py                    # (14 líneas) RegisterRequest, LoginRequest
│   │   ├── token.py                   # (19 líneas) Token, TokenPayload (sub, type, iss, jti), RefreshTokenRequest
│   │   ├── user.py                    # (33 líneas) UserCreate, UserUpdate, UserResponse
│   │   ├── tourist_profile.py         # (26 líneas) TouristProfileCreate, TouristProfileUpdate, TouristProfileResponse
│   │   ├── entrepreneur_profile.py    # (23 líneas) EntrepreneurProfileCreate (RUT pattern), EntrepreneurProfileResponse
│   │   ├── entrepreneur.py            # (121 líneas) EntrepreneurDashboardResponse, EntrepreneurPost schemas, AnalyticsResponse
│   │   ├── poi.py                     # (68 líneas) POICreate, POIUpdate, POIResponse, POISearchRequest
│   │   ├── review.py                  # (33 líneas) ReviewCreate, ReviewUpdate, ReviewResponse, ReviewSummary
│   │   ├── bookmark.py                # (18 líneas) BookmarkCreate, BookmarkResponse
│   │   ├── category.py                # (9 líneas) CategoryResponse
│   │   ├── itinerary.py               # (187 líneas) GenerateItineraryRequest, GeneratedItinerary, ItineraryResponse, ItineraryExportResponse, etc.
│   │   ├── ara.py                     # (155 líneas) AraSessionCreate, AraSessionResponse, AraMessageCreate, AraMessagesResponse,
│   │   │                              #   AraQuickReply, AraIntentInfo, AraPreferenceSummary, AraCandidatePOI, AraGenerateItineraryRequest
│   │   ├── ara_comprehension.py       # (87 líneas) ComprehensionResult, AraIntent, AraEntity, MemoryFact, QuickReplySuggestion,
│   │   │                              #   ExtractedEntity, DateRange, ToolExecutionResult
│   │   ├── geocoding.py               # (12 líneas) GeocodingResult, GeocodingSearchRequest
│   │   ├── weather.py                 # (25 líneas) WeatherDailyForecast, WeatherForecastResponse
│   │   └── media.py                   # (implícito en endpoints/media.py)
│   │
│   └── services/                       # Lógica de negocio + IA (33 archivos)
│       │
│       ├── embedding_service.py       # (101 líneas) OpenAIEmbeddingService (text-embedding-3-small),
│       │                               #   GlobalEmbeddingCache (TTL 900s, double-checked locking con asyncio.Lock),
│       │                               #   EmbeddingCache (request-scoped), get_embedding_service()
│       ├── llm_service.py             # (232 líneas) ItineraryGenerator (DeepSeek deepseek-chat),
│       │                               #   generate_itinerary() con stream opcional, _normalize_itinerary_payload() (legacy days→steps),
│       │                               #   _normalize_step_poi_ids() con fuzzy matching por nombre
│       ├── geo_service.py             # (14 líneas) distance_meters() — fórmula Haversine
│       ├── geocoding_service.py       # (52 líneas) search_places() — Nominatim forward geocoding
│       ├── weather_service.py         # (218 líneas) get_forecast() — OpenWeatherMap 5-day forecast,
│       │                               #   TTLCache 30 min, selección de bloque representativo (más cercano al mediodía)
│       ├── image_service.py           # (61 líneas) save_image() — validación de magic bytes JPG/PNG, max 5MB, UUID4 filename
│       ├── poi_metadata_extractor.py  # (396 líneas) ExtractedMetadata dataclass, HTMLParser para OSM metadata,
│       │                               #   parse_opening_hours(), extracción de servicios, acceso, horarios en español
│       ├── poi_search_service.py      # (345 líneas) search_candidate_pois(), search_generation_context_with_fallbacks(),
│       │                               #   filter_pois_to_search_center(), is_strict_destination_context(),
│       │                               #   wants_expanded_destination_scope(), inherits_strict_destination_context()
│       ├── review_enrichment_service.py # (65 líneas) enrich_review_with_embedding(), update_tourist_interests_embedding() (profile*0.9 + review*0.1)
│       │
│       ├── ara_itinerary_core.py      # (282 líneas) UNIFIED itinerary generation pipeline — 7 fases secuenciales
│       │                               #   generate_itinerary_core() con on_phase callback pattern
│       ├── ara_streaming_service.py   # (179 líneas) SSE wrapper stream_itinerary_generation() alrededor de ara_itinerary_core
│       │                               #   Manejo de CancelledError (marca itinerary como abandoned)
│       ├── ara_conversation_orchestrator.py # (110 líneas) Thin HTTP adapter: create_session_v2(), handle_message_v2()
│       │                               #   Delega a ConversationProcessor, manejo de replacement_context
│       ├── ara_message_normalizer.py  # (19 líneas) normalize_message() — Unicode NFKD + typo replacement de ara_constants
│       ├── ara_preference_merger.py   # (224 líneas) Extracción de preferencias de mensajes:
│       │                               #   _extract_negative_constraints(), _extract_positive_preferences(),
│       │                               #   _estimate_route_ready_score(), compact_constraints(), merge_preferences()
│       ├── ara_replacement_service.py # (102 líneas) build_step_replacement_context(),
│       │                               #   search_step_replacement_alternatives() usando búsqueda semántica
│       ├── ara_response_builder.py    # (464 líneas) build_quick_replies(), build_refined_query(),
│       │                               #   dedupe_quick_replies(), should_offer_create_itinerary(),
│       │                               #   build_poi_cards(), formateo de respuestas Ara
│       ├── ara_trip_draft_builder.py  # (433 líneas) Construcción de trip_draft desde preferencias:
│       │                               #   _build_trip_days(), extract_route_locations(), update_trip_draft(),
│       │                               #   WEEKDAY_NAMES, DAY_ORDINAL_ALIASES, WEEKDAY_ALIASES
│       │
│       └── ara_v2/                     # Subsistema Ara v2 (10 archivos)
│           ├── __init__.py            # (0 líneas) Vacío
│           ├── conversation_processor.py # (662 líneas) ConversationProcessor: orquestador principal.
│           │                           #   process_user_message() con flujo de 10 pasos: memoria→comprensión→hechos→herramientas→respuesta.
│           │                           #   update_session_intent() para cambios de UI. _build_trip_draft_context(),
│           │                           #   _apply_comprehension_to_session(), _filter_resolved_pending_questions(),
│           │                           #   _detect_lodging_preference(), _build_preference_summary(), get_conversation_processor()
│           ├── tool_orchestrator.py   # (663 líneas) ToolOrchestrator: motor de ejecución de herramientas.
│           │                           #   execute() rutea según herramientas_necesarias: search_pois, build_itinerary,
│           │                           #   answer_question, replace_step, geocode_destination, update_preferences,
│           │                           #   generate_trip_draft, show_options, confirm_plan, review_memories, consolidate_memories.
│           │                           #   _resolve_poi_reference(), _handle_step_replacement(), _remember_selected_poi()
│           ├── comprehender.py        # (208 líneas) Comprensor: wrapper GPT-4o-mini con JSON schema estricto.
│           │                           #   comprehend() con sanitize_user_message() y detect_prompt_injection().
│           │                           #   Fallback a fallback_comprehend() si el LLM falla (timeout, API error, parse error)
│           ├── comprehension_fallback.py # (185 líneas) fallback_comprehend() — reglas deterministas por keywords y patrones.
│           │                               #   Detección de build_itinerary, search_pois, answer_question, preferencias.
│           │                               #   Categorías: naturaleza, gastronomía, cultura, aventura, alojamiento, termas.
│           ├── response_generator.py  # (381 líneas) ResponseGenerator: genera respuestas naturales con GPT-4o-mini.
│           │                           #   _generate_search_response(), _generate_itinerary_response(),
│           │                           #   _generate_clarify_response(), _build_quick_replies(), _contextual_quick_replies().
│           │                           #   Catálogo de fallbacks por status: generate, search, respond, clarify, replace, error.
│           ├── answer_service.py      # (133 líneas) answer_question() — responde preguntas sobre POIs usando LLM
│           │                           #   con contexto enriquecido (descripción, horarios, servicios, reviews)
│           ├── prompt_manager.py      # (187 líneas) Sistema de prompts: build_comprehension_prompt() y build_generation_prompt().
│           │                           #   _COMPREHENSION_SYSTEM: reglas de extracción de intenciones, entidades, memoria, modos (auto/mixto/guiado).
│           │                           #   _GENERATION_SYSTEM: reglas de generación de itinerarios (3-6 actividades/día, distancias, clima)
│           ├── memory_service.py      # (185 líneas) MemoryService: CRUD de memoria semántica con embeddings.
│           │                           #   store_fact(), store_facts_batch() (batch embedding), retrieve_relevant_facts() (HNSW),
│           │                           #   update_tourist_profile_embedding(), delete_memory(), consolidate_memories().
│           │                           #   Aislamiento estricto por tourist_id.
│           ├── category_mapping.py    # (42 líneas) CATEGORY_INTENT_TO_DB_NAMES: mapeo de intents del compresor
│           │                           #   (ej: "gastronomía"→["Gastronomía"]) a nombres canónicos de DB.
│           │                           #   DB_NAME_TO_INTENTS: mapeo inverso para debugging.
│           ├── geocoding_service.py   # (124 líneas) geocode_destination() — resuelve nombres de destino a coordenadas.
│           │                           #   3 niveles: cache en memoria → GPT-4o-mini → hardcoded fallback (52 destinos de La Araucanía)
│           └── utils.py               # (30 líneas) get_gpt_mini_client() — singleton AsyncOpenAI para GPT-4o-mini
│                                      #   con timeout de settings.gpt_mini_timeout_seconds
│
├── migrations/                        # Alembic (20 migraciones)
│   ├── env.py                         # Entorno de Alembic
│   ├── README                         # Documentación de migraciones
│   ├── script.py.mako                 # Template de migraciones
│   └── versions/
│       ├── 13e4146989e2_initial_schema_with_dynamic_vector_.py
│       ├── 088edfdc10c4_add_constraints_timestamps_and_.py
│       ├── 9f4a1b2c3d4e_add_poi_visit_rules_and_extended_categories.py
│       ├── a1b2c3d4e5f6_add_frontend_sync_features.py
│       ├── a7b8c9d0e1f2_ara_location_and_candidate_uuid_array.py
│       ├── b2c3d4e5f6a7_add_ara_conversation_sessions.py
│       ├── b8c9d0e1f2a3_fix_ara_sessions_status_constraint.py
│       ├── c3d4e5f6a7b8_add_poi_posts_and_analytics_fields.py
│       ├── c9d0e1f2a3b4_add_gist_index_pois_location.py
│       ├── d0e1f2a3b4c5_add_ara_sessions_version_column.py
│       ├── d4e5f6a7b8c9_add_entrepreneur_post_sort_order.py
│       ├── d5e1f2a3b4c5_normalize_poi_multimedia_urls_to_dict.py
│       ├── e2f3a4b5c6d7_add_timestamps_to_itinerary_steps.py
│       ├── e5f6a7b8c9d0_add_verification_confidence_and_rut_fields.py
│       ├── f3a4b5c6d7e8_add_itinerary_public_id.py
│       ├── f6a7b8c9d0e1_add_unique_constraint_review_tourist_poi.py
│       ├── g4a5b6c7d8e9_add_note_column_to_poi_visits.py
│       ├── h5a6b7c8d9e0_make_review_text_content_nullable.py
│       ├── i6a7b8c9d0e1_add_conversation_memory.py
│       ├── j1k2l3m4n5o6_add_parent_id_to_categories.py
│       └── 82d1bcc33432_fix_poi_description_embedding_openai_1536.py
│
├── scripts/                           # Scripts de datos y mantenimiento (14 scripts)
│   ├── init_db.sql                    # Bootstrap SQL de la base de datos
│   ├── seed_categories.py             # Seeder de categorías base (idempotente, IDs fijos)
│   ├── create_vector_indices.py       # Creación de índice HNSW en pois.description_embedding
│   ├── import_osm_data.py             # Importación masiva de POIs desde OpenStreetMap/Overpass
│   ├── recategorize_pois.py           # Recategorización de POIs existentes
│   ├── apply_poi_quality_fixes.py     # Correcciones de calidad automáticas sobre POIs
│   ├── audit_poi_quality.py           # Auditoría de calidad de POIs (genera poi_issues.jsonl)
│   ├── deduplicate_pois.py            # Deduplicación de POIs duplicados
│   ├── enrich_poi_metadata.py         # Enriquecimiento de metadata de POIs
│   ├── import_conaf_data.py           # Importación de datos de CONAF (parques nacionales)
│   ├── quality_snapshot.py            # Snapshot de calidad de datos
│   ├── rewrite_descriptions_with_llm.py # Reescritura de descripciones con LLM
│   ├── run_full_pipeline.py           # Pipeline completo de ingesta y enriquecimiento
│   └── scrape_conaf_parks.py          # Scraping de parques nacionales de CONAF
│
├── tests/                             # Suite de tests (14 archivos de test, 179 test functions)
│   ├── conftest.py                    # Fixtures compartidos: async_client, db_session, auth_headers
│   ├── __init__.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_rut.py                # (19 tests) Validación de RUT chileno módulo 11
│   │   ├── test_security.py           # (11 tests) JWT y hashing de contraseñas
│   │   ├── test_poi_metadata_extractor.py # (41 tests) Extracción de metadata OSM
│   │   ├── test_repository_base.py    # (2 tests) BaseRepository commit/rollback
│   │   └── ara_v2/
│   │       ├── __init__.py
│   │       ├── test_prompt_manager.py         # (8 tests) Comprehension + generation prompts
│   │       ├── test_comprehender.py           # (29 tests) Comprensor LLM + fallback
│   │       ├── test_memory_service.py         # (6 tests) store_fact, store_facts_batch
│   │       ├── test_response_generator.py     # (14 tests) Generación de respuestas
│   │       ├── test_tool_orchestrator.py      # (12 tests) Ejecución de herramientas
│   │       ├── test_memory_integration.py     # (8 tests) Integración de memoria
│   │       └── test_itinerary_payload_normalization.py # (3 tests) Normalización de payload
│   ├── api/
│   │   ├── test_auth.py               # (4 tests) Endpoints de autenticación
│   │   └── test_itineraries.py        # (10 tests) Endpoints de itinerarios
│   └── e2e/
│       ├── __init__.py
│       └── test_ara_v2_flow.py        # (12 tests) Flujo conversacional Ara v2 end-to-end
│
├── docker-compose.yml                 # Servicios: db (PostgreSQL 16 + pgvector + PostGIS) + api (FastAPI)
├── Dockerfile                         # Imagen de la API
├── Dockerfile.db                      # Imagen de la base de datos
├── .dockerignore
├── .env                               # Variables de entorno (no commiteado)
├── .env.example                       # Template de variables de entorno
├── .gitignore
├── alembic.ini                        # Configuración de Alembic
├── pyproject.toml                     # Configuración de pytest y dependencias
├── requirements.txt                   # Dependencias Python
├── media/                             # Directorio de imágenes servidas
│   └── .gitkeep
├── regions/
│   └── araucania.json                 # Datos geográficos de La Araucanía
├── data/
│   └── conaf_protected_areas.json     # Datos de áreas protegidas CONAF
├── pipeline_state.json               # Estado del pipeline de ingesta
├── poi_issues.jsonl                   # Issues de calidad de POIs (generado por audit_poi_quality.py)
└── audit_poi_quality.jsonl            # Resultados de auditoría
```

---

## 4. API REST — Catálogo Completo de Endpoints

**Base URL:** `/api/v1`

### 4.1 Autenticación (`/api/v1/auth`)

| Método | Ruta | Auth | Rate Limit | Handler | Descripción |
|--------|------|------|------------|---------|-------------|
| POST | `/register` | No | — | `register_tourist_user` | Registro de turista con perfil |
| POST | `/login` | No | 5/min | `login` | Login, retorna JWT access + refresh |
| POST | `/refresh` | No | — | `refresh_token` | Intercambia refresh token por nuevo par |
| POST | `/logout` | Bearer | — | `logout` | Revoca access token por jti (204 No Content) |

**Formato JWT (tanto access como refresh):**
```json
{
  "sub": "<user_id>",
  "type": "access|refresh",
  "iat": 1716840000,
  "jti": "<uuid>",
  "iss": "ruta-viva",
  "exp": 1716843600
}
```

- `sub`: UUID del usuario
- `type`: "access" o "refresh" — validado en deps.py y refresh endpoint
- `iat`: Issued at (epoch)
- `jti`: JWT ID único para blacklist en logout
- `iss`: Fijo "ruta-viva" — validado en `deps.py` (get_current_user y get_optional_current_user)
- `exp`: 1 hora para access token (60 min), 7 días para refresh token (10080 min)

### 4.2 Usuarios (`/api/v1/users`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/me` | Sí | Perfil del usuario autenticado con tourist_profile y entrepreneur_profile |
| PATCH | `/me` | Sí | Editar email, avatar, display_name |
| PUT | `/me/tourist-profile` | Sí | Actualizar perfil turista (full_name, has_own_transport, system_preferences) |
| POST | `/me/entrepreneur-profile` | Sí | Activar perfil emprendedor (RUT chileno validado, admin_data) |
| DELETE | `/me/tourist-profile/interests` | Sí | Resetear perfil semántico (interests_embedding a NULL) |

### 4.3 POIs (`/api/v1/pois`)

| Método | Ruta | Auth | Rate Limit | Descripción |
|--------|------|------|------------|-------------|
| POST | `/` | Sí (emprendedor) | 5/h + 10/d (DB) | Crear POI con embedding y geometría |
| GET | `/mine` | Sí (emprendedor) | — | POIs propios del emprendedor |
| GET | `/search` | No | 30/min | Búsqueda geoespacial por radio (PostGIS ST_DWithin) |
| GET | `/semantic-search` | Opcional | 10/min | Búsqueda híbrida semántica + geo |
| GET | `/{poi_id}` | No | — | Detalle de POI con categorías |
| GET | `/{poi_id}/posts` | No | — | Posts públicos del POI |
| POST | `/{poi_id}/visit` | Opcional | — | Registrar visita al POI |
| PATCH | `/{poi_id}/media` | Sí (owner) | — | Agregar imagen al POI (multimedia_urls) |
| PUT | `/{poi_id}` | Sí (owner) | — | Actualizar POI (owner only) |
| DELETE | `/{poi_id}` | Sí (owner) | — | Eliminar POI (owner only) |

**Búsqueda semántica personalizada:**
```
# Búsqueda normal
score = (query_distance * 0.7) + (profile_distance * 0.3)

# Dentro de generación de itinerario (profile_weight=0.1)
score = (query_distance * 0.9) + (profile_distance * 0.1)
```

### 4.4 Reviews (`/api/v1/reviews`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/` | Sí | Crear review (con embedding en background + actualización de perfil dinámico) |
| GET | `/poi/{poi_id}` | No | Reviews de un POI (con author_name por selectinload) |
| GET | `/poi/{poi_id}/summary` | No | Agregado SQL: count, avg, distribución por rating |
| PUT | `/{review_id}` | Sí (owner) | Editar review propia |
| DELETE | `/{review_id}` | Sí (owner) | Eliminar review propia |

**Perfil dinámico del turista:**
```
nuevo_perfil = (perfil_actual * 0.9) + (embedding_review * 0.1)
```
- 90% conserva historial, 10% incorpora nueva review
- Actualización dimensión por dimensión (1536 floats)
- Reviews sin embedding (error OpenAI) se guardan pero no actualizan perfil

### 4.5 Itinerarios (`/api/v1/itineraries`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | Sí | Listar itinerarios propios (paginado) |
| POST | `/generate` | Sí | Generar itinerario con LLM + clima (usa ara_itinerary_core) |
| GET | `/{itinerary_id}` | Sí (owner) | Obtener itinerario con steps y POIs (selectinload anidado) |
| DELETE | `/{itinerary_id}` | Sí (owner) | Eliminar itinerario |
| GET | `/{itinerary_id}/pois` | Sí (owner) | POIs del itinerario |
| POST | `/{itinerary_id}/steps` | Sí (owner) | Agregar step manual |
| PATCH | `/{itinerary_id}/steps/{step_id}` | Sí (owner) | Actualizar step |
| DELETE | `/{itinerary_id}/steps/{step_id}` | Sí (owner) | Eliminar step |
| PATCH | `/{itinerary_id}/steps/reorder` | Sí (owner) | Reordenar steps |
| PATCH | `/{itinerary_id}/steps/reorder-with-times` | Sí (owner) | Reordenar con horarios |
| PATCH | `/{itinerary_id}/steps/{step_id}/reschedule` | Sí (owner) | Reprogramar step |
| PATCH | `/{itinerary_id}/status` | Sí (owner) | Cambiar estado (draft→active→completed→archived) |
| GET | `/{itinerary_id}/weather` | Sí (owner) | Pronóstico para steps del itinerario |
| GET | `/{itinerary_id}/export` | Sí (owner) | Exportar datos del itinerario |
| POST | `/{itinerary_id}/share` | Sí (owner) | Generar link público (public_id UUID) |
| DELETE | `/{itinerary_id}/share` | Sí (owner) | Revocar link público |
| POST | `/{itinerary_id}/steps/{step_id}/visit` | Sí | Marcar step como visitado |
| GET | `/{itinerary_id}/visits` | Sí | Visitas del itinerario |

### 4.6 Ara — Asistente Conversacional (`/api/v1/ara`)

| Método | Ruta | Auth | Rate Limit | Handler | Descripción |
|--------|------|------|------------|---------|-------------|
| POST | `/sessions` | Sí (tourist) | 5/min | `create_session_v2()` | Crear sesión conversacional + procesar primer mensaje (v2: conversation_processor) |
| POST | `/sessions/{session_id}/messages` | Sí (tourist) | 10/min | `handle_message_v2()` | Enviar mensaje y recibir respuesta (v2: conversation_processor) |
| GET | `/sessions/{session_id}/messages` | Sí (tourist) | — | `get_session_messages()` | Obtener historial de mensajes |
| PATCH | `/sessions/{session_id}/intent` | Sí (tourist) | — | `update_session_intent()` | Actualizar intent desde UI (destino, fechas, pace, intereses) |
| POST | `/sessions/{session_id}/generate-itinerary/stream` | Sí (tourist) | 3/min | `stream_generate_itinerary()` | **SSE streaming** de generación de itinerario |

**Formato SSE del streaming:**
```
event: status
data: {"phase": "searching", "message": "Buscando lugares..."}

event: warning
data: {"message": "Encontré pocos puntos de interés...", "poi_count": 3, "action": "expand_search"}

event: status
data: {"phase": "generating", "message": "Armando tu itinerario con IA..."}

event: result
data: {"session_id": "...", "status": "completed", "itinerary": {...}}
```

**Roles permitidos en Ara:** Solo usuarios con perfil turista. `_ensure_tourist()` verifica en cada endpoint.

**Eventos SSE posibles:** `status`, `warning`, `result`, `error`

### 4.7 Bookmarks (`/api/v1/bookmarks`)

| Método | Ruta | Auth | Rate Limit | Descripción |
|--------|------|------|------------|-------------|
| POST | `/` | Sí | — | Crear bookmark de un POI |
| GET | `/` | Sí | — | Listar bookmarks del usuario |
| DELETE | `/{bookmark_id}` | Sí | — | Eliminar bookmark propio |

**Request (POST):** `{"poi_id": "uuid"}`
**Response:** `{"id": "uuid", "poi_id": "uuid", "tourist_id": "uuid", "created_at": "iso8601"}`
**Implementación:** `app/api/v1/endpoints/bookmarks.py` (69 líneas). Handlers delgados que delegan a `BookmarkRepository` (106 líneas). Unique constraint en DB evita bookmarks duplicados.

### 4.8 Categorías (`/api/v1/categories`)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | No | Listar las 15 categorías base con parent_id |

**Response:** `[{"id": 1, "name": "Naturaleza", "icon_url": null, "parent_id": null}, ...]`
**Implementación:** `app/api/v1/endpoints/categories.py` (16 líneas). Query simple al modelo Category que es self-referential (parent_id → Category.id). Las categorías base se crean en `init_db()` con IDs fijos (1-15). Soporta jerarquía de dos niveles: parent (ej: Naturaleza) → children (ej: Trekking/Senderismo, Lagos/Ríos/Playas, etc.).

### 4.9 Otros Endpoints

**Emprendedor (`/api/v1/entrepreneur`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/me/metrics` | Sí (emprendedor) | Dashboard: total POIs, visits, reviews, bookmarks, income (1 query) |
| GET | `/me/income` | Sí (emprendedor) | Ingresos (stub) |
| GET | `/me/posts` | Sí (emprendedor) | Listar posts propios |
| POST | `/me/posts` | Sí (emprendedor) | Crear post |
| PATCH | `/me/posts/{post_id}` | Sí (emprendedor) | Actualizar post |
| DELETE | `/me/posts/{post_id}` | Sí (emprendedor) | Eliminar post |
| GET | `/pois/{poi_id}/analytics` | Sí (owner) | Analytics detallado: visits con FILTER, reviews, bookmarks (3 queries) |
| GET | `/pois/{poi_id}/activity` | Sí (owner) | Feed de actividad con selectinload en bookmarks.tourist |

**Geocoding (`/api/v1/geocoding`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/search?q=...&lat=...&lon=...` | No | Nominatim forward geocoding (viewbox opcional) |

**Clima (`/api/v1/weather`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/forecast?lat=...&lon=...&start=...&end=...` | No | OpenWeatherMap 5-day forecast (cache TTLCache 30 min) |

**Media (`/api/v1/media`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/upload` | Sí | Subir imagen (JPG/PNG, max 5MB, magic bytes validation, UUID4 filename) |

**Bookmarks (`/api/v1/bookmarks`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/` | Sí (tourist) | Crear bookmark |
| GET | `/` | Sí (tourist) | Listar bookmarks propios |
| DELETE | `/{bookmark_id}` | Sí (owner) | Eliminar bookmark |

**Categorías (`/api/v1/categories`):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | No | Listar todas las categorías |

**Root level (fuera de /api/v1):**
| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/health` | No | Health check con `SELECT 1` |
| GET | `/share/{public_id}` | No | Itinerario compartido público (usando public_id) |
| GET | `/media/{filename}` | Bearer | Servir archivo de imagen (JWT requerido, path traversal protection) |

**Endpoints eliminados (auditoría 2026-05-27):**
- `POST /ara/sessions/{id}/generate-itinerary` — Sync, reemplazado por SSE streaming
- `POST /ara/sessions/{id}/generate-itinerary/async` — Async, reemplazado por SSE streaming

### 4.10 Detalle de Schemas por Endpoint

**Auth Endpoints:**
- `POST /auth/register` → Request: `RegisterRequest(user: UserCreate, profile: TouristProfileCreate)` → Response: `UserResponse` (201)
- `POST /auth/login` → Request: `LoginRequest(email, password)` → Response: `Token(access_token, token_type="bearer", refresh_token)` (200)
- `POST /auth/refresh` → Request: `RefreshTokenRequest(refresh_token)` → Response: `Token` (200)
- `POST /auth/logout` → Request: Bearer token → Response: None (204 No Content)

**Ara Session Schemas:**
- `POST /ara/sessions` → Request: `AraSessionCreate(initial_message, lat?, lon?, radius=5000, start_date?, end_date?, metadata?)` → Response: `AraSessionResponse` (201)
  - Validación Pydantic: end_date >= start_date, trip_days <= 7, lat/lon deben venir juntos
  - metadata.intent = "change_itinerary_step" requiere metadata.itinerary_id y metadata.step_id
- `POST /ara/sessions/{id}/messages` → Request: `AraMessageCreate(message, start_date?, end_date?)` → Response: `AraSessionResponse` (200)
- `PATCH /ara/sessions/{id}/intent` → Request: `AraIntentUpdate(destination?, start_date?, end_date?, pace?, interests?)` → Response: `AraSessionResponse` (200)
- `POST /ara/sessions/{id}/generate-itinerary/stream` → Request: `AraGenerateItineraryRequest(final_instruction?)` → Response: `StreamingResponse(text/event-stream)` (200)

**AraSessionResponse incluye:** session_id, status, start_date, end_date, user_message, assistant_message, quick_replies, intent (AraIntentInfo), preferences (AraPreferenceSummary), candidate_pois, weather, progress

**AraPreferenceSummary incluye:** tags, positive_preferences, negative_constraints, completed_dimensions, trip_draft, destination_scope, selected_poi_ids, conversation_mode, route_ready_score, lodging, day_focus

**Itinerary Schemas:**
- `POST /itineraries/generate` → Request: `GenerateItineraryRequest(query, lat, lon, radius, start_date, end_date)` → Response: `ItineraryResponse` (con steps y POIs anidados)
- `GET /itineraries/{id}/export` → Response: `ItineraryExportResponse` (misma estructura que el endpoint público `/share/{public_id}`)

### 4.11 Detalle del Endpoint de Streaming SSE

**Endpoint:** `POST /ara/sessions/{session_id}/generate-itinerary/stream`
**Rate limit:** 3/min
**Auth:** Bearer token (solo usuarios tourist)
**Content-Type:** `text/event-stream`
**Payload opcional:** `{"final_instruction": "Quiero más naturaleza"}`

**Eventos emitidos:**

| Evento | Campos | Cuándo se emite |
|--------|--------|-----------------|
| `status` | `phase`, `message` | Cada fase del pipeline (validating, searching, weather, generating, repairing, saving) |
| `warning` | `message`, `poi_count`, `action` | Si searching encontró < 5 POIs (action="expand_search") |
| `result` | `session_id`, `status`, `itinerary` | Pipeline completado exitosamente |
| `error` | `message` | Error en cualquier fase (validación, LLM, clima, etc.) |

**Comportamiento del cliente:**
- Si recibe `warning`, debe mostrar el mensaje y ofrecer opción de expandir búsqueda
- Si recibe `error`, debe mostrar el mensaje al usuario
- Si recibe `result`, debe navegar al itinerario generado
- Si el cliente cierra la conexión (CancelledError), el backend marca el itinerario como `abandoned`

**Implementación:** `app/services/ara_streaming_service.py:36` → `stream_itinerary_generation()`
- Crea `asyncio.Queue` para eventos
- `_on_phase` callback encola eventos
- `_run_core()` ejecuta `generate_itinerary_core()` en un `asyncio.Task`
- Loop principal: `event_queue.get()` con timeout 1s, yield en formato SSE
- Al recibir `result` o `error`, rompe el loop y drena eventos restantes
- `CancelledError` → marca itinerary como abandoned en una nueva AsyncSession

---

## 5. Modelo de Datos

### 5.1 Diagrama de Entidades

```
User (1)
  ├── TouristProfile (1)
  │     ├── Review (N) ────────────── POI (1)
  │     ├── Bookmark (N) ──────────── POI (1)
  │     ├── Itinerary (N)
  │     │     └── ItineraryStep (N) ── POI (1)
  │     ├── AraSession (N)
  │     │     └── AraMessage (N)
  │     ├── ConversationMemory (N)
  │     └── POIVisit (N) ──────────── POI (1)
  │
  └── EntrepreneurProfile (1)
        └── POI (N)
              ├── POICategory (N) ──── Category (1)
              │     └── Category.parent_id → Category (self-referential)
              └── EntrepreneurPost (N)
```

### 5.2 Detalle de Constraints por Entidad

**User (`models/user.py`, 56 líneas):**
- `id`: UUID PK
- `email`: String, unique, index
- `password_hash`: String
- `role`: String, CHECK IN ('tourist', 'entrepreneur')
- `display_name`: String, nullable
- `avatar_url`: String, nullable
- `is_active`: Boolean, default True
- `created_at`: DateTime(timezone=True)
- `updated_at`: DateTime(timezone=True), onupdate
- Relaciones: `tourist_profile` (one-to-one), `entrepreneur_profile` (one-to-one)

**TouristProfile (`models/tourist_profile.py`, 45 líneas):**
- `user_id`: UUID PK/FK → users.id, ondelete CASCADE
- `full_name`: String(255)
- `interests_embedding`: Vector(1536), nullable — actualizado dinámicamente por reviews
- `has_own_transport`: Boolean, default False — influye en generación de itinerarios
- `system_preferences`: JSONB, nullable — preferencias de sistema (idioma, notificaciones, etc.)
- Relaciones: `user` (back_populates), `reviews`, `bookmarks`, `itineraries`, `ara_sessions`, `poi_visits`

**EntrepreneurProfile (`models/entrepreneur_profile.py`, 45 líneas):**
- `user_id`: UUID PK/FK → users.id, ondelete CASCADE
- `rut`: String, nullable — validado con `validate_rut()` (módulo 11 chileno)
- `business_name`: String, nullable
- `description`: Text, nullable
- `verification_status`: String, default "unverified" — CHECK IN ('unverified', 'pending', 'verified', 'rejected')
- `admin_data`: JSONB, nullable — datos administrativos flexibles
- `created_at`: DateTime(timezone=True)
- `updated_at`: DateTime(timezone=True), onupdate
- Relaciones: `user` (back_populates), `pois`

**POI (`models/poi.py`, 76 líneas):**
- `id`: UUID PK
- `owner_id`: UUID FK → entrepreneur_profiles.user_id
- `name`: String, not null
- `description`: Text, nullable
- `description_embedding`: Vector(1536) — generado automáticamente al crear/actualizar
- `location`: Geometry("POINT", srid=4326) — índice GiST
- `address`: String, nullable
- `contact_info`: JSONB, nullable — teléfono, email, website, redes sociales
- `multimedia_urls`: JSONB, nullable — dict con URLs de imágenes y videos
- `source`: String, CHECK IN ('manual', 'osm', 'ai_generated')
- `verification_status`: String, default "unverified"
- `access_type`: String, nullable
- `metadata`: JSONB, nullable — horarios, precios, servicios (de poi_metadata_extractor)
- `created_at`, `updated_at`: DateTime(timezone=True)
- Relaciones: `owner` (back_populates), `categories` (via POICategory bridge), `reviews`, `bookmarks`, `itinerary_steps`, `entrepreneur_posts`, `poi_visits`

**Category (`models/category.py`, 31 líneas):**
- `id`: Integer PK (IDs fijos 1-15 para categorías base)
- `name`: String, not null
- `icon_url`: String, nullable
- `parent_id`: Integer FK → categories.id, nullable — self-referential para jerarquía
- Relaciones: `parent` (self-ref), `children` (self-ref), `pois` (via POICategory)

**Review (`models/review.py`, 47 líneas):**
- `id`: UUID PK
- `tourist_id`: UUID FK → tourist_profiles.user_id
- `poi_id`: UUID FK → pois.id
- `rating_stars`: Integer, CHECK BETWEEN 1 AND 5
- `text_content`: Text, nullable (se hizo nullable en migración h5a6b7c8d9e0)
- `embedding`: Vector(1536), nullable — generado asíncronamente en background
- `created_at`, `updated_at`: DateTime(timezone=True)
- Constraints: `UniqueConstraint(tourist_id, poi_id)` — un turista solo puede tener una review por POI
- Relaciones: `tourist` (back_populates), `poi` (back_populates)

**Itinerary (`models/itinerary.py`, 55 líneas):**
- `id`: UUID PK
- `tourist_id`: UUID FK → tourist_profiles.user_id, index
- `title`: String
- `status`: String, CHECK IN ('draft', 'active', 'completed', 'archived'), default "draft"
- `start_date`, `end_date`: Date
- `public_id`: String, unique, nullable — UUID para compartir públicamente
- `created_at`, `updated_at`: DateTime(timezone=True)
- Relaciones: `tourist` (back_populates), `steps` (cascade delete-orphan), `ara_session` (back_populates)

**ItineraryStep (`models/itinerary_step.py`, 53 líneas):**
- `id`: UUID PK
- `itinerary_id`: UUID FK → itineraries.id, ondelete CASCADE
- `step_order`: Integer, CHECK > 0 — unique dentro del itinerary
- `poi_id`: UUID FK → pois.id
- `arrival_time`, `departure_time`: DateTime(timezone=True) — constraint: arrival < departure
- `ai_context`: JSONB — metadata de IA (poi_name, poi_role, scheduled_time, day_index, etc.)
- `visited`: Boolean, default False
- `created_at`, `updated_at`: DateTime(timezone=True)
- Relaciones: `itinerary` (back_populates), `poi` (back_populates)

**AraSession (`models/ara_session.py`, 102 líneas):**
- `id`: UUID PK
- `version`: Integer, CHECK > 0, default 1
- `tourist_id`: UUID FK → tourist_profiles.user_id, ondelete CASCADE, index
- `status`: String, CHECK IN (9 valores: clarifying, searching, ready_to_generate, queued, generating, suggesting_step_replacement, step_replaced, completed, failed), default "clarifying"
- `initial_query`: String(1000)
- `location`: Geometry("POINT", srid=4326), nullable
- `radius`: Float, CHECK > 0, nullable
- `start_date`, `end_date`: Date, nullable
- `intent_data`: JSONB, nullable
- `preferences_data`: JSONB, nullable — trip_draft, lodging, conversation_mode, etc.
- `candidate_poi_ids`: ARRAY(UUID), nullable
- `generated_itinerary_id`: UUID FK → itineraries.id, ondelete SET NULL, index
- `created_at`, `updated_at`: DateTime(timezone=True)
- Relaciones: `tourist` (selectin), `messages` (selectin, cascade delete-orphan), `generated_itinerary` (selectin), `conversation_memories` (noload)
- Propiedades helper: `lat`, `lon` (get/set vía `_set_location()` → WKTElement)

**ConversationMemory (`models/conversation_memory.py`, 40 líneas):**
- `id`: UUID PK
- `tourist_id`: UUID FK → tourist_profiles.user_id, ondelete CASCADE, index
- `session_id`: UUID FK → ara_sessions.id, ondelete SET NULL, nullable
- `hecho`: Text — el hecho memorizado
- `categoria`: String — restriccion, preferencia, destino, entidad, horario, transporte, presupuesto, alojamiento
- `confianza`: Float, CHECK BETWEEN 0 AND 1
- `embedding`: Vector(1536), nullable — generado al crear; si falla OpenAI, se guarda sin embedding
- `contexto`: JSONB, nullable — metadata adicional del hecho
- `expires_at`: DateTime(timezone=True), nullable — TTL opcional
- `created_at`: DateTime(timezone=True)
- Relaciones: `tourist` (back_populates), `session` (back_populates, noload)

### 5.3 Constraints de Integridad

**Check constraints (7):**
- `ck_users_role`: `role IN ('tourist', 'entrepreneur')`
- `ck_reviews_rating_stars`: `rating_stars BETWEEN 1 AND 5`
- `ck_itineraries_status`: `status IN ('draft', 'active', 'completed', 'archived')`
- `ck_ara_sessions_status`: `status IN ('clarifying', 'searching', 'ready_to_generate', 'queued', 'generating', 'suggesting_step_replacement', 'step_replaced', 'completed', 'failed')`
- `ck_ara_messages_role`: `role IN ('user', 'assistant', 'system')`
- `ck_pois_source`: `source IN ('manual', 'osm', 'ai_generated')`
- `ck_entrepreneur_posts_status`: `status IN ('draft', 'published', 'archived')`

**Constraints de negocio (6):**
- `confidence_score`: 0.0 a 1.0
- `step_order > 0`
- `departure_time < arrival_time` en ItineraryStep
- `radius > 0` en AraSession
- `end_date >= start_date`
- `full_name VARCHAR(255)` en TouristProfile

**Unique constraints:**
- `uq_bookmark_tourist_poi`: un turista no puede bookmarked el mismo POI dos veces
- `uq_review_tourist_poi`: un turista no puede reseñar el mismo POI dos veces (crea o actualiza)
- `uq_itinerary_steps_order`: step_order único dentro de un itinerary

**Tipos especiales de columna:**
- `description_embedding`: `Vector(1536)` en POI
- `interests_embedding`: `Vector(1536)` en TouristProfile
- `embedding`: `Vector(1536)` en Review y ConversationMemory
- `location`: `Geometry("POINT", srid=4326)` en POI y AraSession
- `candidate_poi_ids`: `ARRAY(UUID)` en AraSession
- `preferences_data`, `intent_data`, `quick_replies`, `message_metadata`: `JSONB`

### 5.3 Lista Completa de Modelos ORM

| # | Modelo | Archivo | Tabla | Líneas | Relaciones |
|---|--------|---------|-------|--------|------------|
| 1 | User | user.py | users | 56 | → TouristProfile, EntrepreneurProfile |
| 2 | TouristProfile | tourist_profile.py | tourist_profiles | 45 | → User (FK), interests_embedding Vector(1536) |
| 3 | EntrepreneurProfile | entrepreneur_profile.py | entrepreneur_profiles | 45 | → User (FK) |
| 4 | Category | category.py | categories | 31 | → parent_id (self-ref), POICategory |
| 5 | POI | poi.py | pois | 76 | → EntrepreneurProfile (FK), POICategory, Review, Bookmark, POIVisit |
| 6 | POICategory | poi_category.py | poi_categories | 32 | → POI, Category (bridge) |
| 7 | Review | review.py | reviews | 47 | → TouristProfile, POI |
| 8 | Bookmark | bookmark.py | bookmarks | 40 | → TouristProfile, POI |
| 9 | Itinerary | itinerary.py | itineraries | 55 | → TouristProfile, ItineraryStep, AraSession |
| 10 | ItineraryStep | itinerary_step.py | itinerary_steps | 53 | → Itinerary, POI |
| 11 | AraSession | ara_session.py | ara_sessions | 102 | → TouristProfile, AraMessage, Itinerary, ConversationMemory |
| 12 | AraMessage | ara_message.py | ara_messages | 39 | → AraSession |
| 13 | ConversationMemory | conversation_memory.py | conversation_memories | 40 | → TouristProfile, AraSession |
| 14 | EntrepreneurPost | entrepreneur_post.py | entrepreneur_posts | 54 | → POI |
| 15 | POIVisit | poi_visit.py | poi_visits | 47 | → TouristProfile, POI |

**Nota importante sobre lazy loading:** En SQLAlchemy async, el lazy loading sincrónico produce `MissingGreenlet`. Por eso TODOS los repositorios usan `.options(selectinload(...))` explícito en sus queries. Ejemplo en `conversation_processor.py`:
```python
@staticmethod
def _loaded_messages(session: AraSession) -> list[Any]:
    """Accede a messages sin disparar lazy-load implícito."""
    return list(session.__dict__.get("messages") or [])
```

### 5.4 Estrategias de Eager Loading por Entidad

| Entidad | Relación | Estrategia | Dónde se aplica |
|---------|----------|------------|-----------------|
| Review | → tourist | `selectinload` | `review_repository.get_reviews_by_poi`, `create_review`, `update_review` |
| Bookmark | → tourist | `selectinload` | `entrepreneur_repository.get_poi_activity` |
| Itinerary | → steps | `selectinload` anidado | `itinerary_repository.get_itinerary_by_id` y 8 métodos que lo usan |
| ItineraryStep | → poi | `selectinload` anidado | Misma query que arriba (two-level eager loading) |
| AraSession | → messages | `selectinload` | `ara_repository.get_session` |
| AraSession | → generated_itinerary | `selectinload` | `ara_repository.get_session` |
| AraSession | → tourist | `selectinload` | `ara_repository.get_session` |
| ConversationMemory | → session | `noload` | No se carga nunca en queries de memoria |
| POI | → categories | `selectinload` | `poi_repository.get_poi_by_id`, `get_pois_by_ids` |

---

## 6. Servicios de IA

### 6.1 Embedding Service (3 niveles)

**Archivo:** `app/services/embedding_service.py` (101 líneas)

**Arquitectura de caché de 3 niveles:**
```
EmbeddingCache (request-scoped, dict local)
  → delega a GlobalEmbeddingCache (process-scoped, TTL 900s, double-checked locking)
    → delega a OpenAIEmbeddingService (API calls a text-embedding-3-small)
```

**OpenAIEmbeddingService:**
- Modelo: `text-embedding-3-small` (1536 dimensiones)
- Cliente: `AsyncOpenAI` con API key de OpenAI
- Métodos: `get_embedding(text)` → `list[float]`, `get_embeddings_batch(texts)` → `list[list[float]]`
- Batch: una sola llamada API para N textos (OpenAI soporta hasta 2048 inputs por batch)

**GlobalEmbeddingCache:**
- TTL: 900 segundos (15 minutos)
- Thread-safety: `asyncio.Lock` por clave (double-checked locking)
- Sin evicción (aceptable para text-embedding-3-small con ~3000 tokens max)
- Almacena: `{text: (expiry_timestamp, embedding_list)}`

**EmbeddingCache:**
- Request-scoped, wrapper del global
- Dict local para deduplicación intra-request
- Misma interfaz `get_embedding(text)` → `list[float]`

### 6.2 LLM Service — Generación de Itinerarios (DeepSeek)

**Archivo:** `app/services/llm_service.py` (232 líneas)

**Modelo:** DeepSeek (`deepseek-chat`) vía `AsyncOpenAI` con `base_url=https://api.deepseek.com`

**Timeout:** `deepseek_timeout_seconds` = 90 segundos

**Clase principal:** `ItineraryGenerator`
- `generate_itinerary(query, context_pois, weather, schedule_guidance, stream_callback?)` → `dict`
- Usa `with_retry()` con max_retries=1, base_delay=2.0
- Parámetros LLM: temperature=0.2, response_format={"type": "json_object"}
- Prompt: `build_generation_prompt()` de `prompt_manager.py`

**Validación post-LLM:**
1. Parseo JSON de la respuesta
2. Normalización de payload: `_normalize_itinerary_payload()` soporta formato legacy `days[].steps` y formato actual `steps[]`
3. Normalización de POI IDs: `_normalize_step_poi_ids()` con fuzzy matching por nombre (unicode NFKD + lowercase)
4. Validación Pydantic con `GeneratedItinerary`
5. Pipeline de reparación (7 pasos, ver 6.4)

**Streaming:** Si se pasa `stream_callback`, el LLM streamea tokens. El callback recibe cada token individual.

### 6.3 Comprensión Conversacional (GPT-4o-mini)

**Archivo:** `app/services/ara_v2/comprehender.py` (208 líneas)

**Modelo:** GPT-4o-mini (`gpt-4o-mini`) vía `get_gpt_mini_client()` singleton

**Timeout:** `gpt_mini_timeout_seconds` = 10 segundos

**Clase principal:** `Comprensor`
- `comprehend(user_message, session_messages, relevant_facts, trip_draft, candidate_pois_count)` → `ComprehensionResult`
- Temperatura: 0.0 (determinista)
- Security: `detect_prompt_injection()` con 9 patrones regex (ignore previous instructions, you are now, system:, etc.)
- Sanitización: `sanitize_user_message()` envuelve en tags XML `<user_message>`

**Fallback:** `comprehension_fallback.py` (185 líneas)
- Si el LLM falla (timeout, API error, parse error), usa `fallback_comprehend()`
- Reglas deterministas: keywords para build_itinerary, search_pois, answer_question
- Detección de categorías: naturaleza, gastronomía, cultura, aventura, alojamiento, termas
- Soporta parámetros `has_dates` y `has_destination` para evitar preguntas redundantes

**Estructura de `ComprehensionResult`:**
```python
class ComprehensionResult(BaseModel):
    intenciones: list[str]            # ej: ["planificar_viaje", "buscar_restaurante"]
    intencion_principal: str           # ej: "planificar_viaje"
    confianza: float                   # 0.0 a 1.0
    entidades: list[ExtractedEntity]   # destinos, POIs, fechas, categorías, restricciones
    rango_fechas: DateRange | None     # {start, end} en ISO format
    herramientas_necesarias: list[str] # search_pois, build_itinerary, answer_question, etc.
    preguntas_pendientes: list[str]    # preguntas para el usuario
    actualizaciones_memoria: list[MemoryFact]  # hechos para guardar en memoria
    sugerir_quick_replies: list[QuickReplySuggestion]  # quick replies sugeridos
    tono: str                          # entusiasta, neutro, informativo, empatico
    modo: str                          # auto, mixto, guiado
```

### 6.4 Pipeline Unificado de Generación de Itinerarios

**Archivo:** `app/services/ara_itinerary_core.py` (282 líneas)

**Función central:** `generate_itinerary_core(session, payload, db, user, embedding_service, llm_service, candidate_pois?, weather_forecast?, on_phase?)` → `(itinerary, context_pois, generation_payload)`

**Callback pattern:**
```python
async def on_phase(name: str, extra: dict | None) -> None:
    # SSE: encola evento en la queue
    # Tool orchestrator: logger.info()
    # Direct call: None (sin callback)
```

**7 fases secuenciales:**

| # | Fase | Descripción |
|---|------|-------------|
| 1 | **Validating** | Verifica perfil turista, resuelve coordenadas (GPS del session o geocoded destination_scope) |
| 2 | **Query Building** | `build_refined_query()` combina initial_query + user messages + intent_data + preferences_data |
| 3 | **POI Searching** | Dos paths: pre-fetched (conversación) o full search (SSE) con merge de session context + user-selected + semantic search + semantic fallback |
| 4 | **Weather** | Fetch forecast si no se pasó pre-calculado |
| 5 | **LLM Generation** | `llm_service.generate_itinerary()` con query + POIs + weather + schedule_guidance |
| 6 | **Repair** | 7 pasos de validación/corrección post-LLM |
| 7 | **Save** | Persiste via `itinerary_repository.create_generated_itinerary()`, linkea a sesión |

**Pipeline de reparación post-LLM (7 pasos):**
```
normalize_times → repair_invalid_ids → repair_start_times → repair_lodging_duplicates
→ repair_duplicate_steps → repair_schedule_category → validate_rules → sanitize_context
```

Funciones correspondientes en `itinerary_generation_service.py` (997 líneas):
- `normalize_generated_itinerary_times()` — Normaliza horarios a timezone Chile
- `repair_invalid_poi_ids()` — Corrige IDs que no matchean POIs del contexto
- `repair_latest_start_times()` — Ajusta horarios cuando arrival > departure
- `repair_lodging_duplicates()` — Elimina alojamientos duplicados en días consecutivos
- `repair_duplicate_poi_steps()` — Elimina steps duplicados del mismo POI
- `repair_schedule_and_category_issues()` — Corrige saturación de una sola categoría
- `validate_generated_itinerary_rules()` — Reglas de negocio (3-6 actividades/día, distancias, etc.)
- `sanitize_generated_itinerary_context()` — Elimina metalenguaje técnico del LLM

**Llamado por 3 wrappers:**
- `ara_streaming_service.py` — Con callback SSE, manejo de CancelledError
- `tool_orchestrator.py` — Con callback logging, modo conversacional
- `itinerary_generation_service.py` — Directo, sin callback

### 6.5 Servicios de Apoyo

**Weather Service (`app/services/weather_service.py`, 218 líneas):**
- `get_forecast(lat, lon, start_date?, end_date?)` → `list[WeatherDailyForecast]`
- Proveedor: OpenWeatherMap Forecast API 2.5 (5-day, bloques cada 3 horas)
- Cache: `TTLCache` con maxsize=100, ttl=1800 segundos (30 minutos)
- Selección de bloque representativo: el más cercano al mediodía (hora 12) por ser más relevante para turismo
- Nombres de días en español: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo
- Timeout: 15 segundos

**Geocoding Service (`app/services/geocoding_service.py`, 52 líneas):**
- `search_places(query, lat?, lon?, limit=8)` → `list[GeocodingResult]`
- Proveedor: Nominatim (OpenStreetMap) con User-Agent "RutaVivaBackend/0.1"
- Soporta viewbox para sesgar resultados hacia una ubicación (delta=1.5 grados)
- Timeout: 12 segundos
- Usa el pool de httpx compartido (`get_client("nominatim", ...)`)

**Geo Service (`app/services/geo_service.py`, 14 líneas):**
- `distance_meters(lat_a, lon_a, lat_b, lon_b)` → `float`
- Fórmula: Haversine con radio terrestre de 6,371,000 metros
- Sin dependencias externas, solo `math`

**Image Service (`app/services/image_service.py`, 61 líneas):**
- `save_image(file: UploadFile)` → `str` (URL relativa)
- Validación de Content-Type: solo `image/jpeg` y `image/png`
- Validación de magic bytes: JPEG (`\xff\xd8\xff`), PNG (`\x89PNG\r\n\x1a\n`)
- Tamaño máximo: 5 MB (5 * 1024 * 1024 bytes)
- Nombre de archivo: UUID4 + extensión → ej: `0eaa3206-971d-4208-9dd0-98b2897d40d9.jpg`
- Escritura: `asyncio.to_thread(destination.write_bytes, content)` — no bloquea event loop
- Retorna: `/media/{filename}`

**POI Metadata Extractor (`app/services/poi_metadata_extractor.py`, 396 líneas):**
- `ExtractedMetadata` dataclass con: description, opening_hours_text, opening_hours_structured, services, access, evidence
- HTMLParser para extraer datos estructurados de metadata HTML de OSM
- Soporte para horarios en español: `WEEKDAY_KEYS` (mon-sun) + `SPANISH_WEEKDAY_ALIASES` (lunes→mon, etc.)
- Rangos en español: "lunes a viernes"→(mon,fri), "todos los días"→(mon,sun)
- Extracción de servicios: wifi, estacionamiento, accesibilidad, mascotas, etc.
- Extracción de acceso: transporte público, auto, caminando, etc.

**POI Search Service (`app/services/poi_search_service.py`, 345 líneas):**
- `search_candidate_pois()` — Búsqueda principal de candidatos para Ara
- `search_generation_context_with_fallbacks()` — Búsqueda con fallback progresivo:
  1. Búsqueda semántica estricta al destino
  2. Si < `MIN_ITINERARY_CONTEXT_POIS` resultados → fallback a búsqueda ampliada
  3. Si aún pocos → búsqueda sin restricción de destino
- `filter_pois_to_search_center()` — Filtra POIs que están fuera del radio del search center
- `is_strict_destination_context()` — Determina si el usuario quiere búsqueda estricta a un destino
- `wants_expanded_destination_scope()` — Detecta si el usuario pide ampliar búsqueda
- Usa constantes de `ara_constants.py`: KNOWN_DESTINATION_CENTERS, EXPAND_DESTINATION_TERMS, etc.

**Review Enrichment Service (`app/services/review_enrichment_service.py`, 65 líneas):**
- `enrich_review_with_embedding()` — Genera embedding y actualiza review en DB
- `update_tourist_interests_embedding()` — Perfil dinámico:
  - Si tiene `interests_embedding`: `nuevo = perfil_actual * 0.9 + embedding_review * 0.1`
  - Si no tiene: `nuevo = embedding_review`
  - Actualización dimensión por dimensión sobre 1536 floats
- Llamado en background después de `create_review()`

**Itinerary Generation Service (`app/services/itinerary_generation_service.py`, 997 líneas):**
- El archivo más grande del proyecto. Contiene funciones de soporte para el pipeline de generación.
- `build_schedule_guidance()` — Construye guía de horarios para el LLM
- `filter_blacklisted_context_pois()` — Filtra POIs en categorías no deseadas
- `merge_unique_context_pois()` — Deduplica y mergea listas de POIs manteniendo orden
- `prepare_context_pois()` — Prepara POIs del contexto para el prompt del LLM
- `trip_days()` — Calcula número de días a generar
- Funciones de reparación post-LLM (7 pasos): `normalize_generated_itinerary_times`, `repair_invalid_poi_ids`, `repair_latest_start_times`, `repair_lodging_duplicates`, `repair_duplicate_poi_steps`, `repair_schedule_and_category_issues`, `validate_generated_itinerary_rules`, `sanitize_generated_itinerary_context`
- Enfoque: cada función de reparación es determinista y no llama al LLM

**Itinerary Weather Service (`app/services/itinerary_weather_service.py`, 249 líneas):**
- Lógica de clima por paso de itinerario
- Agrupación de forecast diario para múltiples POIs
- Formateo de forecast para el prompt del LLM
- Cache TTLCache compartido con weather_service.py

### 6.6 Subsistema Ara v2 en Profundidad

**Arquitectura interna de Ara v2:**
```
POST /ara/sessions/{id}/messages
  → ara_conversation_orchestrator.handle_message_v2()  [110 líneas, thin adapter]
    → ConversationProcessor.process_user_message()      [662 líneas, orquestador]
      → MemoryService.retrieve_relevant_facts()          [185 líneas, memoria HNSW]
      → Comprensor.comprehend()                          [208 líneas, GPT-4o-mini]
        → fallback_comprehend() si falla                 [185 líneas, rule-based]
        → Prompt: build_comprehension_prompt()           [187 líneas, prompt_manager]
      → MemoryService.store_facts_batch()                [batch embedding]
      → ToolOrchestrator.execute()                       [663 líneas, ejecución]
        → search_candidate_pois()                        [345 líneas, búsqueda]
        → answer_question()                              [133 líneas, answer_service]
        → generate_itinerary_core()                      [282 líneas, pipeline]
        → geocode_destination()                          [124 líneas, geocoding Ara]
      → ResponseGenerator.generate_response()            [381 líneas, GPT-4o-mini]
```

**Flujo de memoria semántica:**
1. Al recibir un mensaje, `retrieve_relevant_facts()` busca los 5 hechos más cercanos por cosine similarity en HNSW
2. El compresor extrae `actualizaciones_memoria` del mensaje (nuevos hechos para guardar)
3. `store_facts_batch()` genera embeddings en batch y los inserta en `conversation_memories`
4. Si la categoría es "preferencia" y confianza > 0.8, actualiza `TouristProfile.interests_embedding`
5. Si falla el batch embedding: fallback individual con `store_fact()`
6. Si falla embedding individual: guarda el hecho sin embedding (último recurso)

**Flujo de herramientas (ToolOrchestrator):**
- **search_pois**: `search_candidate_pois()` → diversifica por categoría → quick replies con opciones
- **build_itinerary**: Si hay fechas → `generate_itinerary_core()` → guarda → quick reply con stream_url
- **answer_question**: `answer_service.answer_question()` → respuesta sobre POI concreto
- **replace_step**: `search_step_replacement_alternatives()` → quick replies con alternativas
- **geocode_destination**: `geocode_destination()` → actualiza session.location
- **update_preferences**: Actualiza session.preferences_data con las preferencias inferidas
- **generate_trip_draft**: Construye trip_draft con días y estructura
- **show_options**: Muestra opciones actuales de candidatos
- **confirm_plan**: Confirma selección de POI y avanza el plan
- **review_memories**: Revisa y muestra hechos guardados en memoria

**Gate de fuera de dominio:** Si `intencion_principal == "general"` y `confianza < 0.4`, el ToolOrchestrator retorna status="clarify" con un mensaje recordando que Ara es asistente de viajes.

**Detección de selección de POI por nombre:**
- `_resolve_poi_reference()` busca el POI mencionado en:
  1. candidate_poi_ids de la sesión
  2. Búsqueda por nombre en la DB
  3. Matching fuzzy del nombre mencionado vs nombres de POIs
- `_looks_like_poi_selection()` detecta si el mensaje parece una selección (ej: "el primero", "la opción 2", "ese")

---

## 7. Rate Limiting

### 7.1 Configuración

**Librería:** slowapi (basada en `limits`)

**Key function:** `get_remote_address` (por IP)

**Instancia:** `limiter = Limiter(key_func=get_remote_address)` en `app/core/rate_limit.py` (5 líneas)

**Binding:** `app.state.limiter = limiter` en `main.py`

### 7.2 Límites por Endpoint

| Endpoint | Límite | Tipo | Justificación |
|----------|--------|------|---------------|
| `POST /auth/login` | 5/min | slowapi | Anti brute-force |
| `POST /ara/sessions` | 5/min | slowapi | Control de creación de sesiones |
| `POST /ara/sessions/{id}/messages` | 10/min | slowapi | Protección del flujo conversacional |
| `POST /ara/sessions/{id}/generate-itinerary/stream` | 3/min | slowapi | Generación costosa (LLM + embeddings + clima + búsqueda) |
| `GET /pois/search` | 30/min | slowapi | PostGIS query relativamente barata |
| `GET /pois/semantic-search` | 10/min | slowapi | Incluye llamada a OpenAI embeddings |
| `POST /pois/` | 5/hora + 10/día | DB custom query | Anti-spam de creación de POIs |

### 7.3 Handler de Error 429

```json
{
  "error": "RateLimitExceeded",
  "detail": "Has enviado muchos mensajes muy rápido. Espera un momento y vuelve a intentarlo."
}
```

Implementado en `main.py:132-140` como exception handler global.

---

## 8. Seguridad

### 8.1 Password Hashing

**Algoritmo:** bcrypt (puro, no `bcrypt_sha256`)

**Librería:** Passlib con `CryptContext(schemes=["bcrypt", "bcrypt_sha256"], deprecated=["bcrypt_sha256"])`

**Migración transparente:** Hashes antiguos (`bcrypt_sha256`) se verifican correctamente y Passlib los re-hashea automáticamente a bcrypt puro en el siguiente login. No se requiere migración masiva.

**Ubicación:** `app/core/security.py:11`

### 8.2 JWT

**Access token:**
- Expiración: `access_token_expire_minutes` = 60 minutos (1 hora)
- Creado con `create_access_token()` en `security.py`

**Refresh token:**
- Expiración: `refresh_token_expire_minutes` = 10080 minutos (7 días)
- Creado con `create_refresh_token()` en `security.py`

**Claims en ambos tokens:**
- `sub`: user UUID
- `type`: "access" o "refresh"
- `iat`: issued at (epoch)
- `jti`: JWT ID (UUID4, único)
- `iss`: "ruta-viva"
- `exp`: expiration (epoch)

**Validación en deps.py (`get_current_user`):**
1. Decodifica JWT con `python-jose`
2. Valida `iss == "ruta-viva"` (rechaza tokens de otros emisores)
3. Valida `type != "refresh"` (no acepta refresh tokens como access)
4. Verifica `jti` contra token blacklist
5. Carga usuario de BD por UUID

### 8.3 Logout / Token Blacklist

**Archivo:** `app/core/token_blacklist.py` (49 líneas)

**Implementación:** `TTLCache` de cachetools en memoria con:
- `maxsize = 10,000` tokens revocados
- `ttl = 8 días` (cubre el refresh token máximo de 7 días + margen)

**Funciones:**
- `revoke_token(jti, exp)` — Agrega jti a la blacklist
- `is_token_revoked(jti)` — Verifica si jti está revocado
- `clear_blacklist()` — Limpia todo (útil para tests)

**Endpoint:** `POST /auth/logout` (204 No Content)
- Extrae `jti` y `exp` del token actual
- Llama a `revoke_token()`
- Si el token ya es inválido, no hace nada (no tira error)

**Limitación conocida:** La blacklist no persiste entre reinicios del servidor. Para producción se necesita Redis o similar.

### 8.4 Protección de Archivos

**Endpoint:** `GET /media/{filename}` en `main.py`

- Requiere JWT válido (`get_current_user`)
- Protección contra path traversal: valida que `filename` no contenga `..` ni `/` ni `\`
- Solo se sirven extensiones `.jpg`, `.jpeg`, `.png`
- Validación de que el archivo resuelto esté dentro de `MEDIA_DIR` (path.parents check)

### 8.5 CORS

**Configuración actual:** `allow_origins=["*"]` (wildcard) en `main.py:46-52`

**Riesgo:** Cualquier origen puede hacer requests. En producción debe restringirse a los dominios del frontend.

### 8.6 Protección contra Prompt Injection

**Archivo:** `app/services/ara_v2/comprehender.py:16-31`

**9 patrones regex detectados:**
- `ignore previous instructions`
- `you are now`
- `^system:`
- `new instruction:`
- `act as`
- `pretend to be`
- `override your rules`
- `bypass your restrictions`
- `disable safety`

Si se detecta inyección, `comprehend()` retorna un `ComprehensionResult` con intención "general" y confianza 0.2, sin usar el LLM.

Adicionalmente, `sanitize_user_message()` envuelve el mensaje del usuario en tags `<user_message>` para que el LLM no lo interprete como instrucciones de sistema.

### 8.7 Rate Limiting para Endpoints Conversacionales (Ara)

Los endpoints de Ara tienen rate limits agresivos por su costo computacional (LLM + embeddings + búsqueda semántica):

| Endpoint | Límite | Justificación |
|----------|--------|---------------|
| `POST /ara/sessions` | 5/min | Anti-abuso en creación de sesiones |
| `POST /ara/sessions/{id}/messages` | 10/min | Protección del flujo conversacional (GPT-4o-mini por mensaje) |
| `POST /ara/sessions/{id}/generate-itinerary/stream` | 3/min | Operación más costosa (DeepSeek + embeddings + clima + búsqueda + reparación) |

Implementado con slowapi en `app/core/rate_limit.py`, key function `get_remote_address` (por IP). Handler 429 en `app/main.py:132` con mensaje en español.

### 8.8 Validación de RUT Chileno

**Archivo:** `app/core/rut.py` (36 líneas)

- `validate_rut(rut)` — Algoritmo de módulo 11 estándar chileno
- `format_rut(rut)` — Formatea a `12345678-K`
- Soporta dígito verificador K (10) y 0 (11)
- Usado en `EntrepreneurProfileCreate` y en la activación de perfil emprendedor

### 8.9 Manejo de Errores HTTP

**Jerarquía de excepciones de dominio (`app/core/exceptions.py`, 25 líneas):**
```python
AppError (status_code=500)
  ├── PermissionError (status_code=403)
  └── ConflictError (status_code=409)
        └── ItineraryNotEditableError (detail="Itinerary is no longer editable.")
```

**Exception handlers en `main.py`:**
1. `StarletteHTTPException` → JSON con `error` y `detail`, status_code del exception
2. `RequestValidationError` → 422 con errores de validación Pydantic en `detail`
3. `AppError` → JSON con `error`=nombre de la clase, `detail`=mensaje, status_code de la clase
4. `RateLimitExceeded` → 429 con mensaje en español
5. `Exception` (catch-all) → 500, loguea traceback completo con `logger.exception()`

**Formato de respuesta de error unificado:**
```json
{
  "error": "PermissionError | Validation Error | RateLimitExceeded | ...",
  "detail": "mensaje descriptivo"
}
```

### 8.10 Protección contra Path Traversal en Media

**Archivo:** `app/main.py:58-75` (`_resolve_media_path()`)

Validaciones en orden:
1. `Path(filename).name` debe ser igual a `filename` (sin path components)
2. No debe contener `/` ni `\`
3. Extensión debe estar en `ALLOWED_MEDIA_SUFFIXES` (`.jpg`, `.jpeg`, `.png`)
4. `candidate_path.resolve()` debe tener `MEDIA_DIR.resolve()` en sus `parents`
5. Debe ser un archivo existente (`is_file()`)

Si alguna validación falla → HTTP 404 (no 403, para no revelar existencia de archivos).

---

## 9. Infraestructura

### 9.1 Docker Compose

**Servicios:**
- `db`: PostgreSQL 16 + pgvector + PostGIS (imagen `Dockerfile.db`)
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

### 9.2 Health Check

- **HTTP:** `GET /health` verifica conectividad DB con `SELECT 1`. Retorna `{"status": "ok", "database": "up"}`
- **Docker:** `pg_isready -U admin -d rutaviva_db` (NOTA: hardcodeado, no usa variables de entorno)

### 9.3 Índices de Base de Datos

- **HNSW** en `pois.description_embedding` para búsqueda vectorial de alta velocidad (`create_vector_indices.py`)
- **GiST** en `pois.location` para búsqueda geoespacial (migración `c9d0e1f2a3b4`)
- **B-tree** en foreign keys (implícitos por SQLAlchemy en todas las FKs)
- **Unique** en `bookmarks(tourist_id, poi_id)` y `reviews(tourist_id, poi_id)`
- **Índice en `ara_sessions.tourist_id`** para búsqueda rápida de sesiones por usuario
- **Índice en `ara_sessions.generated_itinerary_id`** para lookup inverso

### 9.4 Telemetría

**Middleware `telemetry_middleware`** en `main.py:155-187`:
- Mide tiempo de cada request con `time.perf_counter()`
- Header: `X-Process-Time: 0.450123` (segundos con 6 decimales)
- Log: `POST /api/v1/pois/search - 200 OK - 450ms`
- Excluye `/health` del header `X-Process-Time` para no contaminar respuestas
- Captura excepciones no manejadas y loguea como 500

### 9.5 HTTP Client Pool

**Archivo:** `app/core/http_client.py` (24 líneas)

- Singleton pool de `httpx.AsyncClient` por nombre
- Parámetros: timeout configurable, max_connections=20, max_keepalive_connections=10
- `close_all()` llamado en `lifespan` shutdown para cerrar conexiones limpiamente
- Usado por: geocoding_service, weather_service

---

## 10. Tests

### 10.1 Estructura Completa

```
tests/
├── conftest.py                                          # Fixtures: async_client, db_session, auth_headers
├── __init__.py
├── unit/
│   ├── __init__.py
│   ├── test_rut.py                                      # 19 tests
│   ├── test_security.py                                 # 11 tests
│   ├── test_poi_metadata_extractor.py                   # 41 tests
│   ├── test_repository_base.py                          # 2 tests
│   └── ara_v2/
│       ├── __init__.py
│       ├── test_prompt_manager.py                       # 8 tests
│       ├── test_comprehender.py                         # 29 tests
│       ├── test_memory_service.py                       # 6 tests
│       ├── test_response_generator.py                   # 14 tests
│       ├── test_tool_orchestrator.py                    # 12 tests
│       ├── test_memory_integration.py                   # 8 tests
│       └── test_itinerary_payload_normalization.py      # 3 tests
├── api/
│   ├── test_auth.py                                     # 4 tests
│   └── test_itineraries.py                              # 10 tests
└── e2e/
    ├── __init__.py
    └── test_ara_v2_flow.py                              # 12 tests
```

**TOTAL: ~217 test functions** distribuidas en 19 archivos de test (92 de Ara v2).

### 10.2 Desglose por Archivo

| Archivo | Tests | Área |
|---------|-------|------|
| `tests/unit/test_poi_metadata_extractor.py` | 41 | Parsing HTML OSM, horarios, servicios |
| `tests/unit/ara_v2/test_comprehender.py` | 29 | Comprensión LLM + fallback |
| `tests/unit/test_rut.py` | 19 | Validación RUT chileno |
| `tests/unit/ara_v2/test_response_generator.py` | 14 | Generación de respuestas Ara |
| `tests/e2e/test_ara_v2_flow.py` | 12 | Flujo conversacional end-to-end |
| `tests/unit/ara_v2/test_tool_orchestrator.py` | 12 | Ejecución de herramientas |
| `tests/unit/test_security.py` | 11 | JWT y hashing |
| `tests/api/test_itineraries.py` | 10 | Endpoints de itinerarios |
| `tests/unit/ara_v2/test_prompt_manager.py` | 8 | Construcción de prompts |
| `tests/unit/ara_v2/test_memory_integration.py` | 8 | Integración de memoria |
| `tests/unit/ara_v2/test_memory_service.py` | 6 | CRUD de memoria semántica |
| `tests/api/test_auth.py` | 4 | Endpoints de autenticación |
| `tests/unit/ara_v2/test_itinerary_payload_normalization.py` | 3 | Normalización de payload |
| `tests/unit/test_repository_base.py` | 2 | BaseRepository commit/rollback |

### 10.3 Ejecución

```bash
cd ruta_viva
python -m pytest -x -q              # Todos los tests
python -m pytest tests/unit/ara_v2/ -x -q  # Solo Ara v2
python -m pytest -x -q -k "test_comprehension"  # Por keyword
```

### 10.4 Configuración en pyproject.toml

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 11. Flujos de Datos Detallados

### 11.1 Registro y Login

```
POST /auth/register
  → RegisterRequest (Pydantic = UserCreate + TouristProfileCreate)
  → user_repository.get_user_by_email() — verifica duplicado
  → user_repository.create_tourist_user()
    → security.get_password_hash(password)    # bcrypt puro
    → INSERT INTO users
    → INSERT INTO tourist_profiles (con interests_embedding=NULL)
  → commit
  → UserResponse

POST /auth/login
  → LoginRequest (email + password)
  → user_repository.get_by_email()
  → security.verify_password(plain, hashed)
  → security.create_access_token(user_id)
  → security.create_refresh_token(user_id)
  → TokenResponse(access_token, refresh_token)
```

### 11.2 Refresh Token

```
POST /auth/refresh
  → RefreshTokenRequest(refresh_token)
  → Decodifica JWT → valida iss, type=refresh, jti no revocado
  → user_repository.get_user_by_id(sub)
  → revoke_token(jti_antiguo, exp)  # Rotación: el refresh token anterior se invalida
  → create_access_token(user_id) + create_refresh_token(user_id)
  → TokenResponse(nuevo access_token, nuevo refresh_token)
```

### 11.3 Búsqueda Semántica

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
         WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(lon, lat), 4326), radius)
         ORDER BY dist
  → list[POIResponse]
```

### 11.4 Conversación Ara — Flujo Completo (10 pasos)

```
POST /ara/sessions  (con initial_query="Villarrica comida vegetariana")
  → create_session_v2()
    → Crea AraSession(status="clarifying", preferences_data con trip_draft)
    → processor.process_user_message() para el primer mensaje

POST /ara/sessions/{id}/messages  (con content="busco restaurantes vegetarianos")
  → handle_message_v2()
    → processor.process_user_message():
      PASO 1: memory_service.retrieve_relevant_facts(5 hechos más cercanos por HNSW)
      PASO 2: _get_recent_messages() — últimos 10 mensajes de la sesión
      PASO 3: comprensor.comprehend(msg, context, facts, trip_draft)
              → GPT-4o-mini analiza intención, entidades, preferencias, memoria
              → Si falla: fallback_comprehend() rule-based
      PASO 4: Guardar hechos nuevos → memory_service.store_facts_batch()
              → Batch embedding → INSERT INTO conversation_memories
              → Si falla batch: store_fact() individual con fallback sin embedding
      PASO 5: Actualizar TouristProfile.interests_embedding si preferencia > 0.8
      PASO 6: Persiste mensaje del usuario
      PASO 6.5: Geocodifica destino mencionado (si hay entidad tipo "destino")
      PASO 7: tool_orchestrator.execute(comprehension, session, user, db)
              → Gate fuera de dominio: intención "general" + confianza < 0.4 → clarify
              → Rutea según herramientas_necesarias:
                • search_pois: search_candidate_pois() → diversifica → quick replies
                • answer_question: answer_service.answer_question() sobre POI
                • build_itinerary + fechas + ready_to_generate:
                  → status="ready_to_generate", assistant msg con stream_url
                  → Frontend debe llamar al SSE streaming
                • replace_step: search_step_replacement_alternatives()
              → _resolve_poi_reference() para detectar selección de POI por nombre
      PASO 8: Si build_itinerary con fechas → retorna AraSessionResponse con stream_url
      PASO 9: response_generator.generate_response(comprehension, tool_result, session)
              → GPT-4o-mini genera respuesta natural en español
              → Fallbacks estructurados por status (generate/search/respond/clarify/replace)
      PASO 10: Persiste mensaje del asistente + quick replies
    → AraSessionResponse
```

### 11.5 Generación SSE

```
POST /ara/sessions/{id}/generate-itinerary/stream
  → Response: text/event-stream
  → stream_itinerary_generation()
    → Crea asyncio.Queue para eventos SSE
    → _on_phase callback: encola eventos status/warning/result/error
    → Lanza generate_itinerary_core() en asyncio.Task con su propia AsyncSession
      → Fase 1-7 se ejecutan secuencialmente
      → Si low POI count (< 5), emite evento "warning" con action="expand_search"
      → Al completar: actualiza session (conversation_mode="post_generation"),
        agrega mensaje del asistente, emite evento "result"
    → Loop SSE:
      → event_queue.get() con timeout 1.0s
      → Yield "event: {type}\ndata: {json}\n\n"
      → Si timeout y task done, drena queue restante
      → Si CancelledError (cliente desconecta):
        → Marca itinerario como abandoned via itinerary_repository
        → Cancela el task
    → StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 11.6 Creación de Review con Perfil Dinámico

```
POST /reviews
  → ReviewCreate (rating_stars, text_content)
  → review_repository.create_review()
    → INSERT INTO reviews (con embedding=NULL inicialmente)
    → Background: review_enrichment_service.enrich_review_with_embedding()
      → embedding_service.get_embedding(text_content)
      → UPDATE reviews SET embedding = ...
      → review_enrichment_service.update_tourist_interests_embedding()
        → Si tourist tiene interests_embedding:
          → nuevo = perfil_actual * 0.9 + embedding_review * 0.1
          → UPDATE tourist_profiles SET interests_embedding = nuevo
        → Si no tiene:
          → UPDATE tourist_profiles SET interests_embedding = embedding_review
  → ReviewResponse (con author_name por selectinload)
```

### 11.7 Flujo de Creación de POI (Emprendedor)

```
POST /pois/
  → POICreate (Pydantic: name, description?, lat, lon, category_ids, contact_info?, multimedia_urls?)
  → Solo emprendedores autenticados
  → Rate limit: 5/hora + 10/día (DB custom query)
  → embedding_service.get_embedding(name + " " + description)
  → poi_repository.create_poi()
    → INSERT INTO pois (con location=ST_SetSRID(ST_MakePoint(lon, lat), 4326), description_embedding)
    → INSERT INTO poi_categories (bridge table, una fila por category_id)
  → commit
  → POIResponse (con categorías cargadas por selectinload)
```

### 11.8 Flujo de Actualización de Perfil Turista desde UI

```
PUT /users/me/tourist-profile
  → TouristProfileUpdate (full_name?, has_own_transport?, system_preferences?)
  → user_repository.update_tourist_profile()
    → UPDATE tourist_profiles SET ...
  → commit
  → TouristProfileResponse

PATCH /users/me
  → UserUpdate (email?, avatar_url?, display_name?)
  → user_repository.update_user()
    → UPDATE users SET ...
  → commit
  → UserResponse
```

### 11.9 Flujo de Logout y Token Revocation

```
POST /auth/logout
  → Bearer token required
  → jwt.decode(token) → extrae jti, exp
  → revoke_token(jti, exp) → agrega a TTLCache
  → 204 No Content (siempre, incluso si token ya era inválido)

GET /protected-endpoint
  → get_current_user()
    → jwt.decode(token) → extrae jti
    → is_token_revoked(jti) → True → 401 Unauthorized
```

### 11.10 Flujo de Inicialización de Base de Datos

```
Lifespan startup en main.py
  → init_db()
    → CREATE EXTENSION IF NOT EXISTS postgis
    → CREATE EXTENSION IF NOT EXISTS vector
    → Base.metadata.create_all (crea tablas si no existen)
    → INSERT ... ON CONFLICT DO UPDATE para BASE_CATEGORIES (15 categorías con IDs fijos)
    → SELECT setval() para sincronizar el sequence de categories
    → commit
```

### 11.11 Flujo de Compartir Itinerario (Sharing)

```
POST /itineraries/{id}/share
  → Genera UUID como public_id
  → UPDATE itineraries SET public_id = ...
  → Retorna {"public_id": "uuid", "share_url": "/share/uuid"}

GET /share/{public_id}
  → Sin auth requerida (público)
  → itinerary_repository.get_export_data_by_public_id()
    → Busca itinerary por public_id
    → Carga steps con selectinload anidado (step → poi → categories)
    → Retorna ItineraryExportResponse con datos completos

DELETE /itineraries/{id}/share
  → UPDATE itineraries SET public_id = NULL
  → Revoca el acceso público
```

### 11.12 Flujo de Reemplazo de Step en Itinerario (via Ara)

```
Usuario: "cambia el restaurante del día 2 por uno de comida italiana"
  → conversation_processor.process_user_message()
    → comprehension: intencion_principal = "replace_step", entidades = [{tipo: "categoria", valor: "italiana"}]
    → tool_orchestrator.execute()
      → Busca replacement_context en session.preferences_data
      → build_step_replacement_context(itinerary_id, step_id)
      → search_step_replacement_alternatives() — búsqueda semántica con categoría
      → status = "replace", candidate_pois con alternativas
    → response_generator._generate_replace_response()
      → "Encontré estas alternativas: [opciones]"
      → Quick replies con cada opción + "Cancelar"

Usuario: toca quick reply de una opción
  → tool_orchestrator._handle_step_replacement()
    → UPDATE itinerary_steps SET poi_id = nuevo_poi_id
    → Limpia replacement_context de la sesión
    → status = "step_replaced"
    → "¡Listo! He reemplazado el lugar en tu itinerario."
```

---

## 12. Configuración (Settings)

**Archivo:** `app/core/config.py` (65 líneas)
**Clase:** `Settings(BaseSettings)` de `pydantic_settings`
**Fuentes:** `.env` file > environment variables > defaults
**Acceso:** `from app.core.config import settings`

### 12.1 Tabla Completa de Settings

| Setting | Tipo | Default | Descripción |
|---------|------|---------|-------------|
| `app_name` | str | "Ruta Viva" | Título OpenAPI |
| `app_version` | str | "0.1.0" | Versión OpenAPI |
| `api_v1_prefix` | str | "/api/v1" | Prefijo de rutas |
| `postgres_user` | str | "admin" | Usuario PostgreSQL |
| `postgres_password` | str | "admin" | Password PostgreSQL |
| `postgres_db` | str | "rutaviva_db" | Nombre de la base de datos |
| `postgres_host` | str | "localhost" | Host PostgreSQL |
| `postgres_port` | int | 5432 | Puerto PostgreSQL |
| `database_echo` | bool | False | SQL echo para debugging |
| `openai_api_key` | str\|None | None | API key de OpenAI (requerida para embeddings y GPT-4o-mini) |
| `openai_gpt_mini_model` | str | "gpt-4o-mini" | Modelo para comprensión conversacional |
| `gpt_mini_timeout_seconds` | float | 10.0 | Timeout para llamadas a GPT-4o-mini |
| `deepseek_api_key` | str\|None | None | API key de DeepSeek (requerida para generación de itinerarios) |
| `deepseek_base_url` | str | "https://api.deepseek.com" | Endpoint base de DeepSeek |
| `deepseek_timeout_seconds` | float | 90.0 | Timeout para generación de itinerarios con DeepSeek |
| `ara_chat_timeout_seconds` | float | 8.0 | Timeout para chat de Ara (legado) |
| `openweather_api_key` | str\|None | None | API key de OpenWeatherMap (requerida para forecast) |
| `secret_key` | str | (requerido) | Clave secreta para firma JWT |
| `algorithm` | str | "HS256" | Algoritmo de firma JWT |
| `access_token_expire_minutes` | int | 60 | Expiración access token (1 hora) |
| `refresh_token_expire_minutes` | int | 10080 | Expiración refresh token (7 días) |

### 12.2 Settings Eliminadas (Auditoría 2026-05-27)

| Setting | Razón de eliminación |
|---------|---------------------|
| `llm_retry_max_attempts: int = 2` | Sin referencias en el código; el retry usa constantes locales en `llm_retry.py` |
| `llm_retry_base_delay: float = 1.0` | Sin referencias en el código |
| `llm_retry_max_delay: float = 10.0` | Sin referencias en el código |
| `ara_default_language: str = "es"` | Sin referencias; idioma definido en prompts y AraMessages catalog |

### 12.3 Model Config

```python
model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",       # Ignora variables no definidas
    case_sensitive=False,
)
```

### 12.4 Property: async_database_uri

```python
@property
def async_database_uri(self) -> str:
    return (
        f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
        f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    )
```

---

## 13. Deuda Técnica Conocida

### 13.1 Crítica (Bloquea Producción)

| # | Item | Impacto | Plan |
|---|------|---------|------|
| 1 | CORS wildcard (`allow_origins=["*"]`) | Cualquier origen puede llamar a la API | Coordinar con frontend los dominios de producción |
| 2 | Token blacklist solo en memoria (TTLCache) | Tokens revocados reviven después de reinicio del servidor | Implementar Redis para blacklist persistente |
| 3 | Healthcheck Docker hardcodeado (`admin:admin`) | Si se cambian credenciales, el healthcheck Docker falla | Usar variables de entorno en el healthcheck |

### 13.2 Alta (Afecta Rendimiento/Mantenibilidad)

| # | Item | Impacto | Plan |
|---|------|---------|------|
| 4 | `itinerary_generation_service.py` (997 líneas) | Archivo grande, difícil de testear | Refactorizar en sub-módulos |
| 5 | `tool_orchestrator.py` (663 líneas) | Mucha lógica condicional, difícil de extender | Extraer handlers por herramienta |
| 6 | `ara_response_builder.py` (464 líneas) | Quick-reply builder con mucha lógica de decisión | Separar en builders por modo conversacional |
| 7 | `itinerary_repository.py` (884 líneas) | Responsabilidades mezcladas (CRUD + export + share + visitas) | Partir en repositorios específicos |

### 13.3 Media (Mejora de Producto)

| # | Item | Impacto | Plan |
|---|------|---------|------|
| 8 | Sin tiempos de traslado reales | Itinerarios no optimizan orden geográfico | Integrar OSRM o Google Distance Matrix |
| 9 | Clima agrupado por fecha (no por coordenada de POI) | Microclimas distintos en La Araucanía pueden pisarse | Clima por coordenada de POI, no por fecha |
| 10 | Sin pipeline RAG formal | Sin memoria a largo plazo de documentos externos | Diseñar `rag_service.py` |

### 13.4 Baja (Pulido)

| # | Item | Plan |
|---|------|------|
| 11 | `GlobalEmbeddingCache` sin evicción de memoria | Agregar LRU eviction si el uso de memoria crece |
| 12 | Sin observabilidad distribuida | Evaluar OpenTelemetry cuando haya múltiples servicios |
| 13 | Sin tests de integración con DB real | Agregar test DB con Docker en CI |
| 14 | Sin type checking en CI | Agregar mypy o pyright al pipeline |
| 15 | Scripts sin tests | Agregar tests para los 14 scripts de ingesta/procesamiento |

### 13.5 Resueltos en Refactorización Fase 1-2 (2026-06-03)

| # | Item | Solución aplicada |
|---|------|-------------------|
| R1 | OSRM sin fallback | Cliente OSRM con fallback Haversine implementado y testeado |
| R2 | `poi_id` NOT NULL en `itinerary_steps` | Migración `k2l3m4n5o6p7` — `poi_id` ahora nullable con `is_generic` y `name` |
| R3 | Slots de comida genéricos con POI real detrás | Prompt + generador + reparadores ahora crean pasos `is_generic: true` sin `poi_id` |
| R4 | `has_own_transport` no se leía del perfil | Cadena completa: modelo → schema → core → tool_orchestrator |
| R5 | Matriz de tiempos POIs no incluida en prompt | `_build_travel_matrix()` con OSRM + fallback Haversine, limitado a 15 POIs |
| R6 | `itinerary_generation_service.py` — reparadores sin guard `is_generic` | 5 funciones de repair ahora usan `is_generic_itinerary_step()` para saltear pasos genéricos |
| R7 | `_estimate_route_ready_score` "privada" importada desde fuera | Función renombrada/verificada como pública (`estimate_route_ready_score`) |
| R8 | Quick replies `generate` en flujo clarify cuando faltan slots | `response_generator.py` filtra QR tipo `generate`/`finalize` cuando `!_are_all_slots_filled()` |
| R9 | `slot_state.py` — duplicación de `_is_slot_filled` | Extraído a `app/services/ara_v2/slot_state.py`, wrappers de 1 línea en processor y generator |
| R10 | Singletons de repositorio en `ara_itinerary_core.py` | Eliminados. `generate_itinerary_core` recibe repositorios como parámetros keyword-only obligatorios |
| R11 | Logging inexistente en endpoints Ara e itineraries | `logger.info` + `logger.exception` agregados en `ara.py`, `itineraries.py`, `ara_conversation_orchestrator.py` |
| R12 | `itinerary_pending` no en regex Pydantic | `ToolExecutionResult.status` ahora incluye `itinerary_pending` en el patrón |
| R13 | Docstring inconsistente en migración `h5a6b7c8d9e0` | Corregido `Revision ID` y `Revises` |
| R14 | `tool_orchestrator.py` importa `ItineraryRepository` no usado | Import y singleton eliminados |
| R15 | `_search_diverse_pois` secuencial | Cambiado a `asyncio.gather` — búsquedas de categoría en paralelo |
| R16 | N+1 queries en `_build_itinerary` | Batch `get_pois_by_ids` en vez de N `get_poi_by_id` |
| R17 | `search_by_name` secuencial en `_resolve_poi_reference` | Paralelizado con `asyncio.gather` |

### 13.6 Archivos Eliminados en Auditoría (Referencia Histórica)

| Archivo Eliminado | Líneas | Reemplazado Por |
|-------------------|--------|-----------------|
| `app/services/ara_chat_service.py` | 269 | `ara_v2/response_generator.py` + `ara_v2/answer_service.py` |
| `app/services/ara_itinerary_generation.py` | 401 | `app/services/ara_itinerary_core.py` |
| `app/services/ara_turn_classifier.py` | — | `ara_v2/comprehender.py` |

### 13.7 Tests Pre-existentes que Siguen Fallando (No Bloqueantes)

| # | Archivo de test | Causa | Severidad |
|---|----------------|-------|-----------|
| T1 | `test_ara_itinerary_core.py` (7 tests) | Fixture `mock_dependencies` no patchea singleton del módulo `ara_itinerary_core.ara_repository` | Media — Bug del test, no del código productivo |
| T2 | `test_osrm_client.py` (6 tests) | `AsyncMock()` usado para simular `httpx.Response` cuyos métodos `json()` y `raise_for_status()` son síncronos | Baja — Bug del test, ya arreglado en rama actual |
| T3 | `test_itineraries_api.py` (3 tests) | Fecha hardcodeada `date(2026, 5, 28)` vencida (itinerario "pasado" → no editable → 409 Conflict) | Baja — Fixture stale |
| T4 | `test_itineraries_weather.py` (4 tests) | Tests esperan `list[ItineraryStepWeatherResponse]` pero endpoint retorna `ItineraryDayWeatherResponse` (formato cambió) | Baja — Tests desactualizados del contrato |

### 13.8 Deuda Técnica Pendiente Post-Refactorización

| # | Item | Prioridad | Por qué falta |
|---|------|-----------|---------------|
| D1 | `itinerary_generation_service.py` (1,041 líneas) | Media | God Service. Extraer reparadores, validación y normalización a módulos separados. Funciona, pero cada nueva feature es más difícil. |
| D2 | `conversation_processor.py` (733 líneas) | Media | God Class. Extraer `MemoryProcessor`, `ComprehensionProcessor`, `ResponseProcessor`, `ProgressTracker`. |
| D3 | `tool_orchestrator.py` (774 líneas) | Media | God Orchestrator. Extraer `PoiSearcher`, `WeatherFetcher`, `ItineraryBuilder`, `PoiSelector`. |
| D4 | `itinerary_repository.py` (884 líneas) | Baja | CRUD + export + share + visits mezclados. Partir en repositorios específicos. |
| D5 | `ara_response_builder.py` (464 líneas) | Baja | Quick-reply builder con mucha lógica de decisión. Separar en builders por modo conversacional. |

---

## 14. Comandos Útiles

### 14.1 Desarrollo

```bash
# Entorno virtual (desde ruta_viva/)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Solo la base de datos
docker compose up -d db

# API con hot reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# API + DB (todo el stack)
docker compose up -d

# Ver logs
docker compose logs -f api
```

### 14.2 Tests

```bash
cd ruta_viva

# Todos los tests (~217 test functions)
python -m pytest -x -q

# Solo tests unitarios
python -m pytest tests/unit/ -x -q

# Solo tests de Ara v2
python -m pytest tests/unit/ara_v2/ -x -q

# Solo tests de API
python -m pytest tests/api/ -x -q

# Solo tests end-to-end
python -m pytest tests/e2e/ -x -q

# Por keyword
python -m pytest -x -q -k "test_comprehension"

# Con coverage
python -m pytest --cov=app --cov-report=term-missing
```

### 14.3 Base de Datos

```bash
cd ruta_viva

# Migraciones
alembic upgrade head                      # Aplicar todas las migraciones
alembic upgrade +1                        # Aplicar siguiente migración
alembic downgrade -1                      # Revertir última migración
alembic revision --autogenerate -m "msg"  # Crear nueva migración
alembic current                           # Ver migración actual

# Seed inicial
python scripts/seed_categories.py         # Categorías base (idempotente, IDs fijos)
python scripts/create_vector_indices.py   # Índice HNSW en pois.description_embedding

# Importación de datos
python scripts/import_osm_data.py         # Importar POIs de OpenStreetMap
python scripts/import_conaf_data.py       # Importar parques nacionales CONAF

# Pipeline completo de calidad
python scripts/audit_poi_quality.py       # Auditar calidad de POIs
python scripts/apply_poi_quality_fixes.py # Aplicar correcciones
python scripts/run_full_pipeline.py       # Pipeline completo
```

### 14.4 Docker

```bash
# Levantar todo
docker compose up -d

# Bajar todo
docker compose down

# Reconstruir imágenes
docker compose build --no-cache

# Logs de la API
docker compose logs -f api

# Logs de la DB
docker compose logs -f db

# Consola SQL
docker compose exec db psql -U admin -d rutaviva_db

# Shell en el contenedor de la API
docker compose exec api /bin/bash
```

### 14.5 Scripts de Mantenimiento

```bash
# Deduplicación de POIs
python scripts/deduplicate_pois.py

# Recategorización
python scripts/recategorize_pois.py

# Enriquecimiento de metadata
python scripts/enrich_poi_metadata.py

# Reescritura de descripciones con LLM
python scripts/rewrite_descriptions_with_llm.py

# Scraping de parques CONAF
python scripts/scrape_conaf_parks.py

# Snapshot de calidad
python scripts/quality_snapshot.py
```

---

## 15. Guía de Contribución

### 15.1 Principios Fundamentales

1. **Endpoints delgados**: Si un handler supera ~50 líneas, extraer lógica a un service.
2. **Eager loading explícito**: Todo repositorio que expone relaciones debe usar `selectinload()`. Nunca confiar en lazy loading.
3. **Excepciones de dominio**: Usar `AppError`, `PermissionError`, `ConflictError`. No usar `HTTPException` en services.
4. **Settings tipados**: Toda configuración externa va en `Settings` con alias de entorno (AliasChoices).
5. **Tests**: Mínimo un test por endpoint nuevo o bug fix.

### 15.2 Antes de Hacer Cambios

1. Leer esta documentación completa.
2. Revisar la sección "Deuda técnica conocida".
3. Si el cambio es sustancial, seguir el flujo SDD: proposal → spec → design → tasks → apply.

### 15.3 Durante el Desarrollo

- **Nuevos endpoints**: Agregar a `api/v1/endpoints/`, registrar en `api/v1/api.py`
- **Nuevos services**: Colocar en `services/` o `services/ara_v2/` según corresponda
- **Nuevos modelos**: Un archivo por entidad en `models/`, importar en `db/models.py`
- **Nuevos schemas**: Un archivo por dominio en `schemas/`
- **Nuevos repositorios**: Extender `BaseRepository`, un archivo por entidad
- **Rate limits**: Agregar decorador `@limiter.limit()` en el endpoint
- **Constantes**: Agregar a `core/ara_constants.py` o `core/itinerary_constants.py` según dominio

### 15.4 Antes de Commit

1. `python -m pytest -x -q` — Todos los ~217 tests deben pasar.
2. Revisar `git diff` para asegurar que no hay secrets, debug prints ni código comentado.
3. Commit messages en inglés, formato conventional commits.

### 15.5 No Hacer

- **No commitear secrets** (`.env`, API keys reales).
- **No agregar imports no usados**.
- **No crear excepciones de dominio "por si acaso" que nunca se lanzan.**
- **No duplicar lógica de generación de itinerarios**: todo debe pasar por `generate_itinerary_core()`.
- **No confiar en lazy loading de SQLAlchemy**: siempre usar `selectinload` explícito en repositorios.
- **No hardcodear credenciales** en el código. Usar `settings.*`.
- **No crear endpoints sync o async de generación**: solo existe SSE streaming.

---

## 16. Referencias Rápidas

### 16.1 Dónde Encontrar...

| Pregunta | Archivo | Función/Clase |
|----------|---------|---------------|
| ¿Cómo se crea un JWT? | `app/core/security.py:22` | `create_access_token()` |
| ¿Cómo se valida un JWT? | `app/api/deps.py:21` | `get_current_user()` |
| ¿Cómo se revoca un token? | `app/core/token_blacklist.py:22` | `revoke_token()` |
| ¿Cómo se hashea una contraseña? | `app/core/security.py:18` | `get_password_hash()` |
| ¿Cómo se genera un embedding? | `app/services/embedding_service.py:19` | `OpenAIEmbeddingService.get_embedding()` |
| ¿Cómo funciona el caché de embeddings? | `app/services/embedding_service.py:38` | `GlobalEmbeddingCache` |
| ¿Cómo se genera un itinerario? | `app/services/ara_itinerary_core.py:62` | `generate_itinerary_core()` |
| ¿Cómo se streamea por SSE? | `app/services/ara_streaming_service.py:36` | `stream_itinerary_generation()` |
| ¿Cómo se clasifica la intención del usuario? | `app/services/ara_v2/comprehender.py:71` | `Comprensor.comprehend()` |
| ¿Cómo funciona el fallback de comprensión? | `app/services/ara_v2/comprehension_fallback.py:12` | `fallback_comprehend()` |
| ¿Cómo se ejecutan las herramientas de Ara? | `app/services/ara_v2/tool_orchestrator.py:33` | `ToolOrchestrator.execute()` |
| ¿Dónde está el orquestador de conversación? | `app/services/ara_v2/conversation_processor.py:29` | `ConversationProcessor.process_user_message()` |
| ¿Cómo se generan respuestas de Ara? | `app/services/ara_v2/response_generator.py:48` | `ResponseGenerator.generate_response()` |
| ¿Cómo se construyen los prompts? | `app/services/ara_v2/prompt_manager.py` | `build_comprehension_prompt()`, `build_generation_prompt()` |
| ¿Cómo se maneja la memoria conversacional? | `app/services/ara_v2/memory_service.py:24` | `MemoryService.store_fact()` |
| ¿Cómo se mapean categorías? | `app/services/ara_v2/category_mapping.py:13` | `CATEGORY_INTENT_TO_DB_NAMES` |
| ¿Cómo se geocodifica un destino? | `app/services/ara_v2/geocoding_service.py:59` | `geocode_destination()` |
| ¿Cómo se repara un itinerario post-LLM? | `app/services/ara_itinerary_core.py` (fase 6) + `itinerary_generation_service.py` | Funciones repair_* |
| ¿Cómo se configura rate limiting? | `app/core/rate_limit.py` + `app/main.py:42` | `limiter` |
| ¿Cómo se convierte a hora chilena? | `app/core/time_utils.py:10` | `to_chile_timezone()` |
| ¿Cómo se calcula distancia entre coordenadas? | `app/services/geo_service.py:4` | `distance_meters()` (Haversine) |
| ¿Cómo se valida un RUT chileno? | `app/core/rut.py:4` | `validate_rut()` (módulo 11) |
| ¿Cómo funciona el retry de LLM? | `app/core/llm_retry.py:18` | `with_retry()` (backoff exponencial) |
| ¿Dónde está el catálogo de mensajes de Ara? | `app/core/ara_messages.py` | `AraMessages` |
| ¿Dónde están las constantes compartidas de Ara? | `app/core/ara_constants.py` | Términos, patrones, categorías |
| ¿Cómo se validan imágenes? | `app/services/image_service.py:18` | `_validate_image_signature()` (magic bytes) |
| ¿Cómo se normaliza un mensaje de usuario? | `app/services/ara_message_normalizer.py:9` | `normalize_message()` |
| ¿Cómo se extraen preferencias de un mensaje? | `app/services/ara_preference_merger.py` | `_extract_negative_constraints()`, `_extract_positive_preferences()` |
| ¿Cómo se maneja el HTTP client pool? | `app/core/http_client.py:8` | `get_client()` (singleton) |
| ¿Dónde se define el modelo de la base? | `app/db/base.py:4` | `Base` (DeclarativeBase) |
| ¿Dónde se inicializa la DB? | `app/db/session.py:50` | `init_db()` (extensiones + categorías + create_all) |
| ¿Dónde se agrupan los routers? | `app/api/v1/api.py:19` | `api_router` |
| ¿Dónde se configura CORS? | `app/main.py:46` | `CORSMiddleware` |
| ¿Dónde está el health check? | `app/main.py:190` | `health_check()` |
| ¿Dónde está el handler de rate limit? | `app/main.py:132` | `rate_limit_exceeded_handler()` |
| ¿Dónde está la telemetría? | `app/main.py:155` | `telemetry_middleware` |
| ¿Dónde se sirven archivos media? | `app/main.py:78` | `read_media_file()` |
| ¿Dónde está el endpoint de compartir? | `app/api/v1/endpoints/shared.py:13` | `get_shared_itinerary()` |

### 16.2 Estadísticas del Codebase

| Métrica | Valor |
|---------|-------|
| Archivos Python totales (excluyendo `__pycache__` y virtualenv) | ~120 |
| Endpoints HTTP | ~70 |
| Modelos ORM | 15 |
| Schemas Pydantic | 18 archivos |
| Repositorios | 8 |
| Services (incluyendo ara_v2) | 33 |
| Migraciones Alembic | 20 |
| Scripts | 14 |
| Tests (total functions) | ~217 |
| Archivos de test | 19 |
| — Ara v2 tests (unit + e2e) | ~92 |
| Líneas totales de código fuente (estimado) | ~21,000 |

### 16.3 Módulos Más Grandes (Top 10 por líneas)

| # | Archivo | Líneas |
|---|---------|--------|
| 1 | `itinerary_generation_service.py` | 997 |
| 2 | `itinerary_repository.py` | 884 |
| 3 | `ara_v2/tool_orchestrator.py` | 663 |
| 4 | `ara_v2/conversation_processor.py` | 662 |
| 5 | `ara_constants.py` | 546 |
| 6 | `itineraries.py` (endpoint) | 497 |
| 7 | `poi_repository.py` | 485 |
| 8 | `ara_response_builder.py` | 464 |
| 9 | `ara_trip_draft_builder.py` | 433 |
| 10 | `ara_messages.py` | 424 |

---

## Apéndice A: Notas de la Auditoría de Código (2026-06-03)

### Correcciones al documento anterior

1. **Tests:** ~232 (no 164). El conteo anterior omitía los tests de `test_response_generator.py` (14), `test_tool_orchestrator.py` (12), `test_memory_integration.py` (8), `test_itinerary_payload_normalization.py` (3), `test_slot_state.py` (15), `test_generic_backend_steps.py` (2), `test_generic_meal_steps.py` (4), `test_osrm_client.py` (17).
2. **ara_conversation_orchestrator.py:** 110 líneas (no ~1500). Es un thin HTTP adapter que delega a `ConversationProcessor`.
3. **test_conversation_processor.py:** No existe. Reemplazado por `test_ara_v2_flow.py` (e2e, 12 tests) + `test_memory_integration.py` (8 tests).
4. **SSE streaming endpoint:** `POST /ara/sessions/{id}/generate-itinerary/stream` — es el único endpoint de generación. `/generate-itinerary` y `/generate-itinerary/async` fueron eliminados.
5. **Settings eliminadas:** `llm_retry_max_attempts`, `llm_retry_base_delay`, `llm_retry_max_delay`, `ara_default_language` — sin referencias en el código.
6. **Modelos ORM:** Son archivos SEPARADOS (no un solo `models.py`). `models/user.py`, `models/tourist_profile.py`, etc. El archivo `db/models.py` solo hace imports para Alembic.

### Archivos nuevos de la Refactorización (Fases 1-2)

- `ara_v2/slot_state.py` (80 líneas) — Funciones puras `is_slot_filled()` y `are_all_slots_filled()`, source of truth única para el estado de slots.
- `tests/unit/test_slot_state.py` (154 líneas, 15 tests) — Tests unitarios del ciclo completo de slots: `empty → category_selected → filled`.
- `tests/unit/test_generic_backend_steps.py` — Verifica que pasos genéricos NO crean `POIVisit`.
- `tests/unit/test_generic_meal_steps.py` — Verifica normalización y serialización de pasos genéricos.

### Archivos nuevos no documentados antes

- `ara_v2/geocoding_service.py` (124 líneas) — Geocodificación de destinos con GPT-4o-mini + cache + hardcoded fallback
- `ara_v2/category_mapping.py` (42 líneas) — Mapeo de intents a nombres canónicos de categorías
- `ara_v2/utils.py` (30 líneas) — Singleton de cliente GPT-4o-mini
- `ara_preference_merger.py` (224 líneas) — Extracción de preferencias de mensajes
- `ara_replacement_service.py` (102 líneas) — Contexto de reemplazo de step
- `ara_trip_draft_builder.py` (433 líneas) — Construcción de trip_draft
- `ara_message_normalizer.py` (19 líneas) — Normalización Unicode + typos
- `image_service.py` (61 líneas) — Validación de imágenes con magic bytes
- `poi_metadata_extractor.py` (396 líneas) — Extracción de metadata OSM
- `poi_search_service.py` (345 líneas) — Búsqueda de candidatos POI con geocoding
- `review_enrichment_service.py` (65 líneas) — Embedding + perfil dinámico de reviews
- `itinerary_weather_service.py` (249 líneas) — Lógica de clima por paso
- `core/token_blacklist.py` (49 líneas) — Blacklist de tokens JWT
- `core/rut.py` (36 líneas) — Validación de RUT chileno
- `core/llm_retry.py` (43 líneas) — Retry con backoff exponencial
- `core/itinerary_constants.py` (102 líneas) — Constantes de itinerarios
- `core/ara_constants.py` (546 líneas) — Catálogo central de Ara
- `core/ara_messages.py` (424 líneas) — Catálogo de mensajes Ara
- `api/v1/endpoints/shared.py` (27 líneas) — Endpoint público de sharing

---

*Fin del documento. Última revisión integral: 2026-06-05.*

---

## 17. Ara v2 — Asistente Conversacional

### 17.1 Visión General

Ara v2 es la segunda generación del asistente conversacional de Ruta Viva. Reemplaza el sistema monolítico de v1 (handlers hardcodeados) por una arquitectura modular basada en cuatro pilares:

1. **Comprensión semántica** (GPT-4o-mini) — entiende la intención del usuario en lenguaje natural, no por reglas.
2. **Memoria persistente** (embeddings en PostgreSQL/HNSW) — recuerda preferencias y restricciones del usuario entre sesiones.
3. **Orquestación de herramientas** — ejecuta `search_pois`, `get_weather`, `build_itinerary`, `answer_question`, `replace_step`, `geocode_destination` según la intención detectada.
4. **Respuestas naturales** (GPT-4o-mini) — genera texto contextual con quick replies solo cuando hay decisiones puntuales.

### 17.2 Arquitectura

```
Usuario → Endpoint HTTP → ConversationProcessor (app/services/ara_v2/conversation_processor.py:29)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              MemoryService    Comprensor      ToolOrchestrator
              (recuperar)    (GPT-4o-mini)   (ejecutar tools)
              memory_service  comprehender    tool_orchestrator
              .py:24          .py:71          .py:33
                    │               │               │
                    ▼               ▼               ▼
              conversation_   Comprehension   ToolExecution
              memory table      Result          Result
                                    │
                                    ▼
                          ResponseGenerator
                          (GPT-4o-mini + fallbacks)
                          response_generator.py:48
                                    │
                                    ▼
                          AraSessionResponse
```

### 17.3 Servicios del Subsistema (`app/services/ara_v2/`)

| Archivo | Líneas | Responsabilidad |
|---------|--------|----------------|
| `conversation_processor.py` | 662 | Orquestador principal. `process_user_message()` con flujo de 10 pasos: memoria → comprensión → hechos → herramientas → respuesta. `update_session_intent()` para cambios de UI. |
| `tool_orchestrator.py` | 663 | Motor de ejecución de herramientas. `execute()` rutea según `herramientas_necesarias`: search_pois, build_itinerary, answer_question, replace_step, geocode_destination, update_preferences, generate_trip_draft, show_options, confirm_plan, review_memories, consolidate_memories. |
| `comprehender.py` | 208 | Wrapper GPT-4o-mini con JSON schema estricto. `comprehend()` con `sanitize_user_message()` y `detect_prompt_injection()`. Fallback a `comprehension_fallback.py` si el LLM falla. |
| `comprehension_fallback.py` | 185 | `fallback_comprehend()` — reglas deterministas por keywords y patrones. Detección de build_itinerary, search_pois, answer_question, preferencias. Categorías: naturaleza, gastronomía, cultura, aventura, alojamiento, termas. |
| `response_generator.py` | 381 | Genera respuestas naturales con GPT-4o-mini. `_generate_search_response()`, `_generate_itinerary_response()`, `_generate_clarify_response()`, `_build_quick_replies()`, `_contextual_quick_replies()`. Catálogo de fallbacks por status. |
| `answer_service.py` | 133 | RAG sobre descripciones de POIs para responder preguntas puntuales (`answer_question()`). Evidence level tracking. |
| `prompt_manager.py` | 187 | Sistema de prompts: `build_comprehension_prompt()` y `build_generation_prompt()`. `_COMPREHENSION_SYSTEM`: reglas de extracción de intenciones, entidades, memoria, modos (auto/mixto/guiado). `_GENERATION_SYSTEM`: reglas de generación de itinerarios (3-6 actividades/día, distancias, clima). |
| `memory_service.py` | 185 | CRUD de memoria semántica con embeddings. `store_fact()`, `store_facts_batch()` (batch embedding), `retrieve_relevant_facts()` (HNSW), `update_tourist_profile_embedding()`, `delete_memory()`, `consolidate_memories()`. Aislamiento estricto por tourist_id. |
| `geocoding_service.py` | 124 | `geocode_destination()` — resuelve nombres de destino a coordenadas. 3 niveles: cache en memoria → GPT-4o-mini → hardcoded fallback (52 destinos de La Araucanía). |
| `category_mapping.py` | 42 | `CATEGORY_INTENT_TO_DB_NAMES`: mapeo de intents del compresor (ej: "gastronomía" → ["Gastronomía"]) a nombres canónicos de DB. `DB_NAME_TO_INTENTS`: mapeo inverso para debugging. |
| `utils.py` | 30 | `get_gpt_mini_client()` — singleton `AsyncOpenAI` para GPT-4o-mini con timeout de `settings.gpt_mini_timeout_seconds`. |

### 17.4 Migración desde v1

| Archivo v1 | Reemplazado por | Razón |
|-----------|----------------|-------|
| `ara_turn_classifier.py` | `comprehender.py` | Clasificación por reglas → comprensión semántica con LLM |
| `ara_preference_merger.py` | `memory_service.py` | Merge de preferencias en dict → memoria semántica con embeddings |
| `ara_response_builder.py` | `response_generator.py` | Quick replies hardcodeados → respuestas naturales con GPT-4o-mini |
| `ara_constants.py` (parcialmente) | Varios | Términos hardcodeados → config DB + servicios específicos |
| `ara_chat_service.py` (269 líneas) | `response_generator.py` + `answer_service.py` | Chat genérico → respuestas contextuales + RAG |
| `ara_itinerary_generation.py` (401 líneas) | `ara_itinerary_core.py` | Generación monolítica → pipeline de 7 fases con callback pattern |

**Lo que NO cambió:** Los endpoints HTTP y los schemas de request/response son idénticos. El frontend no se entera de la migración.

### 17.5 Contratos HTTP

| Endpoint | Método | Handler v2 | Request | Response |
|----------|--------|------------|---------|----------|
| `/api/v1/ara/sessions` | POST | `create_session_v2()` | `AraSessionCreate` | `AraSessionResponse` (201) |
| `/api/v1/ara/sessions/{id}/messages` | POST | `handle_message_v2()` | `AraMessageCreate` | `AraSessionResponse` (200) |
| `/api/v1/ara/sessions/{id}/messages` | GET | `get_session_messages()` | — | `AraMessagesResponse` (200) |
| `/api/v1/ara/sessions/{id}/intent` | PATCH | `update_session_intent()` | `AraIntentUpdate` | `AraSessionResponse` (200) |
| `/api/v1/ara/sessions/{id}/generate-itinerary/stream` | POST | `stream_generate_itinerary()` | `AraGenerateItineraryRequest` (opcional) | `text/event-stream` (200) |

### 17.6 Flujo de Conversación (10 pasos)

```
POST /ara/sessions/{id}/messages
  → ara_conversation_orchestrator.handle_message_v2()  [app/services/ara_conversation_orchestrator.py, 110 líneas]
    → ConversationProcessor.process_user_message()      [app/services/ara_v2/conversation_processor.py:29]

      PASO 1: memory_service.retrieve_relevant_facts(5 hechos más cercanos por HNSW)
      PASO 2: _get_recent_messages() — últimos 10 mensajes de la sesión
      PASO 3: comprensor.comprehend(msg, context, facts, trip_draft)
              → GPT-4o-mini analiza intención, entidades, preferencias, memoria
              → Si falla: fallback_comprehend() rule-based
      PASO 4: memory_service.store_facts_batch() — batch embedding → INSERT conversation_memories
              → Si falla batch: store_fact() individual con fallback sin embedding
      PASO 5: Actualizar TouristProfile.interests_embedding si preferencia > 0.8
      PASO 6: Persiste mensaje del usuario
      PASO 7: tool_orchestrator.execute(comprehension, session, user, db)
              → Gate fuera de dominio: intención "general" + confianza < 0.4 → clarify
              → Rutea según herramientas_necesarias:
                • search_pois: search_candidate_pois() → diversifica → quick replies
                • answer_question: answer_service.answer_question() sobre POI
                • build_itinerary + fechas: status="ready_to_generate", msg con stream_url
                • replace_step: search_step_replacement_alternatives()
              → _resolve_poi_reference() para detectar selección de POI por nombre
      PASO 8: Si build_itinerary con fechas → retorna AraSessionResponse con stream_url
      PASO 9: response_generator.generate_response(comprehension, tool_result, session)
              → GPT-4o-mini genera respuesta natural en español
              → Fallbacks estructurados por status (generate/search/respond/clarify/replace/error)
      PASO 10: Persiste mensaje del asistente + quick replies
    → AraSessionResponse
```

### 17.7 Generación SSE de Itinerario

```
POST /ara/sessions/{id}/generate-itinerary/stream  [app/api/v1/endpoints/ara.py]
  → ara_streaming_service.stream_itinerary_generation()  [app/services/ara_streaming_service.py:36]
    → Crea asyncio.Queue para eventos SSE
    → _on_phase callback: encola eventos status/warning/result/error
    → Lanza generate_itinerary_core() en asyncio.Task  [app/services/ara_itinerary_core.py:62]
      → Fase 1-7 secuenciales (validating → query → search → weather → LLM → repair → save)
      → Si < 5 POIs, emite evento "warning" con action="expand_search"
    → Loop SSE: event_queue.get() timeout 1s, yield "event: {type}\ndata: {json}\n\n"
    → CancelledError: marca itinerary como abandoned
```

**Eventos SSE:** `status` (phase + message), `warning` (message + poi_count + action), `result` (session_id + status + itinerary), `error` (message).

### 17.8 Memoria Semántica

La tabla `conversation_memories` (`models/conversation_memory.py`, 40 líneas) almacena hechos con embeddings:

1. Al recibir un mensaje, `retrieve_relevant_facts()` busca los 5 hechos más cercanos por cosine similarity (HNSW).
2. El compresor extrae `actualizaciones_memoria` del mensaje (nuevos hechos para guardar).
3. `store_facts_batch()` genera embeddings en batch y los inserta.
4. Si la categoría es `"preferencia"` y confianza > 0.8, actualiza `TouristProfile.interests_embedding` (media móvil exponencial: 90% perfil + 10% nuevo hecho).
5. Si falla batch embedding: fallback individual con `store_fact()`.
6. Si falla embedding individual: guarda el hecho sin embedding (último recurso).
7. Aislamiento estricto: solo se recuperan hechos del mismo `tourist_id`.

### 17.9 Configuración

Variables de entorno relevantes para Ara v2:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | API key de OpenAI (embeddings + GPT-4o-mini) |
| `DEEPSEEK_API_KEY` | — | API key de DeepSeek (generación de itinerarios) |
| `OPENWEATHER_API_KEY` | — | API key de OpenWeatherMap (pronóstico) |
| `OPENAI_GPT_MINI_MODEL` | `gpt-4o-mini` | Modelo para comprensión y respuestas |
| `GPT_MINI_TIMEOUT_SECONDS` | `10.0` | Timeout para GPT-4o-mini |

### 17.10 Tests de Ara v2

| Archivo | Tests | Área |
|---------|-------|------|
| `tests/unit/ara_v2/test_comprehender.py` | 29 | Comprensión LLM + fallback |
| `tests/unit/ara_v2/test_response_generator.py` | 14 | Generación de respuestas |
| `tests/e2e/test_ara_v2_flow.py` | 12 | Flujo conversacional end-to-end |
| `tests/unit/ara_v2/test_tool_orchestrator.py` | 12 | Ejecución de herramientas |
| `tests/unit/ara_v2/test_prompt_manager.py` | 8 | Construcción de prompts |
| `tests/unit/ara_v2/test_memory_integration.py` | 8 | Integración de memoria |
| `tests/unit/ara_v2/test_memory_service.py` | 6 | CRUD de memoria semántica |
| `tests/unit/ara_v2/test_itinerary_payload_normalization.py` | 3 | Normalización de payload |

**Total Ara v2: ~92 tests** (80 unitarios + 12 e2e).
