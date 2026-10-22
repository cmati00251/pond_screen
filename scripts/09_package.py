"""Step 9: package the results.

  outputs/layers.gpkg        study_area, surfaces_50m (class shares per 50 m cell),
                             depressions, flow_paths, flagged_<storm> (overflowing, pass 2),
                             water_<storm> (end-of-storm water >= 0.15 m), buildings_at_risk,
                             plan_problem_areas, plan_deep_spots, hotspots
  outputs/hotspots.csv       10 worst depressions (see RANK below)
  outputs/hotspots.geojson   same points, WGS84
  outputs/maps/hotspots.png  overview map

Ranking of the "worst" depressions (study area, rail-ditch and pond depressions
excluded): number of buildings with >= 0.15 m water within 5 m in the 100-year
storm, then the depression's water depth in the 100-year storm.
"Sealed area draining to it" counts roof + sealed ground in its own catchment
plus the catchments of every depression upstream that spills into it.
Run with:  conda run -n pluvial python scripts/09_package.py
"""
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from scipy import ndimage
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
OUT = ROOT / "outputs"
STORMS = ["2yr", "10yr", "100yr", "2017like"]
STORM_LABEL = {"2yr": "2-year (38.5 mm)", "10yr": "10-year (57.5 mm)", "100yr": "100-year (81.3 mm)",
               "2017like": "2017-like (100 mm)", "none": "none of the four storms"}
RISK_M = 0.15
BUILDING_DIST_M = 5.0
N_HOT = 10
CLASSES = {1: "roof", 2: "tree", 3: "grass", 4: "water", 5: "sealed"}


def main():
    out_g = OUT / "layers.gpkg"
    if out_g.exists():
        out_g.unlink()
    with rasterio.open(PROC / "surfaces.tif") as r:
        surf, tr, crs = r.read(1), r.transform, r.crs
    H, W = surf.shape
    cell = abs(tr.a * tr.e)
    with rasterio.open(PROC / "depression_catchments.tif") as r:
        catch = r.read(1)
    with rasterio.open(PROC / "depressions.tif") as r:
        dep = r.read(1)

    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area")
    sa.to_file(out_g, layer="study_area")

    # surfaces summarised per 50 m cell
    f = 100
    Hc, Wc = -(-H // f), -(-W // f)
    padded = np.zeros((Hc * f, Wc * f), np.uint8)
    padded[:H, :W] = surf
    blocks = padded.reshape(Hc, f, Wc, f)
    valid = (blocks > 0).sum(axis=(1, 3))
    rows = []
    for i in range(Hc):
        for j in range(Wc):
            if valid[i, j] < 0.25 * f * f:
                continue
            b = blocks[i, :, j, :]
            x0, y1 = tr.c + j * f * tr.a, tr.f + i * f * tr.e
            rec = {"geometry": box(x0, y1 - f * abs(tr.e), x0 + f * tr.a, y1)}
            for k, nme in CLASSES.items():
                rec[f"pct_{nme}"] = round(100 * (b == k).sum() / valid[i, j], 1)
            rec["pct_sealed"] = round(rec["pct_roof"] + rec["pct_sealed"], 1)
            rec["pct_sealed_ground"] = round(100 * (b == 5).sum() / valid[i, j], 1)
            rows.append(rec)
    gpd.GeoDataFrame(rows, crs=crs).to_file(out_g, layer="surfaces_50m")

    dg = gpd.read_file(PROC / "storms.gpkg", layer="depressions_storms")
    dg.to_file(out_g, layer="depressions")
    gpd.read_file(PROC / "depressions.gpkg", layer="flow_paths").to_file(out_g, layer="flow_paths")
    prim = dg[dg.primary]
    for k in STORMS:
        prim[prim[f"over2_{k}"]].to_file(out_g, layer=f"flagged_{k}")

    # end-of-storm water >= 0.15 m as polygons, tagged with the depression id
    water = {}
    for k in STORMS:
        with rasterio.open(PROC / f"ponding_{k}.tif") as r:
            w = r.read(1)
        m = (w >= RISK_M - 1e-4) & (dep > 0)
        polys = [(shape(g), int(v)) for g, v in rasterio.features.shapes(np.where(m, dep, 0).astype(np.int32),
                                                                           mask=m, transform=tr)]
        wg = gpd.GeoDataFrame({"dep_id": [v for _, v in polys]}, geometry=[g for g, _ in polys], crs=crs)
        wg = wg.dissolve("dep_id").reset_index()
        wg["storm"] = k
        wg.to_file(out_g, layer=f"water_{k}")
        water[k] = wg

    bld = gpd.read_file(PROC / "storms.gpkg", layer="buildings_at_risk")
    bld.to_file(out_g, layer="buildings_at_risk")
    bench = PROC / "benchmark.gpkg"
    pa = pd.concat([gpd.read_file(bench, layer=l) for l in ["problem_areas_fig82", "problem_areas_fig83"]])
    gpd.GeoDataFrame(pa, crs=crs).to_file(out_g, layer="plan_problem_areas")
    gpd.read_file(bench, layer="plan_deep_spots").to_file(out_g, layer="plan_deep_spots")

    # ---- hotspots
    all_bld = gpd.read_file(PROC / "buildings_study.gpkg").to_crs(crs)
    sa_geom = sa.geometry.iloc[0]
    bld_sa = all_bld[all_bld.representative_point().within(sa_geom)]
    w100 = water["100yr"]
    w100 = w100[w100.dep_id.isin(prim.dep_id)]
    near = gpd.sjoin(bld_sa[["geometry"]], gpd.GeoDataFrame(w100[["dep_id"]], geometry=w100.buffer(BUILDING_DIST_M), crs=crs),
                     predicate="intersects")
    nb = near.groupby("dep_id").size()
    cand = prim.copy()
    cand["buildings_at_risk_100yr"] = cand.dep_id.map(nb).fillna(0).astype(int)
    cand = cand.sort_values(["buildings_at_risk_100yr", "wdepth2_100yr"], ascending=False).head(N_HOT).copy()

    # upstream sets (spill-over tree) and sealed area per catchment
    down = dict(zip(dg.dep_id, dg.downstream_dep_id))
    ups = {}
    for i, j in down.items():
        if j:
            ups.setdefault(j, []).append(i)

    def upstream(i):
        seen, stack = {i}, [i]
        while stack:
            for u in ups.get(stack.pop(), []):
                if u not in seen:
                    seen.add(u)
                    stack.append(u)
        return seen
    ids = np.arange(1, int(dg.dep_id.max()) + 1)
    sealed_c = dict(zip(ids, ndimage.sum((surf == 1) | (surf == 5), catch, ids) * cell))
    area_c = dict(zip(ids, ndimage.sum(catch > 0, catch, ids) * cell))
    roads = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="roads").to_crs(crs)
    named = roads[roads["name"].notna()]
    recs = []
    for rank, (_, d) in enumerate(cand.iterrows(), start=1):
        up = upstream(int(d.dep_id))
        s_area = sum(sealed_c.get(u, 0) for u in up)
        c_area = sum(area_c.get(u, 0) for u in up)
        p = d.geometry.representative_point()
        ll = gpd.GeoSeries([p], crs=crs).to_crs(4326).iloc[0]
        street = named.iloc[named.distance(p).argmin()]["name"]
        recs.append({"rank": rank, "dep_id": int(d.dep_id), "latitude": round(ll.y, 6), "longitude": round(ll.x, 6),
                     "nearest_street": street, "max_depth_m": round(float(d.max_depth_m), 2),
                     "water_depth_100yr_m": round(float(d.wdepth2_100yr), 2),
                     "volume_m3": round(float(d.volume_m3), 0), "area_m2": round(float(d.area_m2), 0),
                     "sealed_area_draining_m2": round(s_area, 0), "catchment_area_m2": round(c_area, 0),
                     "pct_sealed_catchment": round(100 * s_area / c_area, 1) if c_area else None,
                     "upstream_depressions": len(up) - 1,
                     "buildings_at_risk_100yr": int(d.buildings_at_risk_100yr),
                     "smallest_storm_overflow": d.smallest_storm_overflow,
                     "smallest_storm_label": STORM_LABEL[d.smallest_storm_overflow],
                     "x_epsg2958": round(p.x, 1), "y_epsg2958": round(p.y, 1)})
    hot = pd.DataFrame(recs)
    hot.to_csv(OUT / "hotspots.csv", index=False)
    hg = gpd.GeoDataFrame(hot, geometry=gpd.points_from_xy(hot.x_epsg2958, hot.y_epsg2958), crs=crs)
    hg.to_file(out_g, layer="hotspots")
    hg.to_crs(4326).to_file(OUT / "hotspots.geojson", driver="GeoJSON")
    print(hot[["rank", "dep_id", "nearest_street", "max_depth_m", "water_depth_100yr_m", "volume_m3",
               "sealed_area_draining_m2", "pct_sealed_catchment", "buildings_at_risk_100yr",
               "smallest_storm_overflow"]].to_string(index=False))

    # ---- overview map
    with rasterio.open(PROC / "dtm.tif") as r:
        z = r.read(1, masked=True).filled(np.nan)[::2, ::2]
    gy, gx = np.gradient(np.where(np.isnan(z), np.nanmedian(z), z), abs(tr.a) * 2)
    sl = np.arctan(3 * np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    hs = np.clip(0.707 * np.cos(sl) + 0.707 * np.sin(sl) * np.cos(np.radians(135) - asp), 0, 1)
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    fig, ax = plt.subplots(figsize=(10, 13))
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1, alpha=0.85)
    w100.plot(ax=ax, color="#2171b5", lw=0)
    bld[bld.smallest_storm_at_risk.isin(STORMS)].plot(ax=ax, color="#fdae61", lw=0)
    sa.boundary.plot(ax=ax, color="magenta", lw=1.3)
    hg.plot(ax=ax, color="#d7191c", edgecolor="k", markersize=90, zorder=5)
    for _, r in hg.iterrows():
        ax.annotate(str(r["rank"]), (r.geometry.x, r.geometry.y), xytext=(6, 6), textcoords="offset points",
                    fontsize=10, fontweight="bold", color="k",
                    bbox=dict(fc="white", ec="#d7191c", alpha=0.9, pad=1.5))
    ax.set_title("Top 10 ponding hotspots (red), 100-year water ≥ 0.15 m (blue), buildings at risk in any storm "
                 "(orange)\nLesperance pump station service area; sewers assumed full", fontsize=10)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_xticks([]); ax.set_yticks([])
    fig.savefig(OUT / "maps/hotspots.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/layers.gpkg, hotspots.csv, hotspots.geojson, maps/hotspots.png")


if __name__ == "__main__":
    main()
