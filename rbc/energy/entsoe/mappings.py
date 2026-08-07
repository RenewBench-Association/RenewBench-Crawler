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
