"""Step 3c: mosaic the lidar DTM and DSM tiles, clip to the study area + 200 m
on the native 0.5 m tile grid, and make a hillshade map.

Outputs
  data/processed/dtm.tif, dsm.tif  float32, nodata -9999, EPSG:2958, 0.5 m
  outputs/maps/hillshade.png
  outputs/lidar_summary.csv        elevation statistics
Run with:  conda run -n pluvial python scripts/03c_mosaic.py
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
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
SA = ROOT / "data/processed/study_area.gpkg"
PROC = ROOT / "data/processed"
MAPS = ROOT / "outputs/maps"
RES = 0.5
NODATA = -9999.0
# Tiles are tagged EPSG:26917 but their projection is named
# "NAD_1983_CSRS_UTM_Zone_17N": assign NAD83(CSRS) / UTM 17N without resampling.
CRS_OUT = CRS.from_epsg(2958)
PLAUSIBLE = (150.0, 260.0)  # metres; anything else is treated as nodata


def target_grid(buf):
    x0, y0, x1, y1 = buf.total_bounds
    x0, y0 = np.floor(x0 / RES) * RES, np.floor(y0 / RES) * RES
    x1, y1 = np.ceil(x1 / RES) * RES, np.ceil(y1 / RES) * RES
    w, h = int(round((x1 - x0) / RES)), int(round((y1 - y0) / RES))
    return from_origin(x0, y1, RES, RES), w, h


def mosaic(kind, transform, w, h, inside):
    out = np.full((h, w), np.nan, dtype=np.float32)
    files = sorted((ROOT / "data/raw" / kind / "tiles").glob("*.img"))
    for f in files:
        with rasterio.open(f) as src:
            if src.res != (RES, RES):
                raise RuntimeError(f"{f.name}: unexpected resolution {src.res}")
            l, b, r, t = src.bounds
            win = from_bounds(l, b, r, t, transform).round_offsets().round_lengths()
            a = src.read(1, masked=True).filled(np.nan).astype(np.float32)
            a[(a < PLAUSIBLE[0]) | (a > PLAUSIBLE[1])] = np.nan
            r0, c0 = int(win.row_off), int(win.col_off)
            rs0, cs0 = max(0, -r0), max(0, -c0)
            rd0, cd0 = max(0, r0), max(0, c0)
            nr = min(a.shape[0] - rs0, h - rd0)
            nc = min(a.shape[1] - cs0, w - cd0)
            if nr <= 0 or nc <= 0:
                continue
            sub = a[rs0:rs0 + nr, cs0:cs0 + nc]
            dst = out[rd0:rd0 + nr, cd0:cd0 + nc]
            fill = np.isnan(dst) & ~np.isnan(sub)
            dst[fill] = sub[fill]
    out[~inside] = np.nan
    return out


def write(path, a, transform):
    prof = dict(driver="GTiff", dtype="float32", count=1, width=a.shape[1], height=a.shape[0],
                crs=CRS_OUT, transform=transform, nodata=NODATA, compress="deflate",
                predictor=3, tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.where(np.isnan(a), NODATA, a).astype(np.float32), 1)
    print(f"wrote {path.relative_to(ROOT)}")


def hillshade(z, az=315.0, alt=45.0, zf=3.0):
    gy, gx = np.gradient(np.where(np.isnan(z), np.nanmedian(z), z), RES)
    slope = np.arctan(zf * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    a, b = np.radians(360 - az + 90), np.radians(alt)
    hs = np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect)
    return np.clip(hs, 0, 1)


def stats(name, a, mask):
    v = a[mask & ~np.isnan(a)]
    p = np.percentile(v, [0.1, 1, 50, 99, 99.9])
    return {"layer": name, "valid_pct": round(100 * v.size / mask.sum(), 2),
            "min": round(float(v.min()), 2), "p0.1": round(p[0], 2), "p1": round(p[1], 2),
            "median": round(p[2], 2), "p99": round(p[3], 2), "p99.9": round(p[4], 2),
            "max": round(float(v.max()), 2)}


def main():
    MAPS.mkdir(parents=True, exist_ok=True)
    sa = gpd.read_file(SA, layer="study_area")
    buf = gpd.read_file(SA, layer="study_area_buffer200")
    transform, w, h = target_grid(buf)
    inside = rasterio.features.geometry_mask(buf.geometry, (h, w), transform, invert=True)
    in_sa = rasterio.features.geometry_mask(sa.geometry, (h, w), transform, invert=True)
    print(f"grid {w} x {h} px at {RES} m, origin {transform.c}, {transform.f}")

    dtm = mosaic("dtm", transform, w, h, inside)
    dsm = mosaic("dsm", transform, w, h, inside)
    write(PROC / "dtm.tif", dtm, transform)
    write(PROC / "dsm.tif", dsm, transform)

    ndsm = dsm - dtm
    rows = [stats("dtm (study area)", dtm, in_sa), stats("dtm (+200 m)", dtm, inside),
            stats("dsm (study area)", dsm, in_sa), stats("dsm (+200 m)", dsm, inside),
            stats("dsm-dtm (study area)", ndsm, in_sa)]
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "outputs/lidar_summary.csv", index=False)
    print(df.to_string(index=False))
    neg = np.nansum(ndsm[in_sa] < -0.25) / np.sum(in_sa & ~np.isnan(ndsm))
    print(f"share of DSM below DTM by > 0.25 m: {100 * neg:.2f}%")

    # where are the high DTM values?
    hi = np.argwhere(dtm > 185)
    if len(hi):
        r, c = hi.mean(0)
        x, y = transform * (c, r)
        print(f"DTM > 185 m: {len(hi)} px ({len(hi) * RES * RES:.0f} m2), centred near E{x:.0f} N{y:.0f}")

    # hillshade map (1 m display resolution)
    step = 2
    z = dtm[::step, ::step]
    hs = hillshade(z)
    ext = (transform.c, transform.c + w * RES, transform.f - h * RES, transform.f)
    lo, hi_ = np.nanpercentile(dtm[in_sa], [1, 99])
    fig, ax = plt.subplots(figsize=(9, 12))
    ax.imshow(np.where(np.isnan(z), np.nan, hs), cmap="gray", extent=ext, vmin=0, vmax=1)
    im = ax.imshow(z, cmap="terrain", alpha=0.45, extent=ext, vmin=lo, vmax=hi_)
    sa.boundary.plot(ax=ax, color="magenta", lw=1.5)
    buf.boundary.plot(ax=ax, color="k", lw=0.6, ls=":")
    cb = fig.colorbar(im, ax=ax, shrink=0.5, pad=0.01)
    cb.set_label("DTM elevation (m, vertical datum as delivered)")
    ax.set_title("Lesperance service area: lidar DTM hillshade (OMAFRA 2016-18, 0.5 m)\n"
                 "magenta = study area, dotted = +200 m", fontsize=10)
    ax.tick_params(labelsize=7)
    fig.savefig(MAPS / "hillshade.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/maps/hillshade.png")


if __name__ == "__main__":
    main()
