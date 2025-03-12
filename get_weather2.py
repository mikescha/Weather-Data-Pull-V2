import requests
import pandas as pd
from datetime import datetime, timedelta
from geopy.distance import geodesic

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
min_data_points = 300  # Minimum required data points per station

# Read the CSV file
file_path = "TRBL Analysis tracking - Sites.csv"
df_sites = pd.read_csv(file_path)

# Filter out rows where 'Skip' is "Y"
df_sites = df_sites[df_sites["Skip"] != "Y"]

# Storage for station metadata and weather history
stations_used = []
weather_history = {}

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

    response = requests.get(base_url_stations, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json().get("results", [])
    else:
        print(f"Error fetching stations: {response.status_code} - {response.text}")
        return []

def get_weather_data(station_id, year):
    """Fetch daily weather data for a given station and year."""
    params = {
        "datasetid": "GHCND",
        "stationid": station_id,
        "startdate": f"{year}-01-01",
        "enddate": f"{year}-12-31",
        "datatypeid": ["TMAX", "TMIN", "PRCP"],
        "limit": 1000,
        "units": "standard"  # Request data in inches and Fahrenheit
    }

    response = requests.get(base_url_data, headers=headers, params=params)

    if response.status_code == 200:
        return response.json().get("results", [])
    else:
        print(f"Error fetching data for {station_id}: {response.status_code}")
        return []

# Process each row in the CSV file
for _, row in df_sites.iterrows():
    site_name = row["Name"]
    year = site_name[:4]  # Extract year from "Name" column
    latitude = row["Latitude"]
    longitude = row["Longitude"]

    print(f"\nProcessing site: {site_name} (Year: {year}, Lat: {latitude}, Lon: {longitude})")

    # Find stations with sufficient data
    valid_stations = []
    for radius in radius_list:
        potential_stations = get_stations_with_data(latitude, longitude, year, radius)
        for station in potential_stations:
            station_id = station["id"]
            station_data = get_weather_data(station_id, year)
            if len(station_data) >= min_data_points:
                valid_stations.append(station)
            if len(valid_stations) >= max_stations:
                break
        if len(valid_stations) >= max_stations:
            break

    if not valid_stations:
        print("No stations found with sufficient data.")
        continue  # Skip to next site

    print(f"Using {len(valid_stations)} station(s).")

    # Fetch and store daily weather data
    for idx, station in enumerate(valid_stations, start=1):
        station_id = station["id"]
        station_lat = station["latitude"]
        station_lon = station["longitude"]
        station_name = station["name"]
        distance = round(geodesic((latitude, longitude), (station_lat, station_lon)).miles, 1)

        station_data = get_weather_data(station_id, year)

        if station_data:
            stations_used.append({
                "Site": site_name,
                "Latitude": latitude,
                "Longitude": longitude,
                "Station ID": station_id,
                "Station Name": station_name,
                "Station Latitude": station_lat,
                "Station Longitude": station_lon,
                "Distance": distance
            })

        for entry in station_data:
            date = entry["date"][:10]  # Extract YYYY-MM-DD
            dtype = entry["datatype"]
            value = entry["value"]
            
            key = (site_name, date)
            if key not in weather_history:
                weather_history[key] = {
                    "site": site_name, "date": date, "tmax": None, "tmin": None, "prcp": None,
                    "S1 Tmax": None, "S1 Tmin": None, "S1 Prcp": None,
                    "S2 Tmax": None, "S2 Tmin": None, "S2 Prcp": None,
                    "S3 Tmax": None, "S3 Tmin": None, "S3 Prcp": None
                }
            
            if dtype == "TMAX":
                weather_history[key][f"S{idx} Tmax"] = value
            elif dtype == "TMIN":
                weather_history[key][f"S{idx} Tmin"] = value
            elif dtype == "PRCP":
                weather_history[key][f"S{idx} Prcp"] = value

    # Save station usage data
    pd.DataFrame(stations_used).to_csv("stations used.csv", index=False)

    # Save weather history data
    pd.DataFrame(weather_history.values()).to_csv("weather_history.csv", index=False)

    input("Press Enter to continue to the next site...")
