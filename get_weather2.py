import requests
import pandas as pd
from datetime import datetime, timedelta
from geopy.distance import geodesic
import os
import time

stations_used_file = "stations used.csv"
weather_history_file = "weather_history.csv"
# Backup and clear previous CSV files
for file in [stations_used_file, weather_history_file]:
    if os.path.exists(file):
        backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file}"
        os.rename(file, backup_file)
        print(f"Backed up {file} to {backup_file}")

# NOAA API settings
base_url_stations = "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations"
base_url_data = "https://www.ncdc.noaa.gov/cdo-web/api/v2/data"

# Define API token
headers = {
    "token": "hZCHRgmqstfIwofCZtJUmzhkiAmOSOFj"  # Provided token
}

# Search radii in miles
radius_list = [10, 20, 40]
max_stations = 3  # Maximum number of stations to use
min_data_points = 300  # Minimum required data points per datatype
incomplete_sites_file = "incomplete_sites.txt"

# Prompt user to choose full run or incomplete sites
if os.path.exists(incomplete_sites_file):
    choice = input("Do you want to process all sites or only incomplete sites? (a=all/i=incomplete): ").strip().lower()
    if choice == "i":
        with open(incomplete_sites_file, "r") as f:
            incomplete_sites = set(line.strip() for line in f)
    else:
        incomplete_sites = None
else:
    incomplete_sites = None

# Read the CSV file
file_path = "TRBL Analysis tracking - Sites.csv"
df_sites = pd.read_csv(file_path)

# Filter out rows where 'Skip' is "Y"
df_sites = df_sites[df_sites["Skip"] != "Y"]

incomplete_sites_list = []

def make_request_with_retries(url, params, max_retries=3, wait_time=5):
    """Make an HTTP request with retries for handling 503 errors."""
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response
        elif response.status_code == 503:
            print(f"503 Service Unavailable. Retrying in {wait_time} seconds... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        else:
            print(f"Error fetching data: {response.status_code} - {response.text}")
            break
    return None

def get_stations_with_data(latitude, longitude, year, radius):
    """Fetch stations with both temperature and precipitation data within the given radius."""
    params = {
        "extent": f"{latitude-radius/69},{longitude-radius/69},{latitude+radius/69},{longitude+radius/69}",
        "datasetid": "GHCND",
        "startdate": f"{year}-01-01",
        "enddate": f"{year}-12-31",
        "datatypeid": ["TMAX", "TMIN", "PRCP"],
        "limit": 1000
    }

    response = make_request_with_retries(base_url_stations, params)
    
    if response:
        return response.json().get("results", [])
    return []

def get_weather_data(station_id, year):
    """Fetch complete daily weather data for a given station and year, handling pagination."""
    all_data = []
    offset = 0

    while True:
        params = {
            "datasetid": "GHCND",
            "stationid": station_id,
            "startdate": f"{year}-01-01",
            "enddate": f"{year}-12-31",
            "datatypeid": ["TMAX", "TMIN", "PRCP"],
            "limit": 1000,
            "offset": offset,
            "units": "standard"  # Request data in inches and Fahrenheit
        }

        response = make_request_with_retries(base_url_data, params)
        
        if response:
            data = response.json().get("results", [])
            if not data:
                break  # Stop if no more data
            all_data.extend(data)
            offset += 1000  # Move to the next batch
        else:
            break

    return all_data

# Process each row in the CSV file
for _, row in df_sites.iterrows():
    site_name = row["Name"]
    if incomplete_sites is not None and site_name not in incomplete_sites:
        continue  # Skip this site if running in incomplete mode

    year = site_name[:4]  # Extract year from "Name" column
    latitude = row["Latitude"]
    longitude = row["Longitude"]

    print(f"\nProcessing site: {site_name} (Year: {year}, Lat: {latitude}, Lon: {longitude})")
    weather_history = {}

    # Find stations with sufficient data
    valid_stations = []
    for radius in radius_list:
        potential_stations = get_stations_with_data(latitude, longitude, year, radius)
        for station in potential_stations:
            if station in valid_stations:
                continue

            station_id = station["id"]
            station_data = get_weather_data(station_id, year)
            
            # Check data completeness
            data_counts = {"TMAX": 0, "TMIN": 0, "PRCP": 0}
            for entry in station_data:
                if entry["datatype"] in data_counts:
                    data_counts[entry["datatype"]] += 1
            
            if all(count >= min_data_points for count in data_counts.values()):
                valid_stations.append(station)
                
            if len(valid_stations) >= max_stations:
                break
        if len(valid_stations) >= max_stations:
            break

    if not valid_stations:
        print("No stations found with sufficient data.")
        incomplete_sites_list.append(site_name)
        with open(incomplete_sites_file, "a") as f:
            f.write(site_name + "\n")
        continue  # Skip to next site

    print(f"Using {len(valid_stations)} station(s).")

    # Process and store weather data
    for idx, station in enumerate(valid_stations, start=1):
        station_id = station["id"]
        station_data = get_weather_data(station_id, year)
        
        for entry in station_data:
            date = entry["date"][:10]
            dtype = entry["datatype"]
            value = entry["value"]
            
            key = (site_name, date)
            if key not in weather_history:
                weather_history[key] = {"site": site_name, "date": date, "tmax": [], "tmin": [], "prcp": [],
                                        "S1 Tmax": None, "S1 Tmin": None, "S1 Prcp": None,
                                        "S2 Tmax": None, "S2 Tmin": None, "S2 Prcp": None,
                                        "S3 Tmax": None, "S3 Tmin": None, "S3 Prcp": None}
            
            if dtype == "TMAX":
                weather_history[key]["tmax"].append(value)
                weather_history[key][f"S{idx} Tmax"] = value
            elif dtype == "TMIN":
                weather_history[key]["tmin"].append(value)
                weather_history[key][f"S{idx} Tmin"] = value
            elif dtype == "PRCP":
                weather_history[key]["prcp"].append(value)
                weather_history[key][f"S{idx} Prcp"] = value
    
    # Compute median values
    for key, values in weather_history.items():
        for dtype in ["tmax", "tmin", "prcp"]:
            if values[dtype]:
                values[dtype] = round(pd.Series(values[dtype]).median(), 2)

    # Save station usage data
    for station in valid_stations:
        station["Site"] = site_name  # Add site name to each
    pd.DataFrame(valid_stations).to_csv(stations_used_file, mode="a", header=not os.path.exists(stations_used_file), index=False)

    # Save weather history data
    pd.DataFrame(weather_history.values()).to_csv(weather_history_file, mode="a", header=not os.path.exists(weather_history_file), index=False)

    #input("Press Enter to continue to the next site...")
