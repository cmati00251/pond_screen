"""Step 2c: propose the Lesperance pump station service area boundary.

Method
1. Extract the native map image of TMR Figure 1.2 (service area map).
2. Georeference it with road-intersection control points (pixel positions read
   off the figure; map positions from OpenStreetMap), affine least squares.
3. Classify the Lesperance (magenta) fill by colour, close gaps left by street
   lines and labels, keep the main patch, polygonize to EPSG:2958.
4. Snap the west edge to the OSM Town of Tecumseh boundary (the figure uses
   the municipal boundary there) and clip to it.
5. Write data/processed/study_area.gpkg (study_area, study_area_buffer200)
   and check images in outputs/benchmark/.

Run with:  conda run -n pluvial python scripts/02c_study_area.py
"""
import csv
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf
import rasterio.features
from affine import Affine
from PIL import Image
from scipy import ndimage
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/benchmark/storm-drainage-master-plan-technical-modelling-report-final.pdf"
OSM = ROOT / "data/processed/osm_tecumseh.gpkg"
OUT_GPKG = ROOT / "data/processed/study_area.gpkg"
OUT_DIR = ROOT / "outputs/benchmark"
WORK_CRS = "EPSG:2958"
FIG_PAGE = 15                      # TMR PDF page of Figure 1.2
REPORTED_HA = 273.50               # TMR section 1.2, Lesperance pump station
MAGENTA = np.array([205, 120, 185])
COLOUR_TOL = 45                    # RGB distance for "magenta"
CLOSE_PX = 3                       # closing radius to bridge street lines (~14 m)
MIN_PATCH_PX = 2000                # ignore magenta specks (< ~4 ha)
BRIDGE_M = 30                      # patches within 2x this are bridged (road symbols)
PS_SYMBOL = (815, 112, 23, 95)     # Lesperance PS disk: col, row, radius px, shore row
SMOOTH_M = 15                     # close/open to remove symbol artefacts on edges
SNAP_M = 40                      # snap tolerance to the municipal boundary
BUFFER_M = 200

# Control points: (label, pixel col, pixel row in native image, OSM road pair)
GCPS = [
    ("Manning Rd x Tecumseh Rd", 1199, 617, ("Manning Road", "Tecumseh Road")),
    ("Lesperance Rd x Tecumseh Rd", 893, 619, ("Lesperance Road", "Tecumseh Road")),
    ("Lesperance Rd x County Rd 22", 913, 746, ("Lesperance Road", "County Road 22")),
    ("Lesperance Rd x Riverside Dr", 815, 115, ("Lesperance Road", "Riverside Drive")),
    ("Manning Rd north end (Riverside Dr)", 1220, 271, ("Manning Road", None)),
]


def extract_figure():
    doc = pymupdf.open(PDF)
    page = doc[FIG_PAGE - 1]
    xref = max(page.get_images(full=True), key=lambda im: im[2] * im[3])[0]
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return arr[:, :, :3].copy()


def osm_point(roads, a, b):
    ga = unary_union(roads[roads["name"].fillna("").str.startswith(a)].geometry)
    if b is None:  # northern end of road a
        pts = np.vstack([np.asarray(g.coords) for g in getattr(ga, "geoms", [ga])])
        return pts[pts[:, 1].argmax()]
    gb = unary_union(roads[roads["name"].fillna("").str.startswith(b)].geometry)
    x = ga.intersection(gb)
    if x.is_empty:  # roads that meet but do not share a vertex
        from shapely.ops import nearest_points
        p1, p2 = nearest_points(ga, gb)
        return np.array([(p1.x + p2.x) / 2, (p1.y + p2.y) / 2])
    return np.array([x.centroid.x, x.centroid.y])


def fit_affine(px, world):
    A = np.column_stack([px, np.ones(len(px))])
    cx, *_ = np.linalg.lstsq(A, world[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(A, world[:, 1], rcond=None)
    T = Affine(cx[0], cx[1], cx[2], cy[0], cy[1], cy[2])
    pred = np.array([T * tuple(p) for p in px])
    return T, np.hypot(*(pred - world).T)


def magenta_polygon(img, T):
    d = np.linalg.norm(img.astype(int) - MAGENTA, axis=2)
    mask = d < COLOUR_TOL
    # The Lesperance pump station symbol (black disk) hides the fill around the
    # outlet; count the disk as service area on the land side of the shoreline.
    cx, cy, rad, shore_row = PS_SYMBOL
    yy, xx = np.ogrid[:mask.shape[0], :mask.shape[1]]
    mask |= ((xx - cx) ** 2 + (yy - cy) ** 2 <= rad ** 2) & (yy >= shore_row)
    st = ndimage.generate_binary_structure(2, 1)
    mask = ndimage.binary_closing(mask, st, iterations=CLOSE_PX)
    mask = ndimage.binary_fill_holes(mask)
    lab, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    big = [i + 1 for i, s in enumerate(sizes) if s >= MIN_PATCH_PX]
    keep = np.isin(lab, big)
    print(f"magenta components: {n}; {len(big)} >= {MIN_PATCH_PX} px: "
          f"{sorted(int(sizes[i - 1]) for i in big)}")
    geoms = [shape(g) for g, v in rasterio.features.shapes(keep.astype(np.uint8), mask=keep, transform=T)
             if v == 1]
    main_geom = max(geoms, key=lambda g: g.area)
    # Bridge gaps left by road symbols drawn over the fill (County Rd 22 splits
    # off the southern lobe). Only the strip between the two patches is added.
    out = [main_geom]
    for g in geoms:
        if g is main_geom:
            continue
        gap = g.distance(main_geom)
        if gap <= 2 * BRIDGE_M:
            bridge = g.buffer(BRIDGE_M).intersection(main_geom.buffer(BRIDGE_M))
            out += [g, bridge]
            print(f"  merged patch {g.area / 1e4:.1f} ha (gap {gap:.0f} m)")
        else:
            print(f"  dropped patch {g.area / 1e4:.1f} ha (gap {gap:.0f} m)")
    return unary_union(out), keep


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    roads = gpd.read_file(OSM, layer="roads")
    admin = gpd.read_file(OSM, layer="admin")
    town = admin[admin["name"] == "Tecumseh"].geometry.union_all()

    # 1-2 georeference
    img = extract_figure()
    px = np.array([[c + 0.5, r + 0.5] for _, c, r, _ in GCPS])
    world = np.array([osm_point(roads, *pair) for *_, pair in GCPS])
    T, resid = fit_affine(px, world)
    scale = np.sqrt(abs(T.a * T.e - T.b * T.d))
    print(f"affine: {scale:.2f} m/px, rotation {np.degrees(np.arctan2(T.d, T.a)):.2f} deg")
    with open(OUT_DIR / "gcps_fig1-2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "px_col", "px_row", "easting", "northing", "residual_m"])
        for (lbl, c, r, _), (e, n), res in zip(GCPS, world, resid):
            w.writerow([lbl, c, r, round(e, 1), round(n, 1), round(res, 1)])
            print(f"  {lbl:40s} residual {res:6.1f} m")
    print(f"  RMS residual {np.sqrt((resid ** 2).mean()):.1f} m")

    # 3 trace
    poly_raw, main_mask = magenta_polygon(img, T)
    poly = poly_raw.simplify(2.0)

    # 4 snap the west edge to the municipal boundary, then clip to the town
    near_edge = town.boundary.buffer(SNAP_M)
    sliver = poly.buffer(SNAP_M).difference(poly).intersection(near_edge).intersection(town)
    poly = unary_union([poly, sliver]).buffer(SMOOTH_M).buffer(-SMOOTH_M).intersection(town)
    poly = max(getattr(poly, "geoms", [poly]), key=lambda g: g.area)
    poly = Polygon(poly.exterior).simplify(2.0)  # a service area has no holes

    area_ha = poly.area / 1e4
    raw_ha = poly_raw.area / 1e4
    print(f"area traced {raw_ha:.1f} ha -> final {area_ha:.1f} ha "
          f"(reported {REPORTED_HA} ha, diff {100 * (area_ha / REPORTED_HA - 1):+.1f}%)")

    sa = gpd.GeoDataFrame(
        [{"name": "Lesperance pump station service area", "area_ha": round(area_ha, 2),
          "reported_ha": REPORTED_HA, "source": "TMR Fig 1.2 traced + OSM municipal boundary",
          "geometry": poly}], crs=WORK_CRS)
    if OUT_GPKG.exists():
        OUT_GPKG.unlink()
    sa.to_file(OUT_GPKG, layer="study_area")
    sa.assign(geometry=sa.buffer(BUFFER_M), name=f"study area + {BUFFER_M} m",
              area_ha=lambda d: (d.area / 1e4).round(2)).to_file(OUT_GPKG, layer="study_area_buffer200")
    print(f"wrote {OUT_GPKG.relative_to(ROOT)}")

    # 5a check image: OSM roads on the figure
    inv = ~T
    fig, ax = plt.subplots(figsize=(10, 12))
    ax.imshow(img)
    major = roads[roads["highway"].isin(["primary", "secondary", "tertiary", "trunk", "motorway"])]
    for g in major.geometry:
        for part in getattr(g, "geoms", [g]):
            xy = np.array([inv * c for c in part.coords])
            ax.plot(xy[:, 0], xy[:, 1], "-", color="lime", lw=0.8)
    for part in getattr(town.boundary, "geoms", [town.boundary]):
        xy = np.array([inv * c for c in part.coords])
        ax.plot(xy[:, 0], xy[:, 1], "-", color="red", lw=0.8)
    xy = np.array([inv * c for c in poly.exterior.coords])
    ax.plot(xy[:, 0], xy[:, 1], "-", color="k", lw=1.2)
    ax.plot(px[:, 0], px[:, 1], "y+", ms=12, mew=2)
    ax.set_xlim(450, 1400)
    ax.set_ylim(1300, 0)
    ax.set_title("Georeference check: OSM major roads (green), OSM town boundary (red),\n"
                 "proposed study area (black), control points (yellow)", fontsize=9)
    ax.axis("off")
    fig.savefig(OUT_DIR / "study_area_georef_check.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # 5b map: study area over OSM streets
    b = sa.buffer(BUFFER_M + 150).total_bounds
    fig, ax = plt.subplots(figsize=(9, 11))
    streets = roads.cx[b[0]:b[2], b[1]:b[3]]
    streets.plot(ax=ax, color="0.7", lw=0.5)
    major.cx[b[0]:b[2], b[1]:b[3]].plot(ax=ax, color="0.3", lw=1.2)
    gpd.GeoSeries([town.boundary], crs=WORK_CRS).plot(ax=ax, color="red", lw=1, ls="--")
    sa.buffer(BUFFER_M).boundary.plot(ax=ax, color="tab:blue", lw=1, ls=":")
    sa.boundary.plot(ax=ax, color="magenta", lw=2)
    for nm in ["Lesperance Road", "Tecumseh Road", "County Road 22", "Riverside Drive East",
               "St. Pierre Street", "Lacasse Boulevard"]:
        s = streets[streets["name"] == nm]
        if len(s):
            p = s.geometry.union_all().representative_point()
            ax.annotate(nm, (p.x, p.y), fontsize=7, color="0.1")
    ax.set_xlim(b[0], b[2])
    ax.set_ylim(b[1], b[3])
    ax.set_aspect("equal")
    ax.set_title(f"Proposed study area: Lesperance PS service area ({area_ha:.0f} ha; "
                 f"report: {REPORTED_HA:.0f} ha)\nmagenta = boundary, blue dotted = +200 m, "
                 f"red dashed = OSM Town of Tecumseh", fontsize=9)
    ax.tick_params(labelsize=7)
    fig.savefig(OUT_DIR / "study_area_proposed.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
