"""Step 1: download the small sources (master plan PDFs, StatCan ODB v3
buildings, ECCC IDF for Windsor A), filter buildings to Tecumseh, and write
an inventory of every file.

Re-runnable: files already present with the expected size are skipped.
Run with:  conda run -n pluvial python scripts/01_download_small.py
"""
import re
import struct
import zipfile
import zlib
from pathlib import Path

import truststore

truststore.inject_into_ssl()  # local TLS interception: trust the Windows store

import geopandas as gpd
import pyogrio
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
WORK_CRS = "EPSG:2958"  # NAD83(CSRS) / UTM 17N, expected lidar CRS
MAX_BYTES = 5e9
HEADERS = {"User-Agent": "pluvial-mvp/0.1 (research)"}

PDFS = [
    "https://www.tecumseh.ca/media/vbzen1lj/storm-drainage-master-plan-executive-summary.pdf",
    "https://www.tecumseh.ca/media/uh3cbhnj/storm-drainage-master-plan-ea_report.pdf",
    "https://www.tecumseh.ca/media/qn0n4z2c/storm-drainage-master-plan-technical-modelling-report-final.pdf",
    "https://www.tecumseh.ca/media/zn1a5r4z/tecumseh-stormwater-drainage-master-plan-technical-modelling-report-appendices_optimized.pdf",
]
ODB = [
    f"https://www150.statcan.gc.ca/pub/34-26-0001/2018001/zip/ODB_v3_ON_{i}.zip"
    for i in (1, 2, 3)
]
IDF_ROOT = "https://collaboration.cmc.ec.gc.ca/cmc/climate/Engineer_Climate/IDF/"
CSD_NAME = "Tecumseh"


def remote_size(url):
    r = requests.head(url, allow_redirects=True, timeout=60, headers=HEADERS)
    r.raise_for_status()
    n = r.headers.get("Content-Length")
    return int(n) if n else None


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = remote_size(url)
    if size and size > MAX_BYTES:
        raise SystemExit(f"{url} is {size/1e9:.1f} GB (> 5 GB): ask before downloading")
    if dest.exists() and (size is None or dest.stat().st_size == size):
        print(f"skip  {dest.relative_to(ROOT)}")
        return
    print(f"get   {dest.relative_to(ROOT)}  ({(size or 0)/1e6:.1f} MB)")
    part = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120, headers=HEADERS) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    if size and part.stat().st_size != size:
        raise RuntimeError(f"size mismatch for {url}")
    part.replace(dest)


# ---------------------------------------------------------------- IDF
def latest_idf_zip():
    """Latest IDF release. As of v3.40 it is a top-level zip, not a folder."""
    html = requests.get(IDF_ROOT, timeout=60, headers=HEADERS).text
    zips = re.findall(r'href="(idf_v(\d+)-(\d+)_[^"]+\.zip)"', html)
    if not zips:
        raise RuntimeError("no idf_v*.zip found in IDF root")
    name = max(zips, key=lambda z: (int(z[1]), int(z[2])))[0]
    return IDF_ROOT + name


def range_get(url, start, end):
    r = requests.get(url, headers={**HEADERS, "Range": f"bytes={start}-{end}"}, timeout=300)
    r.raise_for_status()
    if r.status_code != 206:
        raise RuntimeError("server ignored range request")
    return r.content


def fetch_zip_member(url, suffix, dest):
    """Pull one member out of a remote zip with range requests."""
    if dest.exists():
        print(f"skip  {dest.relative_to(ROOT)}")
        return
    size = remote_size(url)
    tail = range_get(url, max(0, size - 65536), size - 1)
    i = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
    cd = range_get(url, cd_off, cd_off + cd_size - 1)
    p = 0
    while cd[p:p + 4] == b"PK\x01\x02":
        method = struct.unpack("<H", cd[p + 10:p + 12])[0]
        csize, usize = struct.unpack("<II", cd[p + 20:p + 28])
        n, e, c = struct.unpack("<HHH", cd[p + 28:p + 34])
        loff = struct.unpack("<I", cd[p + 42:p + 46])[0]
        name = cd[p + 46:p + 46 + n].decode("utf-8", "replace")
        if name.endswith(suffix):
            break
        p += 46 + n + e + c
    else:
        raise RuntimeError(f"{suffix} not found in {url}")
    if csize > MAX_BYTES:
        raise SystemExit(f"{name} is > 5 GB: ask before downloading")
    print(f"get   {dest.relative_to(ROOT)}  ({csize/1e6:.1f} MB, from {name})")
    hdr = range_get(url, loff, loff + 29)
    ln, le = struct.unpack("<HH", hdr[26:30])
    start = loff + 30 + ln + le
    data = range_get(url, start, start + csize - 1)
    if method == 8:
        data = zlib.decompress(data, -15)
    elif method != 0:
        raise RuntimeError(f"unsupported zip method {method}")
    if len(data) != usize:
        raise RuntimeError("size mismatch after extraction")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def extract_windsor(on_zip, dest_dir):
    """Extract every file for station WINDSOR A from the Ontario IDF zip."""
    with zipfile.ZipFile(on_zip) as z:
        hits = [n for n in z.namelist()
                if re.search(r"windsor[ _-]*a(?![a-z])", n, re.I) and not n.endswith("/")]
        print("Windsor A members:", hits or "none")
        if not hits:
            cand = [n for n in z.namelist() if "windsor" in n.lower()]
            raise RuntimeError(f"WINDSOR A not found; windsor matches: {cand}")
        for n in hits:
            out = dest_dir / Path(n).name
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))
    return hits


# ---------------------------------------------------------------- buildings
def filter_buildings(zips, dest):
    found = []
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".gpkg")]
        for m in members:
            src = f"/vsizip/{zp.as_posix()}/{m}"
            layer = pyogrio.list_layers(src)[0][0]
            info = pyogrio.read_info(src, layer=layer)
            fields = list(info["fields"])
            csd = next(f for f in fields if f.lower() == "csdname")
            names = pyogrio.read_dataframe(
                src, layer=layer, read_geometry=False, columns=[csd],
                where=f"{csd} LIKE '%ecumse%'",
            )[csd].value_counts()
            print(f"{zp.name}/{m}: layer={layer}, crs={info['crs']}, "
                  f"features={info['features']}, matches={names.to_dict()}")
            if CSD_NAME in names.index:
                gdf = gpd.read_file(src, layer=layer, where=f"{csd} = '{CSD_NAME}'")
                found.append(gdf)
    if not found:
        raise SystemExit("Tecumseh not in ODB v3: fall back to OSM buildings (see PLAN)")
    gdf = gpd.pd.concat(found, ignore_index=True)
    src_crs = gdf.crs
    gdf = gdf.to_crs(WORK_CRS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(dest, layer="buildings", driver="GPKG")
    print(f"wrote {dest.relative_to(ROOT)}: {len(gdf)} buildings "
          f"(source CRS {src_crs.to_string()}, now {WORK_CRS})")


# ---------------------------------------------------------------- inventory
def describe(path):
    ext = path.suffix.lower()
    fmt, crs, count = ext.lstrip(".").upper(), "", ""
    if ext == ".gpkg":
        for lyr, _ in pyogrio.list_layers(path):
            info = pyogrio.read_info(path, layer=lyr)
            crs = info["crs"] or ""
            count = f"{info['features']} ({lyr})"
        fmt = "GeoPackage"
    elif ext == ".zip":
        with zipfile.ZipFile(path) as z:
            n = [i for i in z.namelist() if not i.endswith("/")]
        fmt = f"ZIP ({len(n)} files: {', '.join(Path(i).name for i in n[:3])}{'...' if len(n) > 3 else ''})"
    return fmt, crs, count


def inventory():
    rows = []
    for base in (RAW, PROC):
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.endswith(".part"):
                fmt, crs, count = describe(p)
                rows.append((p.relative_to(ROOT).as_posix(), p.stat().st_size / 1e6, fmt, crs, count))
    lines = ["# Data inventory (Step 1)", "",
             "| Path | Size (MB) | Format | CRS | Features |",
             "|---|---:|---|---|---:|"]
    lines += [f"| {r[0]} | {r[1]:.2f} | {r[2]} | {r[3]} | {r[4]} |" for r in rows]
    OUT.mkdir(exist_ok=True)
    (OUT / "inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    for u in PDFS:
        download(u, RAW / "benchmark" / u.rsplit("/", 1)[1])

    idf_url = latest_idf_zip()
    version = re.search(r"idf_(v[\d-]+)_", idf_url).group(1)
    on_zip = RAW / "rainfall" / f"IDF_{version}_ON.zip"
    print("IDF release:", idf_url)
    fetch_zip_member(idf_url, "IDF_Files_Fichiers/ON.zip", on_zip)
    extract_windsor(on_zip, RAW / "rainfall" / "windsor_a")

    zips = []
    for u in ODB:
        zp = RAW / "buildings" / u.rsplit("/", 1)[1]
        download(u, zp)
        zips.append(zp)
    filter_buildings(zips, PROC / "buildings_tecumseh.gpkg")

    inventory()


if __name__ == "__main__":
    main()
