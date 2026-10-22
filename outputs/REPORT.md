# Lesperance Pluvial Risk: methods and results

Screening-level pluvial (heavy-rain) flood risk for the Lesperance pump station service area,
Town of Tecumseh, Ontario, built only from open data and checked against the Town's 2019
Storm Drainage Master Plan.

*Status: complete through Step 9. The detailed log of every threshold and decision is
[`decisions.md`](decisions.md); this report is the presentation summary.*

---

## 1. Question and approach

**Question.** Where does rain pond when the storm sewers are full, how much sealed surface
drains to each spot, and which buildings sit beside it?

**Approach.** Terrain-only screening in nine steps:

1. Collect open data (master plan, buildings, rainfall statistics).
2. Read the master plan; choose one service area; draw its boundary.
3. Build 0.5 m ground (DTM) and surface (DSM) models from provincial lidar.
4. Prepare 16 cm four-band aerial imagery (with near-infrared).
5. Classify every 0.5 m cell as roof, tree, grass/soil, water or sealed ground.
6. Find every low spot (depression) in the terrain and the ground draining to it.
7. Pour 2-, 10-, 100-year and a 100 mm storm on it; find which low spots overflow and which
   buildings have water beside them.
8. Compare with the master plan's modelled flooding.
9. Package layers, maps and the 10 worst hotspots.

**Key assumption.** Storm sewers are full: no rain leaves through pipes. This is the worst
case for the sewer system and makes the results a screening of *where* water would collect,
not a prediction of everyday flooding.

## 2. Data (all open)

| Data | Source | Used for |
|---|---|---|
| Storm Drainage Master Plan, 2019 (4 PDFs) | Town of Tecumseh (Dillon Consulting) | Service areas, benchmark flooding |
| Building footprints | Statistics Canada, Open Database of Buildings v3 | Roofs; obstacles to flow; buildings at risk |
| Rainfall IDF, Windsor A (1946–2016) | Environment and Climate Change Canada, IDF v3.40 | Storm depths |
| Lidar DTM and DSM, 0.5 m | Ontario MNR, OMAFRA Lidar 2016–18 (Lake Erie) | Terrain, object heights |
| Orthoimagery, 16 cm, RGB + near-infrared, leaf-off | Geospatial Ontario, SWOOP 2025 | Lawn vs pavement (NDVI), QA |
| Streets, town boundary, railways, water | OpenStreetMap contributors (ODbL) | Boundary, georeferencing, labels |

Coordinate system throughout: NAD83(CSRS) / UTM zone 17N (EPSG:2958), 0.5 m grid aligned to the
lidar tiles.

## 3. Study area: Lesperance pump station service area

- Chosen because it floods worst in the master plan (regional problem area W-1), its flooding
  comes mainly from road low points with no overland outlet (what a terrain method can see),
  and it is fully urban.
- Boundary traced from the plan's service-area map (TMR Fig. 1.2) after aligning the map to
  OpenStreetMap (5 control points, 10 m average error), west edge snapped to the Windsor town line.
- **271.3 ha** against **273.5 ha** reported by the plan (−0.8 %); 3,988 buildings.

## 4. Terrain and surfaces

- Lidar ground falls only ~8 m over 4 km (≈ 0.2 %) to Lake St. Clair (174.24 m); the CN railway
  with Tecumseh Rd and the County Rd 22 / E.C. Row corridor are raised barriers.
- Surfaces (study area): roof 21.1 %, tree 15.6 %, grass/soil 27.6 %, sealed ground 35.8 %
  → **56.9 % impervious**.
- Accuracy from 200 random points checked against the imagery (Claude's review, user-confirmed):
  **89.2 % overall**, 92.3 % for impervious vs pervious. Remaining errors: trees removed since
  the 2016–18 lidar, utility poles, dormant grass in early spring.

## 5. Where water pools (Step 6)

- Buildings raised 3 m so water flows around them; lake treated as the outlet.
- **1,655 depressions** in the study area (≥ 5 cm deep, ≥ 20 m²), holding ~110,000 m³ when full.
- The largest (21.8 ha, up to 1.26 m) is the low street network around Little River Blvd,
  St. Pierre and Dillon Dr, enclosed by higher ground along Riverside Dr: the core of the
  plan's problem area W-1.
- Flagged as likely artefacts (kept, excluded from risk): 20 rail ditches lying mostly inside the
  railway right-of-way (culverts not in lidar) and 4 ponds/excavations deeper than 2 m.

## 6. Storms and buildings at risk (Step 7)

Storm depths, 4 hours (matching the plan's benchmark storm), from the Windsor A IDF table:
2-year **38.5 mm**, 10-year **57.5 mm**, 100-year **81.3 mm** (plan's implied value: 82 mm),
plus a 2017-like **100 mm** event.

Runoff shares: roof 0.95, sealed 0.90, grass 0.25 (clay), tree 0.15, water 1.0. Overflow is
passed on to the next depression downstream (spill-over).

| Storm | Water ≥ 0.15 m | Buildings with water ≥ 0.15 m within 5 m | ≥ 0.30 m (high) |
|---|---|---|---|
| 2-year | 14.4 ha | 956 | 196 |
| 10-year | 21.0 ha | 1,081 | 305 |
| 100-year | 24.2 ha | 1,144 | 351 |
| 2017-like | 24.7 ha | 1,152 | 364 |

Of 3,988 buildings in the study area. The plan's literal rule ("within 5 m of any overflowing
depression") would flag 48 % of buildings even in the 2-year storm, because almost every small
dip fills; risk is therefore judged by water depth, using the master plan's own bands.
Changing the lawn runoff share from 0.25 to 0.75 changes the 100-year counts by about 1 %
(1,144 → 1,155; high risk 351 → 359), so the result does not hinge on the lawn assumption.

## 7. Validation against the master plan (Step 8)

**Benchmark.** The plan's Figures 8.2 and 8.3, which show existing-condition ponding in the
1:100-year 4-hour storm, cover 99 % of the study area.
- The figures have no coordinates, so they were aligned to OpenStreetMap streets, by hand
  and then by an objective refinement. The alignment error is about 10–20 m.
- The ponding depth bands and the problem-area outlines were then digitised.

**Test.** The plan reports roadway ponding only, so the comparison is on the street network.
- Each of the plan's **deep spots** (over 0.30 m) on Lesperance streets counts as found if our
  model has at least 0.15 m of water within 15 m.
- The plan's pass mark is 7 in 10.

| Measure (100-year storm) | Result | Chance level |
|---|---|---|
| **Plan deep spots we find (recall)** | **94 % (81 of 86): PASS** | 55 % |
| Our deep spots where the plan shows ponding ≥ 0.15 m | 80 % (33 of 41) | 62 % |
| Our deep spots where the plan also shows ponding > 0.30 m | 39 % (16 of 41) | 12 % |
| Plan's problem areas inside Lesperance touched by an overflowing depression | 2 of 2 | – |

The 2017-like storm gives the same results.

**How to read it.**
- **Recall is strong.** Our water covers more than half the street network, so even a random
  spot would be "found" 55 % of the time and the pass mark is lenient. But 94 % is far above
  that chance level.
- **Our deepest spots line up with the plan's deepest.** They match the plan's deep ponding
  three times more often than chance.
- **Where we disagree, our model ponds more.** It shows water where the plan has little. That
  is expected: we assume full sewers, while the plan's model lets pipes drain the street.

**The 5 misses.**
- Two are on Tecumseh Rd, where our terrain has no low point. The plan's ponding there likely
  comes from sewer surcharge.
- Three sit over shallow dips (6–10 cm deep when full).

**One rule changed during validation.** At first, any depression touching a 30 m buffer
around the CN railway was excluded as a culvert-drained ditch.
- That also removed real roadside ponding on Tecumseh Rd, which runs 16–55 m from the tracks.
- The rule was narrowed to depressions lying mostly inside the rail right-of-way.
- Both versions pass: 87 % with the original rule, 94 % with the final one.
- Because the change was prompted by the test, the 94 % is not a fully independent check.

A scoring bug found during this step was fixed. It had placed the benchmark's filler value
across most of the area. Details are in `decisions.md`.

## 8. The 10 worst ponding hotspots (Step 9)

Ranked by buildings with ≥ 0.15 m of water within 5 m in the 100-year storm, then by water depth.
"Sealed area draining" includes every upstream depression that spills into it.

| # | Where (nearest street) | Max depth when full | Volume when full | Sealed area draining | % sealed | Buildings at risk (100-yr) | Smallest storm that overflows it |
|---|---|---|---|---|---|---|---|
| 1 | Little River Blvd (north basin) | 1.26 m | 46,008 m³ | 89.0 ha | 51 % | 267 | 100-year |
| 2 | Riverside Dr E | 0.55 m | 1,971 m³ | 1.3 ha | 41 % | 23 | none of the four* |
| 3 | Dove Lane | 0.50 m | 141 m³ | 1,649 m² | 54 % | 18 | 100-year |
| 4 | Echo Bay St (beside CN railway) | 1.51 m | 9,512 m³ | 24.2 ha | 63 % | 14 | 10-year |
| 5 | Bedell St | 0.49 m | 939 m³ | 29.0 ha | 60 % | 14 | 2-year |
| 6 | Roxbury Cres | 0.37 m | 263 m³ | 3,514 m² | 38 % | 13 | 100-year |
| 7 | Orchard Dr | 0.35 m | 131 m³ | 2,129 m² | 53 % | 12 | 10-year |
| 8 | St. Pierre Ave | 0.29 m | 143 m³ | 2,061 m² | 36 % | 11 | 100-year |
| 9 | County Rd 22 | 0.62 m | 488 m³ | 5,671 m² | 52 % | 9 | 100-year |
| 10 | Southpark Lane | 0.44 m | 74 m³ | 4,028 m² | 59 % | 9 | 2-year |

\* #2 holds 0.48 m of water beside 23 buildings in the 100-year storm without filling completely.
Coordinates (latitude/longitude and UTM) are in `hotspots.csv` and `hotspots.geojson`.

**Reading the list.** #1 is the area the master plan already identifies as the worst (W-1): a
low street network by the lake that only the Lesperance pump station can drain. It reaches
1.26 m depth when full and needs the 100-year storm to fill. #4 and #9 sit against the CN
railway and County Rd 22 embankments, where culverts not in the lidar may relieve them in
reality. #5 and #10 overflow even in a 2-year storm.

## 10. Outputs

| File | What it is |
|---|---|
| `layers.gpkg` | All map layers for QGIS: study area, surfaces per 50 m, depressions, flow paths, overflowing depressions and water per storm, buildings at risk, plan problem areas and deep spots, hotspots |
| `hotspots.csv`, `hotspots.geojson` | The 10 worst ponding spots (WGS84 GeoJSON for a web map) |
| `maps/*.png` | Hillshade, true colour, NDVI, surfaces, % sealed, depressions, each storm, storms panel, validation, hotspots |
| `validation.md`, `validation_spots.csv` | Comparison with the master plan |
| `storm_summary.csv`, `flagged_depressions.csv`, `buildings_storms.csv`, `sensitivity_grass.csv` | Step 7 tables |
| `qa/` | Surface accuracy review (200 points, 30 chips, accuracy table) |
| `benchmark/` | Master plan pages, summary, georeferencing checks |
| `decisions.md` | Every threshold, assumption and decision, with dates |

## 11. Limitations

- **Terrain only, sewers full.** No pipes, pump stations, inlet capacity or lake backwater; real
  flooding from sewer surcharge without a surface low point is invisible to this method.
- **Volume only.** No timing or flow velocity; every storm's runoff is assumed to arrive.
- **Data dates differ.** Lidar 2016–18, imagery 2025, footprints of mixed age: new buildings
  and removed trees cause local errors.
- **Building walls.** Raising footprints 3 m creates small pockets against walls; the
  ≥ 0.15 m count therefore over-states risk; the ≥ 0.30 m set and the hotspot ranking are more
  meaningful.
- **Benchmark digitised from a figure.** About 10–20 m alignment error; the plan's own model
  is a different method (2D hydraulic model with pipes).

## 12. Reproducing

```
conda env create -f environment.yml        # once
conda run -n pluvial python scripts/run_pipeline.py          # status of every step
conda run -n pluvial python scripts/run_pipeline.py --run    # rerun anything out of date
```

One manual input: SWOOP imagery tiles must be ordered from the Geospatial Ontario Imagery
Orders App into `data/raw/imagery/` (list in `outputs/imagery_tiles_to_order.csv`).
