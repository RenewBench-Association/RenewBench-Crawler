"""Mappings required for coordinate finding."""

OPERATOR_METADATA = {
    "adme": {"country": "Uruguay", "entity_col": ""},
    "aemo": {
        "country": "Australia",
        "entity_col": "unit_code",
        "fuel_col": "unit_fueltech_id",
    },
    "aeso": {"country": "Canada", "entity_col": "Asset Name", "fuel_col": "Fuel Type"},
    "cen": {
        "country": "Chile",
        "entity_col": "central",
        "fuel_col": "tipo_tecnologia",
        "code_col": "id_central",
    },
    "eat": {
        "country": "New Zealand",
        "entity_col": "gen_code",
        "fuel_col": "fuel_code",
    },
    "eia": {
        "country": "United States of America",
        "entity_col": "respondent-name",
        "fuel_col": "type-name",
        "code_col": "respondent",
    },
    "entsoe": {
        "country": "Europe",
        "entity_col": "Unit_Name",
        "fuel_col": "PSR_Type",
        "code_col": "Unit_Code",
    },
    "epias": {"country": "Turkey", "entity_col": "powerPlantName"},
    "ieso": {"country": "Canada", "entity_col": "Generator", "fuel_col": "Fuel Type"},
    "ons": {
        "country": "Brazil",
        "entity_col": "nom_usina",
        "fuel_col": "nom_tipousina",
        "code_col": "id_ons",
    },
    "rei": {"country": "Japan", "entity_col": ""},
}
