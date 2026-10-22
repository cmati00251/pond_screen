"""Step 5: classify surfaces by rules (no model training).

Classes (priority order; first rule that applies wins)
  4 water   lake mask (hydro-flattened DTM, Step 6) or OSM water polygon
  1 roof    inside a building footprint, or an unmapped flat structure:
            nDSM > TREE_H_M with low DSM roughness (see UNMAPPED_*)
  2 tree    nDSM > TREE_H_M (height, not greenness: imagery is leaf-off)
  3 grass   NDVI > threshold picked at the valley of the ground-cell histogram
  5 sealed  everything else

Outputs
  data/processed/surfaces.tif            uint8 class codes, 0 = nodata
  data/processed/pct_sealed_50m.tif      % roof + sealed per 50 m cell
  outputs/surface_areas.csv, outputs/maps/surfaces.png, outputs/maps/pct_sealed_50m.png
  outputs/qa/sample_points.csv           200 random points with labels
  outputs/qa/sheets/sheet_NN.png         contact sheets of all 200 chips (for review)
  outputs/qa/chip_###_<class>.png        30 chips for the user (6 per class where possible)
Run with:  conda run -n pluvial python scripts/05_surfaces.py
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
from osgeo import gdal
from rasterio.windows import from_bounds
from scipy import ndimage

gdal.UseExceptions()
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
MAPS = ROOT / "outputs/maps"
QA = ROOT / "outputs/qa"

CLASSES = {1: "roof", 2: "tree", 3: "grass", 4: "water", 5: "sealed"}
COLOURS = {1: "#c0392b", 2: "#1e6b30", 3: "#8fd16a", 4: "#2f7fd0", 5: "#9a9a9a"}
TREE_H_M = 2.0            # PLAN
EAVE_M = 0.75             # elevated cells within this distance outside a footprint = roof
UNMAPPED_MIN_M2 = 30.0    # flat elevated patch at least this big ...
UNMAPPED_ROUGH_M = 0.15   # ... with 3x3 DSM std below this = unmapped building
NDVI_SEARCH = (-0.10, 0.30)
CELL_50M = 50.0
N_SAMPLES = 200           # PLAN
N_USER_CHIPS = 30         # PLAN
CHIP_M = 20.0             # PLAN
SEED = 20261020


def read(path, band=1):
    with rasterio.open(path) as r:
        a = r.read(band).astype(np.float32)
        if r.nodata is not None:
            a[a == r.nodata] = np.nan
        return a, r.profile


def ndvi_threshold(v):
    """Valley between the pavement peak and the lawn peak of a smoothed histogram."""
    h, e = np.histogram(v, bins=260, range=(-0.5, 0.8))
    c = (e[:-1] + e[1:]) / 2
    hs = ndimage.gaussian_filter1d(h.astype(float), 2)
    lo = (c > NDVI_SEARCH[0]) & (c < 0.03)
    hi = (c > 0.05) & (c < NDVI_SEARCH[1])
    p1 = c[lo][np.argmax(hs[lo])]
    p2 = c[hi][np.argmax(hs[hi])]
    between = (c > p1) & (c < p2)
    t = c[between][np.argmin(hs[between])]
    return float(t), float(p1), float(p2), c, hs


def main():
    for d in (MAPS, QA, QA / "sheets"):
        d.mkdir(parents=True, exist_ok=True)
    for old in QA.glob("chip_*.png"):
        old.unlink()

    dtm, prof = read(PROC / "dtm.tif")
    dsm, _ = read(PROC / "dsm.tif")
    ndvi, _ = read(PROC / "ndvi.tif")
    lake, _ = read(PROC / "lake_mask.tif")
    tr, crs = prof["transform"], prof["crs"]
    H, W = dtm.shape
    cell = abs(tr.a * tr.e)
    valid = ~np.isnan(dtm)

    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").to_crs(crs)
    in_sa = rasterio.features.geometry_mask(sa.geometry, (H, W), tr, invert=True)
    bld = gpd.read_file(PROC / "buildings_study.gpkg").to_crs(crs)
    roof_fp = rasterio.features.geometry_mask(bld.geometry, (H, W), tr, invert=True)
    water_osm = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="water").to_crs(crs)
    water_osm = water_osm[water_osm.geom_type.isin(["Polygon", "MultiPolygon"])]
    water_osm = water_osm[water_osm.intersects(sa.buffer(200).iloc[0])]
    w_osm = (rasterio.features.geometry_mask(water_osm.geometry, (H, W), tr, invert=True)
             if len(water_osm) else np.zeros((H, W), bool))

    ndsm = dsm - dtm
    tall = np.nan_to_num(ndsm) > TREE_H_M
    # unmapped buildings: tall, smooth (planar) DSM patches outside footprints
    d0 = np.nan_to_num(dsm)
    m1 = ndimage.uniform_filter(d0, 3)
    m2 = ndimage.uniform_filter(d0 * d0, 3)
    rough = np.sqrt(np.clip(m2 - m1 * m1, 0, None))
    flat_tall = tall & (rough < UNMAPPED_ROUGH_M) & ~roof_fp
    flat_tall = ndimage.binary_opening(flat_tall, iterations=1)
    lab, n = ndimage.label(flat_tall)
    sizes = ndimage.sum(flat_tall, lab, range(1, n + 1)) * cell
    unmapped = np.isin(lab, 1 + np.flatnonzero(sizes >= UNMAPPED_MIN_M2))

    # roof eaves: footprints are traced at the walls, so elevated cells in a
    # narrow ring outside them are roof overhang, not tree (QA review v1)
    ring = rasterio.features.geometry_mask(bld.buffer(EAVE_M).geometry, (H, W), tr, invert=True) & ~roof_fp
    eaves = ring & tall

    water = ((lake == 1) | w_osm) & valid
    roof = (roof_fp | unmapped | eaves) & valid & ~water
    tree = tall & valid & ~water & ~roof
    ground = valid & ~water & ~roof & ~tree & ~np.isnan(ndvi)
    t, p1, p2, c, hs = ndvi_threshold(ndvi[ground & in_sa])
    print(f"NDVI threshold {t:.3f} (pavement peak {p1:.3f}, lawn peak {p2:.3f})")
    grass = ground & (ndvi > t)

    cls = np.zeros((H, W), np.uint8)
    cls[valid] = 5
    cls[grass] = 3
    cls[tree] = 2
    cls[roof] = 1
    cls[water] = 4
    no_img = valid & np.isnan(ndvi) & (cls == 5)
    print(f"cells without imagery left as sealed: {no_img.sum() * cell:.0f} m2 "
          f"({no_img[in_sa].sum() * cell:.0f} m2 in study area)")
    print(f"unmapped flat structures added to roof: {unmapped.sum() * cell:.0f} m2 "
          f"({(unmapped & in_sa).sum() * cell:.0f} m2 in study area)")
    print(f"roof eaves added (elevated, <= {EAVE_M} m outside footprints): "
          f"{(eaves & valid).sum() * cell / 1e4:.2f} ha ({(eaves & in_sa).sum() * cell / 1e4:.2f} ha in study area)")

    p = dict(prof, dtype="uint8", nodata=0, count=1, compress="deflate", tiled=True,
             blockxsize=512, blockysize=512)
    p.pop("predictor", None)
    with rasterio.open(PROC / "surfaces.tif", "w", **p) as dst:
        dst.write(cls, 1)
        dst.write_colormap(1, {k: tuple(int(COLOURS[k][i:i + 2], 16) for i in (1, 3, 5)) + (255,)
                               for k in CLASSES})
        dst.update_tags(classes=str(CLASSES), ndvi_threshold=f"{t:.3f}")
    print("wrote data/processed/surfaces.tif")

    # areas
    rows = []
    for k, name in CLASSES.items():
        a_sa = (cls[in_sa] == k).sum() * cell
        a_buf = (cls == k).sum() * cell
        rows.append({"code": k, "class": name, "study_area_ha": round(a_sa / 1e4, 2),
                     "study_area_pct": round(100 * a_sa / (in_sa.sum() * cell), 1),
                     "buffer_ha": round(a_buf / 1e4, 2)})
    areas = pd.DataFrame(rows)
    areas.to_csv(ROOT / "outputs/surface_areas.csv", index=False)
    print(areas.to_string(index=False))
    imp = areas.loc[areas["class"].isin(["roof", "sealed"]), "study_area_pct"].sum()
    print(f"impervious (roof + sealed) in study area: {imp:.1f}%")

    # % sealed per 50 m cell (roof + sealed ground), over valid cells
    f = int(round(CELL_50M / abs(tr.a)))
    Hc, Wc = H // f + (H % f > 0), W // f + (W % f > 0)
    pad = lambda a: np.pad(a, ((0, Hc * f - H), (0, Wc * f - W)))
    imp_m = pad(((cls == 1) | (cls == 5)).astype(np.float32))
    val_m = pad((cls > 0).astype(np.float32))
    s_imp = imp_m.reshape(Hc, f, Wc, f).sum(axis=(1, 3))
    s_val = val_m.reshape(Hc, f, Wc, f).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(s_val >= 0.25 * f * f, 100 * s_imp / s_val, np.nan).astype(np.float32)
    tr50 = rasterio.Affine(CELL_50M, 0, tr.c, 0, -CELL_50M, tr.f)
    p50 = dict(p, dtype="float32", nodata=-9999.0, width=Wc, height=Hc, transform=tr50,
               blockxsize=16, blockysize=16, tiled=False)
    with rasterio.open(PROC / "pct_sealed_50m.tif", "w", **p50) as dst:
        dst.write(np.where(np.isnan(pct), -9999.0, pct), 1)
    print("wrote data/processed/pct_sealed_50m.tif")

    # maps
    step = 2
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    cmap = ListedColormap(["#ffffff00"] + [COLOURS[k] for k in CLASSES])
    fig, ax = plt.subplots(figsize=(9, 12))
    ax.imshow(cls[::step, ::step], cmap=cmap, vmin=-0.5, vmax=5.5, extent=ext, interpolation="nearest")
    sa.boundary.plot(ax=ax, color="k", lw=1.2)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOURS[k]) for k in CLASSES]
    ax.legend(handles, [f"{CLASSES[k]} ({areas.loc[areas.code == k, 'study_area_pct'].iloc[0]}%)"
                        for k in CLASSES], loc="lower left", fontsize=8, title="study area share")
    ax.set_title(f"Step 5 surfaces (rules; NDVI threshold {t:.3f}; trees nDSM > {TREE_H_M:.0f} m)\n"
                 f"black = study area; impervious (roof + sealed) {imp:.1f}%", fontsize=10)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.tick_params(labelsize=7)
    fig.savefig(MAPS / "surfaces.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    ext50 = (tr.c, tr.c + Wc * CELL_50M, tr.f - Hc * CELL_50M, tr.f)
    fig, ax = plt.subplots(figsize=(9, 12))
    im = ax.imshow(pct, cmap="magma_r", vmin=0, vmax=100, extent=ext50, interpolation="nearest")
    sa.boundary.plot(ax=ax, color="cyan", lw=1.4)
    fig.colorbar(im, ax=ax, shrink=0.45, pad=0.01).set_label("% sealed (roof + sealed ground)")
    ax.set_title("Percent sealed per 50 m cell", fontsize=10)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.tick_params(labelsize=7)
    fig.savefig(MAPS / "pct_sealed_50m.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(c, hs, color="#4a7a3a")
    for x, s in [(p1, "pavement peak"), (p2, "lawn peak"), (t, "threshold")]:
        ax.axvline(x, ls="--" if s != "threshold" else "-", color="k", lw=0.8)
        ax.text(x, hs.max() * 0.95, f" {s}\n {x:.3f}", fontsize=7, va="top")
    ax.set_xlabel("NDVI"); ax.set_ylabel("cells (smoothed)")
    ax.set_title("NDVI of ground cells (not roof, tree, water), study area", fontsize=9)
    fig.savefig(MAPS / "ndvi_threshold.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote maps: surfaces.png, pct_sealed_50m.png, ndvi_threshold.png")

    # ---- accuracy sample: 200 random points in the study area
    rng = np.random.default_rng(SEED)
    rr, cc = np.nonzero(in_sa & (cls > 0))
    pick = rng.choice(len(rr), N_SAMPLES, replace=False)
    pts = pd.DataFrame({"id": np.arange(1, N_SAMPLES + 1), "row": rr[pick], "col": cc[pick]})
    pts["x"] = tr.c + (pts["col"] + 0.5) * tr.a
    pts["y"] = tr.f + (pts["row"] + 0.5) * tr.e
    pts["label"] = [CLASSES[cls[r, c_]] for r, c_ in zip(pts.row, pts.col)]
    pts["ndsm_m"] = [round(float(ndsm[r, c_]), 2) for r, c_ in zip(pts.row, pts.col)]
    pts["ndvi"] = [round(float(ndvi[r, c_]), 3) for r, c_ in zip(pts.row, pts.col)]
    pts["in_footprint"] = [bool(roof_fp[r, c_]) for r, c_ in zip(pts.row, pts.col)]

    tiles = sorted(str(q) for q in (ROOT / "data/raw/imagery").glob("*.tif"))
    vrt_path = str(QA / "swoop.vrt")
    gdal.BuildVRT(vrt_path, tiles)
    chips = {}
    with rasterio.open(vrt_path) as src:
        for _, r in pts.iterrows():
            h = CHIP_M / 2
            win = from_bounds(r.x - h, r.y - h, r.x + h, r.y + h, src.transform)
            a = src.read([1, 2, 3], window=win, boundless=True, fill_value=0)
            chips[r.id] = np.moveaxis(a, 0, -1)

    sindex = bld.sindex

    def draw(ax, rid, lab, small=True):
        a = chips[rid].astype(np.float32)
        lo, hi = np.percentile(a, [1, 99])
        ax.imshow(np.clip((a - lo) / max(hi - lo, 1), 0, 1), extent=(-CHIP_M / 2, CHIP_M / 2, -CHIP_M / 2, CHIP_M / 2))
        # building footprints (yellow): separates a missed roof from building lean in the ortho
        r = pts.loc[pts.id == rid].iloc[0]
        h = CHIP_M / 2
        for i in sindex.intersection((r.x - h, r.y - h, r.x + h, r.y + h)):
            g = bld.geometry.iloc[i]
            for part in getattr(g, "geoms", [g]):
                xy = np.asarray(part.exterior.coords)
                ax.plot(xy[:, 0] - r.x, xy[:, 1] - r.y, "-", color="yellow", lw=0.6 if small else 1.0)
        ax.set_xlim(-h, h); ax.set_ylim(-h, h)
        ax.add_patch(plt.Circle((0, 0), 0.6, fill=False, color="red", lw=1.2 if small else 2))
        ax.plot([-2.5, -1], [0, 0], "r-", [1, 2.5], [0, 0], "r-", [0, 0], [-2.5, -1], "r-", [0, 0], [1, 2.5], "r-",
                lw=0.8 if small else 1.5)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"#{rid} {lab}", fontsize=8 if small else 12,
                     color=COLOURS[[k for k, v in CLASSES.items() if v == lab][0]])

    per = 25
    for s in range(0, N_SAMPLES, per):
        sub = pts.iloc[s:s + per]
        fig, axes = plt.subplots(5, 5, figsize=(10, 10.6))
        for ax, (_, r) in zip(axes.flat, sub.iterrows()):
            draw(ax, r.id, r.label)
            ax.text(0.02, 0.02, f"h {r.ndsm_m:.1f}  v {r.ndvi:.2f}", transform=ax.transAxes,
                    fontsize=6, color="w", bbox=dict(fc="k", alpha=0.5, pad=1))
        fig.suptitle(f"QA chips {s + 1}-{s + len(sub)}: 20 m SWOOP 2025 (16 cm), red circle = sample point, "
                     f"yellow = building footprint; h = nDSM m, v = NDVI", fontsize=9)
        fig.tight_layout()
        fig.savefig(QA / "sheets" / f"sheet_{s // per + 1:02d}.png", dpi=110)
        plt.close(fig)

    # 30 chips for the user: up to 6 per class, rest filled at random
    chosen = []
    for k, name in CLASSES.items():
        ids = pts.loc[pts.label == name, "id"].tolist()
        chosen += ids[:6]
    rest = [i for i in pts.id if i not in chosen]
    chosen += rest[: N_USER_CHIPS - len(chosen)]
    for rid in chosen[:N_USER_CHIPS]:
        r = pts.loc[pts.id == rid].iloc[0]
        fig, ax = plt.subplots(figsize=(4.2, 4.5))
        draw(ax, rid, r.label, small=False)
        ax.set_xlabel(f"E{r.x:.1f} N{r.y:.1f} | height {r.ndsm_m:.1f} m | NDVI {r.ndvi:.2f}", fontsize=8)
        fig.savefig(QA / f"chip_{rid:03d}_{r.label}.png", dpi=110, bbox_inches="tight")
        plt.close(fig)
    pts["user_chip"] = pts.id.isin(chosen[:N_USER_CHIPS])
    pts.drop(columns=["row", "col"]).to_csv(QA / "sample_points.csv", index=False)
    Path(vrt_path).unlink()
    print("sample labels:", pts.label.value_counts().to_dict())
    print(f"wrote outputs/qa/: {N_SAMPLES // per} sheets, {min(len(chosen), N_USER_CHIPS)} chips, sample_points.csv")


if __name__ == "__main__":
    main()
