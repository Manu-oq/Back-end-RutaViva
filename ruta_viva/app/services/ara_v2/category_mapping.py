"""Mapping between comprehender category intents and actual DB category names.

The comprehender (GPT-4o-mini or fallback) returns generic lowercase category
names like "gastronomía", "naturaleza", "termas". The database stores
canonical names like "Gastronomía", "Termas/Bienestar", "Trekking/Senderismo".

This module provides the semantic bridge between the two.
"""

# Maps comprehender category intent → list of DB category names to match.
# Each intent can map to multiple DB categories (e.g., "naturaleza" maps to
# several nature-related categories).
CATEGORY_INTENT_TO_DB_NAMES: dict[str, list[str]] = {
    "gastronomía": ["Gastronomía"],
    "alojamiento": ["Alojamiento"],
    "naturaleza": [
        "Naturaleza",
        "Trekking/Senderismo",
        "Parques/Reservas",
        "Montañas/Volcanes/Miradores",
        "Lagos/Ríos/Playas",
    ],
    "termas": ["Termas/Bienestar"],
    "cultura": ["Cultura", "Museos/Patrimonio"],
    "aventura": [
        "Trekking/Senderismo",
        "Montañas/Volcanes/Miradores",
        "Aventura/Deportes",
    ],
    "turismo": ["Turismo"],
    "servicios": ["Servicios turísticos/Información"],
    "transporte": ["Transporte/Accesos"],
    "artesanía": ["Artesanía/Compras locales"],
    "compras": ["Artesanía/Compras locales"],
}

# Reverse mapping: DB category name → list of comprehender intents that map to it.
# Useful for debugging and reverse lookups.
DB_NAME_TO_INTENTS: dict[str, list[str]] = {}
for _intent, _db_names in CATEGORY_INTENT_TO_DB_NAMES.items():
    for _db_name in _db_names:
        DB_NAME_TO_INTENTS.setdefault(_db_name, []).append(_intent)
