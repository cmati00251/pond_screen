# PondScreen

PondScreen is a reproducible, open-data model that finds where heavy rain ponds when the storm sewers are full, and which buildings sit beside that water.

It reads the ground surface from lidar, classifies every 0.5 m of ground as roof, tree, lawn, water or pavement, pours design storms on it, and records how deep the water gets next to each building. It then checks itself against a municipal engineering study.

This repository runs it for the **Lesperance pump station service area in the Town of Tecumseh, Ontario** (271 ha, 3,988 buildings), and compares the results with the Town's 2019 Storm Drainage Master Plan.

## Results for Lesperance

| Result (100-year, 4-hour storm, sewers assumed full) | Value |
|---|---|
| Buildings with at least 0.30 m of water within 5 m | 351 of 3,988 |
| Buildings with at least 0.15 m of water within 5 m | 1,144 of 3,988 |
| Area under at least 0.15 m of water | 24.2 ha |
| Share of the area that is roof or pavement | 56.9 % |
| Master plan deep street-ponding spots reproduced | 81 of 86 (94 %); a randomly placed spot would score 55 % |
| Surface classification accuracy (200 checked points) | 89.2 % |

The worst hotspot is the low street grid around Little River Blvd by Lake St. Clair, which the master plan also names as its worst problem area (W-1).

Full write-ups:

- [`outputs/REPORT.md`](outputs/REPORT.md): methods and results
- [`outputs/validation.md`](outputs/validation.md): the comparison with the master plan, spot by spot
- [`outputs/decisions.md`](outputs/decisions.md): every threshold, assumption and change, with reasons and dates
- [`outputs/maps/`](outputs/maps/): maps of surfaces, low spots, each storm, validation and hotspots
- [`outputs/hotspots.csv`](outputs/hotspots.csv) and [`hotspots.geojson`](outputs/hotspots.geojson): the ten worst ponding spots

## What it is, and what it is not

PondScreen is a **screening tool**. It shows where water collects in a worst case for the sewer system, from free public data, in days rather than years. It is not a replacement for a calibrated hydraulic model.

| It does | It does not |
|---|---|
| Find every low spot in the terrain and the ground draining to it | Model pipes, pump stations, inlets or lake backwater |
| Estimate runoff from roofs, pavement, lawn and trees | Model timing, flow speed or soil soaking-in over a storm |
| Pass overflow from one low spot to the next downstream | Predict everyday flooding when sewers have spare capacity |
| Report water depth beside each building for four storms | Estimate damage or cost |

## How it works

| Step | Script | What it does | Main output |
|---|---|---|---|
| 1 | `01_download_small.py` | Downloads the master plan PDFs, StatCan building footprints and the Windsor A rainfall (IDF) file | `data/raw/`, inventory |
| 2 | `02_benchmark.py`, `02b_osm.py`, `02c_study_area.py`, `02d_buildings_study.py` | Renders the master plan pages, fetches OpenStreetMap layers, traces the study area from the plan's map, and selects the buildings | `study_area.gpkg`, `buildings_study.gpkg` |
| 3 | `03a_lidar_index.py`, `03b_lidar_download.py`, `03c_mosaic.py` | Finds the lidar tiles and reads only those out of the provincial packages; builds 0.5 m ground (DTM) and surface (DSM) models | `dtm.tif`, `dsm.tif` |
| 4 | `04a_imagery_index.py`, `04b_imagery.py` | Lists the aerial imagery tiles to order; resamples the delivered tiles to the 0.5 m grid and computes NDVI | `imagery.tif`, `ndvi.tif` |
| 5 | `05_surfaces.py`, `05b_accuracy.py` | Classifies each cell as roof, tree, grass/soil, water or sealed; measures accuracy against a visual review | `surfaces.tif`, `qa/accuracy.csv` |
| 6 | `06_depressions.py` | Raises buildings 3 m, fills hollows (WhiteboxTools), finds low spots, their capacity and catchments, and the flow paths | `depressions.gpkg` |
| 7 | `07_storms.py` | Applies the 2-, 10- and 100-year 4-hour storms and a 100 mm event; passes overflow downstream; finds water beside each building | `storm_summary.csv`, `ponding_<storm>.tif` |
| 8 | `08a_georef_benchmark.py`, `08_validation.py` | Aligns the master plan's ponding maps to real coordinates and scores the match | `validation.md` |
| 9 | `09_package.py` | Packages all layers, maps and the hotspot list | `layers.gpkg`, `hotspots.csv` |

The key calculation, in Step 7, is a volume balance for each low spot *i*:

```
inflow_i = storm depth × Σ (runoff share × 0.25 m²) over the cells draining to i
```

If inflow exceeds the low spot's capacity, the excess passes to the next low spot downstream. Runoff shares are roof 0.95, sealed 0.90, grass/soil 0.25, tree 0.15 and water 1.0. These and all other thresholds are named constants at the top of each script.

## Running it

### 1. Environment

```bash
conda env create -f environment.yml
conda activate pluvial
```

Run scripts with `conda run -n pluvial python scripts/<script>.py`, or from the activated environment, so GDAL finds its data files.

WhiteboxTools is installed by the `whitebox` Python package, which downloads the WhiteboxTools program (about 50 MB) the first time it runs.

### 2. Data

Most data downloads automatically. The aerial imagery cannot: run Step 4a, which writes `outputs/imagery_tiles_to_order.csv`. Order those tiles (full-quality GeoTIFF, all four bands) from the [Geospatial Ontario Imagery Orders App](https://experience.arcgis.com/experience/2358b9d2dd5c4077bdb47049bf0e7fa7/) and put them in `data/raw/imagery/`.

Disk space needed: about 4.5 GB, of which about 2.2 GB is imagery. The lidar step reads about 110 MB from the provincial packages instead of downloading 9.7 GB.

### 3. Pipeline

```bash
python scripts/run_pipeline.py          # status of every step: done / stale / ready / blocked
python scripts/run_pipeline.py --run    # run every step that is missing or out of date, in order
python scripts/run_pipeline.py --run 07 # run one step
```

The runner tracks each step's input files and its own script, so changing a threshold or an input marks that step and everything downstream as stale. Steps 6 and 7 take about 30 minutes each on a laptop; the rest take minutes.

**Behind a corporate proxy or antivirus that re-signs HTTPS?** The download scripts use `truststore` to trust the Windows certificate store. For conda itself, set `CONDA_SSL_VERIFY=truststore`; for git, `git config http.sslBackend schannel`.

## Data sources

| Data | Provider | Used for |
|---|---|---|
| Lidar DTM and DSM, 0.5 m (OMAFRA Lidar 2016–18, Lake Erie) | [Ontario Ministry of Natural Resources](https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDTM_LidarDerived_TileIndex.zip) | Terrain, object heights |
| SWOOP 2025 orthoimagery, 16 cm, RGB + near-infrared | Geospatial Ontario, Open Government Licence – Ontario | Lawn vs pavement, accuracy check |
| Open Database of Buildings v3 | [Statistics Canada](https://www150.statcan.gc.ca/pub/34-26-0001/2018001/zip/ODB_v3_ON_3.zip) | Building footprints |
| Short-duration rainfall IDF, v3.40, Windsor A | [Environment and Climate Change Canada](https://collaboration.cmc.ec.gc.ca/cmc/climate/Engineer_Climate/IDF/) | Storm depths |
| Storm Drainage Master Plan, 2019 | [Town of Tecumseh](https://tecumseh.ca/town-government/plans-studies-projects-and-reports/storm-drainage-master-plan) | Study area and validation benchmark |
| Streets, railways, water, boundaries | © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL | Alignment, street names |

No third-party data is stored in this repository; the scripts download it from the providers, under each provider's terms. The master plan is the Town of Tecumseh's. Its pages are rendered locally for the analysis but not committed.

## Repository layout

```
PLAN.md            the original project plan and step checkpoints
environment.yml    conda environment
scripts/           one script per step, plus run_pipeline.py
outputs/           report, decision log, validation, tables, maps, accuracy check
data/              created by the scripts (not in git): raw/ downloads, processed/ results
```

## Using it for another area

The calculation steps (3c, 4b, 5, 6, 7, 9) carry over unchanged. A new area needs:

- a drainage-area boundary, which replaces `02c_study_area.py`;
- lidar and 4-band imagery from its own provider;
- the nearest IDF station;
- the outlet water level used in `06_depressions.py` (`LAKE_LEVEL_M`).

Validation (Step 8) needs a flood study to compare against and is optional. See the last sections of [`outputs/REPORT.md`](outputs/REPORT.md) and [`outputs/decisions.md`](outputs/decisions.md) for the limits found here.
