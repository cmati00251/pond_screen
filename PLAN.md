# PLAN.md: Tecumseh pluvial risk MVP

## Goal

Build a screening-level pluvial (heavy-rain) flood risk map for ONE drainage
catchment in the Town of Tecumseh, Ontario, using only open data. Show where
rainwater pools when the storm sewers are full, how much sealed surface drains
to each spot, and which buildings sit beside it. Check the result against the
Town's 2019 Storm Drainage Master Plan.

Final outputs: map layers for QGIS, PNG maps, a list of the 10 worst ponding
spots, and a short validation note.

## Ground rules for Claude Code

- Work one step at a time. Each step ends at a CHECKPOINT: summarize what you
  did, list the files you wrote, show any figures, then STOP and wait for me.
- Everything under `data/raw/` is read-only once downloaded. Never edit it.
- One numbered, re-runnable script per step in `scripts/`
  (`01_download_small.py`, `02_benchmark.py`, ...).
- Log every threshold, assumption and decision in `outputs/decisions.md`.
- Ask before any single download over 5 GB. Report sizes before downloading.
- After extracting the tiles we need from a large package, ask before deleting
  the package.
- Work in the lidar tiles' coordinate system (expected NAD83(CSRS) / UTM zone
  17N, EPSG:2958). Reproject everything else to it. Raster grid: 0.5 m,
  aligned to the terrain (DTM) tiles.
- Do not use Google Maps or Google Street View imagery: their terms forbid
  image analysis.

## Setup

Create a conda environment from conda-forge named `pluvial` with: python 3.11,
gdal, rasterio, geopandas, shapely, pyproj, numpy, scipy, matplotlib, pymupdf,
requests. Install `whitebox` (WhiteboxTools) with pip inside it.

Folder layout:

```
data/raw/benchmark/    master plan PDFs
data/raw/buildings/    building footprints
data/raw/rainfall/     IDF file
data/raw/dtm/          lidar terrain tiles
data/raw/dsm/          lidar surface tiles
data/raw/imagery/      aerial imagery tiles
data/processed/        clipped, aligned layers
scripts/               one script per step
outputs/               maps, tables, notes
```

## Study area

Tecumseh's northern urban area drains to Lake St. Clair. The 2019 master plan
splits it into 11 drainage service areas:

- Pump station catchments: Lesperance, West St. Louis, East St. Louis,
  ETLD/Manning, Scully, St. Mark's, PJ Cecile, Brighton.
- Gravity outfall catchments: Pilots Cove, Southwind/Starwood, Mei-Lin.

The MVP covers ONE of these, chosen by me at the Step 2 checkpoint. Until
then, use the Town of Tecumseh boundary from OpenStreetMap (Nominatim) as
the working extent. Clip everything to the study area plus a 200 m buffer.

## Data sources (exact)

1. **Master plan PDFs** -> `data/raw/benchmark/`
   - Executive summary:
     https://www.tecumseh.ca/media/vbzen1lj/storm-drainage-master-plan-executive-summary.pdf
   - Volume 1, EA report:
     https://www.tecumseh.ca/media/uh3cbhnj/storm-drainage-master-plan-ea_report.pdf
   - Volume 2, Technical Modelling Report:
     https://www.tecumseh.ca/media/qn0n4z2c/storm-drainage-master-plan-technical-modelling-report-final.pdf
   - Technical Modelling Report appendices:
     https://www.tecumseh.ca/media/zn1a5r4z/tecumseh-stormwater-drainage-master-plan-technical-modelling-report-appendices_optimized.pdf
   - Source page:
     https://tecumseh.ca/town-government/plans-studies-projects-and-reports/storm-drainage-master-plan

2. **Building footprints**: Statistics Canada Open Database of Buildings v3,
   Ontario, zipped GeoPackages -> `data/raw/buildings/`
   - https://www150.statcan.gc.ca/pub/34-26-0001/2018001/zip/ODB_v3_ON_1.zip
   - https://www150.statcan.gc.ca/pub/34-26-0001/2018001/zip/ODB_v3_ON_2.zip
   - https://www150.statcan.gc.ca/pub/34-26-0001/2018001/zip/ODB_v3_ON_3.zip
   - Keep only features whose `csdname` is Tecumseh (check the exact
     spelling). Save as `data/processed/buildings_tecumseh.gpkg`.
   - If Tecumseh is missing, fall back to OpenStreetMap buildings for the
     working extent (Overpass API), and log the switch.

3. **Rainfall IDF** (intensity-duration-frequency) -> `data/raw/rainfall/`
   - Folder: https://collaboration.cmc.ec.gc.ca/cmc/climate/Engineer_Climate/IDF/
   - Take the latest version subfolder, then the Ontario files, then the file
     for station WINDSOR A.

4. **Lidar terrain (DTM)**, Ontario DTM (Lidar-Derived) -> `data/raw/dtm/`
   - Tile index:
     https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDTM_LidarDerived_TileIndex.zip
   - Tecumseh should fall in the "OMAFRA Lidar DTM 2016-2018, Lake Erie"
     packages A to X. Example package URL:
     https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/LIDAR2016to18_DTM-LkErie-A.zip
   - Use the index to find which package(s) hold the tiles over the study
     area. Confirm the package name field before building URLs, and check
     each URL exists and its size before downloading.

5. **Lidar surface (DSM)**, Ontario DSM (Lidar-Derived) -> `data/raw/dsm/`
   - Tile index:
     https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDSM_LidarDerived_TileIndex.zip
   - Expected packages: "OMAFRA Lidar DSM, Lake Erie" 01 to 35. Example:
     https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/Lake-Erie-DSM-01.zip
   - Same approach as the DTM. Do NOT use the "SWOOP 2020 DSM" packages:
     those come from imagery, not lidar.

6. **Aerial imagery**, SWOOP 2020 -> `data/raw/imagery/`
   - 1 km tile index:
     https://geohub.lio.gov.on.ca/datasets/lio::south-western-ontario-orthophotography-project-swoop-2020-1km-index/about
   - Reported: 16 cm pixels, leaf-off (captured March 7 to May 20, 2020),
     JPEG-compressed GeoTIFF. Bands not confirmed; check for near-infrared.
   - Try to find the index's feature service and a per-tile download link.
     If there is none, STOP and tell me: I will download the tiles by hand.
     Start with at most 4 tiles over the study area.

Not for this MVP: soils, street-level photos, Google data.

## Steps

### Step 1: Download the small sources
Download sources 1, 2 and 3. Filter the buildings to Tecumseh.
CHECKPOINT: an inventory table of every file (path, size, format, CRS where
relevant, feature count for vectors).

### Step 2: Read the benchmark
From the master plan PDFs, find (a) the map of the 11 service areas and
(b) every figure or table showing existing-condition surface flooding
problem areas. Save those pages as PNGs in `outputs/benchmark/` and write
`outputs/benchmark/summary.md`: which service areas flood worst, with page
references.
CHECKPOINT: I pick the MVP service area.
Then propose its boundary as `data/processed/study_area.gpkg`, built from
the streets and features named in the figure using OpenStreetMap geometry.
CHECKPOINT: I check the boundary in QGIS and correct it if needed.

### Step 3: Lidar terrain and surface
Download sources 4 and 5 for the study area. Mosaic and clip DTM and DSM to
the study area plus 200 m. Make a hillshade PNG.
CHECKPOINT: tile list, elevation range, hillshade.

### Step 4: Imagery
Get source 6 for the study area. Clip and resample to the 0.5 m grid.
Report the bands. Make a true-colour PNG and, if near-infrared exists, an
NDVI PNG.
CHECKPOINT: band report and both PNGs.

### Step 5: Classify surfaces (rules, no model training)
- nDSM = DSM - DTM (object height).
- Roof: inside a building footprint.
- Tree: nDSM > 2 m and not a roof. Use height, not greenness: the imagery is
  leaf-off.
- Grass or soil (pervious): NDVI above a threshold picked from the
  histogram. If lawns do not separate from pavement in leaf-off imagery,
  STOP and show me examples before choosing a fallback.
- Water: from OpenStreetMap water polygons or flat hydro-flattened DTM areas.
- Sealed ground: everything else.
Outputs: `data/processed/surfaces.tif` and percent sealed per 50 m cell.
Accuracy check: sample 200 random points, render a 20 m image chip around
each with its label, review the chips yourself and report estimated
accuracy by class. Put 30 chips in `outputs/qa/` for me to check.
CHECKPOINT: class areas, accuracy table, the 30 chips.

### Step 6: Find where water pools
- Raise building footprints in the DTM by 3 m so water flows around them.
- Find depressions (WhiteboxTools: FillDepressions, DepthInSink). Keep
  depressions at least 5 cm deep and 20 m2 in area; log the thresholds.
- For each depression: max depth, volume, and its contributing catchment.
- Flow accumulation and main flow paths.
CHECKPOINT: map of depressions coloured by depth, with flow paths.

### Step 7: Rain on it
- Storm depths: 2-, 10- and 100-year from the Windsor A IDF file (state the
  duration used), plus a 2017-like event of 100 mm.
- Runoff share by surface (starting values; log any change): roof 0.95,
  sealed ground 0.90, grass or soil 0.25 (clay soils), tree 0.15, water 1.0.
- Assume storm sewers are full: no pipe drainage.
- Inflow to each depression = sum of rain x runoff share x cell area over
  its catchment. Flag depressions where inflow exceeds volume. First pass
  without spill-over between depressions; add spill-over only if time allows.
- Buildings at risk: footprints within 5 m of a flagged depression.
CHECKPOINT: flagged depressions per storm, buildings at risk per storm.

### Step 8: Validate against the master plan
Overlay flagged depressions on the master plan's problem areas (georeference
the figure from Step 2). Report the share of problem areas that contain or
touch a flagged depression for the 100-year and 2017-like storms.
Pass mark: at least 7 in 10. Write `outputs/validation.md`, including the
misses and likely reasons.
CHECKPOINT: validation note.

### Step 9: Package the results
- `outputs/layers.gpkg`: study area, surfaces (polygonized or summarized),
  depressions, flow paths, flagged depressions per storm, buildings at risk.
- `outputs/maps/`: PNG maps of surfaces, depressions, and risk per storm.
- `outputs/hotspots.csv`: the 10 worst depressions with id, latitude,
  longitude, nearest street, max depth, volume, sealed area draining to it
  (m2), percent sealed of its catchment, buildings at risk, and the smallest
  storm that overflows it.
- `outputs/hotspots.geojson`: the same points in WGS84 for a web map.
CHECKPOINT: done. List every output file.
