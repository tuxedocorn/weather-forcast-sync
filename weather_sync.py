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

SHEET_ID = 8274999350611844  # numeric ID required by REST API

# Column IDs (do not change — other columns have formulas we leave alone)
COL_DATE = 2351625581318020
COL_MAX  = 6855225208688516
COL_MIN  = 1225725674475396

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

    # Open-Meteo CSV has metadata rows at the top (lat, lon, elevation, etc.)
    # before the actual header row that starts with "time".
    # Find the header row by looking for the line starting with "time".
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("time"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(f"Could not find 'time' header row in CSV. First few lines: {lines[:5]}")

    print(f"  Found data header at line {header_idx}: {lines[header_idx]}")

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        date_val = parts[0].strip()
        max_val  = parts[1].strip()
        min_val  = parts[2].strip()
        if not date_val or not date_val[0].isdigit():
            continue
        rows.append({"date": date_val, "max": max_val, "min": min_val})

    print(f"  Parsed {len(rows)} forecast days")
    return rows


# ── Step 2: Clear existing rows ───────────────────────────────────────────────

def get_existing_row_ids(token):
    # Fetch the full sheet; rows array contains all row IDs
    url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}?include=rowIds"
    resp = requests.get(url, headers=ss_headers(token), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return [r["id"] for r in data.get("rows", [])]


def delete_rows(token, row_ids):
    if not row_ids:
        print("  No existing rows to delete")
        return
    # Smartsheet allows up to 450 row IDs per delete request
    chunk_size = 450
    total = 0
    for i in range(0, len(row_ids), chunk_size):
        chunk = row_ids[i:i + chunk_size]
        ids_param = ",".join(str(rid) for rid in chunk)
        url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows?ids={ids_param}"
        resp = requests.delete(url, headers=ss_headers(token), timeout=60)
        resp.raise_for_status()
        total += len(chunk)
    print(f"  Deleted {total} existing rows")


# ── Step 3: Insert new rows ───────────────────────────────────────────────────

def build_rows(forecast):
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
    if not forecast:
        raise ValueError("No forecast data parsed — aborting to avoid wiping sheet")

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
