from app.core.time_utils import CHILE_TZ

CHILE_TZ = CHILE_TZ
INFORMATION_CATEGORY_ID = 13
GASTRONOMY_CATEGORY_ID = 2
LODGING_CATEGORY_ID = 4
TRANSPORT_CATEGORY_ID = 14

EXPLICIT_INFORMATION_TERMS = ("conaf", "información", "informacion", "oficina", "centro de visitantes", "planificar")
EXPLICIT_LODGING_TERMS = (
    "alojamiento",
    "alojar",
    "hotel",
    "hostal",
    "hostel",
    "cabaña",
    "cabana",
    "dormir",
    "check-in",
    "checkin",
)
EXPLICIT_REST_DAY_TERMS = ("descanso", "día libre", "dia libre", "traslado", "viaje tranquilo", "sin actividades")
EXPLICIT_TRANSPORT_TERMS = ("transporte", "terminal", "bus", "buses", "salida", "llegada", "traslado", "estación")
EXPLICIT_SERVICE_TERMS = (
    "farmacia",
    "hospital",
    "clínica",
    "clinica",
    "banco",
    "cajero",
    "baño",
    "bano",
    "combustible",
    "bencina",
    "policía",
    "policia",
    "emergencia",
)
EXPLICIT_CEMETERY_TERMS = ("cementerio", "cemetery", "patrimonial", "memorial", "histórico", "historico")
EXPLICIT_REPEAT_TERMS = (
    "todos los días",
    "todos los dias",
    "repetir",
    "repite",
    "misma actividad",
    "misma comida",
    "pizza todos los días",
    "pizza todos los dias",
)
BLACKLIST_TERMS_BY_REASON = {
    "cemetery": ("cementerio", "cemetery", "graveyard", "grave_yard", "memorial park", "camposanto"),
    "waste": ("landfill", "waste", "dump", "vertedero", "basural", "relleno sanitario"),
    "industrial": ("industrial", "factory", "works", "plant", "zona industrial", "planta industrial"),
    "pure_transport": ("bus_station", "terminal de buses", "terminal rodoviario", "estación de buses"),
    "logistic_service": (
        "pharmacy",
        "farmacia",
        "hospital",
        "police",
        "policía",
        "policia",
        "fuel",
        "bencinera",
        "servicentro",
        "toilets",
        "baño",
        "baño",
        "banco",
        "bank",
        "atm",
        "cajero",
        "car_rental",
        "rentacar",
        "rent a car",
        "arriendo de autos",
        "arriendo de vehículos",
        "alquiler de autos",
    ),
}
DELEGATED_RECOMMENDATION_TERMS = (
    "consulta su menú",
    "consulta el menú",
    "pregunta por recomendaciones",
    "recomendaciones cercanas",
    "consulta en recepción",
    "pregunta en recepción",
    "pide información",
    "consulta con conaf",
    "consulta a conaf",
    "como alternativa para mantener variedad",
    "evitar repetir el mismo lugar",
    "auto_repaired_duplicate_poi",
    "mantener variedad",
    "evitar repetir",
    "alternativa para",
    "equilibrar la ruta",
    "como contraste",
    "para variar",
    "romper con",
    "no saturar",
    "misma categoría",
)
