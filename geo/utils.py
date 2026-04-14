import pandas as pd
import requests
import time
import io
import traceback
import sys
import re
import zipfile
import country_converter as coco

def get_country_from_eic(eic):
    """
    Returns the ISO country code based on the EIC LIO prefix 
    or internal ISO mapping for Area codes.
    """
    if not isinstance(eic, str) or len(eic) < 16:
        return ""

    # LIO Mapping (First 2 digits of the EIC). Obtained from: https://www.entsoe.eu/data/energy-identification-codes-eic/#eic-lio-websites
    lio_map = {
        "10": "EU", "11": "DE", "12": "CH", "13": "AT",
        "14": "AT", "15": "HU", "16": "PT", "17": "FR", "18": "ES",
        "19": "PL", "20": "LU", "21": "EU", "22": "BE", "23": "EU", "24": "SK",
        "25": "AT", "26": "IT", "27": "CZ", "28": "SI", "29": "GR",
        "30": "RO", "31": "HR", "32": "BG", "33": "MK", "34": "RS",
        "35": "ME", "36": "BA", "37": "DE", "38": "EE", "39": "HU",
        "40": "TR", "41": "LT", "42": "SK", "43": "LV", "44": "FI", "45": "DK", "46": "SE",
        "47": "IE", #["IE", "NI"], 
        "48": "UK", "49": "NL", "50": "NO", "51": "SI", "52": "NL",
        "53": "PL", "54": "AL", "55": "UK", "56": "UA", "57": "BE", "58": "BG",
        "59": "IT", "60": "RO", "61": "LV", "62": "UA", "63": "FR", "64": "MD", "65": "GE", "66": "FI", "67": "RS", "68": "MD", "69": "CY", "70": "MK"
    }

    # Special Case: Area Codes (Type Y)
    # Area codes starting with 10Y often have the ISO code at index 3-4
    # Example: 10YBE----------2 -> BE
    if eic.startswith("10Y"):
        iso_candidate = eic[3:5].upper()
        # Basic check to see if it looks like an ISO code (all letters)
        if iso_candidate.isalpha():
            return iso_candidate

    # Default: Use LIO Prefix
    prefix = eic[:2]
    return lio_map.get(prefix, "")

def convert_zone_to_country(zone):
    # Mapping for complex/multi-country regions or codes not easily parsed
    special_cases = {
        "CWE": ["Germany", "France", "Belgium", "Netherlands", "Luxembourg"],
        "DE_AT_LU": ["Germany", "Austria", "Luxembourg"],
        "DE_LU": ["Germany", "Luxembourg"],
        "CZ_DE_SK": ["Czech Republic", "Germany", "Slovakia"],
        "IE_SEM": ["Ireland", "United Kingdom"], # Includes Northern Ireland
        "GB_IFA": ["United Kingdom", "France"],
        "GB_IFA2": ["United Kingdom", "France"],
        "GB_ELECLINK": ["United Kingdom", "France"],
        "IT_NORD_AT": ["Italy", "Austria"],
        "IT_NORD_CH": ["Italy", "Switzerland"],
        "IT_NORD_FR": ["Italy", "France"],
        "IT_NORD_SI": ["Italy", "Slovenia"],
        "IT_GR": ["Italy", "Greece"],
        "PL_CZ": ["Poland", "Czech Republic"],
        "DE_AMP_LU": ["Germany", "Luxembourg"],
        "DK_1_NO_1": ["Denmark", "Norway"]
    }
    if zone in special_cases :
        return special_cases[zone] 
            
        
        # Mapping specific prefixes/abbreviations back to full names
    if zone.startswith("DE"): country= "Germany"
    elif zone.startswith("IT"): country= "Italy"
    elif zone.startswith("NO"): country= "Norway"
    elif zone.startswith("SE"): country= "Sweden"
    elif zone.startswith("DK"): country= "Denmark"
    elif zone.startswith("GB") or zone == "UK": country = "United Kingdom"
    elif zone.startswith("UA"): country = "Ukraine"
    elif zone== "AT": country = "Austria"
    elif zone == "BE": country = "Belgium"
    elif zone == "FR": country = "France"
   # Fallback to the parsed name from the description
    else: country = ""

    return country

def get_iso_for_zones(zones):
  cc = coco.CountryConverter()
  mapps = {k:"" for k in zones.keys()}
  for zone, meaning in zones.items():
    country = convert_zone_to_country(zone) if convert_zone_to_country(zone) != "" else meaning
    iso = cc.convert(names=country, to='ISO2')
    mapps[zone] = iso
  return mapps

def check_eic_validity(eic):
    """
    Preprocesses and validates an EIC code.
    1. Cleans whitespace and converts to uppercase.
    2. Pads 15-character codes with a leading zero.
    3. Validates against the 16-character alphanumeric standard.
    Returns: The cleaned/fixed EIC if valid, otherwise None.
    """
    # 1. Basic Preprocessing
    if not isinstance(eic, str):
        # Handle cases where EIC might be a float/NaN from a CSV
        eic = str(eic) if eic == eic else "" 
    
    clean_eic = eic.strip().upper()

    # 2. Fix dropped leading zeros (The "Excel Fix")
    if len(clean_eic) == 15:
        clean_eic = "0" + clean_eic

    # 3. Regex Validation
    # Standard: Exactly 16 characters, only A-Z and 0-9
    eic_pattern = r'^[A-Z0-9]{16}$'
    
    if re.match(eic_pattern, clean_eic):
        return clean_eic
    else:
        # If it's still not 16 chars or contains symbols, it's invalid
        return None

def download_jrc_data(url):
    """Downloads JRC ZIP and extracts a clean EIC-to-GPS mapping."""
    print("Downloading JRC database...")
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open('JRC_OPEN_UNITS.csv') as f:
                # We only need the EIC and the coordinates
                df_units = pd.read_csv(f, usecols=['eic_g', 'lat', 'lon'])
        
        return df_units.rename(columns={'eic_g': 'Unit_Code'})

    except Exception:
        print(traceback.format_exc())
        return None

def download_opsd_data(url, timeout= 60, low_mem= False):

    
    print(f"Attempting to download from: {url}")
    
    try:
        # 1. Network Request
        # We set a timeout of 30 seconds so it doesn't hang forever
        response = requests.get(url, timeout=timeout)
        
        # This triggers an exception for 404 (Not Found) or 500 (Server Error)
        response.raise_for_status()
        
        print("Download successful. Now parsing CSV data...")
        
        # 2. Parsing the CSV
        try:
            # We use io.StringIO to treat the downloaded text as a file
            df = pd.read_csv(io.StringIO(response.text))
            
            print("Successfully loaded CSV into a DataFrame.")
            print(f"Columns found: {list(df.columns)}")
            print(f"Total rows: {len(df)}")
            
            return df.rename(columns={'eic_code': 'Unit_Code'})

        except pd.errors.ParserError:
            print("CRITICAL: The file downloaded, but it is not a valid CSV.")
            print("-" * 30)
            print(traceback.format_exc())
            print("-" * 30)
            
        except Exception:
            print("CRITICAL: An unexpected error occurred while processing the CSV data.")
            print("-" * 30)
            print(traceback.format_exc())
            print("-" * 30)

    except requests.exceptions.RequestException:
        print("CRITICAL: Network/Connection Error.")
        print("-" * 30)
        # format_exc() gives you the full 'Traceback' text
        print(traceback.format_exc())
        print("-" * 30)

    return None

def clean_power_plant_data(df):
    """
    Cleans the OPSD dataframe to keep only valid 
    mapping coordinates for EIC codes.
    """
    if df is None:
        print("Error: No data provided to the cleaning function.")
        return None

    initial_count = len(df)
    
    # 1. Select only the necessary columns
    # We use a list of columns we know exist in the OPSD file
    target_cols = ['Unit_Code', 'lat', 'lon']
    df_clean = df[target_cols].copy()
    
    
    # 2. Drop Duplicates
    # If the same EIC appears twice, we only need it once for the map
    df_clean = df_clean.drop_duplicates(subset=['Unit_Code'])
    unique_count = len(df_clean)

    # 3. Drop rows where EIC, Lat, or Lon are NaN (Empty)
    # 'any' means if even one of those three is missing, the row is gone
    df_clean = df_clean.dropna(subset=target_cols, how='any')
    after_nan = len(df_clean)

    #check EIC validity:
    df_clean['Unit_Code'] = df_clean['Unit_Code'].apply(check_eic_validity)

    
    return df_clean

def get_osm_power_plants_per_country(iso_code, t=180):
    overpass_url = "https://overpass-api.de/api/interpreter"
        # 2. Construct the Overpass Query using ISO code
    # We fetch plants (large) and generators (smaller units/wind/solar)
    query = f"""
    [out:json][timeout:{t}];
    area["ISO3166-1"="{iso_code}"]["admin_level"="2"]->.searchArea;
    (
      node["power"="plant"](area.searchArea);
      way["power"="plant"](area.searchArea);
      relation["power"="plant"](area.searchArea);
    );
    out center;
    """
    
    try:
        print(f"Querying OSM for (ISO: {iso_code})...")
        response = requests.get(overpass_url, params={'data': query})
        response.raise_for_status()
        data = response.json()
        
        plants = []
        for element in data.get('elements', []):
            # Coordinates: Ways/Relations use 'center', Nodes use 'lat/lon'
            lat = element.get('lat') or element.get('center', {}).get('lat')
            lon = element.get('lon') or element.get('center', {}).get('lon')
            
            tags = element.get('tags', {})
            plants.append({
                'country': iso_code,
                'name': tags.get('name', 'Unnamed'),
                'fuel_type': tags.get('plant:source', tags.get('source', 'Unknown')),
                'capacity_mw': tags.get('plant:output:electricity', 'Unknown'),
                'latitude': lat,
                'longitude': lon,
                'osm_id': element.get('id')
            })
            
        return pd.DataFrame(plants)

    except Exception as e:
        print(f"Error fetching data for {iso_code}: {e}")
        return None