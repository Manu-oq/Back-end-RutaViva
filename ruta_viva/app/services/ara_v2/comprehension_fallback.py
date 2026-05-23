from __future__ import annotations

import re
from datetime import datetime

from app.core.ara_constants import KNOWN_DESTINATION_NAMES
from app.schemas.ara_comprehension import ComprehensionResult, ExtractedEntity, MemoryFact

KNOWN_DESTINATIONS = [d for d in KNOWN_DESTINATION_NAMES if d not in ("santiago",)]


def fallback_comprehend(user_message: str) -> ComprehensionResult:
    """Comprensión basada en reglas simples cuando GPT-4o-mini falla."""
    msg = user_message.lower().strip()

    if not msg or re.match(r'^[\W_]+$', msg):
        return ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.2,
            entidades=[],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=["¿A qué destino quieres ir?", "¿Qué fechas tienes en mente?"],
            actualizaciones_memoria=[],
            tono="neutro",
        )

    herramientas: list[str] = []
    intenciones: list[str] = []
    entidades: list[ExtractedEntity] = []
    memoria: list[MemoryFact] = []
    preguntas: list[str] = []

    if any(kw in msg for kw in ["generar", "itinerario", "hacelo todo", "armame", "creame", "que lo arme ara"]):
        intenciones.append("build_itinerary")
        herramientas.append("build_itinerary")

    if any(kw in msg for kw in ["clima", "lluvia", "tiempo", "temperatura", "pronostico"]):
        intenciones.append("get_weather")
        herramientas.append("get_weather")
        herramientas.append("answer_question")

    if any(kw in msg for kw in ["cambiar", "reemplazar", "otro lugar", "cambia", "reemplaza"]):
        intenciones.append("suggest_replacement")
        herramientas.append("suggest_replacement")

    found_dest = None
    for dest in KNOWN_DESTINATIONS:
        if dest in msg:
            found_dest = dest.title()
            entidades.append(ExtractedEntity(tipo="destino", valor=found_dest, confianza=0.7))
            intenciones.append("search_pois")
            herramientas.append("search_pois")
            break

    if "vegetariano" in msg or "vegano" in msg or "veggie" in msg:
        dieta = "vegetariano" if "vegetariano" in msg else ("vegano" if "vegano" in msg else "vegetariano")
        memoria.append(MemoryFact(hecho=f"dieta {dieta}", categoria="restriccion", confianza=0.85))

    if "no me gusta caminar" in msg or "no camino" in msg or "baja dificultad" in msg:
        memoria.append(MemoryFact(hecho="prefiere baja dificultad", categoria="preferencia", confianza=0.8))

    if "familia" in msg or "con niños" in msg or "con hijos" in msg:
        memoria.append(MemoryFact(hecho="viaja con familia", categoria="entidad", confianza=0.75))

    date_match = re.search(r'(\d{1,2})\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)', msg)
    if date_match:
        day = int(date_match.group(1))
        month_name = date_match.group(2)
        months = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
                  "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
        current_year = datetime.now().year
        month = months.get(month_name, 6)
        entidades.append(ExtractedEntity(tipo="fecha", valor=f"{current_year}-{month:02d}-{day:02d}", confianza=0.6))

    if not intenciones:
        intenciones = ["general"]
        herramientas = ["search_pois"]

    intencion_principal = intenciones[0] if intenciones else "general"
    confianza = 0.5 if entidades or memoria else 0.3

    if not found_dest and "build_itinerary" not in intenciones:
        preguntas.append("¿A qué destino quieres ir?")
    if not any(e.tipo == "fecha" for e in entidades):
        preguntas.append("¿Qué fechas tienes en mente?")

    return ComprehensionResult(
        intenciones=intenciones,
        intencion_principal=intencion_principal,
        confianza=confianza,
        entidades=entidades,
        herramientas_necesarias=list(dict.fromkeys(herramientas)),
        preguntas_pendientes=preguntas,
        actualizaciones_memoria=memoria,
        tono="neutro",
    )
