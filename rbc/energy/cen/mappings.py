"""CEN MAPPINGS."""

# ---------------------------------------------------------------------------
# Coordinate Finding Definitions (additions/overrides for OPERATOR_METADATA)
# ---------------------------------------------------------------------------
# ======= FUEL TYPES =======
FUELTYPE_BASE_MAPPING = {
    # main types
    "Térmica": "thermal",
    "Nuclear": "nuclear",
    "Hidráulica": "hydro",
    "Geotérmica": "geothermal",
    "Eólica": "wind",
    "Solar": "solar",
    "BESS": "battery energy storage system",
    # subtypes for thermal
    "Diésel": "diesel oil",
    "Fuel Oil": "fuel oil",
    "Carbón": "coal",
    "Gas Natural": "natural gas",
    "BioGas": "biogas gas",
    "Biomasa": "biomass",
    "Cogeneración": "cogeneration, combined heat and power, CHP (gas, oil, diesel, biogas, biomass)",
    "Termosolar": "concentrated solar power, CSP",
    "PetCoke": "petroleum coke, petcoke",
    "GLP": "liquefied petroleum gas, LPG",
    # subtypes for hydro
    "Embalse": "hydro dam reservoir",
    "Pasada": "hydro river",
    # subtypes for BESS
    "Inyección": "battery storage discharge injection",
    "Retiro": "battery storage charge withdrawal",
}
FUELTYPE_MAPPING = FUELTYPE_BASE_MAPPING.copy()
for key, value in FUELTYPE_BASE_MAPPING.items():
    key = key.title()
    if key.endswith("a"):
        FUELTYPE_MAPPING[key[:-1] + "o"] = value
        FUELTYPE_MAPPING[key + "s"] = value


# ======= ENTITY NAMES =======
# Map: CEN-specific EGE terms → english translations
# Apply before fuzzy matching to properly resolve to the correct tokens.
EGE_NAME_BASE_TRANSLATIONS = {
    # from Operator (CEN)
    "los": "",
    "las": "",
    "del": "",  # article, like "los"/"las"
    "parque": "park",
    "TER": "thermal",  # térmica
    "GEO": "geothermal",  # geotérmica
    "HE": "hydro",  # hidroeléctrica
    "HP": "hydro river",  # hidroeléctrica de pasada
    "MCH": "mini hydro",  # mini central hidroeléctrica
    "PE": "wind farm",  # parque eólico
    "CSP": "concentrated solar power",  # concentración solar de potencia
    "PFV": "photovoltaic solar park",  # parque fotovoltaico
    "PVF": "photovoltaic solar park",  # typo for PFV (1 EGE)
    "PSF": "photovoltaic solar park",  # parque solar fotovoltaico
    "PVP": "photovoltaic solar park",
    "PMG": "small generator",  # pequeño medio de generación
    "PMGD": "small distributed generator",  # pequeño medio de generación distribuido
    "SAE": "storage",  # sistema de almacenamiento de energía
    # from Locators (GEM/OSMPP/OSM)
    "central": "power plant",
    "planta": "plant",
    "fotovoltaico": "photovoltaic solar",
    "fotovoltaica": "photovoltaic solar",
    "hidroelectrica": "hydro",
    "termoelectrica": "thermal",
}  # + FUELTYPE_BASE_MAPPING --> added together in coordinate finding (BasePipeline.__init__)
EGE_NAME_TRANSLATIONS = EGE_NAME_BASE_TRANSLATIONS.copy()
for key, value in EGE_NAME_BASE_TRANSLATIONS.items():
    key = key.title()
    if len(key) > 3:
        if key.endswith("a") or key.endswith("e"):
            EGE_NAME_TRANSLATIONS[key + "s"] = value
        elif key.endswith("r"):
            EGE_NAME_TRANSLATIONS[key + "es"] = value
        elif key.endswith("al"):
            EGE_NAME_TRANSLATIONS[key.removesuffix("l") + "es"] = value
        elif key.endswith("el"):
            EGE_NAME_TRANSLATIONS[key.removesuffix("l") + "is"] = value
