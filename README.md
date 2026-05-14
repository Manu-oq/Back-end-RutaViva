# Back-end-RutaViva

Backend FastAPI para Ruta Viva, una plataforma de turismo inteligente para la Región de La Araucanía.

## Stack

- **FastAPI** como framework HTTP con validación Pydantic.
- **SQLAlchemy 2.0 async** como ORM con `asyncpg`.
- **PostgreSQL** con extensiones **PostGIS** (geoespacial) y **pgvector** (búsqueda semántica).
- **Alembic** para migraciones.
- **JWT** con `python-jose` para autenticación.
- **OpenAI** (`text-embedding-3-small`) para embeddings.
- **DeepSeek** (`deepseek-chat`) para generación de itinerarios.
- **OpenWeatherMap** para contexto climático.

## Cómo levantar

```bash
cd ruta_viva
docker compose up -d db          # levanta PostgreSQL + PostGIS + pgvector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head              # ejecuta migraciones
uvicorn app.main:app --reload     # inicia API
```

## Documentación detallada

Ver `documentation.md` para el registro técnico completo del backend.
