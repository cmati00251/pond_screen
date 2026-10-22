"""Step 4a: find the SWOOP 2020 1 km ortho tiles over the study area + 200 m
and rank them by how much of the study area each covers.

The LIO index feature service has tile names only (no download link); tiles
must be requested through the Geospatial Ontario Imagery Orders App.
Writes outputs/imagery_tiles_to_order.csv and data/processed/swoop_tiles.gpkg.
Run with:  conda run -n pluvial python scripts/04a_imagery_index.py
"""
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parents[1]
SA = ROOT / "data/processed/study_area.gpkg"
SERVICE = ("https://services9.arcgis.com/a03W7iZ8T3s5vB7p/arcgis/rest/services/"
           "SWOOP2020_Index_WFL/FeatureServer/0/query")
HEADERS = {"User-Agent": "pluvial-mvp/0.1 (research)"}
FIRST_N = 4  # PLAN: start with at most 4 tiles


def main():
    sa = gpd.read_file(SA, layer="study_area").geometry.iloc[0]
    buf = gpd.read_file(SA, layer="study_area_buffer200").geometry.iloc[0]
    x0, y0, x1, y1 = buf.bounds
    js = requests.get(SERVICE, params={
        "f": "geojson", "where": "1=1", "outFields": "*", "returnGeometry": "true",
        "geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope", "inSR": 2958,
        "spatialRel": "esriSpatialRelIntersects", "outSR": 2958}, headers=HEADERS, timeout=120).json()
    t = gpd.GeoDataFrame.from_features(js["features"], crs=2958)
    t = t[t.intersects(buf)].copy()
    t["study_area_ha"] = t.intersection(sa).area / 1e4
    t["study_area_pct"] = 100 * t["study_area_ha"] / (sa.area / 1e4)
    t["buffer_ha"] = t.intersection(buf).area / 1e4
    t = t.sort_values("study_area_ha", ascending=False).reset_index(drop=True)
    t["priority"] = ["first 4" if i < FIRST_N else "later" for i in range(len(t))]
    t["cum_study_area_pct"] = t["study_area_pct"].cumsum()
    cols = ["Name", "priority", "study_area_ha", "study_area_pct", "cum_study_area_pct", "buffer_ha"]
    out = t[cols].round(1)
    out.to_csv(ROOT / "outputs/imagery_tiles_to_order.csv", index=False)
    t[cols + ["geometry"]].to_file(ROOT / "data/processed/swoop_tiles.gpkg", layer="swoop2020_tiles")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
