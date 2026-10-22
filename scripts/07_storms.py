"""Step 7: rain on the map. Volume balance of every depression for four
storms, with storm sewers assumed full (no pipe drainage).

Storms: 2-, 10-, 100-year 4-hour depths from the Windsor A IDF (v3.40),
log-log interpolated between the 2 h and 6 h values (the master plan's
benchmark storm is a 4 h Chicago storm), plus a 2017-like 100 mm event.

For each depression d (from Step 6):
  CA_d   = sum over its catchment cells of runoff share x 0.25 m2  (m2)
  own_d  = P x CA_d                                            (m3)
  Pass 1 (PLAN first pass): inflow = own_d; overflows if inflow > volume
  Pass 2 (spill-over):      inflow = own_d + overflow of every depression
         spilling into d; processed upstream -> downstream. The receiving
         depression is found by following the D8 pointer (filled DEM) from
         the depression's lowest cell out across its spill point.
  Critical rain (pass 1) = volume / CA_d  (mm needed to fill it from its own catchment)

Primary results use pass 2 and exclude review-flagged depressions
(rail_corridor = embankment ditches drained by culverts; very_deep = ponds /
excavations). Flagged ones are still computed and reported separately.

Water at the end of each storm: depressions that overflow are full; partly
filled ones are drawn at the level that holds their inflow (ponding_<storm>.tif).

Buildings at risk. The PLAN rule (footprint within 5 m of an overflowing
depression) is reported as `bld_plan_rule`, but it flags about half the area
even in a 2-year storm, because most depressions are tiny dips that fill with
any rain. The primary measure therefore uses water depth at the end of the
storm, with the master plan's own depth bands:
  at risk       max water depth within 5 m of the footprint >= 0.15 m
  high risk     max water depth within 5 m of the footprint >= 0.30 m
                (0.30 m = the Town's allowable 1:100 ponding depth)

Outputs
  outputs/storms.csv                  storm depths and how they were derived
  outputs/storm_summary.csv           per storm: depressions overflowing, area, buildings at risk
  outputs/flagged_depressions.csv     per depression, all storms, both passes
  outputs/sensitivity_grass.csv       grass runoff share 0.25 / 0.50 / 0.75
  data/processed/storms.gpkg          depressions_storms, buildings_at_risk
  data/processed/ponding_<storm>.tif  water depth (m) at the end of each storm, pass 2
  outputs/maps/storm_<storm>.png, outputs/maps/storms_panel.png
Run with:  conda run -n pluvial python scripts/07_storms.py
"""
import re
from collections import deque
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
OUT = ROOT / "outputs"
MAPS = OUT / "maps"
IDF = next((ROOT / "data/raw/rainfall/windsor_a").glob("*WINDSOR_A.txt"))

DURATION_H = 4.0
RETURN_PERIODS = [2, 10, 100]
EVENT_2017_MM = 100.0                       # PLAN: 2017-like event
RUNOFF = {1: 0.95, 2: 0.15, 3: 0.25, 4: 1.0, 5: 0.90}  # roof, tree, grass, water, sealed (PLAN)
GRASS_SENSITIVITY = [0.25, 0.50, 0.75]
BUILDING_DIST_M = 5.0                       # PLAN
RISK_DEPTHS_M = (0.15, 0.30)                # master plan depth bands: at risk / high risk
EPS = 1e-4  # lidar heights are stored to 1 cm; 0.15 m must count as >= 0.15 m despite float32
# WhiteboxTools D8 pointer codes -> (drow, dcol)
D8 = {1: (-1, 1), 2: (0, 1), 4: (1, 1), 8: (1, 0), 16: (1, -1), 32: (0, -1), 64: (-1, -1), 128: (-1, 0)}


def idf_depths():
    """Table 2a of the ECCC IDF file: return-period rainfall amounts (mm)."""
    txt = IDF.read_text(encoding="latin-1")
    block = txt[txt.index("Table 2a"):txt.index("Table 2b")]
    rows = {}
    for line in block.splitlines():
        m = re.match(r"\s*(\d+)\s*(min|h)\s+([\d.\s]+)$", line)
        if m:
            dur_h = float(m.group(1)) / (60 if m.group(2) == "min" else 1)
            vals = [float(v) for v in m.group(3).split()]
            rows[dur_h] = dict(zip([2, 5, 10, 25, 50, 100, 200], vals[:7]))
    return rows


def storms():
    t = idf_depths()
    lo, hi = 2.0, 6.0
    out = []
    for rp in RETURN_PERIODS:
        d_lo, d_hi = t[lo][rp], t[hi][rp]
        b = np.log(d_hi / d_lo) / np.log(hi / lo)        # log-log interpolation
        d = d_lo * (DURATION_H / lo) ** b
        out.append({"storm": f"{rp}yr", "label": f"{rp}-year, {DURATION_H:.0f} h", "depth_mm": round(d, 1),
                    "source": f"IDF {lo:.0f} h {d_lo} mm / {hi:.0f} h {d_hi} mm, log-log to {DURATION_H:.0f} h"})
    out.append({"storm": "2017like", "label": "2017-like, 100 mm", "depth_mm": EVENT_2017_MM,
                "source": "PLAN: 100 mm event (Aug 2017 type)"})
    return pd.DataFrame(out)


def read(path):
    with rasterio.open(path) as r:
        return r.read(1), r.profile


def downstream_map(dep, pntr, catch, dem, ids):
    """For each depression, the depression its overflow reaches (0 = none:
    leaves the grid, reaches the lake, or no depression downstream)."""
    H, W = dep.shape
    objs = ndimage.find_objects(dep)
    down = {}
    for i in ids:
        sl = objs[i - 1]
        sub = dep[sl] == i
        z = np.where(sub, dem[sl], np.inf)
        r0, c0 = np.unravel_index(np.argmin(z), z.shape)
        r, c = r0 + sl[0].start, c0 + sl[1].start
        target, steps = 0, 0
        while steps < 200_000:
            code = pntr[r, c]
            if code not in D8:
                break  # pit/edge: water leaves the model
            dr, dc = D8[code]
            r, c = r + dr, c + dc
            if not (0 <= r < H and 0 <= c < W):
                break
            steps += 1
            if dep[r, c] == i:
                continue  # still crossing its own (filled) surface
            lab = catch[r, c]
            if lab == 0:
                break
            if lab != i:
                target = int(lab)
                break
        down[i] = target
    return down


def cascade(own, vol, down, ids):
    """Pass 2: route overflow downstream in topological order."""
    indeg = {i: 0 for i in ids}
    for i in ids:
        if down[i]:
            indeg[down[i]] += 1
    q = deque(i for i in ids if indeg[i] == 0)
    inflow = {i: own[i] for i in ids}
    done = 0
    while q:
        i = q.popleft()
        done += 1
        j = down[i]
        if j:
            inflow[j] += max(0.0, inflow[i] - vol[i])
            indeg[j] -= 1
            if indeg[j] == 0:
                q.append(j)
    if done != len(ids):
        raise RuntimeError("cycle in depression spill graph")
    return inflow


def ponding_depth(depth_full, dep, ids, stored, cell):
    """Water depth when each depression holds `stored` m3 (<= its volume):
    lower the water level below the spill level until the volume matches."""
    out = np.zeros(depth_full.shape, np.float32)
    objs = ndimage.find_objects(dep)
    for i in ids:
        s_vol = stored[i]
        if s_vol <= 0:
            continue
        sl = objs[i - 1]
        m = dep[sl] == i
        d = depth_full[sl][m]
        dd = np.sort(d)[::-1]
        cum = np.cumsum(dd) * cell
        # volume when the level is lowered by s: sum(max(0, d - s)) * cell
        lo, hi = 0.0, float(dd[0])
        for _ in range(40):
            s = (lo + hi) / 2
            v = np.clip(dd - s, 0, None).sum() * cell
            lo, hi = (s, hi) if v > s_vol else (lo, s)
        w = np.clip(d - (lo + hi) / 2, 0, None)
        blk = out[sl]
        blk[m] = w
    return out


def main():
    MAPS.mkdir(parents=True, exist_ok=True)
    st = storms()
    st.to_csv(OUT / "storms.csv", index=False)
    print(st.to_string(index=False))

    surf, prof = read(PROC / "surfaces.tif")
    catch, _ = read(PROC / "depression_catchments.tif")
    dep, _ = read(PROC / "depressions.tif")
    pntr, _ = read(PROC / "wbt/d8_pointer.tif")
    depth_full, _ = read(PROC / "depth_in_sink.tif")
    dem, _ = read(PROC / "dtm_buildings.tif")
    depth_full = np.where(dep > 0, np.nan_to_num(np.where(depth_full < -1000, 0, depth_full)), 0).astype(np.float32)
    dem = np.where(dem < -1000, np.inf, dem)
    tr, crs = prof["transform"], prof["crs"]
    cell = abs(tr.a * tr.e)
    pntr = pntr.astype(np.int32)

    dgdf = gpd.read_file(PROC / "depressions.gpkg", layer="depressions").to_crs(crs)
    ids = dgdf["dep_id"].astype(int).tolist()
    vol = dict(zip(dgdf.dep_id, dgdf.volume_m3))
    artefact = dict(zip(dgdf.dep_id, dgdf.rail_corridor | dgdf.very_deep))

    print("tracing spill routes ...")
    down = downstream_map(dep, pntr, catch, dem, ids)
    n_down = sum(1 for v in down.values() if v)
    print(f"  {n_down} of {len(ids)} depressions spill into another depression; rest leave the system")

    def run(runoff, depth_mm):
        cgrid = np.zeros(surf.shape, np.float32)
        for k, c in runoff.items():
            cgrid[surf == k] = c
        ca = ndimage.sum(cgrid, catch, ids) * cell
        ca = dict(zip(ids, ca))
        p = depth_mm / 1000.0
        own = {i: p * ca[i] for i in ids}
        inflow2 = cascade(own, vol, down, ids)
        return ca, own, inflow2

    summaries = []
    bld = gpd.read_file(PROC / "buildings_study.gpkg").to_crs(crs)
    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").to_crs(crs).geometry.iloc[0]
    bld_sa = bld[bld.representative_point().within(sa)].reset_index(drop=True)
    dgdf["primary"] = ~dgdf.dep_id.map(artefact) & dgdf.in_study_area
    # Water from artefact depressions (rail ditches, ponds) does not count for buildings.
    # Depressions in the buffer still count: water next to a study-area building matters
    # wherever the depression's centre is.
    use_ids = set(dgdf.loc[~dgdf.dep_id.map(artefact), "dep_id"])
    use_mask = np.isin(dep, list(use_ids))
    import rasterio.features as rf
    bld_r = rf.rasterize(((g, i + 1) for i, g in enumerate(bld_sa.geometry)), out_shape=dep.shape,
                         transform=tr, fill=0, dtype="int32")
    bld_ids = np.arange(1, len(bld_sa) + 1)
    rad = int(round(BUILDING_DIST_M / abs(tr.a)))
    yy, xx = np.ogrid[-rad:rad + 1, -rad:rad + 1]
    disk = (yy ** 2 + xx ** 2) <= rad ** 2

    def near_depth(pond):
        """Max water depth within 5 m of each study-area building footprint."""
        near = ndimage.maximum_filter(np.where(use_mask, pond, 0), footprint=disk)
        return ndimage.maximum(near, bld_r, bld_ids)

    def plan_rule(over_ids):
        m = np.isin(dep, list(over_ids)) & use_mask
        near = ndimage.binary_dilation(m, structure=disk)
        return ndimage.maximum(near, bld_r, bld_ids) > 0

    ponding = {}
    p_out = dict(prof, dtype="float32", nodata=-9999.0, compress="deflate", tiled=True,
                 blockxsize=512, blockysize=512)
    p_out.pop("predictor", None)
    for _, s in st.iterrows():
        ca, own, inflow2 = run(RUNOFF, s.depth_mm)
        key = s.storm
        dgdf["ca_m2"] = dgdf.dep_id.map(ca).round(1)
        dgdf[f"in1_{key}"] = dgdf.dep_id.map(own).round(1)
        dgdf[f"in2_{key}"] = dgdf.dep_id.map(inflow2).round(1)
        dgdf[f"over1_{key}"] = dgdf[f"in1_{key}"] > dgdf.volume_m3
        dgdf[f"over2_{key}"] = dgdf[f"in2_{key}"] > dgdf.volume_m3
        dgdf[f"fill2_{key}"] = (dgdf[f"in2_{key}"] / dgdf.volume_m3).clip(upper=1).round(3)
        stored = {i: min(inflow2[i], vol[i]) for i in ids}
        pond = ponding_depth(depth_full, dep, ids, stored, cell)
        ponding[key] = pond
        with rasterio.open(PROC / f"ponding_{key}.tif", "w", **p_out) as dst:
            dst.write(pond, 1)
        dmax = ndimage.maximum(pond, dep, ids)
        dgdf[f"wdepth2_{key}"] = dgdf.dep_id.map(dict(zip(ids, np.round(dmax, 3))))

        nd = near_depth(pond)
        bld_sa[f"near_depth_{key}"] = nd  # full precision; rounded only when written
        bld_sa[f"plan_rule_{key}"] = plan_rule(set(dgdf.loc[dgdf[f"over2_{key}"], "dep_id"]))
        prim = dgdf[dgdf.primary]
        wet = (pond > 0.01) & np.isin(dep, prim.dep_id.to_numpy())
        summaries.append({
            "storm": key, "label": s.label, "depth_mm": s.depth_mm,
            "depressions_primary": len(prim),
            "overflow_pass1": int(prim[f"over1_{key}"].sum()),
            "overflow_pass2": int(prim[f"over2_{key}"].sum()),
            "ponds_ge_0.15m": int((prim[f"wdepth2_{key}"] >= RISK_DEPTHS_M[0] - EPS).sum()),
            "ponds_ge_0.30m": int((prim[f"wdepth2_{key}"] >= RISK_DEPTHS_M[1] - EPS).sum()),
            "water_area_ha": round(float(wet.sum() * cell / 1e4), 2),
            "water_area_ge_0.15m_ha": round(float((wet & (pond >= RISK_DEPTHS_M[0] - EPS)).sum() * cell / 1e4), 2),
            "water_volume_m3": round(float(sum(stored[i] for i in prim.dep_id)), 0),
            "bld_at_risk_0.15m": int((nd >= RISK_DEPTHS_M[0] - EPS).sum()),
            "bld_high_risk_0.30m": int((nd >= RISK_DEPTHS_M[1] - EPS).sum()),
            "bld_plan_rule": int(bld_sa[f"plan_rule_{key}"].sum()),
            "buildings_in_study_area": len(bld_sa),
            "artefact_flagged_overflowing": int(dgdf[dgdf.in_study_area & ~dgdf.primary][f"over2_{key}"].sum()),
        })

    # critical rain, pass 1 (own catchment only), and smallest overflowing storm (pass 2)
    dgdf["critical_rain_mm"] = (1000 * dgdf.volume_m3 / dgdf.ca_m2.where(dgdf.ca_m2 > 0)).round(1)
    order = list(st.storm)
    def smallest(r):
        for k in order:
            if r[f"over2_{k}"]:
                return k
        return "none"
    dgdf["smallest_storm_overflow"] = dgdf.apply(smallest, axis=1)
    dgdf["downstream_dep_id"] = dgdf.dep_id.map(down)

    summ = pd.DataFrame(summaries)
    summ.to_csv(OUT / "storm_summary.csv", index=False)
    print(summ.to_string(index=False))

    # sensitivity: grass runoff share (0.25 is the PLAN value, already computed above)
    sens = []
    prim_ids = set(dgdf.loc[dgdf.primary, "dep_id"])
    for g in GRASS_SENSITIVITY:
        rc = {**RUNOFF, 3: g}
        for _, s in st.iterrows():
            if g == RUNOFF[3]:
                nd = bld_sa[f"near_depth_{s.storm}"].to_numpy()
                o2 = set(dgdf.loc[dgdf[f"over2_{s.storm}"], "dep_id"])
            else:
                ca, own, inflow2 = run(rc, s.depth_mm)
                o2 = {i for i in ids if inflow2[i] > vol[i]}
                stored = {i: min(inflow2[i], vol[i]) for i in ids}
                nd = near_depth(ponding_depth(depth_full, dep, ids, stored, cell))
            sens.append({"grass_runoff": g, "storm": s.storm, "overflow_pass2": len(o2 & prim_ids),
                         "bld_at_risk_0.15m": int((nd >= RISK_DEPTHS_M[0] - EPS).sum()),
                         "bld_high_risk_0.30m": int((nd >= RISK_DEPTHS_M[1] - EPS).sum())})
    sens = pd.DataFrame(sens)
    sens.to_csv(OUT / "sensitivity_grass.csv", index=False)
    print("buildings at risk (>= 0.15 m) by grass runoff share:")
    print(sens.pivot(index="storm", columns="grass_runoff", values="bld_at_risk_0.15m").reindex(order).to_string())
    print("buildings at high risk (>= 0.30 m):")
    print(sens.pivot(index="storm", columns="grass_runoff", values="bld_high_risk_0.30m").reindex(order).to_string())

    # vectors
    out_g = PROC / "storms.gpkg"
    if out_g.exists():
        out_g.unlink()
    dgdf.to_file(out_g, layer="depressions_storms")
    def smallest_bld(r, t):
        for k in order:
            if r[f"near_depth_{k}"] >= t - EPS:
                return k
        return "none"
    bld_sa["smallest_storm_at_risk"] = bld_sa.apply(smallest_bld, axis=1, t=RISK_DEPTHS_M[0])
    bld_sa["smallest_storm_high_risk"] = bld_sa.apply(smallest_bld, axis=1, t=RISK_DEPTHS_M[1])
    risk_b = bld_sa[bld_sa.smallest_storm_at_risk != "none"].copy()
    risk_b.to_file(out_g, layer="buildings_at_risk")
    bld_sa.drop(columns="geometry").round(3).to_csv(OUT / "buildings_storms.csv", index=False)
    cols = ["dep_id", "in_study_area", "primary", "rail_corridor", "very_deep", "area_m2", "max_depth_m",
            "volume_m3", "catchment_m2", "ca_m2", "critical_rain_mm", "downstream_dep_id", "smallest_storm_overflow"] + \
           [c for c in dgdf.columns if re.match(r"(in1|in2|over1|over2|fill2|wdepth2)_", c)]
    dgdf[cols].to_csv(OUT / "flagged_depressions.csv", index=False)
    print("wrote outputs/flagged_depressions.csv, storm_summary.csv, sensitivity_grass.csv; data/processed/storms.gpkg")

    make_maps(st, ponding, dgdf, risk_b, prof, sa)


def dgdf_mask(prim, dep):
    return np.isin(dep, prim.dep_id.to_numpy())


def make_maps(st, ponding, dgdf, risk_b, prof, sa):
    with rasterio.open(PROC / "dtm.tif") as r:
        z = r.read(1, masked=True).filled(np.nan)
    tr = prof["transform"]
    H, W = z.shape
    step = 2
    zs = z[::step, ::step]
    gy, gx = np.gradient(np.where(np.isnan(zs), np.nanmedian(zs), zs), abs(tr.a) * step)
    sl = np.arctan(3 * np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    hs = np.clip(np.sin(np.radians(45)) * np.cos(sl) + np.cos(np.radians(45)) * np.sin(sl) * np.cos(np.radians(135) - asp), 0, 1)
    hs[np.isnan(zs)] = np.nan
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    cmap = ListedColormap(["#9ecae1", "#4292c6", "#08306b"])
    norm = BoundaryNorm([0.01, 0.15, 0.30, 10], cmap.N)
    sa_g = gpd.GeoSeries([sa], crs=prof["crs"])
    summ = pd.read_csv(OUT / "storm_summary.csv").set_index("storm")

    def panel(ax, key, label, small):
        ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1, alpha=0.85)
        w = ponding[key][::step, ::step]
        ax.imshow(np.where(w > 0.01, w, np.nan), cmap=cmap, norm=norm, extent=ext, interpolation="nearest")
        at = risk_b[risk_b[f"near_depth_{key}"] >= RISK_DEPTHS_M[0] - EPS]
        hi = at[at[f"near_depth_{key}"] >= RISK_DEPTHS_M[1] - EPS]
        if len(at):
            at.plot(ax=ax, color="#fdae61", edgecolor="#e66101", lw=0.2)
        if len(hi):
            hi.plot(ax=ax, color="#d7191c", edgecolor="#7f0000", lw=0.2)
        sa_g.boundary.plot(ax=ax, color="magenta", lw=1.0)
        s = summ.loc[key]
        ax.set_title(f"{label}: {s.depth_mm:.1f} mm\nbuildings: {int(s['bld_at_risk_0.15m'])} at risk "
                     f"(≥ 0.15 m), {int(s['bld_high_risk_0.30m'])} high (≥ 0.30 m)", fontsize=8 if small else 10)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        ax.set_xticks([]); ax.set_yticks([])

    for _, s in st.iterrows():
        fig, ax = plt.subplots(figsize=(9, 12))
        panel(ax, s.storm, s.label, False)
        handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ["#9ecae1", "#4292c6", "#08306b"]] + \
                  [plt.Rectangle((0, 0), 1, 1, fc="#fdae61", ec="#e66101"),
                   plt.Rectangle((0, 0), 1, 1, fc="#d7191c", ec="#7f0000")]
        ax.legend(handles, ["water < 0.15 m", "0.15–0.30 m", "> 0.30 m",
                            "building: water ≥ 0.15 m within 5 m", "building: water ≥ 0.30 m within 5 m"],
                  loc="lower left", fontsize=8)
        fig.text(0.5, 0.06, "Storm sewers assumed full; overflow passed downstream (pass 2); "
                 "rail-ditch and pond depressions excluded", ha="center", fontsize=8)
        fig.savefig(MAPS / f"storm_{s.storm}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)
    fig, axes = plt.subplots(1, 4, figsize=(18, 7.5))
    for ax, (_, s) in zip(axes, st.iterrows()):
        panel(ax, s.storm, s.label, True)
    fig.suptitle("Ponding at the end of each storm (sewers full, spill-over on); buildings with water "
                 "≥ 0.15 m (orange) or ≥ 0.30 m (red) within 5 m", fontsize=10)
    fig.savefig(MAPS / "storms_panel.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/maps/storm_*.png and storms_panel.png")


if __name__ == "__main__":
    main()
