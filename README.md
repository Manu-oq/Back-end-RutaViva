# Ruta Viva — Backend

Backend de **Ruta Viva**, plataforma de turismo inteligente desarrollada como trabajo de título para explorar destinos de La Araucanía, descubrir puntos de interés y construir itinerarios personalizados.

La API reúne búsqueda geoespacial y semántica, autenticación, gestión de POIs, reseñas, favoritos, itinerarios y un asistente conversacional. El cliente Flutter vive en el repositorio [Front-end-RutaViva](https://github.com/Manu-oq/Front-end-RutaViva).

## Qué demuestra este proyecto

- API REST asíncrona con FastAPI, Pydantic y SQLAlchemy 2.0.
- Arquitectura por capas: endpoints, servicios, repositorios, modelos ORM y schemas.
- PostgreSQL con PostGIS para consultas geográficas y pgvector para búsqueda semántica.
- Autenticación JWT, control de roles, rate limiting y migraciones Alembic.
- Integración de OpenStreetMap, OpenWeatherMap y OSRM.
- Asistente conversacional para recomendaciones e itinerarios, con SSE y fallbacks deterministas.
- Suite automatizada de pruebas sin dependencia de credenciales externas.

## Arquitectura

```text
Flutter client
     │ REST / SSE
     ▼
FastAPI API
 ├── endpoints        HTTP y validación
 ├── services         lógica de negocio, IA e integraciones
 ├── repositories     consultas SQLAlchemy
 └── PostgreSQL       PostGIS + pgvector
        │
        ├── OpenStreetMap / Nominatim
        ├── OpenWeatherMap
        └── OSRM (opcional, rutas)
```

## Stack

| Área | Tecnologías |
|---|---|
| API | Python, FastAPI, Pydantic, Uvicorn |
| Datos | PostgreSQL, SQLAlchemy async, Alembic, PostGIS, pgvector |
| Seguridad | JWT, Passlib/bcrypt, SlowAPI |
| IA aplicada | Embeddings, búsqueda híbrida, modelos de lenguaje, SSE |
| Infraestructura | Docker Compose, Docker, pytest |

## Ejecución local

### Requisitos

- Docker y Docker Compose.
- Python 3.11+ solo si se ejecutará la API fuera de Docker.

### Levantar API y base de datos con Docker

```bash
git clone git@github.com:Manu-oq/Back-end-RutaViva.git
cd Back-end-RutaViva/ruta_viva
cp .env.example .env
```

Genera una clave local y asígnala a `SECRET_KEY` dentro de `.env`:

```bash
openssl rand -hex 32
```

Para explorar la aplicación sin las funciones de IA, las claves de OpenAI, DeepSeek y OpenWeatherMap pueden permanecer vacías. Nunca subas `.env` al repositorio.

```bash
docker compose up --build
```

La API queda disponible en:

- Documentación interactiva: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

Detén el stack con `Ctrl+C`; para eliminar contenedores ejecuta `docker compose down`.

### Ejecución sin Docker para la API

Primero inicia solo la base de datos:

```bash
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Datos y servicios opcionales

El repositorio no incluye una copia de la base de datos ni el conjunto completo de POIs. En una instalación nueva la API inicia correctamente, pero el mapa no tendrá contenido hasta importar datos. Esto evita distribuir datos generados, archivos voluminosos o credenciales.

OSRM es opcional: si no está disponible, el backend utiliza un cálculo de distancia de respaldo. Para preparar rutas reales de Chile se requieren aproximadamente 3 GB y se debe seguir la guía [README-OSRM.md](ruta_viva/README-OSRM.md).

## Pruebas

Desde `ruta_viva/`:

```bash
pytest -q
```

Las pruebas de integración sustituyen el proveedor de embeddings por una implementación determinista local. Por eso no hacen llamadas a OpenAI ni requieren una API key.

## Capturas del producto

Las capturas viven en el README del [cliente Flutter](https://github.com/Manu-oq/Front-end-RutaViva), ya que muestran el producto completo. Próximamente se incorporarán vistas de inicio, mapa y detalle de itinerario.

## Créditos de datos y servicios

- Datos cartográficos y geocodificación: OpenStreetMap y Nominatim.
- Enrutamiento: Open Source Routing Machine (OSRM).
- Información climática: OpenWeatherMap.

## Estado y uso

Proyecto académico terminado, mantenido como muestra técnica de portafolio. El código se publica para evaluación y aprendizaje; no cuenta todavía con una licencia de código abierto.
