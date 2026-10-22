"""Step 6: find where water pools (lidar + buildings only; no imagery needed).

1. Raise building footprints 3 m in the DTM so water flows around them.
2. WhiteboxTools FillDepressions + DepthInSink -> depth of every sink.
3. Depressions = connected cells deeper than NOISE_M; keep those with
   max depth >= MIN_DEPTH_M and area >= MIN_AREA_M2.
4. Per depression: max/mean depth, area, volume, contributing catchment
   (cells whose D8 path on the filled DEM reaches it first; no spill-over).
5. D8 flow accumulation and main flow paths (>= STREAM_M2 drainage area).

Outputs
  data/processed/dtm_buildings.tif        DTM with buildings raised
  data/processed/depth_in_sink.tif        sink depth (m)
  data/processed/depressions.tif          depression id per cell (int32)
  data/processed/depression_catchments.tif  catchment id per cell (int32)
  data/processed/flow_accum.tif           D8 drainage area (m2)
  data/processed/depressions.gpkg         layers: depressions, flow_paths
  outputs/depressions.csv, outputs/maps/depressions.png
Run with:  conda run -n pluvial python scripts/06_depressions.py
"""
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy import ndimage
from shapely.geometry import shape
import whitebox

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
WBT_DIR = PROC / "wbt"
MAPS = ROOT / "outputs/maps"

BUILDING_RAISE_M = 3.0
LAKE_LEVEL_M = 174.24 # hydro-flattened Lake St. Clair surface in the DTM
LAKE_TOL_M = 0.01
LAKE_MIN_M2 = 50_000  # flat patches >= 5 ha at lake level = lake
NOISE_M = 0.01        # depth below this is treated as dry (float noise)
MIN_DEPTH_M = 0.05    # PLAN
MIN_AREA_M2 = 20.0    # PLAN
STREAM_M2 = 10_000    # main flow path = drains >= 1 ha
DEPTH_BANDS = [0.05, 0.15, 0.30]  # master plan legend breaks (+ our 5 cm floor)
# Rail-ditch flag (v2, after validation): a depression is a rail ditch when at least
# RAIL_SHARE of its area lies within RAIL_ROW_M of the track centreline (the rail
# right-of-way). v1 flagged any depression touching a 30 m buffer, which also removed
# genuine roadside ponding on Tecumseh Rd, 16-55 m from the CN tracks (see decisions.md).
RAIL_ROW_M = 15
RAIL_SHARE = 0.5
VERY_DEEP_M = 2.0     # flag: deeper than this is likely a pond or excavation, not street ponding
NODATA = -9999.0


def read(path):
    with rasterio.open(path) as r:
        a = r.read(1).astype(np.float64)
        nd = r.nodata
        prof = r.profile
    if nd is not None:
        a[a == nd] = np.nan
    return a, prof


def write(path, a, prof, dtype="float32", nodata=NODATA):
    # No floating-point predictor: WhiteboxTools cannot read PREDICTOR=3.
    p = prof.copy()
    p.pop("predictor", None)
    p.update(dtype=dtype, nodata=nodata, compress="deflate", tiled=True,
             blockxsize=512, blockysize=512, count=1)
    if dtype.startswith("float"):
        a = np.where(np.isnan(a), nodata, a)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(a.astype(dtype), 1)


def run(tool, out, *args, **kw):
    """Run a WhiteboxTools tool. The wrapper can return 0 after a crash, so
    also require the named output file to be (re)created."""
    out = Path(out)
    if out.exists():
        out.unlink()
    rc = tool(*args, **kw)
    if rc != 0 or not out.exists():
        raise RuntimeError(f"WhiteboxTools {tool.__name__} failed (rc={rc}, output={out})")


def main():
    WBT_DIR.mkdir(parents=True, exist_ok=True)
    MAPS.mkdir(parents=True, exist_ok=True)
    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    wbt.set_compress_rasters(True)

    # 1. raise buildings
    dtm, prof = read(PROC / "dtm.tif")
    tr, crs = prof["transform"], prof["crs"]
    cell = abs(tr.a * tr.e)
    bld = gpd.read_file(PROC / "buildings_study.gpkg").to_crs(crs)
    bmask = rasterio.features.geometry_mask(bld.geometry, dtm.shape, tr, invert=True)
    dem = np.where(bmask & ~np.isnan(dtm), dtm + BUILDING_RAISE_M, dtm)

    # Lake St. Clair is hydro-flattened at LAKE_LEVEL_M. Treat it as an outlet
    # (nodata = edge for WhiteboxTools); otherwise it is filled like a sink and
    # falsely raises the spill level of the shoreline streets.
    flat = np.abs(dtm - LAKE_LEVEL_M) <= LAKE_TOL_M
    lab_l, n_l = ndimage.label(flat)
    sizes_l = ndimage.sum(flat, lab_l, range(1, n_l + 1)) * cell
    lake = np.isin(lab_l, 1 + np.flatnonzero(sizes_l >= LAKE_MIN_M2))
    dem[lake] = np.nan
    lake_path = PROC / "lake_mask.tif"
    old = None
    if lake_path.exists():
        with rasterio.open(lake_path) as r:
            old = r.read(1)
    if old is None or old.shape != lake.shape or not np.array_equal(old == 1, lake):
        write(lake_path, lake.astype(np.uint8), prof, dtype="uint8", nodata=255)
    # (unchanged mask is not rewritten, so Step 5, which reads it, is not marked stale)
    print(f"lake outlet: {lake.sum() * cell / 1e4:.1f} ha at {LAKE_LEVEL_M} m")

    dem_path = PROC / "dtm_buildings.tif"
    write(dem_path, dem, prof)
    print(f"buildings raised: {len(bld)} footprints, {bmask.sum() * cell / 1e4:.1f} ha")

    # 2. fill + depth in sink
    filled = WBT_DIR / "filled.tif"
    depth_p = WBT_DIR / "depth_in_sink.tif"
    run(wbt.fill_depressions, filled, str(dem_path), str(filled), fix_flats=True)
    run(wbt.depth_in_sink, depth_p, str(dem_path), str(depth_p), zero_background=True)
    depth, _ = read(depth_p)
    depth[np.isnan(dtm) | lake] = np.nan
    write(PROC / "depth_in_sink.tif", depth, prof)

    # 3. depressions
    wet = np.nan_to_num(depth) > NOISE_M
    lab, n = ndimage.label(wet, structure=np.ones((3, 3)))
    idx = np.arange(1, n + 1)
    d0 = np.nan_to_num(depth)
    area = ndimage.sum(wet, lab, idx) * cell
    dmax = ndimage.maximum(d0, lab, idx)
    vol = ndimage.sum(d0, lab, idx) * cell
    keep = (dmax >= MIN_DEPTH_M) & (area >= MIN_AREA_M2)
    print(f"sink patches > {NOISE_M} m: {n:,}; kept (>= {MIN_DEPTH_M} m deep, >= {MIN_AREA_M2} m2): {keep.sum():,}")
    # renumber kept depressions by volume, largest = 1
    kept_old = idx[keep]
    order = np.argsort(-vol[keep])
    new_id = np.zeros(n + 1, dtype=np.int32)
    new_id[kept_old[order]] = np.arange(1, keep.sum() + 1, dtype=np.int32)
    dep = new_id[lab]
    dep_path = PROC / "depressions.tif"
    write(dep_path, dep, prof, dtype="int32", nodata=0)

    # 4. catchments: first depression reached along D8 on the filled DEM
    pntr = WBT_DIR / "d8_pointer.tif"
    run(wbt.d8_pointer, pntr, str(filled), str(pntr))
    ws = WBT_DIR / "watershed.tif"
    run(wbt.watershed, ws, str(pntr), str(dep_path), str(ws))
    catch, _ = read(ws)
    catch = np.nan_to_num(catch, nan=0).astype(np.int32)
    catch[np.isnan(dtm)] = 0
    write(PROC / "depression_catchments.tif", catch, prof, dtype="int32", nodata=0)

    m = dep.max()
    ids = np.arange(1, m + 1)
    dep_area = ndimage.sum(dep > 0, dep, ids) * cell
    dep_max = ndimage.maximum(d0, dep, ids)
    dep_vol = ndimage.sum(d0, dep, ids) * cell
    c_area = ndimage.sum(catch > 0, catch, ids) * cell
    c_bld = ndimage.sum(bmask, catch, ids) * cell

    # 5. flow accumulation + main flow paths
    acc_p = WBT_DIR / "flow_accum.tif"
    run(wbt.d8_flow_accumulation, acc_p, str(filled), str(acc_p), out_type="catchment area")
    acc, _ = read(acc_p)
    acc[np.isnan(dtm)] = np.nan
    write(PROC / "flow_accum.tif", acc, prof)
    streams = WBT_DIR / "streams.tif"
    run(wbt.extract_streams, streams, str(acc_p), str(streams), STREAM_M2)
    streams_shp = WBT_DIR / "flow_paths.shp"
    run(wbt.raster_streams_to_vector, streams_shp, str(streams), str(pntr), str(streams_shp))

    # vectors
    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").to_crs(crs)
    buf = gpd.read_file(PROC / "study_area.gpkg", layer="study_area_buffer200").to_crs(crs)
    polys = [(shape(g), int(v)) for g, v in rasterio.features.shapes(dep, mask=dep > 0, transform=tr)]
    gdf = gpd.GeoDataFrame({"dep_id": [v for _, v in polys]}, geometry=[g for g, _ in polys], crs=crs)
    gdf = gdf.dissolve("dep_id").reset_index()
    stats = pd.DataFrame({"dep_id": ids, "area_m2": dep_area.round(1), "max_depth_m": dep_max.round(3),
                          "mean_depth_m": (dep_vol / dep_area).round(3), "volume_m3": dep_vol.round(2),
                          "catchment_m2": c_area.round(0), "catchment_roof_m2": c_bld.round(0)})
    gdf = gdf.merge(stats, on="dep_id")
    gdf["in_study_area"] = gdf.intersects(sa.geometry.iloc[0])
    edge = buf.geometry.iloc[0].boundary.buffer(5)
    gdf["at_buffer_edge"] = gdf.intersects(edge)
    # Review flags (kept in the data, interpreted in Steps 7-8)
    osm = PROC / "osm_tecumseh.gpkg"
    rail = gpd.read_file(osm, layer="railways").to_crs(crs)
    water = gpd.read_file(osm, layer="water").to_crs(crs)
    water = water[water.geom_type.isin(["Polygon", "MultiPolygon"])]
    row = rail.buffer(RAIL_ROW_M).union_all()
    gdf["rail_share"] = (gdf.intersection(row).area / gdf.area).round(3)
    gdf["rail_corridor"] = gdf["rail_share"] >= RAIL_SHARE
    gdf["osm_water"] = gdf.intersects(water.union_all()) if len(water) else False
    gdf["very_deep"] = gdf["max_depth_m"] > VERY_DEEP_M
    gdf["depth_band"] = pd.cut(gdf["max_depth_m"], [0, 0.15, 0.30, np.inf],
                               labels=["< 0.15 m", "0.15-0.30 m", "> 0.30 m"]).astype(str)
    out_gpkg = PROC / "depressions.gpkg"
    if out_gpkg.exists():
        out_gpkg.unlink()
    gdf.to_file(out_gpkg, layer="depressions")
    fp = gpd.read_file(streams_shp).set_crs(crs, allow_override=True)
    fp.to_file(out_gpkg, layer="flow_paths")
    gdf.drop(columns="geometry").to_csv(ROOT / "outputs/depressions.csv", index=False)

    s = gdf[gdf["in_study_area"]]
    print(f"depressions in study area: {len(s):,}  (whole buffer {len(gdf):,})")
    print(f"  by depth band: {s['depth_band'].value_counts().to_dict()}")
    print(f"  total ponding volume {s['volume_m3'].sum():,.0f} m3 over {s['area_m2'].sum() / 1e4:.1f} ha")
    print(f"  area quantiles m2: {s['area_m2'].quantile([.5, .9, .99]).round(0).to_dict()}, max {s['area_m2'].max():,.0f}")
    print(f"  max depth quantiles m: {s['max_depth_m'].quantile([.5, .9, .99]).round(2).to_dict()}, max {s['max_depth_m'].max():.2f}")
    print(f"  catchments cover {100 * (catch[~np.isnan(dtm)] > 0).mean():.1f}% of the buffer grid")
    print(f"  flags (study area): rail_corridor {int(s['rail_corridor'].sum())}, "
          f"osm_water {int(s['osm_water'].sum())}, very_deep {int(s['very_deep'].sum())}")
    print(s.nlargest(10, "volume_m3")[["dep_id", "area_m2", "max_depth_m", "volume_m3", "catchment_m2"]].to_string(index=False))

    # map
    step = 2
    z = dtm[::step, ::step]
    gy, gx = np.gradient(np.where(np.isnan(z), np.nanmedian(z), z), cell ** 0.5 * step)
    sl = np.arctan(3 * np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    hs = np.clip(np.sin(np.radians(45)) * np.cos(sl) + np.cos(np.radians(45)) * np.sin(sl) * np.cos(np.radians(135) - asp), 0, 1)
    hs[np.isnan(z)] = np.nan
    H, W = dtm.shape
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    dd = np.where(dep[::step, ::step] > 0, d0[::step, ::step], np.nan)
    cmap = ListedColormap(["#9ecae1", "#4292c6", "#08306b"])
    norm = BoundaryNorm([NOISE_M, 0.15, 0.30, 5], cmap.N)
    fig, ax = plt.subplots(figsize=(10, 13))
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1, alpha=0.9)
    fp.plot(ax=ax, color="#d95f02", lw=0.5, alpha=0.85)
    im = ax.imshow(dd, cmap=cmap, norm=norm, extent=ext, interpolation="nearest")
    sa.boundary.plot(ax=ax, color="magenta", lw=1.4)
    cb = fig.colorbar(im, ax=ax, shrink=0.4, pad=0.01, ticks=[0.08, 0.225, 0.4])
    cb.ax.set_yticklabels(["< 0.15 m", "0.15–0.30 m", "> 0.30 m"])
    cb.set_label("Ponding depth when full (bands as in master plan)")
    ax.set_title(f"Step 6: depressions (>= {MIN_DEPTH_M * 100:.0f} cm deep, >= {MIN_AREA_M2:.0f} m²) "
                 f"and main flow paths (orange, >= {STREAM_M2 / 1e4:.0f} ha drainage)\n"
                 f"Buildings raised {BUILDING_RAISE_M:.0f} m; no sewer drainage; magenta = study area",
                 fontsize=9)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
    ax.tick_params(labelsize=7)
    fig.savefig(MAPS / "depressions.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/maps/depressions.png")


if __name__ == "__main__":
    main()
