# Decisions, thresholds and assumptions

## Setup
- Conda env `pluvial` built from `environment.yml` (conda-forge, Python 3.11).
  Run scripts with `conda run -n pluvial python scripts/NN_*.py` so GDAL_DATA
  and PROJ data are set.
- HTTPS on this machine is intercepted by a local certificate (likely
  antivirus). Verification stays ON: conda uses `CONDA_SSL_VERIFY=truststore`
  and scripts call `truststore.inject_into_ssl()` to use the Windows store.

## Step 1: small sources
- **IDF location differs from PLAN.** The ECCC IDF folder has no "latest
  version" subfolder; the latest release (v3.40, 2025-12-05) is a single
  698 MB zip `idf_v3-40_2025-12-5.zip` with one zip per province inside.
  Only the Ontario member (`ON.zip`, 149 MB) was fetched, using HTTP range
  requests. Windsor A files were extracted to `data/raw/rainfall/windsor_a/`.
- Windsor A = climate ID 6139525, 42°16'N 82°57'W, record 1946–2016
  (66 years), Gumbel method of moments. The record ends before the
  August 2017 storm, so that event is not in the fitted statistics.
- **Buildings:** the ODB v3 field `csdname` uses the exact spelling
  `Tecumseh` (18,347 features, all in `ODB_v3_ON_3`). `New Tecumseth`
  (20,322) is a different municipality and is excluded. No OSM fallback needed.
- Buildings were reprojected from EPSG:3347 (StatCan Lambert) to EPSG:2958,
  the expected lidar CRS. If the lidar turns out to use a different CRS in
  Step 3, rerun Step 1 with `WORK_CRS` changed.
- Building extent (WGS84): -83.000 to -82.842 E, 42.181 to 42.334 N, which
  covers the whole town. They'll be clipped to the study area in Step 2.

## Step 2: benchmark
- Main source is the Technical Modelling Report (TMR). The EA report's problem-
  area figures 6.1–6.3 are identical to TMR Figs 8.2, 8.3 and 8.5, so they are
  not rendered twice.
- Benchmark storm is the 1:100-year **4-hour** Chicago storm (existing
  conditions). Its problem areas cover public roads only; parks and private
  land were excluded ("not to be analyzed").
- Pages rendered at 150 dpi.

### MVP service area: Lesperance pump station (chosen by Claude at the user's request)
- Reasons:
  - It has the worst existing-condition flooding in the benchmark (regional
    problem area W-1).
  - Its flooding comes mostly from road low points with no overland escape,
    which a terrain-only depression method can detect.
  - It is fully urban, with curb-and-gutter streets.
  - It has many separate deep-ponding clusters to validate against.
- Caveat: its sewers are joined to West St. Louis at St. Pierre St /
  Riverside Dr, and W-1 spans both areas. Validation (Step 8) will use only the
  parts of W-1 and the isolated problem areas that fall inside the Lesperance
  boundary.
- Rejected:
  - East St. Louis: too few problem areas for a 7-in-10 test.
  - E-1: driven by roadside ditches and pump-station backwater.
  - Southwind/Starwood: flooding caused by lake levels.

### Study area boundary (`data/processed/study_area.gpkg`)
- OSM town boundary: Nominatim structured search (city=Tecumseh,
  state=Ontario), accepting only `category=boundary` results.
  - A free-text query first returned a Canada Post outlet in Lakeshore.
    That cache file and the Overpass extract built from it were deleted
    from `data/raw/osm/` and fetched again. This is the only edit made
    under `data/raw/`, and it was to files Claude had just created.
- Overpass extract (roads, railways, water, admin level 8) cached in
  `data/raw/osm/`. Layers converted to EPSG:2958 in
  `data/processed/osm_tecumseh.gpkg`.
- Traced from TMR Fig 1.2 (PDF p15). The map is an embedded raster
  (1956 × 1559 px), not vector.
- Georeferencing: affine fit from 5 road-intersection control points (pixel
  positions read off the figure, map positions from OSM).
  - Scale 4.59 m/px; RMS error 9.9 m, worst 13.8 m (`gcps_fig1-2.csv`).
- Lesperance fill picked out by colour: RGB (205, 120, 185), tolerance 45.
  - Closing of 3 px to bridge street lines; holes filled.
  - Patches under 2,000 px ignored.
- The County Rd 22 symbol splits off the southern lobe (17.4 ha, 37 m gap).
  It is joined back with a bridge covering only the gap (patches within
  60 m). A 7.9 ha patch 855 m away (St. Mark's colour) is excluded.
- West edge snapped to the OSM Town of Tecumseh boundary (within 40 m) and
  clipped to it. Edges smoothed by 15 m. Holes removed. Simplified to 2 m.
- The Lesperance pump station symbol (a black disk, about 190 m on the
  ground) hid the fill at the outlet. The disk is counted as service area
  on the land side of the shoreline (`PS_SYMBOL` in `02c`).
- Result: **271.3 ha** vs **273.50 ha** reported (TMR §1.2): **−0.8 %**.
- The user asked Claude to use its judgement on the boundary (no manual QGIS
  edit). Accepted as final for the MVP.
- The +200 m buffer extends into the City of Windsor. Buildings for analysis
  therefore come from `02d_buildings_study.py`: every ODB footprint
  intersecting the buffer, whatever the municipality.
  - Output: `data/processed/buildings_study.gpkg`, 6,841 buildings (Tecumseh
    5,873, Windsor 966, Lakeshore 2).
  - `buildings_tecumseh.gpkg` is kept as the Step 1 product.

## Step 3: lidar
- Tile indexes (`data/raw/{dtm,dsm}/Ontario*_TileIndex.zip`) use the field
  `Package`. 13 tiles (1 km) intersect study area + 200 m, for both DTM and
  DSM.
  - DTM: all from "Lake Erie A" → `LIDAR2016to18_DTM-LkErie-A.zip` (3.09 GB).
  - DSM: from `Lake-Erie-DSM-01` (9 tiles, 3.29 GB) and `-02` (4 tiles,
    3.29 GB).
  - Project: OMAFRA Lidar 2016-18.
- **No package was downloaded in full.** The server supports HTTP range
  requests, so only the 26 needed `.img` members were read out of the remote
  zips (`03b`): about 112 MB transferred, about 332 MB unzipped, instead of
  9.7 GB. So there are no packages to delete.
- CRS: tiles are tagged EPSG:26917, but the embedded projection is named
  "NAD_1983_CSRS_UTM_Zone_17N". EPSG:2958 is assigned with no resampling.
  - The datum shift between the two is under 2 m. It is ignored, so the grid
    stays exactly on the tile pixels.
- Grid: 0.5 m, aligned to the tile origins (integer metres). The mosaic
  covers the buffer bounds and is masked outside the buffer polygon.
  - Values outside 150–260 m are treated as nodata. Nodata = -9999.
- Vertical datum not confirmed from metadata. It is only used for relative
  depths.
- The lake is hydro-flattened at **174.24 m** in the DTM, which is useful for
  the water class in Step 5.
- Highest DTM in the buffer: 186.1 m on the County Rd 22 / E.C. Row
  embankment. The 199 m values seen in raw tile 343/4687 are outside the
  buffer.

## Progress brief (16 Oct 2026)
- Private artifact for the user's meeting:
  https://claude.ai/artifact/GVsQEbahyGAvouBEo2ZZyP
  - Local copy: `outputs/progress/lesperance_progress.html`.
  - Contents: Steps 1–3 only. It states that there are no flood-risk
    results yet.

## Step 4: imagery (stopped: manual download needed)
- Index: LIO feature service `SWOOP2020_Index_WFL` (ArcGIS Online item
  7d485abcd5fd4949b1d7aff7024b1f50). Its only field is the tile `Name`; there
  is no download link.
- The item metadata says tiles are supplied through the **Geospatial
  Ontario Imagery Orders App** (request-based):
  https://experience.arcgis.com/experience/2358b9d2dd5c4077bdb47049bf0e7fa7/
  - So, per PLAN, the user downloads the tiles by hand.
- Metadata confirms: **4 bands, RGB + near-infrared (RGBN)**, 8-bit, 16 cm,
  leaf-off/low-leaf, captured 7 Mar – 20 May 2020, accuracy 45 cm (95 %),
  GeoTIFF (full or compressed). Open Government Licence – Ontario.
- 13 tiles intersect the study area + 200 m; 11 touch the study area itself.
  - The first 4 by study-area coverage cover 76 % of it (list in
    `outputs/imagery_tiles_to_order.csv`).
- County image services (Huron, Bruce, Haldimand, etc.) were found but not
  used: none covers Essex, and they are not the official source.

### Imagery delivered (20 Oct 2026)
- The user downloaded **15 SWOOP 2025** tiles (not 2020) from the Imagery
  Orders App into `data/raw/imagery/`.
  - Tiles: `1km17{343-345}0{4684-4688}0SWOOP2025.tif`, 156 MB each, 2.2 GB
    in total.
  - SWOOP 2025 is used as delivered. The specs are the same as 2020: 4 bands
    RGBN, 8-bit, 16 cm, leaf-off/low-leaf, 45 cm accuracy (95 %), Open
    Government Licence – Ontario.
  - Captured 13 Mar – 10 May 2025 (plus 24 Nov 2025), so it is more current.
  - Files: uncompressed GeoTIFF, EPSG:2958. Band 4 has no colour
    interpretation and is the NIR band: it is low over water and high over
    vegetation.
- Coverage: 100 % of the study area, 98.8 % of the buffer. The two
  buffer-only tiles (346/4685, 346/4686) were not delivered; those buffer
  cells have no imagery.
  - The 4 extra tiles delivered (343/4684, 345/4684, 345/4687, 345/4688)
    are harmless.
- Date mismatch: imagery is 2025, lidar 2016–18. Anything built after the
  lidar shows in the imagery but not in the DTM/DSM. Watch for this in the
  Step 5 QA chips.

## Step 4b: imagery
- Mosaic via GDAL VRT, warped onto the exact DTM grid (0.5 m) with
  **area-average** resampling of the 16 cm pixels. Masked outside the
  buffer.
  - Output: `data/processed/imagery.tif` (uint8, R, G, B, NIR; nodata 0).
- NDVI = (NIR − Red)/(NIR + Red) from 8-bit values. It is a relative index:
  no radiometric calibration is available or needed for a threshold.
- NDVI in the study area: median 0.004; 5/25/75/95th percentiles −0.09,
  −0.04, 0.13, 0.27.
- The **histogram is bimodal**: one peak near −0.03 (pavement and roofs),
  one near +0.12 (lawns), valley about 0.04–0.05. Lawns separate from
  pavement in leaf-off imagery, so the Step 5 stop condition is not
  triggered.

## Step 5: surfaces
- Rules apply in priority order: water > roof > tree > grass > sealed.
  Codes 1 roof, 2 tree, 3 grass/soil, 4 water, 5 sealed; 0 nodata
  (`data/processed/surfaces.tif`).
- **Water:** lake mask from Step 6, plus OSM water polygons. Only 0.01 ha
  falls in the study area.
- **Roof:** inside an ODB footprint (6,841 in the buffer), plus two additions:
  - **Unmapped flat structures:** nDSM > 2 m, 3×3 DSM roughness < 0.15 m,
    patch ≥ 30 m². This added 0.16 ha in the study area.
  - **Eaves (added after the QA review):** cells within **0.75 m** outside a
    footprint and **elevated** (nDSM > 2 m). Footprints are traced at the
    walls, so roof overhangs were being called "tree". This added 6.8 ha in
    the study area, moved from tree to roof.
  - Ground-level cells in that ring keep their own class. An unconditional
    0.75 m footprint buffer was rejected because it would have turned a
    strip of lawn or driveway around every house into roof.
- **Tree:** nDSM > **2 m** and not roof (PLAN: height, not greenness).
- **Grass/soil:** NDVI > **0.053**. This is the valley of the smoothed NDVI
  histogram of ground cells (not roof, tree or water) in the study area,
  between the pavement peak (−0.032) and the lawn peak (0.117).
- **Sealed:** everything else. Cells with no imagery (buffer only, 4.7 ha,
  east edge) default to sealed.
- **Areas (study area, 271 ha):**

  | Class | Area | Share |
  |---|---|---|
  | Roof | 57.2 ha | 21.1 % |
  | Tree | 42.2 ha | 15.6 % |
  | Grass/soil | 74.8 ha | 27.6 % |
  | Water | 0.0 ha | 0 % |
  | Sealed | 97.2 ha | 35.8 % |

  **Impervious (roof + sealed) = 56.9 %.**
- **% sealed per 50 m cell** = (roof + sealed) / valid cells. A cell needs
  at least 25 % valid coverage.
- **Accuracy check:**
  - 200 random points in the study area (seed 20261020). Each was rendered as
    a 20 m chip from the 16 cm SWOOP 2025 imagery, with ODB footprints drawn
    on.
  - Claude reviewed all 200 by eye.
    - The verdicts are in `outputs/qa/review_claude.csv`; points not listed
      were judged correct.
    - The reviewed labels are frozen in `sample_points_reviewed_v1.csv`.
  - 8 points were too ambiguous to judge and were excluded. In most of them,
    building lean in the ortho shows a roof over a ground-level point next
    to a footprint.
- **Accuracy results:**

  | Class | Before eave rule | After eave rule (final) |
  |---|---|---|
  | Overall | 88.0 % | **89.6 %** |
  | Tree (user's) | 67.5 % | **75.0 %** |
  | Roof (user's / producer's) | 100 / 80.6 % | 96.6 / 90.3 % |
  | Grass (user's / producer's) | 100 / 84.7 % | same |
  | Sealed (user's / producer's) | 87.0 / 90.5 % | same |
  | Impervious-vs-pervious agreement | 90.1 % | 92.2 % |

  - The rule was tuned on the same points, so the final figures are mildly
    optimistic.
- **Remaining error sources (known limits):**
  - Trees removed since the 2016–18 lidar.
  - Utility poles and wires.
  - Vehicles and carports.
  - Dormant or dry grass and bare soil with NDVI near 0, which end up
    labelled sealed (7 of 59 true-grass points).
  - Unmapped sheds and new buildings.
- **Fixes tested and rejected:**
  - Morphological opening of the tall mask removed poles but also about 10
    genuine trees.
  - A tall-patch size threshold: poles are connected to wires, so their
    patches are 36–52 m².
  - Colour or saturation rules for dormant grass: they overlap gravel and
    shadowed pavement, and the best rule fixed 3 points and broke 1.
- **Effect on Step 7:** dormant grass mapped as sealed overstates runoff,
  while trees over pavement understate it. Step 7 will include the
  grass-coefficient sensitivity test.
- **User review (20 Oct 2026):** the user agreed with Claude's verdicts on
  all 30 chips and resolved the two ambiguous ones.
  - #2 is a **roof**. It is mapped sealed, so it now counts as an error: a
    roof missing from both the footprints and the lidar.
  - #16 is **sealed** (road or alleyway), so the map label is correct.
  - The user's verdicts are stored in `outputs/qa/review_user.csv` and
    override Claude's in `05b`.
  - In the user's CSV, the `your_verdict` cell for #2 reads "sealed" with
    the note "roof". It was interpreted as roof, per the user's message.
  - **Final accuracy:** 194 points evaluated, 6 ambiguous excluded.
    - Overall **89.2 %**.
    - Roof 96.6 / 87.5 % (user's / producer's).
    - Tree 75.0 / 100 %.
    - Grass 100 / 84.7 %.
    - Sealed 86.1 / 90.7 %.
    - Impervious-vs-pervious agreement 92.3 %.
- 30 chips for the user are in `outputs/qa/chip_###_<class>.png`, listed in
  `chips_for_your_review.csv` with Claude's verdict and empty columns for
  the user's. The selection is 6 per class where available (there is no
  water sample), filled at random to 30.

## Step 7: storms
- The user asked Claude (20 Oct 2026) to choose the best approach and to
  document everything for presentation.
- **Storm duration: 4 hours**, because the benchmark is the master plan's
  1:100-year 4-hour Chicago storm.
  - The Windsor A IDF table (v3.40) gives 2 h and 6 h depths. The 4 h depth
    is interpolated **log-log** between them: d(4) = d(2) · 2^b, with
    b = ln(d6/d2) / ln 3.

  | Storm | IDF 2 h | IDF 6 h | 4 h depth used |
  |---|---|---|---|
  | 2-year | 33.7 mm | 41.6 mm | **38.5 mm** |
  | 10-year | 50.7 mm | 61.9 mm | **57.5 mm** |
  | 100-year | 71.9 mm | 87.3 mm | **81.3 mm** |
  | 2017-like | | | **100 mm** (PLAN) |

  - **Check:** the plan's "1:100-year + 40 %" storm is 115 mm (TMR §8.3),
    which implies a base of 115 / 1.4 = **82 mm**. Our 81.3 mm matches.
  - Only depth matters, because the volume balance has no timing.
- **Runoff shares (PLAN, unchanged):** roof 0.95, sealed 0.90, grass/soil
  0.25, tree 0.15, water 1.0.
- **Storm sewers full:** no pipe drainage (PLAN). This is deliberately worst
  case for the minor system. Even the 2-year storm, which the sewers are
  designed to carry, is treated as if the sewers were full.
- **Inflow:** for each depression, inflow = P × Σ(runoff share × 0.25 m²)
  over its catchment (Step 6). The catchment includes the depression itself.
- **Pass 1 (PLAN first pass):** no spill-over between depressions.
- **Pass 2 (added; used for all reported results):** spill-over.
  - Each depression's overflow is routed to the next depression downstream.
    The receiver is found by following the D8 pointer (filled DEM) from the
    depression's lowest cell out across its spill point.
  - Depressions are processed upstream to downstream (topological order).
    2,882 of 3,031 depressions spill into another; the rest drain to the
    lake or the buffer edge.
  - **Why:** on this flat terrain much of the runoff reaches the large street
    depressions through chains of small ones. Pass 1 under-fills downstream
    depressions.
  - Pass 1 vs pass 2, depressions overflowing in the 100-year storm: 1,496
    vs 1,515.
- **Critical rain** (pass 1) = volume / Σ(runoff share × area). This is the
  rain needed to fill a depression from its own catchment.
- **Smallest storm that overflows it:** taken from pass 2.
- **Water at the end of each storm:**
  - A depression that overflows is full.
  - A partly filled one is drawn at the water level that holds its inflow,
    found by bisection on its own depth-when-full values.
  - Output: `data/processed/ponding_<storm>.tif`.
- **Artefacts excluded from the risk results:** depressions flagged
  `rail_corridor` (embankment ditches drained by culverts) or `very_deep`
  (ponds or excavations). They are still computed and are reported as
  "artefact_flagged_overflowing".
- **Buildings at risk: definition changed from PLAN, with both reported.**
  - The PLAN rule ("footprint within 5 m of an overflowing depression")
    flags 1,902 of 3,988 study-area buildings (48 %) even in the 2-year
    storm. Most depressions are tiny dips that any rain fills: 1,411 of
    1,631 overflow in the 2-year storm. The rule therefore does not separate
    risk from no risk.
  - **Primary measure:** the maximum water depth at the end of the storm
    within 5 m of the footprint, using the master plan's own depth bands.
    - **At risk:** ≥ 0.15 m.
    - **High risk:** ≥ 0.30 m, the Town's allowable 1:100 ponding depth
      (TMR §1).
  - The PLAN-rule counts stay in `storm_summary.csv` (`bld_plan_rule`).
  - Buildings in the study area = footprints whose representative point lies
    inside it (3,988).
  - Depth comparisons use a 1e-4 m tolerance: lidar heights are stored to
    1 cm, so 0.15 m comes out as 0.1499999 in float32. Depths keep full
    precision until written to file.
- **Final results** (study area, pass 2, artefacts excluded, rail rule v2;
  see Step 8):

  | Storm | Overflowing depressions | Water ≥ 0.15 m | Buildings at risk (≥ 0.15 m) | High risk (≥ 0.30 m) | PLAN rule |
  |---|---|---|---|---|---|
  | 2-year (38.5 mm) | 1,411 / 1,631 | 14.4 ha | 956 | 196 | 1,902 |
  | 10-year (57.5 mm) | 1,493 | 21.0 ha | 1,081 | 305 | 2,119 |
  | 100-year (81.3 mm) | 1,546 | 24.2 ha | 1,144 | 351 | 2,524 |
  | 2017-like (100 mm) | 1,563 | 24.7 ha | 1,152 | 364 | 2,536 |

  - Under the first rail rule (v1) the 100-year figures were 1,114 at risk
    and 338 high risk (`storm_summary_v1_rail30m.csv`).
- **Sensitivity, grass runoff share 0.25 / 0.50 / 0.75**
  (`outputs/sensitivity_grass.csv`, final run):
  - Buildings at risk (100-year): 1,144 / 1,149 / 1,155.
  - High risk (100-year): 351 / 357 / 359.
  - Largest effect, 2-year high risk: 196 / 232 / 255.
  - So the conclusions are robust to the lawn runoff assumption, and the
    Step 5 dormant-grass errors matter little.
- **Note for interpretation:** the counts say where water would stand next to
  buildings if no water entered the sewers. They are not flood damage
  estimates. Many at-risk buildings sit beside shallow pockets against walls
  that the 3 m building raise creates. The high-risk (≥ 0.30 m) set and the
  hotspot ranking are the more meaningful outputs.

## Step 8: validation
### Benchmark georeferencing (`08a_georef_benchmark.py`)
- Benchmark sources:
  - **TMR Figure 8.2** (PDF p84): problem areas W-1, W-2 and isolated areas
    north of Tecumseh Rd.
  - **TMR Figure 8.3** (PDF p85): W-3 and an isolated area south of Tecumseh
    Rd.
  - Both show existing-condition 1:100-year 4-hour ponding as hexagons in
    three depth bands: < 0.15, 0.15–0.30, > 0.30 m.
  - Together they cover **99 %** of the study area.
- The figures have no grid and no coordinates.
- **Automatic matching failed** and was abandoned:
  - SIFT + RANSAC against the SWOOP 2025 photo found 7 inliers.
  - Scale-searched edge and grey-level correlation gave weak, ambiguous
    peaks and put Manning Rd 300–900 m off.
  - The cause: the figures' background photo is faded, older and about 45 %
    covered by the overlay.
- **Method used:**
  1. A **hand alignment**: OSM streets were drawn over the figure and fitted
     by eye.
     - Fig 8.2 used Dillon Dr at Lesperance Rd, Tecumseh Rd and Manning Rd.
     - Fig 8.3 used Manning Rd on the right-hand boundary and Tecumseh Rd at
       the top.
     - The pump-station symbols are drawn offset from the stations, so they
       were not used.
     - Both maps are north-up (Manning Rd's 3.6° tilt in the figure matches
       its true 3.9°).
  2. **Refinement** by grid search over scale, rotation and offset,
     maximising the share of OSM street centreline points that fall on the
     plan's ponding hexagons. The plan's 2D model ponds water on roadways.
- **Results:**

  | Figure | Score (hand → refined) | Final transform | Refinement shift |
  |---|---|---|---|
  | Fig 8.2 | 0.19 → **0.50** | 1.702 m/px, 0° | 28 m |
  | Fig 8.3 | 0.10 → **0.19** | 1.772 m/px, 0.2° | 46 m |

  - Fig 8.3 scores lower because more of its ponding lies in fields and
    parks rather than on streets.
  - Visual checks: `outputs/benchmark/fig8x_georef_check.png`.
- **Estimated alignment error:** about 10–20 m.
- **Digitising:**
  - **Ponding bands:** nearest of the three legend colours. The legend swatch
    fills were read from the PDF's vector graphics: (0, .89, .96),
    (0, .65, .84), (.01, .15, .83). RGB tolerance 60.
  - **Problem areas:** red outlines (RGB 232/54/53, tolerance 90).
    - Labels and hexagons drawn over the lines break them into pieces.
      Closed rings were filled directly.
    - Open pieces were joined by bridging every separate gap of ≤ 80 px
      between pieces, then filled.
    - W-1 needed bridges at three gaps.
- **Problem areas overlapping the study area:**
  - **W-1:** 131 ha in total, 67.5 ha (52 %) inside Lesperance; the rest is
    in West St. Louis, consistent with TMR §8.1.2.
  - **One isolated ellipse** north of County Rd 22 (Fig 8.3): 2.7 ha inside.
  - W-2, W-3 and the other isolated areas lie outside Lesperance.

### Validation design (`08_validation.py`)
- **A. Plan test (as specified):** share of problem areas overlapping the
  study area that contain or touch an overflowing depression.
  - Only **2** problem areas qualify, so a 7-in-10 test on them is
    meaningless. It is reported for completeness.
- **B. Spot test (primary).** The plan reports roadway ponding only (parks
  and private land were "not analysed"), so:
  - **Domain:** OSM streets ± 10 m, inside the study area and the figures'
    coverage (82.7 ha).
  - **Units:** the plan's **deep spots**, i.e. clusters of > 0.30 m cells
    (joined within 2 m, at least 25 m²): **23 spots**.
  - **Recall:** share of spots with our end-of-storm water ≥ 0.15 m within
    **15 m**. **Pass mark 70 %** (PLAN: 7 in 10).
    - 15 m covers the alignment error and the plan's ~17 m hexagons.
  - **Precision:** share of our deep (≥ 0.30 m) street spots with any plan
    ponding within 15 m.
  - **Area agreement** both ways is also reported.
  - Each miss gets a likely reason from our terrain at that spot:
    - no depression (the plan's ponding comes from sewer surcharge or
      backwater);
    - a shallow depression;
    - a depression the storm does not fill.

### First run (v1) and the rail-ditch correction
- **Bug in the first two validation runs (found and fixed):**
  - When each figure was reprojected onto our grid, rasterio filled the cells
    outside that figure with the source nodata value (**255**), not 0.
  - Taking the maximum over the two figures then set every cell covered by
    only one figure to 255.
  - So only the strip where Figs 8.2 and 8.3 overlap (along Tecumseh Rd)
    held real benchmark classes.
- **Effect of the bug:**
  - Recall was measured on the 23 deep spots inside that strip only.
  - Precision was inflated, because 255 counted as "plan ponding" everywhere.
  - The early figures (v1 recall 61 %, then 87 %, precision 94–95 %) are
    therefore **not valid whole-area results** and are not reported. Their
    files were deleted.
  - The observations about the individual Tecumseh Rd spots (below) came from
    the overlap strip, where the data was correct, so they still hold.
- **Fix:** 255 is now set to 0 after reprojection.
  - Both rail rules (v1 and v2) are scored in the same corrected run. This
    works because the water rasters do not depend on the flag, which only
    decides which depressions are excluded from scoring.
  - The results are in `outputs/validation.md`.
- **Observation that prompted the rule change** (in the overlap strip):
  7 of 9 misses were on or near Tecumseh Rd.
  - 6 of them sit on depressions our terrain does have, holding 0.15–1.5 m of
    water in the 100-year storm (e.g. #61 at 0.35 m, #11 at 0.97 m, #2 at
    1.51 m).
  - The v1 **rail-ditch flag** had excluded them. It flagged any depression
    touching a 30 m buffer around the CN tracks, and Tecumseh Rd runs only
    16–55 m from the tracks.
  - The plan's model, which includes pipes and culverts, shows deep ponding
    at the same places. So these are not only culvert-drained rail ditches.
- **Correction (v2):** a depression is a rail ditch only if **≥ 50 % of its
  area lies within 15 m of the track centreline**, i.e. inside the rail
  right-of-way.
  - Steps 6–9 were rerun with this rule.
- **Caveat stated in the report:** the correction was prompted by the
  validation, so the v2 recall is not an independent test. It measures the
  remaining disagreement after a rule error was fixed. Both rules' results
  are presented side by side.
  - The v1 storm summary (building counts under the 30 m rule) is kept as
    `outputs/storm_summary_v1_rail30m.csv`.
- **Pipeline:** `run_pipeline.py` now also treats each step's own script as
  an input, so editing a script marks that step and everything downstream as
  stale.
  - New option `--accept ID`: records the current inputs as the step's
    baseline without rerunning it. It is only for an input rewritten with
    identical content. Used twice (20 Oct 2026):
    - **05:** Step 6 had rewritten `lake_mask.tif` with identical content.
      Step 6 now skips rewriting an unchanged mask.
    - **06:** after that change to how the mask is written, which cannot
      alter any output.

### Final validation result (corrected run)
- **Recall 94 % (81/86)**, 100-year and 2017-like: **PASS**.
  - Chance level 55 % (the share of street length within 15 m of our water).
  - P(≥ 81/86 by chance) = 5.6e-16.
- **Rail rule comparison:** v1 gave 87 % (75/86), also a pass.
- **Precision of our deep street spots (≥ 0.30 m), with chance levels:**
  - Against any plan ponding: 80 % (chance 77 %).
  - Against plan ponding ≥ 0.15 m: 80 % (chance 62 %).
  - Against plan ponding > 0.30 m: 39 % (chance 12 %).
  - Precision against "any plan ponding" carries little information, because
    the plan shows some ponding on most streets.
- **Area agreement:** 76 % of the plan's ≥ 0.15 m street ponding has ours
  nearby; 84 % the other way round.
- **Plan test:** both problem areas overlapping Lesperance (W-1 part,
  isolated area by County Rd 22) are hit.
- **5 misses:**
  - 2 on Tecumseh Rd with no terrain low point (likely sewer surcharge).
  - 3 over shallow dips (0.06–0.10 m when full).

## Step 9: packaging
- `outputs/layers.gpkg` contains:
  - study_area;
  - surfaces_50m: % of each class per 50 m cell. The raster
    `surfaces.tif` stays the full-resolution product;
  - depressions (all storm attributes) and flow_paths;
  - flagged_<storm>: overflowing primary depressions, pass 2;
  - water_<storm>: end-of-storm water ≥ 0.15 m;
  - buildings_at_risk;
  - plan_problem_areas and plan_deep_spots;
  - hotspots.
- **Hotspots:** 10 primary depressions in the study area, ranked by
  - buildings with ≥ 0.15 m of water within 5 m (100-year, polygons of
    water ≥ 0.15 m buffered 5 m), then
  - water depth in the 100-year storm.
  - PLAN asked for "the 10 worst ponding spots" without a ranking. Ranking
    by buildings affected was chosen because the project's purpose is risk
    to buildings.
- **"Sealed area draining to it":** roof + sealed ground in the
  depression's own catchment plus all upstream catchments that spill into
  it. % sealed is over the same total area.
- **Smallest storm that overflows it:** from pass 2. "None" means the
  depression does not fill completely even at 100 mm, though it may still
  hold deep water (e.g. #2, 0.48 m).
- **Coordinates:** representative point of the depression, in WGS84
  (`hotspots.geojson`, lat/long in the CSV) and EPSG:2958.
- **Nearest street:** nearest named OSM road.
- **Presentation summary:** `outputs/REPORT.md`; final results page
  published as an artifact (same link as the progress brief).

## Order of work
- With the user's agreement, Step 6 was run before Steps 4b and 5, while the
  imagery order is pending. Step 6 uses only the DTM, buildings and study
  area; no imagery-derived input feeds it, so it does not need rerunning
  when the imagery arrives.
- Steps 4b, 5 and 7 must run in that order once the tiles are in
  `data/raw/imagery/`.
- `scripts/run_pipeline.py` lists each step's inputs and outputs, shows
  done / stale / ready / blocked / todo, and runs the outstanding steps in
  order (`--run`).
  - After each successful run it stores an input fingerprint (size + mtime)
    in `data/processed/.pipeline_stamps.json`.

## Step 6: depressions
- WhiteboxTools 2.4.0, installed by the `whitebox` package on first use.
  - It cannot read GeoTIFFs written with PREDICTOR=3, so every raster it reads
    is written without a predictor.
  - Its Python wrapper can return 0 after a crash, so the script also checks
    that each output file was created.
- Buildings: all 6,841 footprints in the buffer (`buildings_study.gpkg`)
  raised **3 m** (PLAN).
- **Lake as outlet:** the hydro-flattened Lake St. Clair surface (174.24 m
  ±0.01 m, flat patches ≥ 5 ha; 16.0 ha) is set to nodata, so it acts as an
  edge outlet. Saved as `data/processed/lake_mask.tif`.
  - Without this, the lake was filled as a 16.5 ha "depression" up to 1.3 m
    deep. That raised the false spill level of the shore streets, and the
    study-area ponding volume was 323,000 m³ instead of 110,000 m³.
- Depression = 8-connected cells with DepthInSink > **0.01 m** (noise floor).
  - Kept if max depth ≥ **0.05 m** and area ≥ **20 m²** (PLAN).
  - Volume = sum of depth × 0.25 m² over those cells.
  - Ids are ordered by volume (1 = largest).
- Catchment = cells whose D8 path, on the filled DEM with flats fixed,
  reaches that depression first (WhiteboxTools Watershed with all depression
  cells as pour points). No spill-over between depressions (PLAN first pass).
- Main flow paths: D8 drainage area ≥ **1 ha** (10,000 m²).
- Review flags, kept in the data and interpreted in Steps 7–8:
  - `rail_corridor`: within 30 m of an OSM railway. Embankment ditches are
    drained by culverts that the DTM does not show.
  - `very_deep`: max depth > 2 m. Likely a pond or excavation.
  - `osm_water`: intersects an OSM water polygon.
- Results, study area: **1,655 depressions**, 65.3 ha, 109,600 m³ when full.
  - By max depth: 882 < 0.15 m, 555 0.15–0.30 m, 218 > 0.30 m.
  - Flags: 51 `rail_corridor`, 4 `very_deep`, 0 `osm_water`.
  - Median area 52 m²; median max depth 0.15 m.
- Largest: #1, 21.8 ha, max 1.26 m, mean 0.21 m, 46,000 m³ when full,
  46 ha catchment.
  - It is the low street network around Little River Blvd, St. Pierre and
    Dillon Dr, inside master plan problem area W-1, enclosed by higher ground
    along Riverside Dr.
  - The size is plausible for "sewers full, no outlet but the pump station",
    but its depth when full is an upper bound. Step 7 tests whether storms
    actually fill it.
