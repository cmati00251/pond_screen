"""Step 4b: mosaic the SWOOP ortho tiles, resample to the 0.5 m DTM grid
(area average of the 16 cm pixels), clip to the study area + 200 m, report
the bands, and make true-colour and NDVI maps.

Input:  data/raw/imagery/*.tif (user-downloaded from the Geospatial Ontario
        Imagery Orders App; SWOOP 2025 delivered, 4 bands RGBN, 16 cm)
Output: data/processed/imagery.tif  4 x uint8 (R, G, B, NIR), nodata 0
        data/processed/ndvi.tif     float32, nodata -9999
        outputs/imagery_bands.csv, outputs/maps/truecolour.png, outputs/maps/ndvi.png
Run with:  conda run -n pluvial python scripts/04b_imagery.py
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
from osgeo import gdal

gdal.UseExceptions()
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/imagery"
PROC = ROOT / "data/processed"
MAPS = ROOT / "outputs/maps"
BANDS = ["red", "green", "blue", "nir"]


def main():
    MAPS.mkdir(parents=True, exist_ok=True)
    tiles = sorted(str(p) for p in RAW.glob("*.tif"))
    if not tiles:
        raise SystemExit("no imagery tiles in data/raw/imagery/")
    with rasterio.open(PROC / "dtm.tif") as d:
        tr, crs, W, H = d.transform, d.crs, d.width, d.height
        bounds = d.bounds
    with rasterio.open(tiles[0]) as t:
        if t.count != 4:
            raise SystemExit(f"expected 4 bands (RGBN), got {t.count}")
        if t.crs.to_epsg() != 2958:
            print(f"note: tiles in {t.crs}; warping to EPSG:2958")

    # 16 cm -> 0.5 m on exactly the DTM grid; 'average' = area-weighted mean
    vrt = gdal.BuildVRT("/vsimem/swoop.vrt", tiles)
    tmp = PROC / "imagery_tmp.tif"
    gdal.Warp(str(tmp), vrt, dstSRS="EPSG:2958",
              outputBounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
              width=W, height=H, resampleAlg="average", srcNodata=None, dstNodata=0,
              outputType=gdal.GDT_Byte, multithread=True,
              creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
    vrt = None
    gdal.Unlink("/vsimem/swoop.vrt")

    with rasterio.open(tmp) as s:
        img = s.read()  # (4, H, W) uint8
    tmp.unlink()
    buf = gpd.read_file(PROC / "study_area.gpkg", layer="study_area_buffer200").to_crs(crs)
    sa = gpd.read_file(PROC / "study_area.gpkg", layer="study_area").to_crs(crs)
    inside = rasterio.features.geometry_mask(buf.geometry, (H, W), tr, invert=True)
    in_sa = rasterio.features.geometry_mask(sa.geometry, (H, W), tr, invert=True)
    covered = (img > 0).any(axis=0)
    img[:, ~inside] = 0
    valid = inside & covered
    print(f"imagery covers {100 * (valid.sum() / inside.sum()):.2f}% of buffer, "
          f"{100 * (valid & in_sa).sum() / in_sa.sum():.2f}% of study area")

    prof = dict(driver="GTiff", width=W, height=H, count=4, dtype="uint8", crs=crs, transform=tr,
                nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512,
                photometric="RGB", interleave="pixel")
    with rasterio.open(PROC / "imagery.tif", "w", **prof) as dst:
        dst.write(img)
        dst.descriptions = tuple(BANDS)
        dst.update_tags(source="SWOOP 2025 (Geospatial Ontario), 16 cm RGBN, area-averaged to 0.5 m")
    print("wrote data/processed/imagery.tif")

    # NDVI from 8-bit DN (relative index; no radiometric calibration)
    r = img[0].astype(np.float32)
    n = img[3].astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (n - r) / (n + r)
    ndvi[~valid] = np.nan
    p = dict(prof, count=1, dtype="float32", nodata=-9999.0)
    p.pop("photometric")
    with rasterio.open(PROC / "ndvi.tif", "w", **p) as dst:
        dst.write(np.where(np.isnan(ndvi), -9999.0, ndvi).astype(np.float32), 1)
    print("wrote data/processed/ndvi.tif")

    # band report (study area)
    m = valid & in_sa
    rows = []
    for i, b in enumerate(BANDS):
        v = img[i][m]
        q = np.percentile(v, [1, 50, 99])
        rows.append({"band": i + 1, "name": b, "dtype": "uint8", "min": int(v.min()), "p1": q[0],
                     "median": q[1], "p99": q[2], "max": int(v.max()), "mean": round(float(v.mean()), 1)})
    v = ndvi[m]
    q = np.nanpercentile(v, [1, 5, 25, 50, 75, 95, 99])
    rows.append({"band": "-", "name": "ndvi", "dtype": "float32", "min": round(float(np.nanmin(v)), 3),
                 "p1": round(q[0], 3), "median": round(q[3], 3), "p99": round(q[6], 3),
                 "max": round(float(np.nanmax(v)), 3), "mean": round(float(np.nanmean(v)), 3)})
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "outputs/imagery_bands.csv", index=False)
    print(df.to_string(index=False))
    print("NDVI percentiles 5/25/50/75/95:", [round(x, 3) for x in q[1:6]])

    # maps (1 m display)
    step = 2
    ext = (tr.c, tr.c + W * tr.a, tr.f + H * tr.e, tr.f)
    rgb = np.moveaxis(img[:3, ::step, ::step], 0, -1).astype(np.float32)
    lo, hi = np.percentile(rgb[valid[::step, ::step]], [1, 99])
    rgb = np.clip((rgb - lo) / (hi - lo), 0, 1)
    alpha = valid[::step, ::step].astype(np.float32)
    for name, arr, kw, title in [
        ("truecolour", np.dstack([rgb, alpha]), {}, "SWOOP 2025 true colour (leaf-off), resampled to 0.5 m"),
        ("ndvi", ndvi[::step, ::step], dict(cmap="RdYlGn", vmin=-0.3, vmax=0.5),
         "NDVI = (NIR - Red) / (NIR + Red), SWOOP 2025 8-bit values"),
    ]:
        fig, ax = plt.subplots(figsize=(9, 12))
        im = ax.imshow(arr, extent=ext, interpolation="nearest", **kw)
        sa.boundary.plot(ax=ax, color="magenta" if name == "ndvi" else "yellow", lw=1.4)
        if name == "ndvi":
            fig.colorbar(im, ax=ax, shrink=0.45, pad=0.01).set_label("NDVI")
        ax.set_title(title + "\noutline = study area", fontsize=10)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        ax.tick_params(labelsize=7)
        fig.savefig(MAPS / f"{name}.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"wrote outputs/maps/{name}.png")

    # NDVI histogram (for the Step 5 threshold)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(v[~np.isnan(v)], bins=200, range=(-0.5, 0.8), color="#4a7a3a")
    ax.set_xlabel("NDVI"); ax.set_ylabel("cells (0.5 m) in study area")
    ax.set_title("NDVI distribution, study area (SWOOP 2025, leaf-off)", fontsize=10)
    fig.savefig(MAPS / "ndvi_hist.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote outputs/maps/ndvi_hist.png")


if __name__ == "__main__":
    main()
