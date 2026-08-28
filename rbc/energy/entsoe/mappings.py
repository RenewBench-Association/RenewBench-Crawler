"""ENTSOE-E MAPPINGS.

Mappings of relevant ENTSO-E bidding zones (EIC codes) that return generation data per unit.
"""

ACTIVE_ZONES_METADATA: dict[str, dict[str, int | str]] = {
    "10Y1001A1001A016": {
        "alpha2": "GB",
        "country": "Northern Ireland",
        "start": 2015,
        "end": 2025,
    },
    "10Y1001A1001A39I": {"alpha2": "EE", "country": "Estonia", "start": 2015},
    "10Y1001A1001A796": {"alpha2": "DK", "country": "Denmark", "start": 2015},
    "10Y1001A1001A990": {"alpha2": "MD", "country": "Moldova", "start": 2020},
    "10Y1001A1001B012": {"alpha2": "GE", "country": "Georgia", "start": 2021},
    "10Y1001C--00100H": {"alpha2": "XK", "country": "Kosovo", "start": 2021},
    "10YAL-KESH-----5": {"alpha2": "AL", "country": "Albania", "start": 2024},
    "10YAT-APG------L": {"alpha2": "AT", "country": "Austria", "start": 2015},
    "10YBA-JPCC-----D": {
        "alpha2": "BA",
        "country": "Bosnia and Herzegovina",
        "start": 2017,
    },
    "10YBE----------2": {"alpha2": "BE", "country": "Belgium", "start": 2015},
    "10YCA-BULGARIA-R": {"alpha2": "BG", "country": "Bulgaria", "start": 2015},
    "10YCH-SWISSGRIDZ": {"alpha2": "CH", "country": "Switzerland", "start": 2015},
    "10YCS-CG-TSO---S": {"alpha2": "ME", "country": "Montenegro", "start": 2015},
    "10YCS-SERBIATSOV": {
        "alpha2": "RS",
        "country": "Serbia",
        "start": 2022,
        "end": 2025,
    },
    "10YCZ-CEPS-----N": {"alpha2": "CZ", "country": "Czech Republic", "start": 2015},
    "10YDE-ENBW-----N": {"alpha2": "DE", "country": "Germany", "start": 2015},
    "10YDE-EON------1": {"alpha2": "DE", "country": "Germany", "start": 2015},
    "10YDE-RWENET---I": {"alpha2": "DE", "country": "Germany", "start": 2015},
    "10YDE-VE-------2": {"alpha2": "DE", "country": "Germany", "start": 2015},
    "10YES-REE------0": {"alpha2": "ES", "country": "Spain", "start": 2014},
    "10YFI-1--------U": {"alpha2": "FI", "country": "Finland", "start": 2015},
    "10YFR-RTE------C": {"alpha2": "FR", "country": "France", "start": 2014},
    "10YGB----------A": {
        "alpha2": "GB",
        "country": "Great Britain",
        "start": 2015,
        "end": 2021,
    },
    "10YGR-HTSO-----Y": {"alpha2": "GR", "country": "Greece", "start": 2015},
    "10YHU-MAVIR----U": {"alpha2": "HU", "country": "Hungary", "start": 2015},
    "10YIE-1001A00010": {"alpha2": "IE", "country": "Ireland", "start": 2015},
    "10YIT-GRTN-----B": {"alpha2": "IT", "country": "Italy", "start": 2015},
    "10YLT-1001A0008Q": {"alpha2": "LT", "country": "Lithuania", "start": 2015},
    "10YLV-1001A00074": {"alpha2": "LV", "country": "Latvia", "start": 2015},
    "10YMK-MEPSO----8": {"alpha2": "MK", "country": "North Macedonia", "start": 2018},
    "10YNL----------L": {"alpha2": "NL", "country": "Netherlands", "start": 2015},
    "10YNO-0--------C": {"alpha2": "NO", "country": "Norway", "start": 2020},
    "10YPL-AREA-----S": {"alpha2": "PL", "country": "Poland", "start": 2015},
    "10YPT-REN------W": {"alpha2": "PT", "country": "Portugal", "start": 2014},
    "10YRO-TEL------P": {"alpha2": "RO", "country": "Romania", "start": 2015},
    "10YSE-1--------K": {"alpha2": "SE", "country": "Sweden", "start": 2014},
    "10YSI-ELES-----O": {"alpha2": "SI", "country": "Slovenia", "start": 2015},
    "10YSK-SEPS-----K": {"alpha2": "SK", "country": "Slovakia", "start": 2015},
}

ACTIVE_ZONES = list(ACTIVE_ZONES_METADATA.keys())
MIN_YEAR = min([int(v["start"]) for v in ACTIVE_ZONES_METADATA.values()])


COLS_MAPPING = {
    "timestamp": "timestamp",
    "time_series.mkt_psrtype.power_system_resources.name": "Unit_Name",
    "time_series.mkt_psrtype.power_system_resources.m_rid.value": "Unit_Code",
    "time_series.mkt_psrtype.psr_type": "PSR_Type",
    "time_series.mkt_psrtype.power_system_resources.nominal_p": "Capacity",
    "time_series.period.point.quantity": "Generation_MW",
    "time_series.period.point.secondary_quantity": "Consumption_MW",
    "time_series.quantity_measure_unit_name": "Measurement_Unit",
    "time_series.period.resolution": "Temporal_Resolution",
}


# ---------------------------------------------------------------------------
# Coordinate Finding Definitions (additions/overrides for OPERATOR_METADATA)
# ---------------------------------------------------------------------------
# ======= FUEL TYPES =======
FUELTYPE_CODE_MAPPINGS = {
    "B01": "biomass",
    "B02": "coal",  # brown
    "B03": "gas",  # coal-derived
    "B04": "gas",
    "B05": "coal",  # black
    "B06": "oil",
    "B07": "oil",  # shale
    "B08": "peat",
    "B09": "thermal",
    "B10": "hydro",  # storage
    "B11": "hydro",  # run-of-river
    "B12": "hydro",  # reservoir
    "B13": "marine",
    "B14": "nuclear",
    "B15": "renewable",
    "B16": "solar",
    "B17": "waste",
    "B18": "wind",  # offshore
    "B19": "wind",  # onshore
    "B20": "other",
    "B21": "link",  # AC
    "B22": "link",  # DC
    "B23": "substation",
    "B24": "transformer",
    "B25": "storage",
}

FUELTYPE_DEFINITION_MAPPINGS = {
    "Biomass": "biomass",
    "Fossil Brown coal/Lignite": "coal",
    "Fossil Coal-derived gas": "gas",
    "Fossil Gas": "gas",
    "Fossil Hard coal": "coal",
    "Fossil Oil": "oil",
    "Fossil Oil shale": "oil",
    "Fossil Peat": "peat",
    "Geothermal": "thermal",
    "Hydro Pumped Storage": "hydro",
    "Hydro Run-of-river and poundage": "hydro",
    "Hydro Water Reservoir": "hydro",
    "Marine": "marine",
    "Nuclear": "nuclear",
    "Other renewable": "renewable",
    "Solar": "solar",
    "Waste": "waste",
    "Wind Offshore": "wind",
    "Wind Onshore": "wind",
    "Other": "other",
    "AC Link": "link",
    "DC Link": "link",
    "Substation": "substation",
    "Transformer": "transformer",
    "Energy storage": "storage",
    # Battery storage sites are commonly tagged/labelled just "battery" by OSM
    # (plant:source=battery) and "Battery"/"Battery Storage" by GEM/PPM, while
    # ENTSO-E's own code/definition (B25 / "Energy storage") normalizes to
    # "storage" — map these synonyms to the same canonical label so the
    # fuel-type guardrail doesn't reject legitimate battery-storage matches.
    "battery": "storage",
    "Battery": "storage",
    "battery storage": "storage",
    "Battery Storage": "storage",
}

# combine code and definition mappings into a single master dictionary
FUELTYPE_MAPPINGS = {**FUELTYPE_CODE_MAPPINGS, **FUELTYPE_DEFINITION_MAPPINGS}


# ======= ENTITY NAMES =======
ALBANIAN_NAME_TRANSLATIONS = {
    "centrali": "power plant",
    "central": "power plant",
    "hidrocentrali": "hydroelectric",
    "hidrocentral": "hydroelectric",
    "termocentrali": "thermal",
    "termocentral": "thermal",
    "solare": "solar",
    "fotovoltaik": "solar",
}

CZECH_SLOVAK_NAME_TRANSLATIONS = {
    "elektrárna": "power plant",
    "elektráreň": "power plant",
    "vodní": "hydroelectric",
    "vodná": "hydroelectric",
    "tepelná": "thermal",
    "větrná": "wind",
    "veterná": "wind",
    "solární": "solar",
    "solárna": "solar",
    "fotovoltaická": "solar",
    "fotovoltická": "solar",
    "jaderná": "nuclear",
    "jadrová": "nuclear",
    # "ve": "hydroelectric",
    # "te": "thermal",
    # "fve": "solar",
    # "vte": "wind",
    # "je": "nuclear",
}

DUTCH_NAME_TRANSLATIONS = {
    "centrale": "power plant",
    "elektriciteitscentrale": "power plant",
    "windpark": "wind park",
    "zonnepark": "solar park",
    "waterkrachtcentrale": "hydroelectric",
    "kerncentrale": "nuclear",
    "warmtekrachtcentrale": "thermal power",
}

FRENCH_NAME_TRANSLATIONS = {
    "centrale": "power plant",
    "central": "power plant",
    "électrique": "electric power",
    "thermique": "thermal power",
    "nucléaire": "nuclear power",
    "hydroélectrique": "hydroelectric hydro",
    "éolien": "wind power",
    "solaire": "solar power",
    "photovoltaïque": "solar power",
    "photovoltaique": "solar power",
    "parc": "park",
}

GERMAN_NAME_TRANSLATIONS = {
    "kraftwerk": "power plant",
    "heizkraftwerk": "power plant heating",
    "gaskraftwerk": "power plant gas",
    "kohlekraftwerk": "power plant coal",
    "wasserkraftwerk": "power plant hydro hydroelectric",
    "windkraftwerk": "power plant wind",
    "windpark": "wind park",
    "biomassekraftwerk": "power plant biomass",
    "photovoltaik": "power plant solar",
    "solarpark": "solar park",
    "kernkraftwerk": "power plant nuclear",
    "atomkraftwerk": "power plant nuclear",
    "pumpspeicherkraftwerk": "pumped hydro",
}

ITALIAN_NAME_TRANSLATIONS = {
    "centrale": "power plant",
    "elettrica": "electric power",
    "termica": "thermal power",
    "idroelettrica": "hydroelectric hydro",
    "eolica": "wind power",
    "solare": "solar power",
    "fotovoltaico": "solar power",
    "nucleare": "nuclear",
}

SOUTH_SLAVIC_NAME_TRANSLATIONS = {  # Bosnian / Croatian / Serbian
    "elektrana": "power plant",
    "elektrane": "power plant",
    "hidroelektrana": "hydroelectric",
    "hidroelektrane": "hydroelectric",
    "termoelektrana": "thermal",
    "termoelektrane": "thermal",
    "vjetroelektrana": "wind",
    "vjetroelektrane": "wind",
    "fotonaponska": "solar",
    "solarna": "solar",
    "sunčana": "solar",
    "nuklearna": "nuclear",
    "reverzibilna": "pumped hydro",
    # Abbreviations frequently found in names (e.g. "HE Trebinje")
    "he": "hydroelectric",
    "te": "thermal",
    "ve": "wind",
    "fe": "solar",
    "ne": "nuclear",
    "re": "pumped hydro",
    "bess": "bess battery",
}

ROMANIAN_NAME_TRANSLATIONS = {
    "centrală": "power plant",
    "electrică": "electric power",
    "termocentrală": "thermal",
    "hidrocentrală": "hydroelectric",
    "eoliană": "wind",
    "fotovoltaică": "solar",
    "solară": "solar",
    "nucleară": "nuclear",
    "cte": "thermal",
    "cet": "thermal",
    "che": "hydroelectric",
    "cne": "nuclear",
}


# Map: Per country codes - country-specific EGE terms → english translations
# Apply before fuzzy matching to properly resolve to the correct tokens.
# E.g. to be able to match:
#   ENTSOE's "HE_CAPLJINA_G1" & OSM's "Hidroelektrana Čapljina" → same "hydro" token
EGE_NAME_TRANSLATIONS: dict[str, dict[str, str]] = {
    "AL": ALBANIAN_NAME_TRANSLATIONS,
    "AT": GERMAN_NAME_TRANSLATIONS,  # Austrian
    "BA": SOUTH_SLAVIC_NAME_TRANSLATIONS,  # Bosnian
    "BE": {  # Belgian (Dutch / French / German)
        **DUTCH_NAME_TRANSLATIONS,
        **FRENCH_NAME_TRANSLATIONS,
        **GERMAN_NAME_TRANSLATIONS,
    },
    "BG": {  # Bulgarian (Cyrillic + Latin)
        "централа": "power plant",
        "централи": "power plant",
        "centrala": "power plant",
        # "аец": "nuclear",
        # "aec": "nuclear",
        # "тец": "thermal",
        # "tec": "thermal",
        # "вец": "hydroelectric",
        # "vec": "hydroelectric",
        # "фец": "solar",
        # "fec": "solar",
        # "вяц": "wind",
        # "vyac": "wind",
    },
    "CH": {  # Swiss German / French / Italian
        **GERMAN_NAME_TRANSLATIONS,
        **FRENCH_NAME_TRANSLATIONS,
        **ITALIAN_NAME_TRANSLATIONS,
    },
    "CZ": CZECH_SLOVAK_NAME_TRANSLATIONS,
    "DE": GERMAN_NAME_TRANSLATIONS,
    "DK": {  # Danish
        "kraftværk": "power plant",
        "vindmøllepark": "wind park",
        "solcelleanlæg": "solar power",
        "vandkraftværk": "hydroelectric",
        "varmeværk": "thermal power",
    },
    "EE": {  # Estonian
        "elektrijaam": "power plant",
        "elektrijaama": "power plant",
        "elektrijaamad": "power plant",
        "soojuselektrijaam": "thermal power plant",
        "soojus": "thermal",
        "ej": "power plant elektrijaam",
        # "balti": "balti",
        # "eesti": "eesti",
    },
    "ES": {  # Spanish
        "central": "power plant",
        "eléctrica": "electric power",
        "térmica": "thermal power",
        "hidroeléctrica": "hydroelectric hydro",
        "eólica": "wind power",
        "fotovoltaica": "solar power",
    },
    "FI": {  # Finnish
        "voimalaitos": "power plant",
        "voimala": "power plant",
        "vesivoimala": "hydroelectric",
        "tuulivoimala": "wind",
        "lämpövoimala": "thermal",
        "ydinvoimala": "nuclear",
        "aurinkovoimala": "solar",
    },
    "FR": FRENCH_NAME_TRANSLATIONS,
    "GE": {  # Georgian (Georgian script + Latin transliterations)
        "ჰესი": "hydroelectric",
        "hesi": "hydroelectric",
        "თბოსადგური": "thermal",
        "tbes": "thermal",
        "tbosadguri": "thermal",
        "ელექტროსადგური": "power plant",
        "elektrosadguri": "power plant",
    },
    "GR": {  # Greek (Greek script + Latin transliterations)
        "σταθμός": "power plant",
        "stathmos": "power plant",
        "υδροηλεκτρικός": "hydroelectric",
        "yhs": "hydroelectric",
        "θερμοηλεκτρικός": "thermal",
        "αιολικό": "wind",
        "φωτοβολταϊκό": "solar",
    },
    "HR": SOUTH_SLAVIC_NAME_TRANSLATIONS,
    "HU": {  # Hungarian
        "erőmű": "power plant",
        "vízerőmű": "hydroelectric",
        "hőerőmű": "thermal",
        "atomerőmű": "nuclear",
        "szélerőmű": "wind",
        "napelemes": "solar",
    },
    "IT": ITALIAN_NAME_TRANSLATIONS,
    "LT": {  # Lithuanian
        "elektrinė": "power plant",
        "šiluminė": "thermal",
        "hidroelektrinė": "hydroelectric",
        "vėjo": "wind",
        "saulės": "solar",
        "atominė": "nuclear",
    },
    "LV": {  # Latvian
        "elektrostacija": "power plant",
        "stacija": "power plant",
        # "hes": "hydroelectric",
        # "tes": "thermal",
        "vēja": "wind",
        "saules": "solar",
        "atomelektrostacija": "nuclear",
    },
    "MD": ROMANIAN_NAME_TRANSLATIONS,
    "ME": SOUTH_SLAVIC_NAME_TRANSLATIONS,
    "MK": {  # Macedonian (Cyrillic + South Slavic Latin)
        **SOUTH_SLAVIC_NAME_TRANSLATIONS,
        "електрана": "power plant",
        "тек": "thermal",
        "хек": "hydroelectric",
        "век": "wind",
        "фек": "solar",
    },
    "NL": DUTCH_NAME_TRANSLATIONS,
    "NO": {  # Norwegian
        "kraftverk": "power plant",
        "vannkraftverk": "hydroelectric",
        "vindkraftverk": "wind",
        "varmekraftverk": "thermal",
        "kjernekraftverk": "nuclear",
        "solkraftverk": "solar",
    },
    "PL": {
        "elektrownia": "power plant",
        "wodna": "hydroelectric",
        "cieplna": "thermal",
        "wiatrowa": "wind",
        "słoneczna": "solar",
        "sloneczna": "solar",
        "fotowoltaiczna": "solar",
        "jądrowa": "nuclear",
        # "ew": "hydroelectric",
        # "ec": "thermal",
        # "ej": "nuclear",
        # "fw": "wind",
        # "pv": "solar",
    },
    "PT": {  # Portuguese
        "central": "power plant",
        "elétrica": "electric power",
        "térmica": "thermal power",
        "hidrelétrica": "hydroelectric hydro",
        "hidroelétrica": "hydroelectric hydro",
        "eólica": "wind power",
        "solar": "solar power",
        "fotovoltaica": "solar power",
    },
    "RO": ROMANIAN_NAME_TRANSLATIONS,
    "RS": {  # Serbian
        **SOUTH_SLAVIC_NAME_TRANSLATIONS,
        "vjetroelektrana": "wind",  # Ijekavian (cross-border)
        "vjetroelektrane": "wind",
    },
    "SE": {  # Swedish
        "kraftverk": "power plant",
        "vattenkraftverk": "hydroelectric",
        "vindkraftverk": "wind",
        "varmekraftverk": "thermal",
        "kärnkraftverk": "nuclear",
        "solkraftverk": "solar",
    },
    "SI": {  # Slovenian
        "elektrarna": "power plant",
        "hidroelektrarna": "hydroelectric",
        "termoelektrarna": "thermal",
        "vetrna": "wind",
        "sončna": "solar",
        "jedrska": "nuclear",
        # "he": "hydroelectric",
        # "te": "thermal",
        # "ve": "wind",
        # "je": "nuclear",
        # "fe": "solar",
    },
    "SK": CZECH_SLOVAK_NAME_TRANSLATIONS,
    "XK": {  # Kosovo (Albanian primary + South Slavic)
        **ALBANIAN_NAME_TRANSLATIONS,
        **SOUTH_SLAVIC_NAME_TRANSLATIONS,
    },
}
