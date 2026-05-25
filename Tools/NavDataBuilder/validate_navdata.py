#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SITE = ROOT / "UpdateSite" / "navdata"
DEFAULT_EXPECTATIONS = ROOT / "Data" / "NavDataValidation.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate generated AeroRouteMap navdata against fixed reference points."
    )
    parser.add_argument("--site", default=str(DEFAULT_SITE), help="Generated navdata site folder.")
    parser.add_argument(
        "--expectations",
        default=str(DEFAULT_EXPECTATIONS),
        help="CSV containing expected reference points.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    site_dir = Path(args.site)
    expectations_path = Path(args.expectations)
    manifest_path = site_dir / "manifest.json"

    manifest = read_json(manifest_path)
    navdata_entry = manifest.get("files", {}).get("NavData.csv")
    if not navdata_entry or not navdata_entry.get("path"):
        print("NavData validation failed: manifest does not include NavData.csv.", file=sys.stderr)
        return 1

    navdata_path = site_dir / navdata_entry["path"]
    rows = read_navdata(navdata_path)
    expectations = read_expectations(expectations_path)
    failures: list[str] = []

    for expected in expectations:
        candidates = [
            row
            for row in rows
            if row["ident"] == expected["ident"]
            and (not expected["kind"] or row["kind"] == expected["kind"])
        ]

        if not candidates:
            failures.append(
                f"{expected['ident']} missing"
                + (f" kind={expected['kind']}" if expected["kind"] else "")
            )
            continue

        best = min(
            candidates,
            key=lambda row: distance_nm(
                expected["latitude"],
                expected["longitude"],
                row["latitude"],
                row["longitude"],
            ),
        )
        best_distance = distance_nm(
            expected["latitude"],
            expected["longitude"],
            best["latitude"],
            best["longitude"],
        )
        if best_distance > expected["tolerance_nm"]:
            failures.append(
                f"{expected['ident']} {expected['kind']} is {best_distance:.2f} NM from expected "
                f"({best['latitude']:.6f}, {best['longitude']:.6f}); "
                f"expected ({expected['latitude']:.6f}, {expected['longitude']:.6f})"
            )

    if failures:
        print("NavData validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"Validated {len(expectations)} navdata reference points.")
    return 0


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_navdata(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {
                "ident": row["ident"].strip().upper(),
                "kind": row["kind"].strip().lower(),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
            for row in csv.DictReader(handle)
        ]


def read_expectations(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        expectations = []
        for row in csv.DictReader(handle):
            expectations.append(
                {
                    "ident": row["IDENT"].strip().upper(),
                    "kind": row["KIND"].strip().lower(),
                    "latitude": float(row["LATITUDE"]),
                    "longitude": float(row["LONGITUDE"]),
                    "tolerance_nm": float(row["TOLERANCE_NM"]),
                    "reference": row.get("REFERENCE", "").strip(),
                }
            )
        return expectations


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_nm = 3440.065
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


if __name__ == "__main__":
    raise SystemExit(main())
