# RouteMap NavData Update Pipeline

This repository is a static update site for the RouteMap iOS app. The app should
not depend directly on upstream aviation-data URLs. It should download RouteMap
owned files from GitHub Pages instead.

```text
Upstream sources
  -> Tools/NavDataBuilder/build_navdata.py
  -> GitHub Pages UpdateSite/navdata/
  -> https://fox3nova.github.io/routemap/navdata/manifest.json
```

## GitHub Pages

Repository settings:

1. Open `Settings > Pages`.
2. Set `Source` to `GitHub Actions`.
3. Optionally add repository variable:

```text
NAVDATA_BASE_URL=https://fox3nova.github.io/routemap/navdata
```

The workflow also works without that variable because it derives the default URL
from the repository owner and name.

## Schedule

`.github/workflows/navdata-update.yml` runs every Thursday:

```text
03:23 UTC / 11:23 Taiwan time
```

The workflow can also be run manually. It compares the new package `dataHash`
with the currently published manifest and skips deployment when the normalized
data has not changed.

## Generated Files

The workflow publishes these files to GitHub Pages:

```text
navdata/manifest.json
navdata/index.json
navdata/cycles/<cycle>/manifest.json
navdata/cycles/<cycle>/NavData.csv
navdata/cycles/<cycle>/navdata.sqlite
navdata/cycles/<cycle>/RouteMapNavData_<cycle>.rmapnavdata
```

Generated files are not committed to this repository. They are only uploaded as
a GitHub Pages artifact.

## Local Build

Use download mode because this repository does not commit large upstream source
snapshots:

```sh
python3 Tools/NavDataBuilder/build_navdata.py \
  --download \
  --cycle test \
  --base-url https://fox3nova.github.io/routemap/navdata
```

The generated static site is written to:

```text
UpdateSite/navdata/
```

## App Import Flow

The iOS app should request:

```text
https://fox3nova.github.io/routemap/navdata/manifest.json
```

The app reads the manifest, downloads `NavData.csv`, validates the SHA-256 hash,
stores the CSV in Application Support, and prefers the installed CSV before
falling back to bundled navdata on later launches.

## Static Pages

The same GitHub Pages deployment also hosts App Store support pages:

```text
https://fox3nova.github.io/routemap/privacy.html
https://fox3nova.github.io/routemap/support.html
```

Pushes that touch the workflow, source data, builder, docs, or static HTML pages
deploy the Pages artifact immediately. Scheduled runs deploy only when the
generated navdata hash differs from the currently published manifest.

## Current Source Limits

Current sources are suitable for RouteMap planning display and prototype use:

- `global-waypoints`: waypoint CSV from `FayyazAK/Global-Aviation-Waypoints`.
- `ourairports-airports`: airport CSV from OurAirports, normalized into ICAO and IATA lookup rows.
- `ourairports-navaids`: navaid CSV from OurAirports.
- `routemap-overrides`: RouteMap curated waypoint corrections.

These sources are not certified AIRAC navigation data and are not suitable for
operational navigation. Airway segment tables are present in the generated SQLite
schema but remain empty until a licensed airway source is added.
