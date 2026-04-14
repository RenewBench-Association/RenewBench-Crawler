import pandas as pd
from pathlib import Path
import requests
import io
import json
from rbc.energy.entsoe.mappings import *
from utils import get_country_from_eic

def merge_bidding_zone_data(root_folder_path= "entsoe", output_filename="merged_data.csv"):
    root_path = Path(root_folder_path)
    all_dataframes = []

    # Iterate through each subfolder in the root directory
    for subfolder in root_path.iterdir():
        if subfolder.is_dir():
            # Extract characters at index 3 and 4 from the folder name
            # Example: "DE_LU" -> "LU"
            folder_tag = subfolder.name
            
            # Find all CSV files inside this subfolder
            for csv_file in subfolder.glob("*.csv"):
                print(f"Processing {csv_file} (Tag: {folder_tag})...")
                
                try:
                    # Read the CSV
                    df = pd.read_csv(csv_file)
                    
                    # Create the new column
                    df['folder_tag'] = folder_tag
                    df['iso_mapping'] = [ACTIVE_ZONES_METADATA[f]["name"][:2] for f in df['folder_tag']]
                    # Add to our list
                    all_dataframes.append(df)
                except Exception as e:
                    print(f"Error reading {csv_file}: {e}")

    # Merge all dataframes into one
    if all_dataframes:
        combined_df = pd.concat(all_dataframes, ignore_index=True)
        
        # Save to a single CSV
        combined_df.to_csv(output_filename, index=False)
        print(f"\nSuccessfully merged {len(all_dataframes)} files into {output_filename}")
    else:
        print("No CSV files found to merge.")

def get_live_eic_mapping():
    url = "https://eepublicdownloads.blob.core.windows.net/cio-lio/csv/W_eicCodes.csv"
    #"https://www.entsoe.eu/fileadmin/user_upload/edi/library/eic/W_eicCodes.csv"
    print(f"Fetching latest official EIC registry from: {url}...")
    
    try:
        # 1. Download as raw bytes to handle encoding manually
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # 2. Decode using utf-8-sig to remove the 'BOM' (invisible character at start)
        content = response.content.decode('utf-8-sig')
        lines = content.splitlines()
        
        # 3. Locate the header row dynamically
        header_index = None
        for i, line in enumerate(lines):
            # We look for the exact string you found in your manual download
            if "EicCode" in line and "MarketParticipantIsoCountryCode" in line:
                header_index = i
                break
        
        if header_index is None:
            print("Error: Still could not find the header row in the file.")
            return None

        # 4. Extract data starting from the header
        csv_text = "\n".join(lines[header_index:])
        
        # 5. Read into Pandas using the semicolon separator you confirmed
        registry_df = pd.read_csv(
            io.StringIO(csv_text), 
            sep=';', 
            engine='python', 
            on_bad_lines='skip'
        )
        
        # Clean up column names in case of trailing spaces
        registry_df.columns = [c.strip() for c in registry_df.columns]
        
        # 6. Create the Mapping
        # We ensure both keys and values are strings and stripped of whitespace
        mapping = dict(zip(
            registry_df['EicCode'].astype(str).str.strip(), 
            registry_df['MarketParticipantIsoCountryCode'].astype(str).str.strip().str.upper()
        ))
        
        print(f"Success! Loaded {len(mapping)} EIC codes.")
        with open ("mapping.json", "w") as f:
            json.dump(mapping, f, indent= 1)
        return mapping

    except Exception as e:
        print(f"Unexpected Error: {e}")
        return None

def validate_merged_with_live_data(merged_file_path):
    # 1. Get the official mapping
    official_map = get_live_eic_mapping()
    if not official_map:
        return False

    # 2. Load your merged data
    print(f"Loading {merged_file_path}...")
    df = pd.read_csv(merged_file_path)

    # 3. Perform the comparison
    df['inferred_iso'] = [official_map.get(cod) for cod in df['Unit_Code']]
    mismatches = df[df['folder_tag'].str.upper() != df['inferred_iso'].str.upper()]
    
    num_mismatches = len(mismatches)
    total_rows = len(df)

    # 4. Return results
    if num_mismatches == 0:
        print(f"Validation Successful: All {total_rows} rows match.")
        return True
    else:
        print(f"Validation Failed!")
        print(f"Number of unequal cases: {num_mismatches} (out of {total_rows})")
        
        # Optional: Print a few examples of mismatches for debugging
        print("\nExample mismatches:")
        print(mismatches[['Unit_Code', 'folder_tag', 'inferred_iso']].head())

        return False

def validate_merged_data(file_path):
    # 1. Load the merged file
    print(f"Loading {file_path}...")
    df = pd.read_csv(file_path)

    if 'Unit_Code' not in df.columns or 'folder_tag' not in df.columns:
        print("Error: Required columns ('Unit_Code' or 'folder_tag') missing.")
        return False

    # 2. Infer the ISO code from the Unit_Code column
    df['inferred_iso'] = df['Unit_Code'].apply(get_country_from_eic)


    # 3. Compare inferred ISO with folder_tag
    # We use .str.upper() to ensure the comparison is case-insensitive
    mismatches = df[df['iso_mapping'].str.upper() != df['inferred_iso'].str.upper()]
    
    num_mismatches = len(mismatches)
    total_rows = len(df)

    # 4. Return results
    if num_mismatches == 0:
        print(f"Validation Successful: All {total_rows} rows match.")
        return True
    else:
        print(f"Validation Failed!")
        print(f"Number of unequal cases: {num_mismatches} (out of {total_rows})")
        
        # Optional: Print a few examples of mismatches for debugging
        print("\nExample mismatches:")
        print(mismatches[['Unit_Code', 'folder_tag', 'iso_mapping', 'inferred_iso']].head())
        
        return False

merge_bidding_zone_data()
m = validate_merged_data("merged_data.csv")
print(m)