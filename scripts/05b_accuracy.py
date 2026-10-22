"""Step 5b: accuracy of the surface classes against the visual review of the
200 random QA points (outputs/qa/review_claude.csv lists only the points whose
true class differs from the label, or that were too ambiguous to judge;
every other point was judged correct).

Writes outputs/qa/accuracy.csv (per class) and prints overall accuracy.
Run with:  conda run -n pluvial python scripts/05b_accuracy.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "outputs/qa"
CLASSES = ["roof", "tree", "grass", "water", "sealed"]


def main():
    # Truth = reviewed class; points not listed in the review were judged
    # correct *as labelled at review time* (v1), so take that frozen label.
    pts = pd.read_csv(QA / "sample_points.csv")
    v1 = pd.read_csv(QA / "sample_points_reviewed_v1.csv")[["id", "label"]].rename(columns={"label": "label_v1"})
    rev = pd.read_csv(QA / "review_claude.csv")
    user = QA / "review_user.csv"  # the user's verdicts override Claude's
    if user.exists():
        u = pd.read_csv(user)
        rev = pd.concat([rev[~rev["id"].isin(u["id"])], u], ignore_index=True)
        print(f"user overrides applied: {len(u)} points ({', '.join(map(str, u['id']))})")
    pts = pts.merge(v1, on="id").merge(rev, on="id", how="left")
    pts["truth"] = pts["truth"].fillna(pts["label_v1"])
    changed = pts[pts["label"] != pts["label_v1"]]
    if len(changed):
        print(f"labels changed since review: {len(changed)} points")
        print(changed[["id", "label_v1", "label", "truth"]].to_string(index=False))
    ev = pts[pts["truth"] != "ambiguous"]
    n_amb = (pts["truth"] == "ambiguous").sum()
    cm = pd.crosstab(ev["label"], ev["truth"]).reindex(index=CLASSES, columns=CLASSES, fill_value=0)
    rows = []
    for c in CLASSES:
        mapped, true, hit = cm.loc[c].sum(), cm[c].sum(), cm.loc[c, c]
        rows.append({"class": c, "mapped_n": int(mapped), "true_n": int(true), "correct": int(hit),
                     "users_acc_pct": round(100 * hit / mapped, 1) if mapped else None,
                     "producers_acc_pct": round(100 * hit / true, 1) if true else None})
    acc = pd.DataFrame(rows)
    overall = 100 * (ev["label"] == ev["truth"]).mean()
    acc.loc[len(acc)] = {"class": "overall", "mapped_n": len(ev), "true_n": len(ev),
                         "correct": int((ev["label"] == ev["truth"]).sum()),
                         "users_acc_pct": round(overall, 1), "producers_acc_pct": None}
    acc.to_csv(QA / "accuracy.csv", index=False)
    cm.to_csv(QA / "confusion_matrix.csv")
    print(f"evaluated {len(ev)} of {len(pts)} points ({n_amb} ambiguous excluded)")
    print("confusion (rows = mapped label, columns = truth):")
    print(cm.to_string())
    print(acc.to_string(index=False))
    imp_map = ev["label"].isin(["roof", "sealed"])
    imp_true = ev["truth"].isin(["roof", "sealed"])
    print(f"impervious vs pervious agreement: {100 * (imp_map == imp_true).mean():.1f}%")


if __name__ == "__main__":
    main()
