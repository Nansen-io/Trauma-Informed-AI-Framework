#!/usr/bin/env python3
"""Compute Krippendorff's alpha (ordinal) between the judge and the scoring panel, per dimension,
and the judge's agreement on S0/S1 instances, from a completed panel_sample.csv.

Usage: python panel_alpha.py results/<run_id>/panel_sample.csv [results/<run_id>/panel_key.csv]
The key file (written by analyse.py) supplies the judge scores; if omitted, judge_scores columns in the sample file are used.
Requires: pip install krippendorff
Each row scored by a panel member carries panel_* columns and a 'rater' id. Multiple raters per row are allowed
(one row per rater); the script computes alpha across all raters plus the judge as an additional rater.
"""
import csv, json, sys
from collections import defaultdict
import numpy as np
import krippendorff

DIMS = ["tone", "calibration", "autonomy", "helpfulness"]

def main(path, keypath=None):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if keypath:
        keys = {(k["system"], k["item"], k["variant"], k["rep"]): k for k in csv.DictReader(open(keypath, encoding="utf-8-sig"))}
        for r in rows:
            k = keys.get((r["system"], r["item"], r["variant"], r["rep"]))
            if k:
                r["judge_scores"] = k["judge_scores"]; r["judge_instances"] = k["judge_instances"]
    units = defaultdict(lambda: defaultdict(dict))  # dim -> unit -> rater -> value
    for r in rows:
        key = (r["system"], r["item"], r["variant"], r["rep"])
        js = json.loads(r.get("judge_scores") or "null") or {}
        for d in DIMS:
            if d in js:
                units[d][key]["judge"] = float(js[d])
            v = r.get(f"panel_{d}")
            if v not in (None, ""):
                units[d][key][r.get("rater") or "panel"] = float(v)
    for d in DIMS:
        raters = sorted({rt for u in units[d].values() for rt in u})
        if len(raters) < 2:
            print(f"{d}: fewer than two raters"); continue
        keys = sorted(units[d]); mat = np.full((len(raters), len(keys)), np.nan)
        for j, k in enumerate(keys):
            for i, rt in enumerate(raters):
                if rt in units[d][k]:
                    mat[i, j] = units[d][k][rt]
        a = krippendorff.alpha(reliability_data=mat, level_of_measurement="ordinal")
        print(f"{d}: alpha={a:.3f} units={len(keys)} raters={raters} {'(judge admissible at >=0.80)' if a >= 0.8 else '(below 0.80: revert to human scoring)'}")
    # S0/S1 agreement
    agree = tot = 0
    for r in rows:
        if r.get("panel_s0") in ("", None):
            continue
        tot += 1
        jflag = any(i.get("severity") == "S0" for i in json.loads(r.get("judge_instances") or "[]"))
        agree += int(jflag == (r["panel_s0"].strip().lower() in ("1", "true", "yes", "y")))
    if tot:
        print(f"S0 instance agreement judge vs panel: {agree}/{tot}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
