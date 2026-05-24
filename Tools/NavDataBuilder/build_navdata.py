#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = Path(__file__).resolve().with_name("sources.json")
DATA_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NavPoint:
    ident: str
    name: str
    latitude: float
    longitude: float
    country: str
    kind: str
    source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static RouteMap navdata update package."
    )
    parser.add_argument("--sources", default=str(DEFAULT_SOURCES), help="Path to sources.json.")
    parser.add_argument("--output", default="UpdateSite/navdata", help="Output folder for static hosting.")
    parser.add_argument("--cycle", default="auto", help="AIRAC/data cycle label. Use auto for YYYYMMDD.")
    parser.add_argument("--base-url", default="", help="Public base URL ending at /navdata. Optional.")
    parser.add_argument("--download", action="store_true", help="Download source files instead of using localPath.")
    parser.add_argument("--skip-unchanged", action="store_true", help="Do not rewrite output if normalized data is unchanged.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_config = read_json(resolve_path(args.sources))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cycle = datetime.now(timezone.utc).strftime("%Y%m%d") if args.cycle == "auto" else args.cycle

    source_results = []
    points = []
    with tempfile.TemporaryDirectory(prefix="routemap-navdata-") as temp_name:
        temp_dir = Path(temp_name)
        for source in source_config["sources"]:
            data = load_source(source, args.download, temp_dir)
            source_results.append(source_result(source, data))
            points.extend(normalize_source(source, data))

        csv_bytes = make_navdata_csv(points)
        data_hash = sha256_bytes(csv_bytes)

        output_dir = resolve_path(args.output)
        latest_manifest_path = output_dir / "manifest.json"
        if args.skip_unchanged and latest_manifest_path.exists():
            latest_manifest = read_json(latest_manifest_path)
            if latest_manifest.get("dataHash") == data_hash:
                print(f"No navdata changes detected. Existing dataHash={data_hash}")
                return 0

        cycle_dir = output_dir / "cycles" / cycle
        cycle_dir.mkdir(parents=True, exist_ok=True)

        navdata_csv_path = cycle_dir / "NavData.csv"
        sqlite_path = cycle_dir / "navdata.sqlite"
        package_path = cycle_dir / f"RouteMapNavData_{cycle}.rmapnavdata"

        navdata_csv_path.write_bytes(csv_bytes)
        build_sqlite(sqlite_path, points, cycle, generated_at, data_hash)

        internal_manifest = make_manifest(
            cycle=cycle,
            generated_at=generated_at,
            data_hash=data_hash,
            points=points,
            source_results=source_results,
            base_url=args.base_url,
            cycle_dir=cycle_dir,
            package_path=None,
        )
        (cycle_dir / "manifest.json").write_text(
            json.dumps(internal_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        build_package(
            package_path=package_path,
            manifest_path=cycle_dir / "manifest.json",
            csv_path=navdata_csv_path,
            sqlite_path=sqlite_path,
        )

        external_manifest = make_manifest(
            cycle=cycle,
            generated_at=generated_at,
            data_hash=data_hash,
            points=points,
            source_results=source_results,
            base_url=args.base_url,
            cycle_dir=cycle_dir,
            package_path=package_path,
        )
        latest_manifest_path.write_text(
            json.dumps(external_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        update_index(output_dir / "index.json", external_manifest)
        print_summary(external_manifest)

    return 0


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_source(source: dict, should_download: bool, temp_dir: Path) -> bytes:
    if should_download and source.get("url"):
        destination = temp_dir / f"{source['id']}.csv"
        print(f"Downloading {source['displayName']} from {source['url']}")
        try:
            request = urllib.request.Request(
                source["url"],
                headers={"User-Agent": "RouteMapNavDataBuilder/1.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                destination.write_bytes(response.read())
            return destination.read_bytes()
        except Exception as error:
            local_path = resolve_path(source["localPath"])
            if local_path.exists():
                print(f"Download failed for {source['id']}; using local fallback: {error}", file=sys.stderr)
                return local_path.read_bytes()
            raise

    return resolve_path(source["localPath"]).read_bytes()


def source_result(source: dict, data: bytes) -> dict:
    return {
        "id": source["id"],
        "displayName": source["displayName"],
        "type": source["type"],
        "url": source.get("url", ""),
        "license": source.get("license", ""),
        "notes": source.get("notes", ""),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def normalize_source(source: dict, data: bytes) -> list[NavPoint]:
    text = data.decode("utf-8-sig")
    if source["type"] == "global_waypoints":
        return normalize_global_waypoints(source["id"], text)
    if source["type"] == "ourairports_navaids":
        return normalize_ourairports_navaids(source["id"], text)
    if source["type"] == "ourairports_airports":
        return normalize_ourairports_airports(source["id"], text)
    if source["type"] == "waypoint_overrides":
        return normalize_waypoint_overrides(source["id"], text)
    raise ValueError(f"Unsupported source type: {source['type']}")


def normalize_global_waypoints(source_id: str, text: str) -> list[NavPoint]:
    points = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = clean_ident(row.get("IDENT", ""))
        latitude = parse_coordinate(row.get("LATITUDE"), 90)
        longitude = parse_coordinate(row.get("LONGITUDE"), 180)
        if not ident or latitude is None or longitude is None:
            continue
        country = clean_text(row.get("COUNTRY_NAME") or row.get("COUNTRY_CODE") or "")
        points.append(
            NavPoint(
                ident=ident,
                name=ident,
                latitude=latitude,
                longitude=longitude,
                country=country,
                kind="fix",
                source=source_id,
            )
        )
    return points


def normalize_ourairports_navaids(source_id: str, text: str) -> list[NavPoint]:
    points = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = clean_ident(row.get("ident", ""))
        latitude = parse_coordinate(row.get("latitude_deg"), 90)
        longitude = parse_coordinate(row.get("longitude_deg"), 180)
        if not ident or latitude is None or longitude is None:
            continue
        navaid_type = clean_text(row.get("type") or "navaid").lower()
        name = clean_text(row.get("name") or ident)
        country = clean_text(row.get("iso_country") or "")
        points.append(
            NavPoint(
                ident=ident,
                name=name,
                latitude=latitude,
                longitude=longitude,
                country=country,
                kind=navaid_type,
                source=source_id,
            )
        )
    return points


def normalize_ourairports_airports(source_id: str, text: str) -> list[NavPoint]:
    points = []
    seen_idents = set()
    for row in csv.DictReader(io.StringIO(text)):
        airport_type = clean_text(row.get("type") or row.get("airport_type") or "")
        if airport_type == "closed":
            continue

        iata = clean_ident(row.get("iata") or row.get("iata_code") or "")
        icao = clean_ident(row.get("icao") or row.get("icao_code") or row.get("gps_code") or "")
        ident = clean_ident(row.get("ident") or icao or iata)
        primary_ident = icao or ident or iata
        latitude = parse_coordinate(row.get("latitude") or row.get("latitude_deg"), 90)
        longitude = parse_coordinate(row.get("longitude") or row.get("longitude_deg"), 180)
        if not primary_ident or latitude is None or longitude is None:
            continue

        scheduled_service = clean_text(row.get("scheduled_service") or "")
        if not is_route_airport(airport_type, scheduled_service, iata):
            continue

        name = clean_text(row.get("name") or primary_ident)
        municipality = clean_text(row.get("municipality") or "")
        country = clean_text(row.get("country") or row.get("iso_country") or "")
        code_parts = [primary_ident]
        if iata and iata != primary_ident:
            code_parts.append(iata)
        code_label = " / ".join(code_parts)
        point_name = clean_text(" ".join(part for part in [code_label or primary_ident, name, municipality] if part))

        for airport_ident in [primary_ident, iata]:
            if not airport_ident:
                continue
            key = (airport_ident, latitude, longitude)
            if key in seen_idents:
                continue
            seen_idents.add(key)
            points.append(
                NavPoint(
                    ident=airport_ident,
                    name=point_name,
                    latitude=latitude,
                    longitude=longitude,
                    country=country,
                    kind="airport",
                    source=source_id,
                )
            )
    return points


def normalize_waypoint_overrides(source_id: str, text: str) -> list[NavPoint]:
    points = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = clean_ident(row.get("IDENT", ""))
        latitude = parse_coordinate(row.get("LATITUDE"), 90)
        longitude = parse_coordinate(row.get("LONGITUDE"), 180)
        if not ident or latitude is None or longitude is None:
            continue
        name = clean_text(row.get("NAME") or ident)
        points.append(
            NavPoint(
                ident=ident,
                name=name,
                latitude=latitude,
                longitude=longitude,
                country="",
                kind="route-fix",
                source=source_id,
            )
        )
    return points


def clean_ident(value: str) -> str:
    return clean_text(value).upper()


def clean_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def is_route_airport(airport_type: str, scheduled_service: str, iata: str) -> bool:
    if airport_type in ("large_airport", "medium_airport"):
        return True
    if iata and airport_type not in ("closed", "heliport", "balloonport"):
        return True
    return scheduled_service == "yes"


def parse_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse_coordinate(value: str | None, maximum_degrees: float) -> float | None:
    text = clean_text(value or "").replace("°", "").upper()
    if not text:
        return None

    sign = 1.0
    if text[0] in ("S", "W"):
        sign = -1.0
        text = text[1:]
    elif text[0] in ("N", "E"):
        text = text[1:]

    if text and text[-1] in ("S", "W"):
        sign = -1.0
        text = text[:-1]
    elif text and text[-1] in ("N", "E"):
        text = text[:-1]

    parsed = parse_float(text)
    if parsed is None:
        return None
    if abs(parsed) > maximum_degrees:
        parsed = parse_compact_dms(text, maximum_degrees)
        if parsed is None:
            return None
    return parsed * sign


def parse_compact_dms(text: str, maximum_degrees: float) -> float | None:
    if not text.isdigit():
        return None

    degree_digits = 2 if maximum_degrees <= 90 else 3
    minute_second_length = len(text) - degree_digits
    if minute_second_length not in (2, 4):
        return None

    degrees = float(text[:degree_digits])
    minutes = float(text[degree_digits:degree_digits + 2])
    seconds = float(text[degree_digits + 2:]) if minute_second_length == 4 else 0.0
    if degrees > maximum_degrees or minutes >= 60 or seconds >= 60:
        return None
    return degrees + minutes / 60 + seconds / 3600


def make_navdata_csv(points: list[NavPoint]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["ident", "name", "latitude", "longitude", "country", "kind", "source"])
    for point in points:
        writer.writerow(
            [
                point.ident,
                point.name,
                f"{point.latitude:.8f}",
                f"{point.longitude:.8f}",
                point.country,
                point.kind,
                point.source,
            ]
        )
    return output.getvalue().encode("utf-8")


def build_sqlite(path: Path, points: list[NavPoint], cycle: str, generated_at: str, data_hash: str) -> None:
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute(
            """
            CREATE TABLE metadata (
              key TEXT PRIMARY KEY NOT NULL,
              value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE points (
              id INTEGER PRIMARY KEY,
              ident TEXT NOT NULL,
              name TEXT NOT NULL,
              latitude REAL NOT NULL,
              longitude REAL NOT NULL,
              country TEXT NOT NULL,
              kind TEXT NOT NULL,
              source TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX points_ident_idx ON points(ident)")
        connection.execute("CREATE INDEX points_kind_idx ON points(kind)")
        connection.execute("CREATE INDEX points_country_idx ON points(country)")
        connection.execute(
            """
            CREATE TABLE airways (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              source TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE airway_segments (
              id INTEGER PRIMARY KEY,
              airway_name TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              from_ident TEXT NOT NULL,
              to_ident TEXT NOT NULL,
              source TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [
                ("schemaVersion", str(DATA_SCHEMA_VERSION)),
                ("cycle", cycle),
                ("generatedAt", generated_at),
                ("dataHash", data_hash),
            ],
        )
        connection.executemany(
            """
            INSERT INTO points(ident, name, latitude, longitude, country, kind, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    point.ident,
                    point.name,
                    point.latitude,
                    point.longitude,
                    point.country,
                    point.kind,
                    point.source,
                )
                for point in points
            ],
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def make_manifest(
    cycle: str,
    generated_at: str,
    data_hash: str,
    points: list[NavPoint],
    source_results: list[dict],
    base_url: str,
    cycle_dir: Path,
    package_path: Path | None,
) -> dict:
    counts_by_kind = {}
    for point in points:
        counts_by_kind[point.kind] = counts_by_kind.get(point.kind, 0) + 1

    manifest = {
        "schemaVersion": 1,
        "dataSchemaVersion": DATA_SCHEMA_VERSION,
        "cycle": cycle,
        "generatedAt": generated_at,
        "dataHash": data_hash,
        "counts": {
            "points": len(points),
            "byKind": dict(sorted(counts_by_kind.items())),
            "airways": 0,
            "airwaySegments": 0,
        },
        "sources": source_results,
        "warnings": [
            "Prototype data package only.",
            "Not certified AIRAC data and not for operational navigation.",
            "Airway segment tables are present but empty until a licensed airway source is added."
        ],
    }

    files = {}
    for name in ["NavData.csv", "navdata.sqlite"]:
        path = cycle_dir / name
        files[name] = file_entry(path, base_url, cycle)
    manifest["files"] = files

    if package_path:
        manifest["package"] = file_entry(package_path, base_url, cycle)

    return manifest


def file_entry(path: Path, base_url: str, cycle: str) -> dict:
    relative_path = f"cycles/{cycle}/{path.name}"
    entry = {
        "fileName": path.name,
        "path": relative_path,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if base_url:
        entry["url"] = f"{base_url.rstrip('/')}/{relative_path}"
    return entry


def build_package(package_path: Path, manifest_path: Path, csv_path: Path, sqlite_path: Path) -> None:
    if package_path.exists():
        package_path.unlink()

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(manifest_path, "manifest.json")
        archive.write(csv_path, "NavData.csv")
        archive.write(sqlite_path, "navdata.sqlite")


def update_index(index_path: Path, latest_manifest: dict) -> None:
    if index_path.exists():
        index = read_json(index_path)
    else:
        index = {"schemaVersion": 1, "cycles": []}

    cycles = [cycle for cycle in index.get("cycles", []) if cycle.get("cycle") != latest_manifest["cycle"]]
    cycles.insert(
        0,
        {
            "cycle": latest_manifest["cycle"],
            "generatedAt": latest_manifest["generatedAt"],
            "dataHash": latest_manifest["dataHash"],
            "counts": latest_manifest["counts"],
            "package": latest_manifest.get("package"),
        },
    )
    index["cycles"] = cycles[:24]
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_summary(manifest: dict) -> None:
    print(f"Built RouteMap navdata cycle {manifest['cycle']}")
    print(f"Data hash: {manifest['dataHash']}")
    print(f"Points: {manifest['counts']['points']}")
    if "package" in manifest:
        package = manifest["package"]
        print(f"Package: {package['path']} ({package['bytes']} bytes)")


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
