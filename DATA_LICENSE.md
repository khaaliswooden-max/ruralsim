# Data licensing

The **code** in this repository is licensed under the Apache License 2.0 (`LICENSE`).
The **data** is not. It falls into three groups, each under its own terms.

## 1. OpenStreetMap-derived data: ODbL 1.0

Map data from OpenStreetMap © OpenStreetMap contributors, available under the
[Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
See <https://www.openstreetmap.org/copyright>.

This covers:

- `worlds/*/layers_raw/osm/` (roads, buildings, schools, healthcare, power, places, water,
  food shops, bridges)
- every layer built from those files: the matching `worlds/*/stage/*.usda` layers and
  `worlds/*/viewer_data/*.json` files (roads, buildings, power lines, substations and
  generators, OSM-placed facilities)

If you publicly use or share a database derived from these files, the ODbL requires you to
share it under the ODbL and to keep the attribution. Images and other "produced works" made
from them must credit "© OpenStreetMap contributors".

## 2. Third-party public data: the publisher's terms

Everything else in `data/`, `pilots/`, `national/` and `worlds/*/layers_raw/` comes from the
publishers named in `data/codebook.csv` and in each layer's `_meta.json`. It stays under
their terms. Most are U.S. federal works (Census Bureau, USDA ERS, CMS, USGS, EPA, FHWA, EIA,
BTS), which are generally not subject to U.S. copyright. Non-federal sources keep their own
licenses, including Open-Meteo weather data (CC BY 4.0, attribution required) and the
compiled county election returns (see their Harvard Dataverse and GitHub listings).
Election data is governance context only and is excluded from every model (D-007).

## 3. RuralSim's own data and writing: CC BY 4.0

Original material created for RuralSim is licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/):
specifications (`specs/`), experiment cards and results (`experiments/`), validation sheets
(`validation/`), documentation (`docs/`, READMEs), the codebook's descriptions, and the
website's text. Credit "RuralSim (ruralsim.io)".

Where a file mixes groups (for example a validation sheet quoting OSM counts), each part
keeps the terms of its source.

This summary is provided for convenience and is not legal advice.
