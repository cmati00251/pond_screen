"""Step 3b: fetch only the needed lidar DTM/DSM tiles out of the large
provincial packages, using HTTP range requests (no full package download).

Reads outputs/lidar_tiles.csv (from 03a). Every zip member whose name contains
a needed tile name is saved to data/raw/{dtm,dsm}/tiles/.
Run with:  conda run -n pluvial python scripts/03b_lidar_download.py [--list]
"""
import io
import sys
import zipfile
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TILES = ROOT / "outputs/lidar_tiles.csv"
BASE = "https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/"
HEADERS = {"User-Agent": "pluvial-mvp/0.1 (research)"}
MAX_BYTES = 5e9


def package_url(kind, package):
    if kind == "dtm":  # index "Lake Erie A" -> LIDAR2016to18_DTM-LkErie-A.zip
        letter = package.split()[-1]
        return f"{BASE}LIDAR2016to18_DTM-LkErie-{letter}.zip"
    return f"{BASE}{package}.zip"  # index "Lake-Erie-DSM-01" -> Lake-Erie-DSM-01.zip


class HTTPRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (for zipfile)."""

    def __init__(self, url):
        self.url, self.pos, self.session = url, 0, requests.Session()
        r = self.session.head(url, allow_redirects=True, timeout=60, headers=HEADERS)
        r.raise_for_status()
        if r.headers.get("Accept-Ranges") != "bytes":
            raise RuntimeError(f"server does not support range requests: {url}")
        self.size = int(r.headers["Content-Length"])
        self.fetched = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        r = self.session.get(self.url, headers={**HEADERS, "Range": f"bytes={self.pos}-{end}"},
                             timeout=300)
        r.raise_for_status()
        if r.status_code != 206:
            raise RuntimeError("range request ignored")
        n = len(r.content)
        b[:n] = r.content
        self.pos += n
        self.fetched += n
        return n


def main():
    list_only = "--list" in sys.argv
    tiles = pd.read_csv(TILES)
    for (kind, package), grp in tiles.groupby(["kind", "Package"]):
        url = package_url(kind, package)
        dest = ROOT / "data/raw" / kind / "tiles"
        dest.mkdir(parents=True, exist_ok=True)
        f = HTTPRangeFile(url)
        z = zipfile.ZipFile(io.BufferedReader(f, buffer_size=1 << 20))
        names = set(grp["TileName"])
        members = [i for i in z.infolist() if not i.is_dir()
                   and any(t in Path(i.filename).name for t in names)]
        total = sum(i.file_size for i in members)
        print(f"\n[{kind}] {package}: {f.size / 1e9:.2f} GB package, {len(z.infolist())} members; "
              f"{len(members)} needed members, {total / 1e6:.1f} MB")
        found = {t for t in names if any(t in Path(i.filename).name for i in members)}
        if found != names:
            print("  MISSING tiles:", sorted(names - found))
        if total > MAX_BYTES:
            raise SystemExit("needed members exceed 5 GB: ask before downloading")
        for i in members:
            out = dest / Path(i.filename).name
            if list_only:
                print(f"  {i.filename}  {i.file_size / 1e6:.1f} MB")
                continue
            if out.exists() and out.stat().st_size == i.file_size:
                continue
            with z.open(i) as src, open(out, "wb") as dst:
                while chunk := src.read(1 << 22):
                    dst.write(chunk)
            print(f"  wrote {out.relative_to(ROOT)} ({i.file_size / 1e6:.1f} MB)")
        print(f"  transferred {f.fetched / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
