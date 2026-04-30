# Documentación Técnica Viva — Backend Ruta Viva

> Este archivo es una **plantilla evolutiva**. Debe actualizarse en cada sesión relevante para dejar trazabilidad técnica real del backend.

---

## 1. Objetivo del documento
Registrar de forma continua:

- qué se construyó,
- qué decisiones técnicas se tomaron,
- qué problemas aparecieron,
- cómo se resolvieron,
- qué archivos cambiaron,
- qué queda pendiente.

Este documento **no debe resumirse en exceso**. Debe servir como memoria técnica acumulativa del proyecto.

---

## 2. Cómo mantener este documento
Actualizar este archivo cuando ocurra cualquiera de estos eventos:

- creación de nuevos módulos,
- cambios de arquitectura,
- incorporación de librerías o infraestructura,
- cambios en Docker, base de datos o migraciones,
- problemas técnicos relevantes,
- cambios de convenciones,
- implementación de endpoints, servicios o repositorios,
- cambios en seguridad, autenticación, RAG o despliegue.

### Reglas de mantenimiento
1. No borrar historial importante.
2. Agregar nuevas entradas por fecha/sesión.
3. Si una decisión cambia, registrar el cambio y el motivo.
4. Si se corrige un error, documentar síntoma, causa y solución.
5. Mantener actualizadas las secciones de estado actual y próximos pasos.

---

## 3. Resumen ejecutivo actual

### Estado general
Backend en fase inicial de infraestructura + persistencia + arranque FastAPI.

### Ya implementado
- estructura base del proyecto,
- configuración centralizada con `pydantic-settings`,
- PostgreSQL en Docker,
- soporte para `pgvector` y `PostGIS`,
- modelos SQLAlchemy 2.0 async,
- Alembic async,
- endpoint `GET /health`,
- registro y login con JWT,
- dependencia global para endpoints protegidos,
- endpoint protegido `GET /users/me`,
- creación y búsqueda geoespacial de POIs,
- sesión asíncrona con `AsyncSession`.

### Aún pendiente
- servicios de negocio más completos,
- control de roles/permisos por tipo de usuario,
- lógica RAG,
- tests automatizados,
- observabilidad,
- despliegue formal.

---

## 4. Estructura actual del proyecto

```text
ruta_viva/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── api.py
│   │       └── endpoints/
│   ├── core/
│   │   ├── config.py
│   │   └── security.py
│   ├── db/
│   │   ├── models.py
│   │   ├── base.py
│   │   └── session.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── bookmark.py
│   │   ├── category.py
│   │   ├── entrepreneur_profile.py
│   │   ├── itinerary.py
│   │   ├── itinerary_step.py
│   │   ├── poi.py
│   │   ├── poi_category.py
│   │   ├── review.py
│   │   ├── tourist_profile.py
│   │   └── user.py
│   ├── schemas/
│   │   ├── poi.py
│   │   ├── token.py
│   │   ├── tourist_profile.py
│   │   └── user.py
│   ├── repositories/
│   │   ├── poi_repository.py
│   │   └── user_repository.py
│   └── main.py
├── migrations/
│   ├── env.py
│   └── versions/
├── scripts/
│   └── init_db.sql
├── Dockerfile
├── Dockerfile.db
├── docker-compose.yml
├── requirements.txt
└── alembic.ini
```

---

## 5. Arquitectura y convenciones vigentes

### Arquitectura base
Separación inspirada en Clean Architecture:

- `api/` → exposición HTTP,
- `services/` → casos de uso y lógica de negocio,
- `repositories/` → acceso a datos,
- `models/` → persistencia ORM,
- `core/` → configuración transversal,
- `db/` → engine, metadata y sesiones.

### Convenciones de naming
- módulos: `snake_case`
- clases: `PascalCase`
- tablas: plural
- identificadores principales: `UUID` salvo `Category`
- relaciones ORM con `back_populates`

### Convenciones ORM
- SQLAlchemy 2.0 moderno,
- uso de `Mapped[...]`,
- uso de `mapped_column(...)`,
- carga `selectin` o `noload` según el caso.

---

## 6. Estado técnico por componente

### 6.1 Configuración
**Estado:** Implementado

**Archivos:**
- `ruta_viva/app/core/config.py`

**Notas:**
- se usa `BaseSettings`,
- se leen variables de entorno de `.env`,
- se construye `async_database_uri` con `postgresql+asyncpg://`.

### 6.2 Base de datos
**Estado:** Implementado y operativo

**Notas:**
- PostgreSQL corre en Docker,
- se requieren extensiones `vector` y `postgis`,
- se usa imagen custom vía `Dockerfile.db`.

### 6.3 ORM
**Estado:** Implementado

**Notas:**
- modelos creados según ERD,
- tipos espaciales y vectoriales operativos,
- tablas físicas ya creadas.

### 6.4 Migraciones
**Estado:** Implementado con ajustes manuales

**Notas:**
- Alembic async configurado,
- migración inicial generada,
- se corrigieron imports y duplicidad de índice espacial.

### 6.5 API FastAPI
**Estado:** Parcialmente implementado

**Notas:**
- `app/main.py` existe,
- CORS abierto temporalmente,
- endpoint `/health` implementado,
- routers v1 agregados para `auth`, `users` y `pois`,
- endpoint protegido `GET /users/me`,
- endpoint público `GET /pois/search`,
- endpoint protegido `POST /pois/`.

### 6.6 Seguridad
**Estado:** Base implementada

**Notas:**
- hashing de passwords con `bcrypt_sha256`,
- login JWT implementado,
- dependencia `get_current_user` usando `HTTPBearer`,
- falta autorización por roles/permisos finos.

### 6.7 Repositorios
**Estado:** Parcialmente implementado

**Notas:**
- `UserRepository` implementado para registro y búsqueda por email/id,
- `POIRepository` implementado para creación y búsqueda geoespacial.

### 6.8 Testing
**Estado:** Pendiente

### 6.9 RAG / embeddings / búsqueda semántica
**Estado:** Parcialmente preparado a nivel de modelo, pendiente de implementación funcional

---

## 7. Registro evolutivo por sesión

> Agregar una nueva entrada por cada sesión importante.

### Plantilla de entrada

```md
### [YYYY-MM-DD] Título corto de la sesión

#### Objetivo
- 

#### Cambios realizados
- 

#### Archivos creados/modificados
- path/to/file

#### Decisiones técnicas
- 

#### Problemas encontrados
- 

#### Soluciones aplicadas
- 

#### Comandos relevantes
```bash
# comandos usados
```

#### Estado resultante
- 

#### Pendientes
- 
```

---

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
- `ruta_viva/migrations/versions/02e127623076_initial_schema.py`

#### Decisiones técnicas
- usar FastAPI + SQLAlchemy 2.0 async,
- usar PostgreSQL con `pgvector` y `PostGIS`,
- usar UUID nativo PostgreSQL,
- usar `Geometry('POINT', srid=4326)` para ubicación,
- usar `Vector(1536)` para embeddings,
- usar `selectin` y `noload` en relaciones ORM,
- usar `pydantic-settings` para configuración.

#### Problemas encontrados
- Alembic tomó `driver://...` desde el placeholder inicial,
- hubo conflicto de password por volumen persistente,
- `vector` no estaba habilitado inicialmente,
- la imagen base no traía PostGIS,
- faltaban imports manuales en la migración,
- el índice espacial fue duplicado por GeoAlchemy2 + Alembic.

#### Soluciones aplicadas
- corregir `alembic.ini` y `env.py`,
- recrear volumen Docker,
- verificar extensiones con `\dx`,
- crear `Dockerfile.db` con PostGIS,
- agregar imports en migración,
- eliminar el `create_index` espacial duplicado.

#### Comandos relevantes
```bash
docker compose down -v
docker compose up --build -d
source ../fastapi/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

#### Estado resultante
- tablas físicas creadas,
- extensiones disponibles,
- API arranca,
- conexión async operativa.

#### Pendientes
- routers,
- schemas,
- repositorios,
- servicios,
- autenticación,
- tests.

---

### [2026-04-18] DTOs, registro/login JWT, dependencia auth y capa inicial de POIs

#### Objetivo
- completar la FASE 2 del backend,
- agregar DTOs Pydantic,
- habilitar registro y login,
- preparar endpoints protegidos,
- implementar infraestructura inicial de POIs con PostGIS.

#### Cambios realizados
- se crearon schemas Pydantic v2 para `User`, `TouristProfile`, `Token` y `POI`,
- se implementó hashing de passwords y creación de JWT,
- se creó `UserRepository` con registro atómico de usuario turista,
- se implementaron endpoints `POST /auth/register` y `POST /auth/login`,
- se agregó la dependencia global `get_current_user`,
- se implementó `GET /users/me`,
- se implementó `POIRepository` con creación de geometría `POINT(lon lat)` y búsqueda con `ST_DWithin` + `ST_Distance`,
- se agregaron endpoints `POST /pois/` y `GET /pois/search`.

#### Archivos creados/modificados
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/core/security.py`
- `ruta_viva/app/api/deps.py`
- `ruta_viva/app/api/v1/api.py`
- `ruta_viva/app/api/v1/endpoints/auth.py`
- `ruta_viva/app/api/v1/endpoints/users.py`
- `ruta_viva/app/api/v1/endpoints/pois.py`
- `ruta_viva/app/schemas/user.py`
- `ruta_viva/app/schemas/tourist_profile.py`
- `ruta_viva/app/schemas/token.py`
- `ruta_viva/app/schemas/poi.py`
- `ruta_viva/app/repositories/user_repository.py`
- `ruta_viva/app/repositories/poi_repository.py`
- `ruta_viva/app/db/base.py`
- `ruta_viva/app/db/models.py`
- `ruta_viva/app/models/__init__.py`
- `ruta_viva/requirements.txt`

#### Decisiones técnicas
- usar Pydantic v2 con `ConfigDict(from_attributes=True)`,
- usar `HTTPBearer` en vez de `OAuth2PasswordBearer` para no forzar el flujo OAuth2 form en Swagger,
- usar `bcrypt_sha256` para evitar el límite de 72 bytes de bcrypt,
- fijar versiones compatibles de `passlib` y `bcrypt`,
- separar `Base` de un agregador `app/db/models.py` para evitar ciclos de importación,
- representar POIs hacia la API con `latitude/longitude` extraídos desde PostGIS en vez de exponer la geometría cruda.

#### Problemas encontrados
- imports circulares entre `app/db/base.py` y los modelos,
- falta de `email-validator` por uso de `EmailStr`,
- incompatibilidad entre `passlib` y versiones recientes de `bcrypt`,
- límite de 72 bytes de bcrypt al registrar passwords largos,
- confusión de Swagger con `OAuth2PasswordBearer` para un login JSON.

#### Soluciones aplicadas
- mover el registro agregador de modelos a `app/db/models.py`,
- dejar `app/models/__init__.py` neutro,
- agregar `email-validator`, `python-jose[cryptography]` y `python-multipart` a dependencias,
- fijar `passlib[bcrypt]==1.7.4` y `bcrypt==4.0.1`,
- cambiar a `bcrypt_sha256`,
- reemplazar `OAuth2PasswordBearer` por `HTTPBearer`.

#### Comandos relevantes
```bash
source ../fastapi/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

#### Estado resultante
- registro funcional,
- login JWT funcional,
- autenticación Bearer funcional,
- endpoint `/users/me` funcional,
- infraestructura inicial de POIs implementada.

#### Pendientes
- autorización por roles para distinguir turistas y emprendedores,
- validación de negocio para creación de POIs,
- endpoints CRUD adicionales de POIs,
- tests automatizados,
- integración real de embeddings y RAG.

---

## 8. Decisiones técnicas consolidadas

### 8.1 Base de datos
- PostgreSQL como DB principal.
- `pgvector` para embeddings.
- `PostGIS` para geolocalización.

### 8.2 Persistencia
- SQLAlchemy 2.0 async.
- Alembic para versionado de esquema.

### 8.3 API
- FastAPI.
- CORS abierto temporalmente en desarrollo.
- versionado de rutas mediante `/api/v1`.

### 8.4 Seguridad
- JWT firmado con `HS256`.
- autenticación Bearer con `HTTPBearer`.
- hashing de passwords con `bcrypt_sha256`.

### 8.5 Configuración
- `pydantic-settings` como mecanismo central de settings.
- `SECRET_KEY`, `ALGORITHM` y expiración del access token definidos en settings.

### 8.6 Infraestructura contenedorizada
- DB con imagen custom construida desde `ankane/pgvector:latest` + instalación de PostGIS.

---

## 9. Incidentes técnicos y soluciones

### Incidente: placeholder `driver://...` en Alembic
**Síntoma:** error `NoSuchModuleError`.

**Causa:** URL placeholder inválida.

**Solución:** configurar una URL PostgreSQL real y sobreescribirla desde `env.py`.

### Incidente: password inválida en PostgreSQL
**Síntoma:** `InvalidPasswordError`.

**Causa:** volumen Docker persistente con credenciales anteriores.

**Solución:** recrear contenedor y volumen.

### Incidente: extensión `vector` no existe
**Síntoma:** `type "vector" does not exist`.

**Causa:** extensión no cargada en la base actual.

**Solución:** recrear correctamente la DB y verificar `\dx`.

### Incidente: `postgis` no disponible
**Síntoma:** `extension "postgis" is not available`.

**Causa:** la imagen no incluía el paquete del sistema.

**Solución:** construir imagen custom con PostGIS.

### Incidente: índice espacial duplicado
**Síntoma:** `relation "idx_pois_location" already exists`.

**Causa:** doble creación del índice espacial.

**Solución:** eliminar la creación manual en la migración.

### Incidente: imports circulares en modelos
**Síntoma:** errores `partially initialized module` al importar modelos como `Bookmark` o `TouristProfile`.

**Causa:** `app/db/base.py` importaba todos los modelos mientras los modelos importaban `Base`.

**Solución:** dejar `Base` sola en `app/db/base.py`, crear `app/db/models.py` como agregador y mantener `app/models/__init__.py` neutro.

### Incidente: validación de EmailStr sin dependencia extra
**Síntoma:** `email-validator is not installed`.

**Causa:** `EmailStr` requiere dependencia adicional en Pydantic.

**Solución:** agregar `email-validator` a `requirements.txt`.

### Incidente: límite de bcrypt y compatibilidad de Passlib
**Síntoma:** errores por passwords de más de 72 bytes y `bcrypt has no attribute __about__`.

**Causa:** límite propio de bcrypt e incompatibilidad entre versiones recientes de `bcrypt` y `passlib`.

**Solución:** usar `bcrypt_sha256` y fijar versiones compatibles (`passlib[bcrypt]==1.7.4`, `bcrypt==4.0.1`).

---

## 10. Archivos críticos del backend

### Infraestructura
- `ruta_viva/docker-compose.yml`
- `ruta_viva/Dockerfile`
- `ruta_viva/Dockerfile.db`
- `ruta_viva/scripts/init_db.sql`
- `ruta_viva/requirements.txt`

### Configuración y arranque
- `ruta_viva/app/core/config.py`
- `ruta_viva/app/db/base.py`
- `ruta_viva/app/db/session.py`
- `ruta_viva/app/main.py`

### Persistencia
- `ruta_viva/app/models/*.py`
- `ruta_viva/migrations/env.py`
- `ruta_viva/migrations/versions/*.py`

---

## 11. Estado actual verificable

### Base de datos
- [x] contenedor operativo
- [x] PostgreSQL accesible por `psql`
- [x] extensión `vector`
- [x] extensión `postgis`
- [x] tablas creadas

### Backend
- [x] FastAPI arranca
- [x] endpoint `/health`
- [x] conexión async funcional
- [x] registro de usuario
- [x] login JWT
- [x] endpoint protegido `/users/me`
- [x] endpoints iniciales de POIs
- [ ] autorización por roles
- [ ] tests
- [ ] servicios RAG

---

## 12. Próximos pasos

### Próximo bloque técnico sugerido
1. definir autorización por roles (turista vs emprendedor),
2. endurecer validaciones de negocio en POIs,
3. crear CRUD adicional de POIs y categorías,
4. añadir tests de auth, usuarios y búsquedas geoespaciales,
5. crear primeros servicios de negocio,
6. comenzar capa RAG.

---

## 13. Sección de notas rápidas futuras
> Espacio libre para observaciones breves entre sesiones.

- 
- 
- 

---

## 14. Historial de actualizaciones de este documento

- 2026-04-18: convertido de documento descriptivo estático a plantilla evolutiva por sesiones.
- 2026-04-18: documentada la FASE 2 con DTOs, JWT, endpoints protegidos y capa inicial de POIs.
