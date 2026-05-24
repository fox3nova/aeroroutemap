# RouteMap NavData Update Site

This repository only hosts RouteMap navigation-data updates. It does not need
the iOS app source code.

The app-facing manifest is published by GitHub Pages at:

```text
https://fox3nova.github.io/routemap/navdata/manifest.json
```

## What Is In This Repository

```text
.github/workflows/navdata-update.yml
Tools/NavDataBuilder/
Data/WaypointOverrides.csv
UpdateSite/privacy.html
UpdateSite/support.html
Docs/NavDataUpdate.md
```

The workflow downloads public upstream waypoint, airport, and navaid sources,
applies the RouteMap override layer, builds a static update package, and deploys
only the generated `UpdateSite/` artifact to GitHub Pages.

Generated files are intentionally not committed back to the repository.

## Schedule

The workflow runs every Thursday at `03:23 UTC`, which is Thursday `11:23` in
Taiwan. It can also be run manually from GitHub Actions.

This is intentionally less frequent than daily because aviation navdata normally
changes by cycle rather than every day. The workflow compares the generated
`dataHash` with the currently published manifest and skips deployment when the
normalized data has not changed. Pushes that touch the workflow, source data,
builder, docs, or static site pages deploy the Pages artifact immediately.

## Public Pages

```text
https://fox3nova.github.io/routemap/privacy.html
https://fox3nova.github.io/routemap/support.html
```

## Manual Run

In GitHub:

```text
Actions > Build RouteMap NavData > Run workflow
```

Optional repository variable:

```text
NAVDATA_BASE_URL=https://fox3nova.github.io/routemap/navdata
```

If the variable is not set, the workflow derives the same URL from the repository
owner and repository name.
