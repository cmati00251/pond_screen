"""Pipeline status and runner.

Each step lists the files it needs and the files it makes. A step is
  done     - outputs exist and are newer than all inputs
  stale    - outputs older than an input (rerun needed)
  ready    - inputs present, outputs missing
  blocked  - an input is missing (e.g. imagery not yet delivered)
  todo     - script not written yet

Usage (from the project root):
  conda run -n pluvial python scripts/run_pipeline.py            # status table
  conda run -n pluvial python scripts/run_pipeline.py --run      # run ready/stale steps in order
  conda run -n pluvial python scripts/run_pipeline.py --run 05   # run one step (and nothing else)
  conda run -n pluvial python scripts/run_pipeline.py --accept 05  # input rewritten with identical content
"""
import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (id, script, inputs, outputs, note). Patterns are globs relative to ROOT.
STEPS = [
    ("01", "01_download_small.py", [],
     ["data/processed/buildings_tecumseh.gpkg", "outputs/inventory.md"], "PDFs, buildings, IDF"),
    ("02b", "02b_osm.py", [], ["data/processed/osm_tecumseh.gpkg"], "OpenStreetMap layers"),
    ("02c", "02c_study_area.py", ["data/processed/osm_tecumseh.gpkg", "data/raw/benchmark/*.pdf"],
     ["data/processed/study_area.gpkg"], "study area boundary"),
    ("02d", "02d_buildings_study.py", ["data/processed/study_area.gpkg", "data/raw/buildings/*.zip"],
     ["data/processed/buildings_study.gpkg"], "buildings in study area + 200 m"),
    ("03a", "03a_lidar_index.py", ["data/processed/study_area.gpkg"], ["outputs/lidar_tiles.csv"], "lidar tile list"),
    ("03b", "03b_lidar_download.py", ["outputs/lidar_tiles.csv"],
     ["data/raw/dtm/tiles/*.img", "data/raw/dsm/tiles/*.img"], "lidar tiles"),
    ("03c", "03c_mosaic.py", ["data/raw/dtm/tiles/*.img", "data/raw/dsm/tiles/*.img", "data/processed/study_area.gpkg"],
     ["data/processed/dtm.tif", "data/processed/dsm.tif"], "DTM/DSM mosaics"),
    ("04a", "04a_imagery_index.py", ["data/processed/study_area.gpkg"],
     ["outputs/imagery_tiles_to_order.csv"], "imagery tile list"),
    ("04b", "04b_imagery.py", ["data/raw/imagery/*.tif", "data/processed/dtm.tif"],
     ["data/processed/imagery.tif"], "imagery to 0.5 m grid (tiles hand-downloaded to data/raw/imagery/)"),
    ("05", "05_surfaces.py", ["data/processed/imagery.tif", "data/processed/dtm.tif", "data/processed/dsm.tif",
                              "data/processed/buildings_study.gpkg", "data/processed/lake_mask.tif"],
     ["data/processed/surfaces.tif"], "surface classes (needs imagery)"),
    ("05b", "05b_accuracy.py", ["outputs/qa/sample_points.csv", "outputs/qa/review_claude.csv",
                                "outputs/qa/review_user.csv",
                                "outputs/qa/sample_points_reviewed_v1.csv"],
     ["outputs/qa/accuracy.csv"], "accuracy vs visual review"),
    ("06", "06_depressions.py", ["data/processed/dtm.tif", "data/processed/buildings_study.gpkg",
                                 "data/processed/study_area.gpkg"],
     ["data/processed/depressions.gpkg", "data/processed/depression_catchments.tif"], "depressions + flow"),
    ("07", "07_storms.py", ["data/processed/surfaces.tif", "data/processed/depressions.gpkg",
                            "data/processed/depression_catchments.tif", "data/processed/buildings_study.gpkg",
                            "data/raw/rainfall/windsor_a/*.txt"],
     ["outputs/flagged_depressions.csv", "outputs/storm_summary.csv", "data/processed/storms.gpkg"],
     "storm runoff vs depression volume (needs Step 5)"),
    ("08a", "08a_georef_benchmark.py", ["data/raw/benchmark/*.pdf", "data/processed/osm_tecumseh.gpkg",
                                        "data/processed/study_area.gpkg"],
     ["data/processed/benchmark.gpkg", "data/processed/benchmark_ponding_fig82.tif"],
     "georeference + digitise master plan Figs 8.2, 8.3"),
    ("08", "08_validation.py", ["outputs/flagged_depressions.csv", "data/processed/benchmark_ponding_fig82.tif",
                                "data/processed/storms.gpkg"], ["outputs/validation.md"], "validation"),
    ("09", "09_package.py", ["outputs/validation.md", "data/processed/storms.gpkg"],
     ["outputs/layers.gpkg", "outputs/hotspots.csv", "outputs/hotspots.geojson"], "packaging"),
]


def files(patterns):
    out = []
    for p in patterns:
        hits = glob.glob(str(ROOT / p))
        out.append(hits)
    return out


STAMPS = ROOT / "data/processed/.pipeline_stamps.json"


def fingerprint(patterns):
    """size + mtime of every input file (cheap; no hashing of large rasters)."""
    fp = {}
    for h in files(patterns):
        for f in h:
            s = Path(f).stat()
            fp[Path(f).relative_to(ROOT).as_posix()] = [s.st_size, round(s.st_mtime, 3)]
    return fp


def load_stamps():
    return json.loads(STAMPS.read_text()) if STAMPS.exists() else {}


def state(step):
    sid, script, ins, outs, _ = step
    if not (ROOT / "scripts" / script).exists():
        return "todo", ""
    in_hits = files(ins)
    missing = [p for p, h in zip(ins, in_hits) if not h]
    if missing:
        return "blocked", "missing " + ", ".join(missing)
    out_hits = files(outs)
    if any(not h for h in out_hits):
        return "ready", ""
    script_mtime = round((ROOT / "scripts" / script).stat().st_mtime, 3)
    oldest_out = min(Path(f).stat().st_mtime for h in out_hits for f in h)
    stamp = load_stamps().get(sid)
    if stamp is not None:  # inputs (and script) as they were at this step's last successful run
        stamp = dict(stamp)
        ran_script = stamp.pop("__script__", None)
        if stamp != fingerprint(ins):
            return "stale", "an input changed"
        if (ran_script is not None and script_mtime != ran_script) or (ran_script is None and script_mtime > oldest_out):
            return "stale", "script changed"
        return "done", ""
    newest_in = max((Path(f).stat().st_mtime for h in in_hits for f in h), default=0)
    if newest_in > oldest_out:
        return "stale", "an input is newer"
    return ("stale", "script changed") if script_mtime > oldest_out else ("done", "")


def status():
    print(f"{'step':5} {'state':8} {'script':24} note")
    for st in STEPS:
        s, why = state(st)
        print(f"{st[0]:5} {s:8} {st[1]:24} {st[4]}{'  [' + why + ']' if why else ''}")


def run(only=None):
    for st in STEPS:
        if only and st[0] != only:
            continue
        s, why = state(st)
        if s in ("ready", "stale") or (only and s == "done"):
            print(f"\n=== running {st[0]} {st[1]} ({s}) ===")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / st[1])], cwd=ROOT)
            if r.returncode != 0:
                raise SystemExit(f"step {st[0]} failed")
            stamps = load_stamps()
            stamps[st[0]] = {**fingerprint(st[2]),
                             "__script__": round((ROOT / "scripts" / st[1]).stat().st_mtime, 3)}
            STAMPS.write_text(json.dumps(stamps, indent=1))
        elif s == "blocked" and only:
            raise SystemExit(f"step {st[0]} is blocked: {why}")
    status()


def accept(sid):
    """Record the current inputs of a step as its baseline without rerunning it.
    Only for an input rewritten with identical content; logged in decisions.md."""
    st = next(s for s in STEPS if s[0] == sid)
    stamps = load_stamps()
    stamps[sid] = {**fingerprint(st[2]), "__script__": round((ROOT / "scripts" / st[1]).stat().st_mtime, 3)}
    STAMPS.write_text(json.dumps(stamps, indent=1))
    print(f"accepted current inputs for step {sid}")
    status()


if __name__ == "__main__":
    if "--accept" in sys.argv:
        accept(sys.argv[sys.argv.index("--accept") + 1])
    elif "--run" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--run"]
        run(args[0] if args else None)
    else:
        status()
