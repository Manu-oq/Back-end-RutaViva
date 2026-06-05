#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# OSRM Setup Script — Chile extract
# =============================================================================
# Descarga el extracto PBF de Chile desde Geofabrik y lo procesa con OSRM.
# Requiere Docker. Los archivos procesados pesan ~2-3 GB en total.
# Tiempo estimado total: 15-40 min (depende de CPU, RAM y descarga).
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/../osrm_data"
OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:latest"
PBF_URL="https://download.geofabrik.de/south-america/chile-latest.osm.pbf"
PBF_FILE="${DATA_DIR}/chile-latest.osm.pbf"
PROFILE="${OSRM_PROFILE:-car}"

mkdir -p "${DATA_DIR}"

# ---- Step 1: Download PBF ----
if [ -f "${PBF_FILE}" ]; then
    echo "✓ ${PBF_FILE} ya existe. Saltando descarga."
else
    echo "↓ Descargando Chile PBF desde Geofabrik (~700 MB)..."
    wget -q --show-progress -O "${PBF_FILE}" "${PBF_URL}" || {
        echo "✗ Falló la descarga. Reintentá manualmente:"
        echo "  wget -O ${PBF_FILE} ${PBF_URL}"
        exit 1
    }
    echo "✓ Descarga completada."
fi

# ---- Step 2: Extract ----
if [ -f "${DATA_DIR}/chile-latest.osrm" ]; then
    echo "✓ Datos OSRM ya extraídos. Saltando extracción."
else
    echo "▶ Extrayendo datos del PBF (5-15 min)..."
    docker run --rm \
        -v "${DATA_DIR}:/data" \
        "${OSRM_IMAGE}" \
        osrm-extract -p "/opt/${PROFILE}.lua" /data/chile-latest.osm.pbf || {
        echo "✗ Falló osrm-extract. Verificá que el PBF no esté corrupto."
        exit 1
    }
    echo "✓ Extracción completada."
fi

# ---- Step 3: Partition ----
if [ -f "${DATA_DIR}/chile-latest.osrm.partition" ]; then
    echo "✓ Datos ya particionados. Saltando."
else
    echo "▶ Particionando grafo (1-5 min)..."
    docker run --rm \
        -v "${DATA_DIR}:/data" \
        "${OSRM_IMAGE}" \
        osrm-partition /data/chile-latest.osrm || {
        echo "✗ Falló osrm-partition."
        exit 1
    }
    echo "✓ Particionamiento completado."
fi

# ---- Step 4: Customize ----
if [ -f "${DATA_DIR}/chile-latest.osrm.cell_metrics" ]; then
    echo "✓ Datos ya customizados. Saltando."
else
    echo "▶ Customizando pesos del grafo (1-5 min)..."
    docker run --rm \
        -v "${DATA_DIR}:/data" \
        "${OSRM_IMAGE}" \
        osrm-customize /data/chile-latest.osrm || {
        echo "✗ Falló osrm-customize."
        exit 1
    }
    echo "✓ Customización completada."
fi

echo ""
echo "============================================"
echo "  OSRM setup completado exitosamente."
echo "  Levantá el servidor con:"
echo "    docker compose up -d osrm"
echo "  O manualmente:"
echo "    docker compose -f docker-compose.yml up osrm"
echo "  Endpoint: http://localhost:5000"
echo "============================================"
