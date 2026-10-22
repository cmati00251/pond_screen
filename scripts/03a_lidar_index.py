"""Step 3a: download the Ontario lidar DTM and DSM tile indexes, find the tiles
and packages covering the study area + 200 m, and check package URLs/sizes.
Writes outputs/lidar_tiles.csv. Downloads no tile packages.

Run with:  conda run -n pluvial python scripts/03a_lidar_index.py [--inspect]
"""
import sys
import zipfile
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import geopandas as gpd
import pandas as pd
import pyogrio
import requests

ROOT = Path(__file__).resolve().parents[1]
SA = ROOT / "data/processed/study_area.gpkg"
OUT = ROOT / "outputs"
HEADERS = {"User-Agent": "pluvial-mvp/0.1 (research)"}
INDEXES = {
    "dtm": "https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDTM_LidarDerived_TileIndex.zip",
    "dsm": "https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDSM_LidarDerived_TileIndex.zip",
}


def download(url, dest):
    if dest.exists():
        print(f"skip  {dest.relative_to(ROOT)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"get   {dest.relative_to(ROOT)}")
    with requests.get(url, stream=True, timeout=300, headers=HEADERS) as r:
        r.raise_for_status()
        part = dest.with_suffix(".part")
        with open(part, "wb") as f:
            for c in r.iter_content(1 << 20):
                f.write(c)
    part.replace(dest)


def index_source(zp):
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
    for ext in (".gdb/", ".gpkg", ".shp"):
        hit = [n for n in names if ext in n.lower() or n.lower().endswith(ext)]
        if hit:
            n = hit[0]
            if ext == ".gdb/":
                n = n[: n.lower().index(".gdb/") + 4]
            return f"/vsizip/{zp.as_posix()}/{n}", names
    raise RuntimeError(f"no vector data in {zp}: {names[:20]}")


def remote_size(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=60, headers=HEADERS)
        n = r.headers.get("Content-Length")
        return r.status_code, (int(n) if n else None)
    except requests.RequestException as e:
        return f"ERR {e.__class__.__name__}", None


def main():
    inspect = "--inspect" in sys.argv
    buf = gpd.read_file(SA, layer="study_area_buffer200")
    rows = []
    for kind, url in INDEXES.items():
        zp = ROOT / "data/raw" / kind / Path(url).name
        download(url, zp)
        src, names = index_source(zp)
        layers = pyogrio.list_layers(src)
        print(f"\n[{kind}] {src}\n  layers: {layers.tolist()}")
        for lyr, _ in layers:
            info = pyogrio.read_info(src, layer=lyr)
            print(f"  {lyr}: {info['features']} features, crs={info['crs']}, fields={list(info['fields'])}")
            if inspect:
                df = pyogrio.read_dataframe(src, layer=lyr, read_geometry=False, max_features=3)
                print(df.T.to_string())
                continue
            gdf = gpd.read_file(src, layer=lyr, bbox=tuple(buf.to_crs(info["crs"]).total_bounds))
            gdf = gdf[gdf.to_crs(buf.crs).intersects(buf.geometry.iloc[0])]
            gdf["kind"] = kind
            gdf["layer"] = lyr
            rows.append(gdf.drop(columns="geometry"))
            print(f"  -> {len(gdf)} tiles intersect study area + 200 m")
            if len(gdf):
                print(gdf.drop(columns="geometry").to_string(max_colwidth=90))
    if inspect or not rows:
        return
    tiles = pd.concat(rows, ignore_index=True)
    OUT.mkdir(exist_ok=True)
    dest = OUT / "lidar_tiles.csv"
    text = tiles.to_csv(index=False)
    if dest.exists() and dest.read_text(encoding="utf-8") == text:
        print(f"\nunchanged outputs/lidar_tiles.csv ({len(tiles)} rows)")  # keep mtime for run_pipeline
        return
    dest.write_text(text, encoding="utf-8")
    print(f"\nwrote outputs/lidar_tiles.csv ({len(tiles)} rows)")


if __name__ == "__main__":
    main()
