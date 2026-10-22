"""Step 2d: building footprints for the study area + 200 m buffer, from all
municipalities (the buffer crosses into the City of Windsor).

Reads the ODB v3 Ontario GeoPackages inside the raw zips with a bbox filter.
Writes data/processed/buildings_study.gpkg (EPSG:2958).
Run with:  conda run -n pluvial python scripts/02d_buildings_study.py
"""
from pathlib import Path
import zipfile

import geopandas as gpd
import pandas as pd
import pyogrio

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/buildings"
SA = ROOT / "data/processed/study_area.gpkg"
OUT = ROOT / "data/processed/buildings_study.gpkg"
WORK_CRS = "EPSG:2958"


def main():
    buf = gpd.read_file(SA, layer="study_area_buffer200")
    parts = []
    for zp in sorted(RAW.glob("ODB_v3_ON_*.zip")):
        with zipfile.ZipFile(zp) as z:
            member = next(n for n in z.namelist() if n.endswith(".gpkg"))
        src = f"/vsizip/{zp.as_posix()}/{member}"
        crs = pyogrio.read_info(src)["crs"]
        bbox = tuple(buf.to_crs(crs).total_bounds)
        gdf = gpd.read_file(src, bbox=bbox)
        print(f"{zp.name}: {len(gdf)} in bbox")
        if len(gdf):
            parts.append(gdf.to_crs(WORK_CRS))
    b = pd.concat(parts, ignore_index=True)
    b = gpd.GeoDataFrame(b, crs=WORK_CRS)
    b = b[b.intersects(buf.geometry.iloc[0])].drop_duplicates(subset="id")
    print("by municipality:", b["csdname"].value_counts().to_dict())
    if OUT.exists():
        OUT.unlink()
    b.to_file(OUT, layer="buildings")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(b)} buildings")


if __name__ == "__main__":
    main()
