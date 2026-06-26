#!/usr/bin/env python3
"""
weather_sync.py
Fetches 16-day forecast from Open-Meteo and writes it to Smartsheet.
Runs on a schedule via GitHub Actions (2x/day).
"""

import os
import csv
import requests

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_ID = "wPPcCrWJQ5vpGgm6C3MR22W7pHqGQ5Gwjhc5rxx1"

# Column IDs (do not change — other columns have formulas we leave alone)
COL_DATE    = 2351625581318020
COL_MAX     = 6855225208688516
COL_MIN     = 1225725674475396

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=38.663900"
    "&longitude=-107.985372"
    "&daily=temperature_2m_max,temperature_2m_min"
    "&timezone=auto"
    "&forecast_days=16"
    "&temperature_unit=fahrenheit"
    "&format=csv"
)

SMARTSHEET_API = "https://api.smartsheet.com/2.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_token():
    token = os.environ.get("SMARTSHEET_TOKEN")
    if not token:
        raise EnvironmentError("SMARTSHEET_TOKEN environment variable not set")
    return token


def ss_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ── Step 1: Fetch forecast ────────────────────────────────────────────────────

def fetch_forecast():
    """Returns list of dicts: [{date, max, min}, ...]"""
    print("Fetching forecast from Open-Meteo...")
    resp = requests.get(OPEN_METEO_URL, timeout=30)
    resp.raise_for_status()

    lines = resp.text.splitlines()

    # Open-Meteo CSV structure:
    #   Row 0: #latitude=38.6639          ← skip
    #   Row 1: #longitude=-107.985372     ← skip
    #   Row 2: #elevation=...             ← skip (may vary)
    #   Row N: header row (time,temperature_2m_max (°F),temperature_2m_min (°F))
    #   Rows N+1...: data

    # Skip comment/metadata lines starting with '#'
    data_lines = [l for l in lines if not l.startswith("#")]

    reader = csv.DictReader(data_lines)
    rows = []
    for row in reader:
        date_val = row.get("time", "").strip()
        max_val  = row.get("temperature_2m_max (°F)", "").strip()
        min_val  = row.get("temperature_2m_min (°F)", "").strip()
        if date_val and max_val and min_val:
            rows.append({"date": date_val, "max": max_val, "min": min_val})

    print(f"  Parsed {len(rows)} forecast days")
    return rows


# ── Step 2: Clear existing rows ───────────────────────────────────────────────

def get_existing_row_ids(token):
    url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows"
    resp = requests.get(url, headers=ss_headers(token), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [r["id"] for r in data.get("rows", [])]


def delete_rows(token, row_ids):
    if not row_ids:
        print("  No existing rows to delete")
        return
    # Smartsheet allows up to 450 row IDs per delete request
    chunk_size = 450
    for i in range(0, len(row_ids), chunk_size):
        chunk = row_ids[i:i + chunk_size]
        ids_param = ",".join(str(rid) for rid in chunk)
        url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows?ids={ids_param}"
        resp = requests.delete(url, headers=ss_headers(token), timeout=30)
        resp.raise_for_status()
    print(f"  Deleted {len(row_ids)} existing rows")


# ── Step 3: Insert new rows ───────────────────────────────────────────────────

def build_rows(forecast):
    """Build Smartsheet row payload from forecast list."""
    rows = []
    for f in forecast:
        rows.append({
            "cells": [
                {"columnId": COL_DATE, "value": f["date"]},
                {"columnId": COL_MAX,  "value": float(f["max"])},
                {"columnId": COL_MIN,  "value": float(f["min"])},
            ]
        })
    return rows


def insert_rows(token, rows):
    url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows"
    resp = requests.post(url, headers=ss_headers(token), json=rows, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    inserted = len(result.get("result", []))
    print(f"  Inserted {inserted} rows")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = get_token()

    # 1. Fetch forecast
    forecast = fetch_forecast()

    # 2. Clear sheet
    print("Clearing existing rows...")
    row_ids = get_existing_row_ids(token)
    delete_rows(token, row_ids)

    # 3. Insert fresh data
    print("Inserting new forecast rows...")
    rows = build_rows(forecast)
    insert_rows(token, rows)

    print("Done ✓")


if __name__ == "__main__":
    main()
