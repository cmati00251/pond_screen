"""Step 8: validate against the master plan (TMR Figures 8.2 and 8.3, existing
conditions, 1:100-year 4-hour storm), for the 100-year and 2017-like storms.

Benchmark (from 08a): the plan's modelled ponding in three depth bands and its
problem areas (red outlines), georeferenced to EPSG:2958.

Two tests
  A. PLAN test (as specified): share of the plan's problem areas that overlap
     our study area and contain or touch an overflowing depression. Only two
     problem areas overlap Lesperance (W-1 and one isolated area), so this
     test is reported but cannot carry a 7-in-10 judgement on its own.
  B. Spot test (primary): the plan reports ponding on roadways only, so the
     comparison domain is the street network (OSM streets +/- ROAD_BUF_M)
     inside the study area and inside the figures' coverage.
       recall    = share of the plan's deep spots (> 0.30 m clusters) with our
                   water >= OUR_MIN_M within TOL_M        (pass mark 7 in 10)
       precision = share of our deep spots (>= 0.30 m clusters) with any plan
                   ponding within TOL_M
     TOL_M covers the georeferencing error (~10-20 m) and the plan's ~17 m hexagons.
Each missed spot gets a likely reason from our terrain at that place.

Outputs
  outputs/validation.md, outputs/validation_spots.csv, outputs/maps/validation.png
  data/processed/benchmark.gpkg (adds layer plan_deep_spots)
Run with:  conda run -n pluvial python scripts/08_validation.py
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
from matplotlib.colors import ListedColormap
from rasterio.warp import Resampling, reproject
from scipy import ndimage
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
OUT = ROOT / "outputs"
FIGS = ["fig82", "fig83"]
STORMS = {"100yr": "100-year, 4 h (81.3 mm)", "2017like": "2017-like (100 mm)"}
ROAD_BUF_M = 10.0
TOL_M = 15.0
OUR_MIN_M = 0.15       # our water depth that counts as ponding for the spot test
DEEP_M = 0.30
MIN_SPOT_M2 = 25.0
PASS = 0.70


def near(mask, res):
    """cells within TOL_M of any True cell (Euclidean distance transform)."""
    if not mask.any():
        return np.zeros_like(mask)
    return ndimage.distance_transform_edt(~mask) * res <= TOL_M


def local_max(values, lab, sid, res):
    """max of `values` within TOL_M of the cells of spot `sid` (local window)."""
    r = int(np.ceil(TOL_M / res)) + 1
    sl = ndimage.find_objects((lab == sid).astype(np.int8))[0]
    r0, r1 = max(0, sl[0].start - r), sl[0].stop + r
    c0, c1 = max(0, sl[1].start - r), sl[1].stop + r
    m = lab[r0:r1, c0:c1] == sid
    nm = ndimage.distance_transform_edt(~m) * res <= TOL_M
    return float(values[r0:r1, c0:c1][nm].max())


def main():
    with rasterio.open(PROC / "dtm.tif") as r:
        prof, tr, crs, H, W = r.profile, r.transform, r.crs, r.height, r.width
    cell = abs(tr.a * tr.e)
    res = abs(tr.a)

    # benchmark ponding classes on our grid (nearest); coverage of the figure frames
    mp = np.zeros((H, W), np.uint8)
    cover = np.zeros((H, W), bool)
    for f in FIGS:
        with rasterio.open(PROC / f"benchmark_ponding_{f}.tif") as src:
            dst = np.zeros((H, W), np.uint8)
            reproject(src.read(1), dst, src_transform=src.transform, src_crs=src.crs, dst_transform=tr,
                      dst_crs=crs, resampling=Resampling.nearest, src_nodata=255, dst_nodata=0)
            # rasterio fills cells outside the figure with the source nodata (255), not dst_nodata:
            # without this, max() over the two figures put 255 everywhere one figure was missing
            dst[dst == 255] = 0
            ones = np.zeros((H, W), np.uint8)
            reproject(np.ones((src.height, src.width), np.uint8), ones, src_transform=src.transform,
                      src_crs=src.crs, dst_transform=tr, dst_crs=crs, resampling=Resampling.nearest, dst_nodata=0)
        mp = np.maximum(mp, dst)
        cover |= ones > 0

    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").to_crs(crs)
    in_sa = rasterio.features.geometry_mask(sa.geometry, (H, W), tr, invert=True)
    roads = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="roads").to_crs(crs)
    roads = roads[roads.highway.isin(["primary", "secondary", "tertiary", "residential", "unclassified",
                                      "living_street", "service"])]
    road = rasterio.features.geometry_mask(roads.buffer(ROAD_BUF_M).geometry, (H, W), tr, invert=True)
    domain = in_sa & cover & road
    cov_pct = 100 * (in_sa & cover).sum() / in_sa.sum()
    print(f"study area covered by Figs 8.2/8.3: {cov_pct:.1f}%; street domain {domain.sum() * cell / 1e4:.1f} ha")

    # our results: water at the end of each storm, artefact depressions removed
    dep_g = gpd.read_file(PROC / "storms.gpkg", layer="depressions_storms")
    with rasterio.open(PROC / "depressions.tif") as r:
        dep = r.read(1)
    with rasterio.open(PROC / "depth_in_sink.tif") as r:
        full = r.read(1)
    full = np.where(full < -1000, 0, full)
    # Artefact (excluded) depressions under the final rail rule (v2) and the first rule (v1:
    # any depression touching a 30 m railway buffer). The water rasters themselves do not
    # depend on the flag, so both rules are scored from the same run.
    rail = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="railways").to_crs(crs)
    v1_rail = dep_g.intersects(rail.buffer(30).union_all())
    variants = {"v2": dep_g.loc[dep_g.rail_corridor | dep_g.very_deep, "dep_id"].to_numpy(),
                "v1": dep_g.loc[v1_rail | dep_g.very_deep, "dep_id"].to_numpy()}
    raw = {}
    for k in STORMS:
        with rasterio.open(PROC / f"ponding_{k}.tif") as r:
            raw[k] = r.read(1)

    # ---- B. spot test
    mp_deep = (mp == 3) & domain
    lab, n = ndimage.label(ndimage.binary_dilation(mp_deep, iterations=4), structure=np.ones((3, 3)))
    lab = np.where(mp_deep, lab, 0)
    ids = np.arange(1, n + 1)
    areas = ndimage.sum(mp_deep, lab, ids) * cell
    spot_ids = ids[areas >= MIN_SPOT_M2]
    print(f"plan deep spots (> {DEEP_M} m) on streets in study area: {len(spot_ids)}")
    # plan ponding at three depth thresholds (class >= 1, >= 2, == 3) and their tolerance zones
    mp_near = {c: near((mp >= c) & cover, res) for c in (1, 2, 3)}
    mp_any_near = mp_near[1]
    # chance level for precision: share of street cells inside each zone
    prec_chance = {c: round(100 * (mp_near[c] & domain).sum() / domain.sum(), 1) for c in (1, 2, 3)}
    print("precision chance levels by plan class threshold:", prec_chance)

    def score(artefact_ids):
        keep = (dep > 0) & ~np.isin(dep, artefact_ids)
        ours = {k: np.where(keep, raw[k], 0) for k in STORMS}
        full_keep = np.where(keep, full, 0)
        rows = []
        for k in STORMS:
            for sid in spot_ids:
                dmax = local_max(ours[k], lab, sid, res)
                rows.append({"storm": k, "spot": int(sid), "hit": dmax >= OUR_MIN_M - 1e-4,
                             "our_depth_nearby_m": round(dmax, 3),
                             "our_depth_if_full_nearby_m": round(local_max(full_keep, lab, sid, res), 3)})
        prec = {}
        for k in STORMS:
            od = (ours[k] >= DEEP_M - 1e-4) & domain
            l2, n2 = ndimage.label(ndimage.binary_dilation(od, iterations=4), structure=np.ones((3, 3)))
            l2 = np.where(od, l2, 0)
            a2 = ndimage.sum(od, l2, np.arange(1, n2 + 1)) * cell
            sid2 = np.arange(1, n2 + 1)[a2 >= MIN_SPOT_M2]
            for c in (1, 2, 3):
                h2 = ndimage.maximum(mp_near[c], l2, sid2) > 0 if len(sid2) else np.array([])
                prec[(k, c)] = (int(np.sum(h2)), len(sid2))
            prec[k] = prec[(k, 1)]
        return pd.DataFrame(rows), prec, ours

    spots_v1, prec_v1, _ = score(variants["v1"])
    spots, prec, ours = score(variants["v2"])
    com = ndimage.center_of_mass(mp_deep, lab, spot_ids)
    xy = {sid: (tr.c + (c + 0.5) * tr.a, tr.f + (r + 0.5) * tr.e) for sid, (r, c) in zip(spot_ids, com)}
    spots["x"] = spots.spot.map(lambda s: round(xy[s][0], 1))
    spots["y"] = spots.spot.map(lambda s: round(xy[s][1], 1))
    spots["area_m2"] = spots.spot.map(dict(zip(ids, areas.round(1))))
    pts = gpd.GeoSeries(gpd.points_from_xy(spots.x, spots.y), crs=crs)
    named = roads[roads["name"].notna()]
    spots["nearest_street"] = [named.iloc[named.distance(p).argmin()]["name"] for p in pts]

    def reason(r):
        if r.hit:
            return ""
        if r.our_depth_if_full_nearby_m >= OUR_MIN_M:
            return "our depression is there but the storm does not fill it to 0.15 m (runoff/catchment too small, no spill-over in)"
        if r.our_depth_if_full_nearby_m > 0.05:
            return "only a shallow depression in our terrain (< 0.15 m when full)"
        return "no depression in the terrain: plan's ponding comes from sewer surcharge / pump-station backwater (HGL), not a surface low point"
    spots["likely_reason_if_missed"] = spots.apply(reason, axis=1)
    spots.to_csv(OUT / "validation_spots.csv", index=False)

    # chance level: share of street-domain cells within TOL_M of our water >= OUR_MIN_M.
    # A spot placed at random on the streets would be a "hit" this often.
    chance = {k: round(100 * (near(ours[k] >= OUR_MIN_M - 1e-4, res) & domain).sum() / domain.sum(), 1)
              for k in STORMS}
    print("chance level (street cells within tolerance of our water):", chance)

    # cell-level overlap on the street domain
    agree = {}
    for k in STORMS:
        a = (mp >= 2) & domain
        b = (ours[k] >= OUR_MIN_M) & domain
        agree[k] = (round(100 * (a & near(b, res)).sum() / max(a.sum(), 1), 1),
                    round(100 * (b & near(a, res)).sum() / max(b.sum(), 1), 1))

    # ---- A. plan test on problem areas
    pa = pd.concat([gpd.read_file(PROC / "benchmark.gpkg", layer=f"problem_areas_{f}") for f in FIGS])
    pa = gpd.GeoDataFrame(pa, crs=crs)
    pa_sa = pa[pa.in_study_area_m2 > 0].copy()
    prim = dep_g[~(dep_g.rail_corridor | dep_g.very_deep)]
    a_rows = []
    for _, p in pa_sa.iterrows():
        part = p.geometry.intersection(sa.geometry.iloc[0])
        row = {"pa_id": p.pa_id, "kind": p.kind, "area_in_study_area_ha": round(part.area / 1e4, 1)}
        for k in STORMS:
            ov = prim[prim[f"over2_{k}"]]
            touch = ov[ov.intersects(part)]
            row[f"overflowing_depressions_{k}"] = len(touch)
            row[f"hit_{k}"] = len(touch) > 0
        a_rows.append(row)
    atab = pd.DataFrame(a_rows)

    # plan deep spots layer (for QGIS)
    polys = [(shape(g), int(v)) for g, v in rasterio.features.shapes(lab.astype(np.int32), mask=np.isin(lab, spot_ids),
                                                                       transform=tr)]
    sp = gpd.GeoDataFrame({"spot": [v for _, v in polys]}, geometry=[g for g, _ in polys], crs=crs).dissolve("spot").reset_index()
    s100 = spots[spots.storm == "100yr"].set_index("spot")
    sp["hit_100yr"] = sp.spot.map(s100.hit)
    sp["hit_2017like"] = sp.spot.map(spots[spots.storm == "2017like"].set_index("spot").hit)
    sp["nearest_street"] = sp.spot.map(s100.nearest_street)
    sp["likely_reason_if_missed"] = sp.spot.map(s100.likely_reason_if_missed)
    sp.to_file(PROC / "benchmark.gpkg", layer="plan_deep_spots")

    # ---- report
    lines = ["# Validation against the 2019 Storm Drainage Master Plan", "",
             "Benchmark: TMR Figures 8.2 and 8.3, existing conditions, 1:100-year 4-hour storm (Dillon "
             "Consulting, June 2019), georeferenced and digitised in `scripts/08a_georef_benchmark.py`. "
             f"The two figures cover {cov_pct:.0f}% of the Lesperance study area.", "",
             "Our results: pass 2 (spill-over), storm sewers assumed full, rail-ditch and pond depressions "
             "excluded. Water depth at the end of each storm.", ""]
    lines += ["## A. Plan test: problem areas", "",
              "The plan's test counts problem areas that contain or touch an overflowing depression. Only "
              f"{len(atab)} of the plan's problem areas overlap the Lesperance study area, so this test is "
              "reported for completeness but cannot support a 7-in-10 judgement.", "",
              "| Problem area | Type | Area in study area | 100-year | 2017-like |", "|---|---|---|---|---|"]
    for _, r in atab.iterrows():
        lines.append(f"| {r.pa_id} | {r.kind} | {r.area_in_study_area_ha} ha | "
                     f"{'hit' if r.hit_100yr else 'miss'} ({r.overflowing_depressions_100yr} depressions) | "
                     f"{'hit' if r.hit_2017like else 'miss'} ({r.overflowing_depressions_2017like} depressions) |")
    lines += ["", "## B. Spot test (primary)", "",
              f"Domain: streets (OSM centrelines ± {ROAD_BUF_M:.0f} m) inside the study area and inside the "
              f"figures, where the plan reports ponding. Tolerance {TOL_M:.0f} m.", "",
              "| Measure | 100-year | 2017-like |", "|---|---|---|"]
    rec = {k: spots[spots.storm == k].hit.mean() for k in STORMS}
    nsp = len(spot_ids)
    lines.append(f"| **Recall**: plan deep spots (> 0.30 m) with our water ≥ {OUR_MIN_M} m within {TOL_M:.0f} m | "
                 f"**{100 * rec['100yr']:.0f}%** ({int(spots[(spots.storm == '100yr')].hit.sum())}/{nsp}) | "
                 f"**{100 * rec['2017like']:.0f}%** ({int(spots[(spots.storm == '2017like')].hit.sum())}/{nsp}) |")
    lines.append(f"| Chance level: street length within {TOL_M:.0f} m of our water ≥ {OUR_MIN_M} m "
                 f"(recall a random spot would get) | {chance['100yr']}% | {chance['2017like']}% |")
    for c, lab_c in [(1, "any plan ponding"), (2, "plan ponding ≥ 0.15 m"), (3, "plan ponding > 0.30 m")]:
        p1, p2 = prec[("100yr", c)], prec[("2017like", c)]
        lines.append(f"| Precision: our deep spots (≥ 0.30 m) with {lab_c} within {TOL_M:.0f} m "
                     f"(chance level {prec_chance[c]}%) | {100 * p1[0] / max(p1[1], 1):.0f}% ({p1[0]}/{p1[1]}) | "
                     f"{100 * p2[0] / max(p2[1], 1):.0f}% ({p2[0]}/{p2[1]}) |")
    lines.append(f"| Plan ponding ≥ 0.15 m area with our water ≥ 0.15 m nearby | {agree['100yr'][0]}% | {agree['2017like'][0]}% |")
    lines.append(f"| Our water ≥ 0.15 m area with plan ponding ≥ 0.15 m nearby | {agree['100yr'][1]}% | {agree['2017like'][1]}% |")
    verdict = "PASS" if min(rec.values()) >= PASS else "FAIL"
    from scipy.stats import binom
    k_hit = int(spots[spots.storm == "100yr"].hit.sum())
    p_val = binom.sf(k_hit - 1, nsp, chance["100yr"] / 100)
    lines += ["", f"**Pass mark: at least 7 in 10. Result: {verdict}** "
              f"(recall {100 * rec['100yr']:.0f}% for the 100-year storm, {100 * rec['2017like']:.0f}% for the 2017-like storm).", "",
              "**Reading the numbers against chance.** Our water covers a lot of the street network, so a randomly "
              f"placed spot would be 'hit' {chance['100yr']:.0f}% of the time; the 7-in-10 pass mark is therefore lenient "
              f"here. Recall of {100 * rec['100yr']:.0f}% is far above that (probability of {k_hit}/{nsp} or better by chance: "
              f"{p_val:.1e}). Precision against *any* plan ponding is close to its chance level "
              f"({prec_chance[1]}%), because the plan shows some ponding on most streets, so it carries little information; "
              "precision against the plan's deeper ponding is the more telling figure.", ""]
    o = spots_v1
    r1 = {k: o[o.storm == k].hit.mean() for k in STORMS}
    v1_verdict = "PASS" if min(r1.values()) >= PASS else "FAIL"
    lines += ["### Effect of the rail-ditch rule", "",
              "The rail-ditch rule was changed during validation, so both versions are scored here on the "
              "same water results:", "",
              "| Rail-ditch rule | Recall 100-year | Recall 2017-like | Precision 100-year | Verdict |",
              "|---|---|---|---|---|",
              f"| v1: any depression touching a 30 m railway buffer | {100 * r1['100yr']:.0f}% "
              f"({int(o[o.storm == '100yr'].hit.sum())}/{nsp}) | {100 * r1['2017like']:.0f}% | "
              f"{100 * prec_v1['100yr'][0] / max(prec_v1['100yr'][1], 1):.0f}% | {v1_verdict} |",
              f"| **v2 (final)**: ≥ 50 % of the depression within 15 m of the track | **{100 * rec['100yr']:.0f}%** "
              f"({int(spots[spots.storm == '100yr'].hit.sum())}/{nsp}) | **{100 * rec['2017like']:.0f}%** | "
              f"{100 * prec['100yr'][0] / max(prec['100yr'][1], 1):.0f}% | **{verdict}** |", "",
              "Why it changed: under v1, misses on Tecumseh Rd lay on depressions that hold 0.15–1.5 m of water "
              "but were excluded because Tecumseh Rd runs only 16–55 m from the CN tracks; the plan's own model, "
              "which includes pipes and culverts, shows deep ponding at the same places. v2 limits the flag to the "
              "rail right-of-way. Because the change was prompted by this test, the v2 result is not an independent "
              "confirmation; it measures the remaining disagreement once the rule error was fixed.", ""]
    miss = spots[(spots.storm == "100yr") & ~spots.hit]
    lines += ["## Misses (100-year) and likely reasons", ""]
    if len(miss):
        lines += ["| Spot | Nearest street | Plan spot area | Our depth nearby | Our depth if full | Likely reason |",
                  "|---|---|---|---|---|---|"]
        for _, r in miss.sort_values("area_m2", ascending=False).iterrows():
            lines.append(f"| {r.spot} | {r.nearest_street} | {r.area_m2:.0f} m² | {r.our_depth_nearby_m:.2f} m | "
                         f"{r.our_depth_if_full_nearby_m:.2f} m | {r.likely_reason_if_missed} |")
        lines += ["", "Reason counts: " + "; ".join(f"{v} × {k}" for k, v in miss.likely_reason_if_missed.value_counts().items())]
    else:
        lines.append("None.")
    lines += ["", "## Why the methods differ", "",
              "- The plan's 2D PCSWMM model includes the pipes, pump-station capacity and backwater (HGL); "
              "ours is terrain-only with sewers assumed full. Ponding caused by surcharging sewers with no "
              "surface low point cannot appear in our results.",
              "- The plan excluded parkland and private property; it reports roadway ponding only. Most of "
              "our depressions are in yards, which is why the comparison is limited to streets.",
              "- The benchmark was digitised from a figure without coordinates; alignment error is about "
              "10–20 m, and the plan's ponding is drawn as ~17 m hexagons.",
              "- The plan's terrain model dates from before 2019; our lidar is 2016–18 and imagery 2025.", ""]
    (OUT / "validation.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    # ---- map
    step = 2
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    with rasterio.open(PROC / "dtm.tif") as r:
        z = r.read(1, masked=True).filled(np.nan)[::step, ::step]
    gy, gx = np.gradient(np.where(np.isnan(z), np.nanmedian(z), z), abs(tr.a) * step)
    sl = np.arctan(3 * np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    hs = np.clip(0.707 * np.cos(sl) + 0.707 * np.sin(sl) * np.cos(np.radians(135) - asp), 0, 1)
    fig, axes = plt.subplots(1, 2, figsize=(16, 11))
    for ax, title, arr, cmap in [
        (axes[0], "Master plan 1:100-year ponding (digitised)", np.where((mp > 0) & cover, mp, np.nan)[::step, ::step],
         ListedColormap(["#9ecae1", "#4292c6", "#08306b"])),
        (axes[1], "Our 100-year ponding (sewers full, spill-over)",
         np.digitize(ours["100yr"], [0.01, 0.15, 0.30]).astype(float)[::step, ::step], ListedColormap(["#9ecae1", "#4292c6", "#08306b"]))]:
        ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1, alpha=0.8)
        if "Our" in title:
            arr = np.where(arr > 0, arr, np.nan)
        ax.imshow(arr, cmap=cmap, vmin=0.5, vmax=3.5, extent=ext, interpolation="nearest")
        sa.boundary.plot(ax=ax, color="magenta", lw=1.2)
        pa_sa.boundary.plot(ax=ax, color="red", lw=1.0, ls="--")
        ax.set_title(title, fontsize=10)
        ax.set_xlim(343550, 345400); ax.set_ylim(4685400, 4688650)
        ax.set_xticks([]); ax.set_yticks([])
    hit_pts = gpd.GeoDataFrame(spots[spots.storm == "100yr"], geometry=gpd.points_from_xy(spots[spots.storm == "100yr"].x,
                                                                                        spots[spots.storm == "100yr"].y), crs=crs)
    for ax in axes:
        hit_pts[hit_pts.hit].plot(ax=ax, color="lime", edgecolor="k", markersize=28, zorder=5)
        hit_pts[~hit_pts.hit].plot(ax=ax, color="red", edgecolor="k", marker="X", markersize=40, zorder=5)
    fig.suptitle(f"Validation, 100-year storm: plan deep spots (> 0.30 m) on streets matched by our ponding (green) "
                 f"or missed (red X); recall {100 * rec['100yr']:.0f}%. Red dashed = plan problem areas; blue bands "
                 f"< 0.15, 0.15–0.30, > 0.30 m", fontsize=10)
    fig.savefig(OUT / "maps/validation.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/validation.md, validation_spots.csv, maps/validation.png")


if __name__ == "__main__":
    main()
