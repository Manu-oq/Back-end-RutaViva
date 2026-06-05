# OSRM — Routing Engine para Ruta Viva

OSRM (Open Source Routing Machine) calcula tiempos de traslado y distancias
reales entre puntos geográficos usando datos de OpenStreetMap. El backend
de Ruta Viva lo usa para validar coherencia geográfica entre paradas de
itinerarios y para mostrar tiempos estimados de viaje.

## Requisitos

- Docker (20.10+)
- ~3 GB de espacio en disco (PBF ~700 MB + datos procesados ~2 GB)
- 4+ GB de RAM recomendados para el procesamiento

## Setup inicial (una sola vez)

```bash
# Desde el directorio raíz del proyecto (ruta_viva/)
cd ruta_viva

# 1. Ejecutar script de setup (descarga PBF + procesa datos)
bash scripts/setup_osrm.sh
```

Este script:
1. Descarga `chile-latest.osm.pbf` (~700 MB) desde Geofabrik
2. Extrae los datos con `osrm-extract` (5-15 min)
3. Particiona el grafo con `osrm-partition` (1-5 min)
4. Customiza los pesos con `osrm-customize` (1-5 min)

Los datos procesados se guardan en `osrm_data/`.

## Levantar el servidor

```bash
# Solo OSRM
docker compose up -d osrm

# OSRM + API + DB (stack completo)
docker compose --profile routing up -d
```

OSRM queda disponible en `http://localhost:5000`.

## Verificar que funciona

```bash
# Ruta simple: Temuco a Pucón (~100 km)
curl "http://localhost:5000/route/v1/driving/-72.667,-38.900;-71.977,-39.282?overview=false"
```

Respuesta esperada (200 OK):
```json
{
  "code": "Ok",
  "routes": [{
    "distance": 102348.5,
    "duration": 4680.2
  }]
}
```

## API OSRM — Endpoints útiles

| Endpoint | Uso |
|----------|-----|
| `GET /route/v1/driving/{lon},{lat};{lon},{lat}` | Ruta punto a punto |
| `GET /table/v1/driving/{lon},{lat};{lon},{lat};...` | Matriz de tiempos entre múltiples puntos |
| `GET /nearest/v1/driving/{lon},{lat}` | POI más cercano en la red vial |

Parámetros comunes:
- `?overview=false` — solo devuelve distancia/duración, no geometría
- `?sources=0&destinations=1;2;3` — para table, especificar orígenes y destinos

## Actualizar datos

Chile se actualiza diariamente en Geofabrik. Para refrescar los datos:

```bash
rm osrm_data/chile-latest.osm.pbf
bash scripts/setup_osrm.sh
docker compose restart osrm
```

## Troubleshooting

| Error | Causa probable | Solución |
|-------|---------------|----------|
| `No such file or directory: /data/chile-latest.osrm` | No ejecutaste setup_osrm.sh | Ejecutar `bash scripts/setup_osrm.sh` |
| `curl: (7) Failed to connect` | OSRM no está corriendo | `docker compose up -d osrm` |
| `wget: command not found` | Falta wget | `sudo apt install wget` o `brew install wget` |
| Memoria insuficiente durante extract | RAM < 4 GB | Agregar `--memory=4g` al docker run en setup_osrm.sh |
