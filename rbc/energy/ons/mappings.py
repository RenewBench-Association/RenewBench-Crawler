"""ONS MAPPINGS."""

# ---------------------------------------------------------------------------
# Coordinate Finding Definitions (additions/overrides for OPERATOR_METADATA)
# ---------------------------------------------------------------------------
# ======= FUEL TYPES =======
FUELTYPE_BASE_MAPPING = {
    "TÉRMICA": "thermal (coal/gas/oil/waste/biomass)",
    "termeletrica": "thermal (coal/gas/oil/waste/biomass)",
    "Óleo Diesel": "diesel oil",
    "Óleo Combustível": "fuel oil",
    "Carvão": "coal",
    "Gás": "gas",
    "Resíduos Industriais": "industrial waste",
    "NUCLEAR": "nuclear",
    "Nuclear": "nuclear",
    "Biomassa": "biomass",
    "Bioen": "bioenergy",
    "Bioenergia": "bioenergy",
    "HIDROELÉTRICA": "hydroelectric",
    "Hidrelétrica": "hydroelectric",
    "Hidráulica": "hydro",
    "EOLIELÉTRICA": "wind",
    "Eólica": "wind",
    "FOTOVOLTAICA": "solar",
    "Fotovoltaica": "solar",
}
FUELTYPE_MAPPING = FUELTYPE_BASE_MAPPING.copy()
for key, value in FUELTYPE_BASE_MAPPING.items():
    key = key.title()
    if key.endswith("a"):
        FUELTYPE_MAPPING[key[:-1] + "o"] = value
        FUELTYPE_MAPPING[key + "s"] = value


# ======= ENTITY NAMES =======
# GENERIC_UNIT_TOKENS = {
#     "bloco",
#     "conj.",
#     "conjunto"
# }

# Map: ONS-specific EGE terms → english translations
# Apply before fuzzy matching to properly resolve to the correct tokens.
# E.g. to prevent matching:
#      ONS' "Pequenas Centrais Hidrelétricas da Copel" &
#      OSM's "Casa de Força da Pequena Central Hidrelétrica Colino Dois"
EGE_NAME_BASE_TRANSLATIONS = {
    # overrides for multi-key fuel values
    "Térmica": "thermal",
    "Diesel": "diesel oil",
    "Combustível": "fuel oil",
    "Industrial": "industrial",
    "Resíduos": "waste",
    # from Operator (ONS)
    "Central": "power plant",
    "Pequena": "small",
    "Gov": "operator",
    "Governador": "operator",
    # from Locator (OSM)
    "Casa": "house",
    "Força": "power",
    "Usina": "power station",
    "UHE": "hydroelectric power station",
    "Barragem": "dam",
}
EGE_NAME_TRANSLATIONS = EGE_NAME_BASE_TRANSLATIONS.copy()
for key, value in EGE_NAME_BASE_TRANSLATIONS.items():
    key = key.title()
    if len(key) > 3:
        if key.endswith("a"):
            EGE_NAME_TRANSLATIONS[key + "s"] = value
        elif key.endswith("r"):
            EGE_NAME_TRANSLATIONS[key + "es"] = value
        elif key.endswith("al"):
            EGE_NAME_TRANSLATIONS[key.removesuffix("l") + "is"] = value
        elif key.endswith("em"):
            EGE_NAME_TRANSLATIONS[key.removesuffix("m") + "ns"] = value
        elif key.endswith("el"):
            EGE_NAME_TRANSLATIONS[key.removesuffix("l") + "is"] = value
