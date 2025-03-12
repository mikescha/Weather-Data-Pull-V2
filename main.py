import requests
import pandas as pd
from datetime import datetime, timedelta

# NOAA API settings
base_url_stations = "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations"
base_url_data = "https://www.ncdc.noaa.gov/cdo-web/api/v2/data"

# Define API token
headers = {
    "token": "hZCHRgmqstfIwofCZtJUmzhkiAmOSOFj"  
}



