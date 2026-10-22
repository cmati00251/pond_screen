"""Step 8a: georeference master plan Figures 8.2 and 8.3 and digitise them.

Figure 8.2 (TMR PDF p84) shows, for existing conditions and the 1:100-year
4-hour storm, the modelled surface ponding as coloured hexagons in three depth
bands, plus the regional (W-1, W-2) and isolated surface flooding problem
areas as red outlines. The map has no grid or coordinates.

Georeferencing (north-up similarity transform: scale, rotation, offset)
  1. Initial transform by hand: OSM roads were overlaid on the figure and
     aligned on Dillon Dr at Lesperance Rd, Tecumseh Rd and Manning Rd
     (INITIAL below). Automatic image matching against the SWOOP 2025 photo
     (SIFT; edge correlation) was tried and failed: the figure's background
     photo is faded, older and largely covered by the overlay.
  2. Refinement: grid search around the initial transform maximising the share
     of OSM street centrelines that fall on the figure's ponding hexagons
     (the master plan's 2D model ponds water on the roadways).
Digitising
  - Ponding depth bands by nearest legend colour (legend swatch fills read
    from the PDF vector graphics).
  - Red outlines (problem areas) filled into polygons; large ones = regional
    (W-1, W-2), small closed rings = isolated problem areas.

Outputs
  data/processed/benchmark_<fig>.tif          figure image, georeferenced (fig82, fig83)
  data/processed/benchmark_ponding_<fig>.tif  0 none, 1 <0.15 m, 2 0.15-0.30 m, 3 >0.30 m (1:100 yr)
  data/processed/benchmark.gpkg               layers problem_areas_<fig>
  outputs/benchmark/<fig>_georef.json, outputs/benchmark/<fig>_georef_check.png
Run with:  conda run -n pluvial python scripts/08a_georef_benchmark.py
"""
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf
import rasterio
import rasterio.features
from affine import Affine
from scipy import ndimage
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/benchmark/storm-drainage-master-plan-technical-modelling-report-final.pdf"
OUTB = ROOT / "outputs/benchmark"
PROC = ROOT / "data/processed"
# Figures to georeference. INITIAL = hand alignment, E = E0 + col*s, N = N0 - row*s (north-up).
# SEARCH = refinement stages (scale step, offset step m, rotation step deg).
FIGURES = {
    "fig82": dict(page=84, title="TMR Figure 8.2 (problem areas W-1, W-2)",
                  # Dillon Dr at Lesperance Rd, Tecumseh Rd and Manning Rd lined up by eye on OSM overlays
                  initial=dict(s=1.675, E0=343299.0, N0=4688477.0, rot=0.0),
                  search=[(0.02, 40.0, 1.0), (0.006, 12.0, 0.3), (0.002, 4.0, 0.1)]),
    "fig83": dict(page=85, title="TMR Figure 8.3 (problem area W-3)",
                  # same map series/scale; Manning Rd on the right study boundary, Tecumseh Rd at the top
                  initial=dict(s=1.70, E0=342906.0, N0=4686164.0, rot=0.0),
                  search=[(0.10, 200.0, 2.0), (0.02, 40.0, 0.5), (0.006, 12.0, 0.2), (0.002, 4.0, 0.1)]),
}
# legend swatch fill colours read from the PDF page (0-1 RGB) -> 0-255
LEGEND = {1: (0.00, 0.89, 0.96), 2: (0.00, 0.65, 0.84), 3: (0.01, 0.15, 0.83)}
COLOUR_TOL = 60       # max RGB distance to a legend colour
RED = (232, 54, 53)   # outline colour (median sampled along the W-1 outline)
RED_TOL = 90
REGIONAL_MIN_PX = 20000
GAP_MAX_PX = 80       # outline gaps bridged up to this length (labels/hexagons drawn over lines)


def figure_image(page_no):
    doc = pymupdf.open(PDF)
    page = doc[page_no - 1]
    xref = max(page.get_images(full=True), key=lambda im: im[2] * im[3])[0]
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)


def transform(p):
    """figure px (col, row) -> EPSG:2958, similarity about the figure centre."""
    c, s = np.cos(np.radians(p["rot"])), np.sin(np.radians(p["rot"]))
    return Affine(p["s"] * c, p["s"] * s, p["E0"], p["s"] * s, -p["s"] * c, p["N0"])


def road_points(step=2.0):
    roads = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="roads")
    roads = roads[roads.highway.isin(["primary", "secondary", "tertiary", "residential", "unclassified"])]
    pts = []
    for g in roads.geometry:
        for part in getattr(g, "geoms", [g]):
            n = max(2, int(part.length / step))
            pts.append(np.array([part.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, n)]))
    return np.vstack(pts)


def process(key, cfg):
    INITIAL = cfg["initial"]
    print(f"\n=== {key}: {cfg['title']} ===")
    fig = figure_image(cfg["page"])
    H, W = fig.shape[:2]

    # --- digitise ponding classes (nearest legend colour)
    leg = np.array([np.array(LEGEND[k]) * 255 for k in (1, 2, 3)])
    d = np.linalg.norm(fig[:, :, None, :] - leg[None, None, :, :], axis=3)
    cls = np.argmin(d, axis=2) + 1
    cls[d.min(axis=2) > COLOUR_TOL] = 0
    cls = cls.astype(np.uint8)
    hexmask = ndimage.binary_dilation(cls > 0, iterations=1)
    print(f"ponding pixels by class: { {k: int((cls == k).sum()) for k in (1, 2, 3)} }")

    # --- refine transform: share of OSM street points that land on hexagons
    P = road_points()

    def score(p):
        inv = ~transform(p)
        cr = np.array(inv * (P[:, 0], P[:, 1]))
        c, r = np.round(cr).astype(int)
        ok = (c >= 0) & (c < W) & (r >= 0) & (r < H)
        return hexmask[r[ok], c[ok]].mean() if ok.sum() > 1000 else 0.0

    best = dict(INITIAL)
    s0 = score(best)
    print(f"initial score {s0:.4f}")
    n = 9
    for stage, (ds, dE, drot) in enumerate(cfg["search"]):
        base = dict(best)
        for sv in np.linspace(base["s"] - ds, base["s"] + ds, 5):
            for rv in np.linspace(base["rot"] - drot, base["rot"] + drot, 5):
                for Ev in np.linspace(base["E0"] - dE, base["E0"] + dE, n):
                    for Nv in np.linspace(base["N0"] - dE, base["N0"] + dE, n):
                        p = dict(s=sv, E0=Ev, N0=Nv, rot=rv)
                        v = score(p)
                        if v > s0:
                            s0, best = v, p
        print(f"stage {stage + 1}: score {s0:.4f}  s={best['s']:.4f} rot={best['rot']:.2f} "
              f"E0={best['E0']:.1f} N0={best['N0']:.1f}")
    T = transform(best)
    shift = np.hypot(*(np.array(T * (W / 2, H / 2)) - np.array(transform(INITIAL) * (W / 2, H / 2))))
    print(f"refinement moved the figure centre by {shift:.1f} m")

    # --- write georeferenced rasters
    prof = dict(driver="GTiff", width=W, height=H, crs="EPSG:2958", transform=T, compress="deflate")
    with rasterio.open(PROC / f"benchmark_{key}.tif", "w", count=3, dtype="uint8", photometric="RGB", **prof) as dst:
        dst.write(np.moveaxis(fig.astype(np.uint8), -1, 0))
    with rasterio.open(PROC / f"benchmark_ponding_{key}.tif", "w", count=1, dtype="uint8", nodata=255, **prof) as dst:
        dst.write(cls, 1)

    # --- problem area outlines. Labels and hexagons drawn over the red lines leave
    # small gaps, so each outline is closed on its own, only as much as needed.
    red = np.linalg.norm(fig - np.array(RED), axis=2) < RED_TOL
    red = ndimage.binary_closing(red, iterations=2)
    lab, n = ndimage.label(red, structure=np.ones((3, 3)))
    sizes = ndimage.sum(red, lab, range(1, n + 1))
    open_parts, closed_parts = [], []
    for i in range(1, n + 1):
        if sizes[i - 1] < 150:
            continue  # specks
        comp = lab == i
        filled = ndimage.binary_fill_holes(comp)
        interior = (filled & ~comp).sum()
        if interior > 0.2 * filled.sum():
            closed_parts.append(filled)              # complete ring
        elif interior == 0 and comp.sum() > 0.5 * np.prod([s.stop - s.start for s in ndimage.find_objects(comp.astype(int))[0]]):
            continue                                  # solid red box (the "W-1"/"W-2" labels)
        else:
            open_parts.append(comp)                   # piece of an outline broken by overlying labels/hexagons
    # Bridge the gaps: join the nearest pixels of open pieces lying within GAP_MAX_PX of each other.
    from scipy.spatial import cKDTree
    bridged = np.zeros((H, W), bool)
    coords = [np.argwhere(p) for p in open_parts]
    for p in open_parts:
        bridged |= p
    n_bridges = 0
    for a in range(len(coords)):
        ta = cKDTree(coords[a])
        for b in range(len(coords)):
            if b == a:
                continue
            d, j = ta.query(coords[b], k=1)
            near = d <= GAP_MAX_PX
            if not near.any():
                continue
            # one bridge per separate gap: cluster the near pixels of piece b
            m = np.zeros((H, W), bool)
            m[coords[b][near, 0], coords[b][near, 1]] = True
            cl, ncl = ndimage.label(ndimage.binary_dilation(m, iterations=3))
            cid = cl[coords[b][near, 0], coords[b][near, 1]]
            idx_near = np.flatnonzero(near)
            for c in range(1, ncl + 1):
                sel = idx_near[cid == c]
                k = sel[np.argmin(d[sel])]
                (r0, c0), (r1, c1) = coords[a][j[k]], coords[b][k]
                t = np.linspace(0, 1, int(d[k]) * 2 + 2)
                bridged[np.round(r0 + t * (r1 - r0)).astype(int), np.round(c0 + t * (c1 - c0)).astype(int)] = True
                n_bridges += 1
    bridged = ndimage.binary_dilation(bridged, iterations=2)
    filled = ndimage.binary_fill_holes(bridged)
    lab2, n2 = ndimage.label(filled)
    print(f"outline pieces: {len(closed_parts)} closed rings, {len(open_parts)} open pieces joined by {n_bridges} bridges")
    shapes_px = list(closed_parts) + [lab2 == i for i in range(1, n2 + 1)
                                      if ((lab2 == i) & ~bridged).sum() > 0.2 * (lab2 == i).sum()]
    rows = []
    for full in shapes_px:
        geoms = [shape(g) for g, v in rasterio.features.shapes(full.astype(np.uint8), mask=full, transform=T) if v]
        poly = max(geoms, key=lambda g: g.area)
        sz = int(full.sum())
        rows.append({"kind": "regional" if sz >= REGIONAL_MIN_PX else "isolated", "px": sz, "geometry": poly})
    pa = gpd.GeoDataFrame(rows, crs="EPSG:2958")
    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").geometry.iloc[0]
    pa["area_m2"] = pa.area.round(0)
    pa["in_study_area_m2"] = pa.intersection(sa).area.round(0)
    pa["share_in_study_area"] = (pa["in_study_area_m2"] / pa["area_m2"]).round(3)
    pa = pa.sort_values("area_m2", ascending=False).reset_index(drop=True)
    pa["pa_id"] = [f"{k[0].upper()}{i + 1}" for i, k in enumerate(pa.kind)]
    pa["figure"] = key
    pa["pa_id"] = key + "_" + pa["pa_id"]
    pa.to_file(PROC / "benchmark.gpkg", layer=f"problem_areas_{key}")
    print(pa.drop(columns="geometry").to_string(index=False))

    info = {"figure": cfg["title"], "page": cfg["page"], "method": "hand alignment on OSM roads, refined by "
            "maximising OSM street points on ponding hexagons", "initial": INITIAL,
            "refined": {k: round(v, 4) for k, v in best.items()}, "score_initial": round(score(INITIAL), 4),
            "score_refined": round(s0, 4), "refinement_shift_m": round(float(shift), 1),
            "transform": list(T)[:6], "problem_areas": len(pa)}
    (OUTB / f"{key}_georef.json").write_text(json.dumps(info, indent=1))

    # --- check image
    inv = ~T
    roads = gpd.read_file(PROC / "osm_tecumseh.gpkg", layer="roads")
    roads = roads[roads.highway.isin(["primary", "secondary", "tertiary", "residential", "unclassified"])]
    f, ax = plt.subplots(figsize=(13, 10.5))
    ax.imshow(fig.astype(np.uint8))
    for g in roads.geometry:
        for part in getattr(g, "geoms", [g]):
            xy = np.array(inv * tuple(np.asarray(part.coords).T)).T
            ax.plot(xy[:, 0], xy[:, 1], "-", color="#ff00ff", lw=0.4, alpha=0.9)
    xy = np.array(inv * tuple(np.asarray(sa.exterior.coords).T)).T
    ax.plot(xy[:, 0], xy[:, 1], "-", color="k", lw=1.8)
    for _, r in pa.iterrows():
        xy = np.array(inv * tuple(np.asarray(r.geometry.exterior.coords).T)).T
        ax.plot(xy[:, 0], xy[:, 1], "--", color="yellow", lw=1.0)
        cx, cy = inv * (r.geometry.centroid.x, r.geometry.centroid.y)
        ax.text(cx, cy, r.pa_id, color="yellow", fontsize=8, ha="center", fontweight="bold")
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.set_title(f"Master plan {cfg['title']} georeferenced (street-on-ponding score {s0:.3f}). Magenta = OSM streets, "
                 f"black = our study area, yellow = digitised problem areas", fontsize=9)
    f.savefig(OUTB / f"{key}_georef_check.png", dpi=120, bbox_inches="tight")
    plt.close(f)
    print(f"wrote benchmark_{key}.tif, benchmark_ponding_{key}.tif, problem_areas_{key}, {key}_georef_check.png")


def main():
    OUTB.mkdir(parents=True, exist_ok=True)
    out = PROC / "benchmark.gpkg"
    if out.exists():
        out.unlink()
    for key, cfg in FIGURES.items():
        process(key, cfg)


if __name__ == "__main__":
    main()
