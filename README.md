# AeroRouteMap NavData Update Site

This repository only hosts AeroRouteMap navigation-data updates. It does not need
the iOS app source code.

The app-facing manifest is published by GitHub Pages at:

```text
https://fox3nova.github.io/aeroroutemap/navdata/manifest.json
```

## What Is In This Repository

```text
.github/workflows/navdata-update.yml
Tools/NavDataBuilder/
Data/WaypointOverrides.csv
Data/NavDataValidation.csv
UpdateSite/privacy.html
UpdateSite/support.html
Docs/NavDataUpdate.md
```

The workflow downloads public upstream waypoint, airport, and navaid sources,
applies the AeroRouteMap override layer, builds a static update package, validates
known reference points, and deploys only the generated `UpdateSite/` artifact to
GitHub Pages.

Generated files are intentionally not committed back to the repository.

## Schedule

The workflow runs every Thursday at `03:23 UTC`, which is Thursday `11:23` in
Taiwan. It can also be run manually from GitHub Actions.

This is intentionally less frequent than daily because aviation navdata normally
changes by cycle rather than every day. The workflow compares the generated
`dataHash` with the currently published manifest and skips deployment when the
normalized data has not changed. Pushes that touch the workflow, source data,
builder, docs, or static site pages deploy the Pages artifact immediately.

## Data Validation

`Data/NavDataValidation.csv` lists reference points that have been checked
against official or curated sources. The workflow validates the generated
`NavData.csv` before deployment and fails if any listed point is missing or
outside its tolerance.

## Public Pages

```text
https://fox3nova.github.io/aeroroutemap/privacy.html
https://fox3nova.github.io/aeroroutemap/support.html
```

## Manual Run

In GitHub:

```text
Actions > Build AeroRouteMap NavData > Run workflow
```

Optional repository variable:

```text
NAVDATA_BASE_URL=https://fox3nova.github.io/aeroroutemap/navdata
```

If the variable is not set, the workflow derives the same URL from the repository
owner and repository name.
