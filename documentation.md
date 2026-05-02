# Documentación Técnica Viva — Backend Ruta Viva

> Última actualización integral: **2026-05-02**
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
- creación de POIs con embedding automático,
- búsqueda geoespacial,
- búsqueda semántica/híbrida basada en embeddings OpenAI,
- generación de itinerarios con DeepSeek,
- persistencia de itinerarios e itinerarios por pasos,
- ingesta masiva de POIs reales desde OpenStreetMap/Overpass,
- sistema de reviews con embeddings semánticos,
- perfil dinámico de intereses del turista,
- búsqueda híbrida personalizada por perfil cuando existe usuario autenticado,
- migraciones Alembic operativas,
- y metadata ORM correctamente registrada para futuras autogeneraciones.

## 3.2 Funcionalidades ya implementadas y operativas
### Infraestructura y arranque
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
- `GET /api/v1/users/me` retorna el usuario autenticado.
- la autenticación usa `HTTPBearer` + validación JWT con `python-jose`.

### POIs
- `POST /api/v1/pois/` crea POIs autenticados.
- en la creación se genera automáticamente `description_embedding` con OpenAI.
- `GET /api/v1/pois/search` hace búsqueda geográfica por radio.
- `GET /api/v1/pois/semantic-search` hace búsqueda híbrida actual: filtro por radio + ranking semántico por cosine distance.

### Reviews y perfil dinámico
- `POST /api/v1/reviews/` permite a turistas autenticados crear valoraciones.
- cada review genera un embedding del texto con OpenAI.
- la review se persiste con `text_embedding`.
- el perfil del turista se actualiza en `tourist_profiles.interests_embedding` usando media móvil exponencial.
- `GET /api/v1/reviews/poi/{poi_id}` permite ver reseñas de un POI específico.

### Itinerarios
- `POST /api/v1/itineraries/generate` genera un itinerario turístico con DeepSeek.
- el endpoint:
  - recibe consulta de usuario + coordenadas + radio + fechas,
  - genera embedding de la query con OpenAI,
  - recupera POIs relevantes con `POIRepository.search_hybrid`,
  - envía esos POIs a DeepSeek bajo un prompt estricto,
  - valida el JSON devuelto,
  - verifica que el LLM no inventó POIs fuera del contexto,
  - persiste `Itinerary` e `ItineraryStep`,
  - y devuelve el itinerario completo guardado.

## 3.3 Funcionalidades presentes pero aún incompletas
- `app/services/geo_service.py` existe pero está vacío.
- `app/services/rag_service.py` existe pero está vacío.
- no hay tests automatizados todavía.
- no hay autorización fina por roles más allá de checks puntuales.
- no existe aún pipeline RAG completo de ingesta, chunking, retrieval y respuesta final.
- no hay observabilidad formal, métricas ni tracing.
- no hay capa formal de service/orchestration para todos los casos de uso; parte de la lógica sigue en endpoints y repositories.

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
├── ruta_viva/
│   ├── alembic.ini
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── Dockerfile.db
│   ├── requirements.txt
│   ├── scripts/
│   │   └── init_db.sql
│   ├── migrations/
│   │   ├── README
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 13e4146989e2_initial_schema_with_dynamic_vector_.py
│   │       └── 82d1bcc33432_fix_poi_description_embedding_openai_1536.py
│   └── app/
│       ├── main.py
│       ├── api/
│       │   ├── deps.py
│       │   └── v1/
│       │       ├── api.py
│       │       └── endpoints/
│       │           ├── auth.py
│       │           ├── itineraries.py
│       │           ├── pois.py
│       │           └── users.py
│       ├── core/
│       │   ├── config.py
│       │   └── security.py
│       ├── db/
│       │   ├── base.py
│       │   ├── models.py
│       │   └── session.py
│       ├── models/
│       │   ├── bookmark.py
│       │   ├── category.py
│       │   ├── entrepreneur_profile.py
│       │   ├── itinerary.py
│       │   ├── itinerary_step.py
│       │   ├── poi.py
│       │   ├── poi_category.py
│       │   ├── review.py
│       │   ├── tourist_profile.py
│       │   └── user.py
│       ├── repositories/
│       │   ├── itinerary_repository.py
│       │   ├── poi_repository.py
│       │   └── user_repository.py
│       ├── schemas/
│       │   ├── itinerary.py
│       │   ├── poi.py
│       │   ├── token.py
│       │   ├── tourist_profile.py
│       │   └── user.py
│       └── services/
│           ├── embedding_service.py
│           ├── geo_service.py
│           ├── llm_service.py
│           └── rag_service.py
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

### `app/core/`
Responsable de infraestructura transversal:
- configuración vía settings,
- seguridad JWT,
- hashing de passwords.

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
- flush/commit/rollback,
- rehidratación a schemas de salida.

### `app/services/`
Responsable de integraciones externas o lógica de orquestación especializada:
- embeddings OpenAI,
- generación de itinerarios con DeepSeek,
- espacios reservados para geológica y RAG.

## 6.2 Estado real de la separación
La separación existe y es útil, pero todavía no está llevada al máximo. Actualmente:
- hay endpoints delgados en autenticación y usuarios,
- hay lógica de integración en services para IA,
- hay persistencia encapsulada en repositories,
- pero algunos endpoints todavía orquestan parte importante del caso de uso directamente.

Esto no es incorrecto en esta etapa, pero sí marca un punto de evolución futura hacia services de aplicación más completos.

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
- `access_token_expire_minutes`

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
ACCESS_TOKEN_EXPIRE_MINUTES=10080
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
4. devuelve `Token(access_token=..., token_type="bearer")`.

## 8.3 Validación de usuario autenticado
La dependencia `get_current_user`:
1. recibe `HTTPAuthorizationCredentials` vía `HTTPBearer`,
2. decodifica JWT con `settings.secret_key` y `settings.algorithm`,
3. extrae `sub`,
4. lo transforma a `UUID`,
5. carga el usuario desde base,
6. y devuelve la entidad `User` si todo es válido.

## 8.4 Estado actual de autorización
Hay autenticación funcional, pero autorización fina aún parcial.

### Casos actuales
- `GET /users/me` solo exige usuario autenticado.
- `POST /pois/` exige usuario autenticado, pero no impone formalmente que deba ser emprendedor; si el usuario tiene `entrepreneur_profile`, se usa como `entrepreneur_id`, y si no, queda `None`.
- `POST /itineraries/generate` sí valida específicamente que `current_user.tourist_profile is not None`.

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
- `admin_data: JSONB | None`

Relaciones:
- `pois`

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

Relaciones:
- `entrepreneur`
- `category_links`
- `bookmarks`
- `reviews`
- `itinerary_steps`

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

### `Itinerary`
Cabecera del itinerario generado o planificado.
Campos relevantes:
- `tourist_id`
- `title`
- `start_date`
- `end_date`
- `status`

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
- `TokenPayload`
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

## 15.8 `POST /api/v1/itineraries/generate`
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
3. genera embedding de `payload.query`,
4. busca `context_pois` con `POIRepository.search_hybrid`,
5. si no hay POIs devuelve `404`,
6. enriquece la query con fechas, ubicación y radio,
7. envía consulta y POIs a `ItineraryGenerator`,
8. valida el JSON generado con `GeneratedItinerary`,
9. comprueba que todos los `poi_id` estén dentro de `context_pois`,
10. si el LLM inventó lugares devuelve `502`,
11. si el LLM no devolvió pasos devuelve `502`,
12. persiste `Itinerary` e `ItineraryStep`,
13. retorna `ItineraryResponse` completo.


---

## 15.9 `POST /api/v1/reviews/`
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
4. genera embedding del texto de la review con OpenAI,
5. persiste la review en `reviews`, incluyendo `text_embedding`,
6. actualiza `tourist_profiles.interests_embedding`,
7. confirma transacción,
8. devuelve `ReviewResponse`.

### Importancia técnica
Este endpoint es la primera feature donde una acción explícita del usuario modifica su representación semántica interna. La review no solo queda como contenido histórico; también se convierte en señal vectorial para personalización.

## 15.10 `GET /api/v1/reviews/poi/{poi_id}`
Archivo:
- `app/api/v1/endpoints/reviews.py`

Flujo:
1. recibe `poi_id` como path param,
2. consulta reviews asociadas a ese POI,
3. ordena por `created_at DESC`,
4. devuelve lista de `ReviewResponse`.

Este endpoint es público y sirve para visualizar la reputación/opiniones asociadas a un lugar.

## 15.11 Búsqueda semántica personalizada
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

## 15.12 Itinerarios con retrieval personalizado
Archivo:
- `app/api/v1/endpoints/itineraries.py`

El endpoint de itinerarios ya exigía usuario turista autenticado. Ahora, al llamar a `search_hybrid`, también pasa:

```python
user_interests_embedding=current_user.tourist_profile.interests_embedding
```

Esto significa que los POIs que entran como contexto para DeepSeek ya no dependen solo de la consulta puntual, sino también del perfil aprendido del turista. Por lo tanto, el grounding del itinerario queda personalizado.


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
- persiste POIs con `POIRepository.create_poi`,
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
- se reutilizó `POIRepository.create_poi`,
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


## 24. Estado final al cierre de esta actualización
Hoy el backend puede:

- autenticar usuarios,
- identificar al usuario actual,
- crear POIs con embedding automático,
- buscar POIs por cercanía,
- buscar POIs por intención semántica dentro de un radio,
- personalizar búsquedas semánticas con perfil dinámico cuando hay turista autenticado,
- crear reviews con embeddings semánticos,
- actualizar el perfil de intereses del turista con cada review,
- generar itinerarios con contexto recuperado y personalizado,
- persistir itinerarios y pasos,
- mantener su esquema versionado con Alembic sobre una metadata ORM correctamente registrada,
- e importar masivamente POIs reales desde OpenStreetMap para enriquecer el contexto del sistema.

La siguiente gran etapa natural del proyecto sería profundizar:
- autorización por roles,
- tests automatizados,
- services de aplicación más ricos,
- ranking híbrido más avanzado,
- endpoints para editar/eliminar reviews,
- métricas agregadas por POI,
- y evolución hacia RAG completo.
