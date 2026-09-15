# Documentación técnica — Backend Ruta Viva

## 1. Propósito y alcance

Este documento describe el estado actual del backend de Ruta Viva. Está dirigido a quien necesite ejecutar, revisar o extender la API; no es una bitácora de desarrollo ni un registro de cambios.

Ruta Viva es una plataforma de turismo inteligente para explorar puntos de interés, administrar información aportada por turistas y emprendedores, y construir itinerarios. La API expone contratos REST y un flujo SSE para el asistente Ara.

La referencia operativa de los endpoints es la documentación interactiva disponible en `/docs` cuando la API está en ejecución. El código y sus migraciones son la fuente de verdad para el esquema de datos.

## 2. Arquitectura

```text
Cliente Flutter
    │ REST / SSE
    ▼
FastAPI
├── api/v1/endpoints/   capa HTTP, validación y respuestas
├── services/           lógica de negocio e integraciones externas
├── repositories/       persistencia y consultas SQLAlchemy
├── models/             entidades ORM
├── schemas/            contratos Pydantic
└── db/                 sesión, metadata y bootstrap de base de datos
    │
    ▼
PostgreSQL + PostGIS + pgvector
```

Los handlers reciben la petición, validan el contrato y delegan. Las consultas viven en repositorios; los servicios concentran reglas de negocio, generación de embeddings, clima, geocodificación, rutas y el flujo conversacional.

## 3. Estructura del repositorio

```text
ruta_viva/
├── app/
│   ├── api/v1/endpoints/  routers HTTP por dominio
│   ├── core/              settings, seguridad, errores y utilidades
│   ├── db/                sesión y registro de modelos
│   ├── models/            entidades SQLAlchemy
│   ├── repositories/      acceso a datos
│   ├── schemas/           requests y responses Pydantic
│   └── services/          dominio, IA e integraciones
├── migrations/            historial Alembic
├── scripts/               ingesta y mantenimiento de datos
├── tests/                 pruebas unitarias, API y end-to-end
├── docker-compose.yml     API, PostgreSQL y perfil opcional OSRM
└── .env.example           plantilla de configuración local
```

## 4. Dominios funcionales

| Dominio | Responsabilidad |
|---|---|
| Auth y usuarios | Registro, login, refresh/logout JWT y perfiles de turista o emprendedor. |
| POIs y categorías | Catálogo, búsqueda geográfica/semántica, aportes, visitas, media y categorías. |
| Reviews y bookmarks | Opiniones, resumen de valoraciones y favoritos por usuario. |
| Itinerarios | Generación, pasos, reordenamiento, reprogramación, clima, exportación, visitas y enlaces compartibles. |
| Emprendedores | Métricas, actividad, POIs administrados y publicaciones asociadas. |
| Ara | Sesiones conversacionales, mensajes, preferencias, generación de itinerario y streaming SSE. |

Las entidades persistidas principales son `User`, `TouristProfile`, `EntrepreneurProfile`, `POI`, `Category`, `Review`, `Bookmark`, `Itinerary`, `ItineraryStep`, `AraSession`, `AraMessage`, `ConversationMemory` y `EntrepreneurPost`.

## 5. API e integración

Todos los routers se agrupan bajo `/api/v1`. Las áreas públicas principales son:

| Prefijo | Contenido |
|---|---|
| `/auth` y `/users` | Sesión, tokens y perfiles. |
| `/pois`, `/categories`, `/reviews`, `/bookmarks` | Catálogo turístico y acciones del usuario. |
| `/itineraries` | Gestión completa de itinerarios. |
| `/ara` | Conversación y generación de itinerarios por SSE. |
| `/entrepreneur` | Dashboard, métricas y publicaciones. |
| `/weather`, `/geocoding`, `/media` | Servicios auxiliares. |

Además, `GET /share/{public_id}` entrega un itinerario compartido y `GET /health` comprueba la conectividad de base de datos.

La API aplica autenticación JWT en las rutas que operan sobre datos de usuario. Los roles y la propiedad de recursos se validan antes de modificar POIs, itinerarios, reseñas o contenido de emprendedores.

## 6. Datos, búsqueda e IA aplicada

PostgreSQL usa PostGIS para coordenadas y consultas geográficas, y pgvector para embeddings. La búsqueda semántica y la generación de itinerarios dependen de proveedores externos configurados por variables de entorno.

Ara combina comprensión de intención, memoria de preferencias, búsqueda de POIs y generación de respuestas. Si un proveedor externo no está configurado, las rutas que requieren ese proveedor no están disponibles; el resto de la API sigue siendo ejecutable.

La ingesta, normalización, deduplicación y auditoría de POIs viven en `scripts/`. Los reportes generados y la base de datos no se distribuyen en el repositorio.

OSRM es opcional. Cuando no responde, el cliente de rutas utiliza una estimación basada en distancia geográfica. La preparación de datos de rutas para Chile está documentada en [ruta_viva/README-OSRM.md](ruta_viva/README-OSRM.md).

## 7. Configuración y ejecución

Parte desde `ruta_viva/`:

```bash
cp .env.example .env
docker compose up --build
```

`SECRET_KEY` es obligatoria y debe ser única por entorno. Las claves de OpenAI, DeepSeek y OpenWeatherMap solo son necesarias para sus respectivas funciones. Nunca se debe versionar `.env`.

Variables principales:

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Firma de JWT. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Conexión local de PostgreSQL. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Host y puerto de base de datos. |
| `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` | Embeddings y funciones conversacionales. |
| `OPENWEATHER_API_KEY` | Pronóstico climático. |
| `OSRM_BASE_URL` | Servicio de rutas opcional. |

Con el stack activo, FastAPI expone `/docs` y `/health` en el puerto 8000. Para ejecución sin Docker, inicia `docker compose up -d db`, instala `requirements.txt`, ejecuta `alembic upgrade head` y levanta `uvicorn app.main:app --reload`.

## 8. Migraciones

Alembic mantiene el esquema versionado en `migrations/versions/`.

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

Una migración nueva debe representar un cambio de esquema verificable y no incluir datos locales, credenciales ni archivos de salida de scripts.

## 9. Pruebas y calidad

Desde `ruta_viva/`:

```bash
pytest -q
```

La suite incluye pruebas unitarias, de endpoints y de flujos conversacionales. Las pruebas que crean o modifican POIs reemplazan el proveedor de embeddings por una implementación determinista local, por lo que no realizan llamadas a OpenAI ni requieren credenciales de producción.

## 10. Límites conocidos

- Una instalación nueva no contiene el catálogo histórico de POIs ni datos de demostración.
- Los servicios de IA, clima y rutas requieren su proveedor o datos locales correspondientes.
- El rate limit de creación de POIs está implementado a nivel de aplicación; una carga concurrente alta requeriría una estrategia atómica a nivel de base de datos o infraestructura.
- El proyecto se conserva como demostración académica y de portafolio; no se presenta como servicio desplegado en producción.

## 11. Regla de mantenimiento documental

Actualiza este documento solo cuando cambie una interfaz, una dependencia estructural, un flujo de ejecución o una decisión de arquitectura. Mantén el texto en presente, describe comportamiento verificable y evita agregar cronologías, porcentajes de avance o auditorías históricas.
