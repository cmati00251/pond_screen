"""Step 2b: fetch OpenStreetMap reference layers for the Tecumseh working
extent (Nominatim town boundary + Overpass roads, railways, water).

Raw API responses are cached in data/raw/osm/ (read-only once written);
a GeoPackage in EPSG:2958 is written to data/processed/osm_tecumseh.gpkg.
Run with:  conda run -n pluvial python scripts/02b_osm.py
"""
import json
import time
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import geopandas as gpd
import requests
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import linemerge, polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "osm"
OUT = ROOT / "data" / "processed" / "osm_tecumseh.gpkg"
WORK_CRS = "EPSG:2958"
HEADERS = {"User-Agent": "pluvial-mvp/0.1 (research; cmati00251 project)"}
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def cached(path, fetch):
    if path.exists():
        print(f"skip  {path.relative_to(ROOT)}")
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return data


def nominatim():
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"city": "Tecumseh", "state": "Ontario", "country": "Canada",
                "featureType": "city", "format": "geojson", "polygon_geojson": 1, "limit": 10},
        headers=HEADERS, timeout=60)
    r.raise_for_status()
    js = r.json()
    js["features"] = [f for f in js["features"]
                      if f["properties"].get("category") == "boundary"
                      and f["properties"].get("name") == "Tecumseh"
                      and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    if not js["features"]:
        raise SystemExit("Nominatim: no administrative boundary named Tecumseh")
    return js


def overpass(bbox):
    s, w, n, e = bbox
    q = f"""
    [out:json][timeout:180];
    (
      way["highway"]({s},{w},{n},{e});
      way["railway"~"rail|abandoned|disused"]({s},{w},{n},{e});
      way["natural"~"coastline|water"]({s},{w},{n},{e});
      way["waterway"]({s},{w},{n},{e});
      relation["natural"="water"]({s},{w},{n},{e});
      relation["boundary"="administrative"]["admin_level"="8"]({s},{w},{n},{e});
    );
    out geom;
    """
    last = None
    for attempt in range(6):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, headers=HEADERS, timeout=300)
            r.raise_for_status()
            print(f"overpass ok from {url}")
            return r.json()
        except requests.RequestException as e:
            last = e
            print(f"overpass attempt {attempt + 1} failed ({url}): {e}")
            time.sleep(10 * (attempt + 1))
    raise last


def way_geom(el):
    coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
    if len(coords) >= 4 and coords[0] == coords[-1] and (
            el["tags"].get("natural") == "water" or "building" in el["tags"]):
        return Polygon(coords)
    return LineString(coords)


def relation_polygon(el):
    lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in el["members"] if m["type"] == "way" and m.get("geometry")]
    merged = linemerge(lines)
    polys = list(polygonize(merged))
    return unary_union(polys) if polys else None


def main():
    town = cached(RAW / "nominatim_tecumseh.geojson", nominatim)
    feats = [f for f in town["features"] if f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    if not feats:
        raise SystemExit("Nominatim returned no polygon for Tecumseh")
    f0 = feats[0]
    print("Nominatim:", f0["properties"].get("display_name"))
    town_geom = shape(f0["geometry"])
    w, s, e, n = town_geom.buffer(0.01).bounds  # ~1 km pad in degrees
    data = cached(RAW / "overpass_tecumseh.json", lambda: overpass((s, w, n, e)))

    rows = {"roads": [], "railways": [], "water": [], "admin": []}
    for el in data["elements"]:
        t = el.get("tags", {})
        if el["type"] == "way":
            g = way_geom(el)
            rec = {"osm_id": el["id"], "name": t.get("name"), "geometry": g}
            if "highway" in t:
                rec["highway"] = t["highway"]
                rows["roads"].append(rec)
            elif "railway" in t:
                rec["railway"] = t["railway"]
                rows["railways"].append(rec)
            else:
                rec["kind"] = t.get("natural") or t.get("waterway")
                rows["water"].append(rec)
        elif el["type"] == "relation":
            g = relation_polygon(el)
            if g is None or g.is_empty:
                continue
            rec = {"osm_id": el["id"], "name": t.get("name"), "geometry": g}
            if t.get("boundary") == "administrative":
                rows["admin"].append(rec)
            else:
                rec["kind"] = "water"
                rows["water"].append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    gpd.GeoDataFrame([{"name": f0["properties"].get("display_name"), "geometry": town_geom}],
                     crs="EPSG:4326").to_crs(WORK_CRS).to_file(OUT, layer="town_nominatim")
    for layer, recs in rows.items():
        if not recs:
            print(f"{layer}: 0 (skipped)")
            continue
        gdf = gpd.GeoDataFrame(recs, geometry="geometry", crs="EPSG:4326").to_crs(WORK_CRS)
        gdf.to_file(OUT, layer=layer)
        print(f"{layer}: {len(gdf)}")
    print("admin names:", sorted({r['name'] for r in rows['admin'] if r['name']}))


if __name__ == "__main__":
    main()
