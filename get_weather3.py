#!/usr/bin/env python3
"""
Fetch daily gridMET weather for TRBL sites.

Input:
    - "TRBL Analysis tracking - Sites.csv"
      Required columns:
        - Name      (e.g. "2024 Rush Ranch")
        - Latitude  (decimal degrees, +N)
        - Longitude (decimal degrees, -W)

For each row:
    - Extract year = first 4 characters of Name (must be YYYY).
    - Query gridMET for daily data from Feb 1 to Sep 1 of that year
      at the site's coordinates using pygridmet.get_bycoords().
    - Retrieve variables:
        * tmmx  (daily max temperature, K)
        * tmmn  (daily min temperature, K)
        * pr    (precipitation, mm)
        * vs    (daily mean wind speed, m/s)

Output:
    - "trbl_sites_gridmet_weather.csv" with columns:
        Name
        Latitude
        Longitude
        date                  (YYYY-MM-DD)
        year
        tmax_K                (gridMET tmmx)
        tmax_C                (tmmx converted to deg C)
        tmin_K                (gridMET tmmn)
        tmin_C                (tmmn converted to deg C)
        precip_mm             (gridMET pr)
        wind_speed_mean_m_s   (gridMET vs)
        wind_speed_max_m_s    (placeholder; NaN, not available in gridMET)
        gridmet_dataset       ("gridMET daily")
        gridmet_variables     ("tmmx,tmmn,pr,vs")
        gridmet_source        ("pygridmet via gridMET NCSS")
        gridmet_reference     ("Abatzoglou 2013, Int. J. Climatol.")

Notes:
    - gridMET daily values correspond to midnight-to-midnight MST
      (approx 07:00 UTC). See gridMET docs for details.
    - Temperatures are provided by gridMET in Kelvin; we convert to Celsius.
    - gridMET provides *daily mean* wind speed (vs), not daily max;
      we leave max wind speed as NaN for scientific honesty.

To reproduce:
    - A reviewer can rerun this script with the same input CSV and
      date range, given a working pygridmet installation.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import pygridmet as gridmet
import requests
from pathlib import Path

INPUT_CSV = r"C:\Users\mikes\OneDrive\Documents\GitHub\TRBLSummarizer\TRBLSummarizer\Data\TRBL Analysis tracking - Sites.csv"
OUTPUT_CSV = "trbl_sites_gridmet_weather.csv"
FAILED_CSV = "gridmet_failed_sites.csv"


def get_year_from_name(name: str) -> int:
    """
    Extract 4-digit year from the beginning of the site Name.
    Raises ValueError if the first 4 chars are not digits.
    """
    if not isinstance(name, str):
        raise ValueError(f"Name '{name}' is not a string")

    year_str = name[:4]
    if not year_str.isdigit():
        raise ValueError(
            f"Name '{name}' does not start with a 4-digit year (YYYY)."
        )
    year = int(year_str)
    if year < 1979:
        # gridMET starts in 1979
        raise ValueError(
            f"Year {year} in Name '{name}' is before gridMET begins (1979)."
        )
    return year

def _find_var_column(df: pd.DataFrame, abbr: str, required: bool = True) -> str:
    """Return the actual column name for a gridMET variable abbreviation.

    pygridmet/get_bycoords names columns like "tmmx (K)", "pr (mm)", etc.
    This helper finds the first column whose name starts with the given
    abbreviation (e.g. "tmmx").
    """
    matches = [c for c in df.columns if c.startswith(abbr)]
    if not matches:
        if required:
            raise KeyError(
                f"No column starting with '{abbr}' found in gridMET DataFrame. "
                f"Available columns: {list(df.columns)}"
            )
        return ""
    return matches[0]


def fetch_gridmet_for_site(lat: float, lon: float, year: int) -> pd.DataFrame:
    start_date = f"{year}-02-01"
    end_date = f"{year}-10-01"
    coords = (float(lon), float(lat))
    try:
        df = gridmet.get_bycoords(
            coords,
            (start_date, end_date),
            variables=["tmmx", "tmmn", "pr", "vs"],
        )
        if df.empty:
            raise RuntimeError("gridMET returned no data")

        # Resolve variable columns, which come back like "tmmx (K)", etc.
        tmmx_col = _find_var_column(df, "tmmx")
        tmmn_col = _find_var_column(df, "tmmn")
        pr_col = _find_var_column(df, "pr")
        vs_col = _find_var_column(df, "vs")

        # Move index to a proper date column; handle both "index" and "time" cases
        df = df.reset_index()
        if "index" in df.columns:
            df = df.rename(columns={"index": "date"})
        elif "time" in df.columns:
            df = df.rename(columns={"time": "date"})
        if "date" not in df.columns:
            raise RuntimeError(
                f"Could not find time/date column in gridMET result. Columns: {list(df.columns)}"
            )

        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["year"] = year

        # gridMET daily values are aggregated midnight-to-midnight MST (UTC-7).
        # For sites in the approximate Pacific Time region (Baja CA to WA),
        # shift the label forward by one calendar day so that precipitation
        # totals align with local calendar days.
        df["date_mst"] = df["date"]
        if -130.0 <= float(lon) <= -110.0 and 25.0 <= float(lat) <= 50.0:
            df["date"] = df["date"] + pd.to_timedelta(1, unit="D")

        df["tmax_K"] = df[tmmx_col]
        df["tmin_K"] = df[tmmn_col]
        df["tmax_C"] = df[tmmx_col] - 273.15
        df["tmin_C"] = df[tmmn_col] - 273.15
        # Output-friendly units
        df["tmax_F"] = df["tmax_C"] * 9.0 / 5.0 + 32.0
        df["tmin_F"] = df["tmin_C"] * 9.0 / 5.0 + 32.0
        df["precip_mm"] = df[pr_col]
        df["precip_in"] = df["precip_mm"] / 25.4
        df["wind_speed_mean_m_s"] = df[vs_col]
        df["wind_speed_max_m_s"] = pd.NA
        df["weather_source"] = "gridMET"

        return df[[
            "date",
            "date_mst",
            "year",
            "tmax_K",
            "tmax_F",
            "tmin_K",
            "tmin_F",
            "precip_in",
            "wind_speed_mean_m_s",
            "wind_speed_max_m_s",
            "weather_source",
        ]]
    except Exception as e:
        print(f"gridMET failed, falling back to ERA5: {e}", file=sys.stderr)
        return fetch_era5_for_site(lat, lon, year)


def fetch_era5_for_site(lat: float, lon: float, year: int) -> pd.DataFrame:
    start_date = f"{year}-02-01"
    end_date = f"{year}-09-01"
    url = "https://archive-api.open-meteo.com/v1/era5"
    params = {"latitude":float(lat),"longitude":float(lon),"start_date":start_date,"end_date":end_date,
              "daily":["temperature_2m_max","temperature_2m_min","precipitation_sum","windspeed_10m_mean","windspeed_10m_max"],
              "windspeed_unit":"ms","timezone":"UTC"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    rows=[]
    for i,dt in enumerate(d["time"]):
        rows.append({"date":pd.to_datetime(dt).date(),"year":year,
                     "tmax_C":d["temperature_2m_max"][i],"tmin_C":d["temperature_2m_min"][i],
                     "precip_mm":d["precipitation_sum"][i],
                     "wind_speed_mean_m_s":d["windspeed_10m_mean"][i],
                     "wind_speed_max_m_s":d["windspeed_10m_max"][i]})
    df=pd.DataFrame(rows)
    df["date_mst"] = df["date"]  # ERA5 daily label is UTC; treat as equivalent here
    df["tmax_K"] = df["tmax_C"] + 273.15
    df["tmin_K"] = df["tmin_C"] + 273.15
    df["tmax_F"] = df["tmax_C"] * 9.0 / 5.0 + 32.0
    df["tmin_F"] = df["tmin_C"] * 9.0 / 5.0 + 32.0
    df["precip_in"] = df["precip_mm"] / 25.4
    df["weather_source"]="ERA5"
    return df[["date","date_mst","year","tmax_K","tmax_F","tmin_K","tmin_F","precip_in","wind_speed_mean_m_s","wind_speed_max_m_s","weather_source"]]

def main():
    input_path = Path(INPUT_CSV)
    failed_path = Path(FAILED_CSV)

    # Decide which sites to process:
    # - if FAILED_CSV exists, retry only those
    # - otherwise, use the full TRBL sites CSV
    if False: #failed_path.exists():
        print(f"Found {FAILED_CSV}; retrying only failed sites from previous run.")
        sites = pd.read_csv(failed_path)
        using_failed_file = True
    else:
        if not input_path.exists():
            print(f"ERROR: Input CSV not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        sites = pd.read_csv(input_path)
        using_failed_file = False

    required_cols = {"Name", "Latitude", "Longitude"}
    missing = required_cols - set(sites.columns)
    if missing:
        print(
            f"ERROR: Sites CSV is missing required columns: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    all_rows = []
    failed_rows = []

    for idx, row in sites.iterrows():
        name = row["Name"]
        lat = row["Latitude"]
        lon = row["Longitude"]
        site_id = row["Id"]

        try:
            year = get_year_from_name(name)
        except ValueError as e:
            print(f"Skipping row {idx} ({name}): {e}", file=sys.stderr)
            failed_rows.append({"Name": name, "Latitude": lat, "Longitude": lon})
            continue

        print(f"Processing site '{name}' (lat={lat}, lon={lon}), year={year}...")

        try:
            df_site = fetch_gridmet_for_site(lat, lon, year)
        except Exception as e:
            print(
                f"  ERROR fetching gridMET data for '{name}' "
                f"(lat={lat}, lon={lon}, year={year}): {e}",
                file=sys.stderr,
            )
            failed_rows.append({"Name": name, "Latitude": lat, "Longitude": lon})
            continue

        df_site["Site Id"] = site_id
        df_site["Name"] = name
        df_site["Latitude"] = lat
        df_site["Longitude"] = lon

        source_label = df_site["weather_source"].iloc[0] if "weather_source" in df_site.columns else "gridMET"

        if source_label == "gridMET":
            df_site["gridmet_dataset"] = "gridMET daily"
            df_site["gridmet_variables"] = "tmmx,tmmn,pr,vs"
            df_site["gridmet_source"] = "pygridmet via GridMET NCSS"
            df_site["gridmet_reference"] = "Abatzoglou 2013, Int. J. Climatol."
        elif source_label == "ERA5":
            df_site["gridmet_dataset"] = "ERA5 daily reanalysis"
            df_site["gridmet_variables"] = (
                "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                "windspeed_10m_mean,windspeed_10m_max"
            )
            df_site["gridmet_source"] = "Open-Meteo ERA5 API"
            df_site["gridmet_reference"] = "Hersbach et al. 2020, QJRMS"
        else:
            df_site["gridmet_dataset"] = source_label
            df_site["gridmet_variables"] = "unknown"
            df_site["gridmet_source"] = "unknown"
            df_site["gridmet_reference"] = "unknown"

        all_rows.append(df_site)

    # If nothing succeeded
    if not all_rows:
        print("No data fetched for any sites.", file=sys.stderr)
        if failed_rows:
            failed_df = pd.DataFrame(failed_rows).drop_duplicates()
            failed_df.to_csv(FAILED_CSV, index=False)
            print(
                f"Wrote {len(failed_df)} failed sites to {FAILED_CSV}.",
                file=sys.stderr,
            )
        sys.exit(1)

    # Concatenate successful site/day rows
    out = pd.concat(all_rows, ignore_index=True)

    col_order = [
        "Site Id", 
        "Name",
        "Latitude",
        "Longitude",
        "date",
        "date_mst",
        "year",
        "weather_source",
        "tmax_K",
        "tmax_F",
        "tmin_K",
        "tmin_F",
        "precip_in",
        "wind_speed_mean_m_s",
        "wind_speed_max_m_s",
        "gridmet_dataset",
        "gridmet_variables",
        "gridmet_source",
        "gridmet_reference",
    ]
    out = out[col_order]

    # Round numeric output columns to 1 decimal place for readability
    numeric_round_cols = [
        "tmax_K", "tmax_F", "tmin_K", "tmin_F",
        "precip_in", "wind_speed_mean_m_s", "wind_speed_max_m_s"
    ]
    for col in numeric_round_cols:
        if col in out.columns:
            out[col] = out[col].astype(float).round(1)

    out.sort_values(by=["Name", "date"], inplace=True)

    out_path = Path(OUTPUT_CSV)

    # Retry loop for writing main output file
    while True:
        try:
            out.to_csv(out_path, index=False)
            break
        except Exception as e:
            print(f"ERROR writing {out_path}: {e}")
            ans = input("File write failed. Close the file if open. Retry? (Y/N): ").strip().lower()
            if ans != "y":
                print("User cancelled output write. Exiting.")
                sys.exit(1)

    print(f"\nWrote {len(out)} rows to {out_path.resolve()}")
    print(
        "Note: For gridMET rows, wind_speed_max_m_s is NaN because gridMET "
        "provides only daily mean wind (vs). For ERA5 rows, "
        "wind_speed_max_m_s is filled from ERA5 daily max 10 m wind."
    )

    # Handle failed sites bookkeeping
    if failed_rows:
        failed_df = pd.DataFrame(failed_rows).drop_duplicates()
        failed_df.to_csv(FAILED_CSV, index=False)
        print(
            f"{len(failed_df)} site(s) failed; written to {FAILED_CSV}. "
            "Next run will retry only those.",
            file=sys.stderr,
        )
    else:
        # If everything succeeded, remove any existing failed file
        if failed_path.exists():
            failed_path.unlink()
            print(f"All sites succeeded; removed {FAILED_CSV}.")



def qa_gridmet_vs_station(
    gridmet_csv: str,
    station_csv: str,
    name_to_station_csv: str,
    out_summary_csv: str = "gridmet_station_qa_summary.csv",
    out_pairwise_csv: str = "gridmet_station_qa_pairwise.csv",
) -> pd.DataFrame:
    """Compare gridMET/ERA5 daily weather with station observations for QA.

    Parameters
    ----------
    gridmet_csv : str
        Path to CSV produced by this script (trbl_sites_gridmet_weather.csv).
    station_csv : str
        CSV of daily station data with at least the following columns:
            - station_id
            - date (YYYY-MM-DD)
            - tmax_F
            - tmin_F
            - precip_in
            - wind_speed_mean_m_s (optional)
    name_to_station_csv : str
        Mapping CSV with:
            - Name       (matching the 'Name' in gridmet_csv)
            - station_id
    out_summary_csv : str, default "gridmet_station_qa_summary.csv"
        Output path for per-variable QA metrics by station.
    out_pairwise_csv : str, default "gridmet_station_qa_pairwise.csv"
        Output path for merged day-by-day comparison rows.

    Returns
    -------
    pd.DataFrame
        QA summary metrics (one row per station_id × variable).
    """

    # Load data
    grid = pd.read_csv(gridmet_csv, parse_dates=["date"])
    stn = pd.read_csv(station_csv, parse_dates=["date"])
    mapping = pd.read_csv(name_to_station_csv)

    # Basic column checks
    required_grid_cols = {"Name", "date", "tmax_F", "tmin_F", "precip_in"}
    missing = required_grid_cols - set(grid.columns)
    if missing:
        raise ValueError(
            f"gridmet_csv is missing required columns: {', '.join(sorted(missing))}"
        )

    required_map_cols = {"Name", "station_id"}
    missing = required_map_cols - set(mapping.columns)
    if missing:
        raise ValueError(
            f"name_to_station_csv is missing required columns: {', '.join(sorted(missing))}"
        )

    required_stn_cols = {"station_id", "date", "tmax_F", "tmin_F", "precip_in"}
    missing = required_stn_cols - set(stn.columns)
    if missing:
        raise ValueError(
            f"station_csv is missing required columns: {', '.join(sorted(missing))}"
        )

    # Merge gridMET/ERA5 data with station IDs
    grid_map = grid.merge(mapping, on="Name", how="inner")

    # Merge with station data on station_id + date
    merged = grid_map.merge(
        stn,
        on=["station_id", "date"],
        suffixes=("_gridmet", "_station"),
        how="inner",
    )

    if merged.empty:
        raise RuntimeError("No overlapping dates between gridMET/ERA5 and station data.")

    # Variables to compare if present
    var_pairs = [
        ("tmax_F_gridmet", "tmax_F_station", "tmax_F"),
        ("tmin_F_gridmet", "tmin_F_station", "tmin_F"),
        ("precip_in_gridmet", "precip_in_station", "precip_in"),
    ]
    if (
        "wind_speed_mean_m_s_gridmet" in merged.columns
        and "wind_speed_mean_m_s_station" in merged.columns
    ):
        var_pairs.append(
            (
                "wind_speed_mean_m_s_gridmet",
                "wind_speed_mean_m_s_station",
                "wind_speed_mean_m_s",
            )
        )

    # Compute per-station QA metrics
    summary_rows = []
    for station_id, grp in merged.groupby("station_id"):
        for grid_col, stn_col, base_name in var_pairs:
            if grid_col not in grp.columns or stn_col not in grp.columns:
                continue

            g = grp[grid_col].astype(float)
            s = grp[stn_col].astype(float)
            diff = g - s

            mae = diff.abs().mean()
            bias = diff.mean()
            rmse = np.sqrt((diff**2).mean())
            corr = g.corr(s)

            summary_rows.append(
                {
                    "station_id": station_id,
                    "variable": base_name,
                    "n": int(len(grp)),
                    "mae": mae,
                    "bias_gridmet_minus_station": bias,
                    "rmse": rmse,
                    "pearson_r": corr,
                }
            )

    summary_df = pd.DataFrame(summary_rows)

    # Write outputs
    summary_df.to_csv(out_summary_csv, index=False)
    merged.to_csv(out_pairwise_csv, index=False)

    print(f"QA summary written to {out_summary_csv}")
    print(f"Pairwise gridMET vs station data written to {out_pairwise_csv}")

    return summary_df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TRBL gridMET/ERA5 fetch + QA tool")
    parser.add_argument(
        "--qa", nargs=3, metavar=("GRIDMET_CSV", "STATION_CSV", "MAP_CSV"),
        help="Run QA instead of fetching weather: provide gridmet_csv station_csv name_to_station_csv"
    )
    args = parser.parse_args()

    if args.qa:
        gridmet_csv, station_csv, map_csv = args.qa
        qa_gridmet_vs_station(gridmet_csv, station_csv, map_csv)
    else:
        main()
