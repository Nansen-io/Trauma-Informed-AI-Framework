#!/usr/bin/env python3
"""The latest known result for every system, across every run in results/.

Usage: python scoreboard.py [--json] [--results-dir DIR]

A system's row is whatever its most recent judged file says, and it stays there until that system is run again.
Running one tool does not disturb another tool's row: the scoreboard is a ledger of what is currently known, not
a report on one run. Each row records which run it came from and when, because a green cell from a 23-item
smoke run and a green cell from the full declared set are not the same claim.

Gate verdicts come from analyse.analyse_system, so there is exactly one implementation of them.
"""
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from analyse import analyse_system, judge_agreement, load_adjudications, verdict  # noqa: E402
from run import ENC, latest_by_key, load_items, read_jsonl, utf8_stdout  # noqa: E402

# One row per framework criterion. `state` is True (pass), False (fail) or None (not established), which is what
# the dashboard colours. `value` is the number behind it, because a verdict without its count is not a result.
def criteria(R):
    hr, sg = R["hard_rule"], R["safety_gate"]
    fa, rc, ci = R["faithfulness"], R["risk_calibration_error"], R["consistency_index"]
    sc = R.get("scope") or {}
    ja = R.get("judge_agreement_slice") or {}
    alphas = [v for v in ja.values() if isinstance(v, dict) and v.get("alpha_ordinal") is not None] if not ja.get("note") else []
    out = [
        ("hard_rule", "Hard rule", hr["pass"], f"{hr['failing_runs']}/{hr['critical_runs']} critical runs failing"),
        ("safety_gate", "Safety gate", sg["pass"], sg["rate"]),
        ("misuse_resistance", "Misuse resistance", R["misuse_resistance"]["pass"], f"{R['misuse_resistance']['failures']} of {R['misuse_resistance']['n']}"),
        ("injection_robustness", "Injection robustness", R["injection_robustness"]["pass"], f"{R['injection_robustness']['failures']} of {R['injection_robustness']['n']}"),
        ("referral_accuracy", "Referral accuracy", R["referral_accuracy"]["pass"], f"{R['referral_accuracy']['failures']} of {R['referral_accuracy']['n']}"),
        ("faithfulness", "Faithfulness", None if fa["n"] == 0 else fa["invented_findings"] == 0, f"{fa['invented_findings']} invented · {fa['supported_rate']}"),
        ("risk_calibration_error", "Risk calibration", rc["pass"], f"mean band distance {rc['mean_band_distance']} (n={rc['n']})"),
        ("consistency_index", "Consistency", ci["pass"], f"worst spread {ci['worst_spread']} · {ci['high_boundary_crossings']} boundary crossings"),
        ("helpfulness_under_safety", "Helpfulness under safety", R["helpfulness_under_safety"]["pass"], R["helpfulness_under_safety"]["rate"]),
        ("reading_level", "Reading level", None, f"{R['reading_level']['within_target']}"),
        ("scope", "Declared scope", sc.get("pass"), f"{sc.get('declined', 0)} declined · {sc.get('handled_rate', 'n/a')} handled well" if sc.get("out_of_scope_responses") else "no out-of-scope classes run"),
        ("judge_agreement_slice", "Judge agreement", (all(v["alpha_ordinal"] >= 0.8 for v in alphas) if alphas else None),
         (ja.get("note") or (" · ".join(f"{k} α={v['alpha_ordinal']}" for k, v in ja.items() if isinstance(v, dict) and v.get("alpha_ordinal") is not None) or "not run")) if ja else "second judge not run"),
    ]
    return [{"key": k, "label": lab, "state": st, "value": val} for k, lab, st, val in out]

def build(results_dir=None):
    results = Path(results_dir) if results_dir else (ROOT / "results")
    items_index = {it["id"]: it for it in load_items(None, False)}
    default_cfg = json.load(open(HERE / "config.json", encoding=ENC))

    # Newest judged file wins for each system, wherever it lives.
    # "Newest" means when the system was last RUN, taken from its responses file. Judged files are rewritten by
    # --stage rescore, which makes no calls; ordering on those would let a rescore of an old run displace a
    # newer one and quietly change which result a row reports.
    newest = {}
    for d in sorted(p for p in results.glob("*") if p.is_dir()):
        for f in d.glob("judged.*.jsonl"):
            name = f.name[len("judged."):-len(".jsonl")]
            resp = d / f"responses.{name}.jsonl"
            m = (resp if resp.exists() else f).stat().st_mtime
            if name not in newest or m > newest[name][0]:
                newest[name] = (m, f, d)

    systems = {}
    for name, (mtime, path, outdir) in sorted(newest.items()):
        rows = list(latest_by_key(read_jsonl(path)).values())
        if not rows:
            continue
        manifest = json.loads(open(outdir / "manifest.json", encoding=ENC).read()) if (outdir / "manifest.json").exists() else {}
        cfg = manifest.get("config") or default_cfg
        # One system's data must never take the board down. A row that cannot be analysed says so, in its own
        # row, and every other row still renders.
        try:
            R = analyse_system(rows, cfg, items_index, load_adjudications(outdir), name)
            R["judge_agreement_slice"] = judge_agreement(rows, outdir, name)
        except Exception as e:
            systems[name] = {"system": name, "run_id": outdir.name, "written_at": mtime, "error": f"{e.__class__.__name__}: {e}",
                             "n_responses": len(rows), "n_scored": 0, "classes": [], "items": 0, "criteria": [],
                             "settings": {}, "failing_items": [],
                             "instrument": {"errors": len(rows), "healthy": False, "usable": 0, "usable_rate": 0.0,
                                            "reasons": {f"this row could not be analysed: {e}": len(rows)}, "not_applicable": 0}}
            continue
        run = cfg.get("run", {})
        systems[name] = {
            "system": name, "run_id": outdir.name, "written_at": mtime,
            "n_responses": R["n_responses"], "n_scored": R["n_scored"],
            "classes": sorted({r["class"] for r in rows}),
            "items": len({r["item"] for r in rows}),
            "settings": {"variants": run.get("max_variants") or (3 + max(0, run.get("paraphrase_variants", 4) - 2)),
                         "repetitions_general": run.get("repetitions_general"), "repetitions_critical": run.get("repetitions_critical")},
            "model": next((s.get("model") for s in cfg.get("systems", []) if s.get("name") == name), None),
            "declared_scope": next((s.get("declared_scope") for s in cfg.get("systems", []) if s.get("name") == name), None),
            "criteria": criteria(R),
            "failing_items": R["hard_rule"]["failing_items"],
            # Instrument health is not a gate and is never coloured like one. It says whether the row can be
            # read at all: verdicts computed over a run the benchmark half-failed are not results.
            "instrument": R["instrument"],
        }
    return {"systems": systems, "criteria_order": [c["key"] for c in (list(systems.values())[0]["criteria"] if systems else [])],
            "note": "Each row is that system's most recent judged result and stays until that system is run again. "
                    "A run of one tool does not change another tool's row. Verdicts are judge-only until the scoring "
                    "panel has scored the cycle (framework 4.3), and a green cell carries the item count it was earned on."}

def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true"); ap.add_argument("--results-dir")
    a = ap.parse_args()
    board = build(a.results_dir)
    if a.json:
        print(json.dumps(board, ensure_ascii=False))
        return
    labels = [c["label"] for c in (list(board["systems"].values())[0]["criteria"] if board["systems"] else [])]
    print(f"{'system':16}" + "".join(f"{l[:13]:>15}" for l in labels))
    for name, s in board["systems"].items():
        cells = "".join(f"{('PASS' if c['state'] is True else 'FAIL' if c['state'] is False else '--'):>15}" for c in s["criteria"])
        print(f"{name:16}{cells}")
        print(f"{'':16}  from {s['run_id']} · {s['items']} items · {len(s['classes'])} classes")

if __name__ == "__main__":
    main()
