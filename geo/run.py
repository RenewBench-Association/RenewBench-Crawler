import pandas as pd
import requests
import time
import zipfile
import io
import traceback
import json
from pathlib import Path
from entsoe.mappings import lookup_area, Area
from utils import *

###if we need mapping from bidding zones to iso codes to query
#zones_dict = {a.name:a.meaning for a in Area}
#iso_codes = get_iso_for_zones(zones_dict)

###Example to querying per country ---Italy ---
#it = get_osm_power_plants_per_country("BE", 200)
#it.to_csv("df.csv")

#OPSD conventional:
opsd_conventional_url = "https://data.open-power-system-data.org/conventional_power_plants/2020-10-01/conventional_power_plants_EU.csv"
df_conventional = download_opsd_data(opsd_conventional_url, 60, True)
df_conventional_cleaned = clean_power_plant_data(df_conventional)

#Get JRC data:
jrc_url = "https://zenodo.org/records/3574566/files/JRC-PPDB-OPEN.ver1.0.zip?download=1"
df_jrc = download_jrc_data(jrc_url)
df_jrc_cleaned = clean_power_plant_data(df_jrc)

# 1. Combine the two cleaned datasets
# We stack them vertically. 
# Note: If an EIC is in both, JRC is generally more accurate, 
# so we put it first in the list.
df_master_map = pd.concat([df_jrc_cleaned, df_conventional_cleaned], ignore_index=True)

# 2. Drop duplicates based on the EIC code
# 'keep=first' ensures that if a code exists in both files, 
# we keep the one from the first dataframe (JRC) and discard the second.
df_master_map = df_master_map.drop_duplicates(subset=['Unit_Code'], keep='first')

# 3. Final cleanup - ensure only the 3 necessary columns remain
df_master_map = df_master_map[["Unit_Code", "lat", "lon"]]

# 4. Report the size of your new library
print(f"--- Master Map Statistics ---")
print(f"Units from JRC: {len(df_jrc_cleaned)}")
print(f"Units from OPSD: {len(df_conventional_cleaned)}")
print(f"Total Unique Units in Master Map: {len(df_master_map)}")

data = pd.read_csv("merged_data.csv")

# Merge the merged_data with the master map on the EIC code
located_data = data.merge(df_master_map, left_on='Unit_Code', right_on='Unit_Code', how='left')

#identify rows with missing locations
# Returns rows where ANY of the specified columns are NaN
missing_locations = located_data[located_data[['lat', 'lon']].isna().any(axis=1)].copy()
missing_locations['iso'] = missing_locations['Unit_Code'].apply(get_country_from_eic)

print(f"number of located rows is : {located_data.shape[0] - missing_locations.shape[0]}")
print(f"Number of unlocated rows is: {missing_locations.shape[0]}")

###Obtain remaining locations per country from OSM
osm_list = []
for country in missing_locations['iso'].unique():
  print(f"Downloading OSM data for {country}")
  country_plants = get_osm_power_plants_per_country(country, 300)
  osm_list.append(country_plants)

df_osm = pd.concat(osm_list, ignore_index=True)
df_osm = df_osm.rename(columns={"latitude": "lat", "longitude": "lon"})

#dropping latlon from missing locs
missing_locations = missing_locations.drop(columns=['lat','lon'])

osm_locations = missing_locations.merge(df_osm[['name', 'lat', 'lon']], left_on= "Unit_Name", right_on= "name", how= "left")

#Now merge with entire data frame
located_data = located_data.set_index('Unit_Code')
osm_locations = osm_locations.set_index('Unit_Code')

##we have 2 options either: combine first, which prioritizes the jrc/osd (the first location mapping) VS update which prioritizes the second mapping (OSM)
located_data[['lat', 'lon']] = located_data[['lat', 'lon']].combine_first(osm_locations[['lat', 'lon']])
#located_data.update(osm_locations[['lat', 'lon']])

located_data = located_data.reset_index()
print(f"Number of still unknown locations  is {located_data[['lat', 'lon']].isna().sum()}")
located_data.to_csv("final_located_data.csv", index= False)