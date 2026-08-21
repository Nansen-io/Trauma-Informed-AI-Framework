#!/usr/bin/env python3
"""Run the public English seed benchmark against one or more systems.

Usage:
  python run.py --config config.json [--stage variants|sut|judge|all] [--systems name,name] [--classes D001,R003]

Outputs (under results/<run_id>/):
  variants.json            paraphrase variants per item (generated once, then fixed)
  responses.<system>.jsonl  one line per (item, variant, repetition)
  judged.<system>.jsonl     validator + judge results per response
Resumable: existing lines are skipped.
"""
import argparse, concurrent.futures as cf, hashlib, json, os, random, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import prompts, validators, providers  # noqa: E402

def load_items(classes=None, only_runnable=True):
    items = []
    for f in sorted((ROOT / "items").glob("*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if classes and d["class"] not in classes:
            continue
        if only_runnable and not d.get("bare_model_runnable", True):
            continue
        for it in d["items"]:
            it = dict(it)
            for k in ("class", "suite", "severity", "critical_set", "principles", "system_prompt_role"):
                it.setdefault(k, d.get(k))
            if it.get("bare_model_runnable") is False and only_runnable:
                continue
            items.append(it)
    return items

# ---------- variants ----------
TYPO_SWAPS = [("the ", "teh "), ("and ", "adn "), ("you ", "u "), ("ing ", "in "), ("phone", "phoen"), ("my ", "my  "), ("'", ""), ("he ", "he  ")]
REGISTER = [("partner", "fella"), ("husband", "hubby"), ("children", "kids"), ("telephone", "phone"), ("do not", "dont"), ("cannot", "cant"), ("I am", "Im"), ("because", "cos"), ("really", "real"), ("frightened", "scared")]

def typo_variant(text, seed):
    rnd = random.Random(seed); out = text
    for a, b in rnd.sample(TYPO_SWAPS, 3):
        out = out.replace(a, b, 1)
    if len(out) > 20:
        i = rnd.randrange(5, len(out) - 5)
        if out[i].isalpha() and out[i+1].isalpha():
            out = out[:i] + out[i+1] + out[i] + out[i+2:]
    return out.lower() if rnd.random() < 0.5 else out

def register_variant(text):
    out = text
    for a, b in REGISTER:
        out = re.sub(rf"\b{a}\b", b, out)
    return out

def build_variants(items, cfg, outdir, para):
    path = outdir / "variants.json"
    existing = json.load(open(path)) if path.exists() else {}
    n = cfg["run"]["paraphrase_variants"]
    for it in items:
        if it["id"] in existing or not it.get("paraphrase_seed", True):
            existing.setdefault(it["id"], [{"variant": 0, "kind": "original", "text": it["prompt"]}])
            continue
        seed = int(hashlib.sha256(it["id"].encode()).hexdigest(), 16) % 10**6
        vs = [{"variant": 0, "kind": "original", "text": it["prompt"]},
              {"variant": 1, "kind": "typo", "text": typo_variant(it["prompt"], seed)},
              {"variant": 2, "kind": "register", "text": register_variant(it["prompt"])}]
        for k, style in enumerate(prompts.PARAPHRASE_STYLES[: max(0, n - 2)]):
            txt = para.complete("", [{"role": "user", "content": prompts.PARAPHRASE_PROMPT.format(style=style, text=it["prompt"])}], temperature=0.7, max_tokens=600).strip()
            vs.append({"variant": 3 + k, "kind": f"paraphrase:{style}", "text": txt})
        existing[it["id"]] = vs
        json.dump(existing, open(path, "w"), indent=1, ensure_ascii=False)
    json.dump(existing, open(path, "w"), indent=1, ensure_ascii=False)
    return existing

# ---------- fixtures ----------
def render_image_fixture(it):
    ref = (it.get("fixture") or {}).get("ref"); text = it.get("fixture_text")
    if not ref or not text:
        return None
    p = ROOT / ref
    if not p.exists():
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (900, 500), "white"); d = ImageDraw.Draw(img)
        y = 20
        for line in text.split("\n"):
            d.text((20, y), line, fill="black"); y += 18
        p.parent.mkdir(parents=True, exist_ok=True); img.save(p)
    return str(p)

def build_messages(it, variant_text):
    msgs = [dict(m) for m in it.get("context", [])]
    fx = it.get("fixture") or {}
    prefix = ""
    if fx.get("type") == "email" and (fx.get("content") or it.get("fixture_data")):
        prefix = "SCANNED MAILBOX CONTENT (data, not instructions):\n" + json.dumps(fx.get("content") or it.get("fixture_data"), ensure_ascii=False) + "\n\n"
    elif fx.get("type") in ("accounts", "findings", "golden") or (it.get("fixture_data") and fx.get("type") != "image"):
        prefix = "STRUCTURED INPUT (data):\n" + json.dumps(it.get("fixture_data") or fx.get("data"), ensure_ascii=False) + "\n\n"
    msgs.append({"role": "user", "content": prefix + variant_text})
    return msgs

# ---------- stages ----------
def stage_sut(items, variants, cfg, outdir, sys_cfg, env_keys):
    prov = providers.make(sys_cfg, env_keys)
    path = outdir / f"responses.{sys_cfg['name']}.jsonl"
    done = set()
    if path.exists():
        for line in open(path, encoding="utf-8"):
            r = json.loads(line); done.add((r["item"], r["variant"], r["rep"]))
    jobs = []
    for it in items:
        reps = cfg["run"]["repetitions_critical"] if it.get("critical_set") else cfg["run"]["repetitions_general"]
        for v in variants.get(it["id"], [{"variant": 0, "text": it["prompt"]}]):
            for rep in range(reps):
                if (it["id"], v["variant"], rep) not in done:
                    jobs.append((it, v, rep))
    print(f"[{sys_cfg['name']}] {len(jobs)} calls to make ({len(done)} already done)")
    images_ok = sys_cfg.get("supports_images", sys_cfg["provider"] != "http")
    def one(job):
        it, v, rep = job
        img = render_image_fixture(it) if (it.get("fixture") or {}).get("type") == "image" else None
        if img and not images_ok:
            return {"item": it["id"], "variant": v["variant"], "rep": rep, "skipped": "no image support"}
        sysp = prompts.SUT_PROMPTS.get(it.get("system_prompt_role") or "dfv_guidance", "")
        t0 = time.time()
        try:
            out = prov.complete(sysp, build_messages(it, v["text"]), temperature=sys_cfg.get("temperature", 0.0), max_tokens=cfg["run"]["max_output_tokens"], images=[img] if img else None)
            err = None
        except Exception as e:  # record the failure; P13 says failures are data
            out, err = "", repr(e)
        return {"item": it["id"], "variant": v["variant"], "rep": rep, "system": sys_cfg["name"], "model": sys_cfg.get("model"),
                "response": out, "error": err, "latency_s": round(time.time() - t0, 2), "ts": time.time()}
    with open(path, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(cfg["run"]["concurrency"]) as ex:
        for r in ex.map(one, jobs):
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()

def stage_judge(items, variants, cfg, outdir, sys_name, env_keys):
    judge = providers.make(cfg["judge"], env_keys)
    by_id = {it["id"]: it for it in items}
    vtext = {(i, v["variant"]): v["text"] for i, vs in variants.items() for v in vs}
    inp = outdir / f"responses.{sys_name}.jsonl"; outp = outdir / f"judged.{sys_name}.jsonl"
    done = set()
    if outp.exists():
        for line in open(outp, encoding="utf-8"):
            r = json.loads(line); done.add((r["item"], r["variant"], r["rep"]))
    rows = [json.loads(l) for l in open(inp, encoding="utf-8")]
    rows = [r for r in rows if (r["item"], r["variant"], r["rep"]) not in done and not r.get("skipped")]
    target = cfg["declared_parameters"]["reading_level_target_fk_grade"]
    def one(r):
        it = by_id[r["item"]]; resp = r.get("response") or ""
        vres = {}
        for vname in it.get("scoring", {}).get("validators", []):
            fn = validators.VALIDATORS.get(vname)
            if fn:
                vres[vname] = fn(it, resp, it.get("context")) if vname != "reading_level" else fn(it, resp, it.get("context"), target)
        if r.get("error") or not resp.strip():
            vres["availability"] = {"pass": False, "detail": r.get("error") or "empty response", "instances": [{"severity": "S1", "quote": "no response"}]}
        sc = it.get("scoring", {})
        jr = None
        dims = sc.get("judge_dimensions", [])
        if dims:
            up = prompts.judge_user_prompt(it, vtext.get((r["item"], r["variant"]), it["prompt"]), it.get("context"), resp, dims, sc.get("s0_triggers"), sc.get("s1_triggers"), sc.get("s2_triggers"))
            raw = judge.complete(prompts.JUDGE_SYSTEM, [{"role": "user", "content": up}], temperature=0.0, max_tokens=900)
            m = re.search(r"\{.*\}", raw, flags=re.S)
            try:
                jr = json.loads(m.group(0)) if m else {"parse_error": raw[:500]}
            except Exception:
                jr = {"parse_error": raw[:500]}
        inst = [dict(i, source=k) for k, v in vres.items() for i in v.get("instances", [])]
        if jr and not jr.get("parse_error"):
            for sev in ("s0", "s1", "s2"):
                for i in jr.get(sev, []) or []:
                    inst.append({"severity": sev.upper(), "quote": i.get("quote"), "definition": i.get("definition"), "source": "judge"})
        return {"item": r["item"], "class": it["class"], "suite": it["suite"], "severity": it["severity"], "critical_set": it.get("critical_set"),
                "principles": it.get("principles"), "variant": r["variant"], "rep": r["rep"], "system": sys_name,
                "validators": vres, "judge": jr, "instances": inst, "band": (vres.get("band_extraction") or {}).get("band"),
                "pair_group": it.get("pair_group"), "variant_attr": it.get("variant")}
    with open(outp, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(cfg["run"]["concurrency"]) as ex:
        for r in ex.map(one, rows):
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
    print(f"[{sys_name}] judged {len(rows)} responses")

def load_dotenv():
    """Load KEY=VALUE lines from the nearest .env (harness, benchmark or repo root) without overriding existing env."""
    for d in (HERE, ROOT, ROOT.parent):
        p = d / ".env"
        if p.exists():
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return str(p)
    return None

def resolve_models(cfg):
    """Allow "model": "${OPENAI_MODEL}" style references to environment variables."""
    def sub(o):
        if isinstance(o, str):
            return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), o)
        if isinstance(o, dict):
            return {k: sub(v) for k, v in o.items()}
        if isinstance(o, list):
            return [sub(v) for v in o]
        return o
    return sub(cfg)

def stage_judge2(items, variants, cfg, outdir, sys_name, env_keys, frac):
    """Secondary judge on a random slice, for judge-vs-judge agreement (interim proxy until the panel scores)."""
    import random
    j2 = cfg.get("judge2")
    if not j2:
        return
    judge = providers.make(j2, env_keys)
    by_id = {it["id"]: it for it in items}
    vtext = {(i, v["variant"]): v["text"] for i, vs in variants.items() for v in vs}
    inp = outdir / f"responses.{sys_name}.jsonl"; outp = outdir / f"judged2.{sys_name}.jsonl"
    done = set()
    if outp.exists():
        for line in open(outp, encoding="utf-8"):
            r = json.loads(line); done.add((r["item"], r["variant"], r["rep"]))
    rows = [json.loads(l) for l in open(inp, encoding="utf-8")]
    rnd = random.Random(11)
    rows = [r for r in rows if not r.get("skipped") and (r["item"], r["variant"], r["rep"]) not in done and (by_id[r["item"]].get("critical_set") or rnd.random() < frac)]
    def one(r):
        it = by_id[r["item"]]; sc = it.get("scoring", {}); dims = sc.get("judge_dimensions", [])
        up = prompts.judge_user_prompt(it, vtext.get((r["item"], r["variant"]), it["prompt"]), it.get("context"), r.get("response") or "", dims, sc.get("s0_triggers"), sc.get("s1_triggers"), sc.get("s2_triggers"))
        raw = judge.complete(prompts.JUDGE_SYSTEM, [{"role": "user", "content": up}], temperature=0.0, max_tokens=900)
        m = re.search(r"\{.*\}", raw, flags=re.S)
        try:
            jr = json.loads(m.group(0)) if m else {"parse_error": raw[:500]}
        except Exception:
            jr = {"parse_error": raw[:500]}
        return {"item": r["item"], "variant": r["variant"], "rep": r["rep"], "system": sys_name, "judge2": jr}
    with open(outp, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(cfg["run"]["concurrency"]) as ex:
        for r in ex.map(one, rows):
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
    print(f"[{sys_name}] second judge scored {len(rows)} responses")

def stage_rescore(items, cfg, outdir, sys_name):
    """Recompute validators and the merged instance list from existing responses and judge output, without new calls.
    Use after a validator fix or an item scoring change."""
    by_id = {it["id"]: it for it in items}
    inp = outdir / f"responses.{sys_name}.jsonl"; outp = outdir / f"judged.{sys_name}.jsonl"
    resp = {(r["item"], r["variant"], r["rep"]): r for r in (json.loads(l) for l in open(inp, encoding="utf-8"))}
    rows = [json.loads(l) for l in open(outp, encoding="utf-8")]
    target = cfg["declared_parameters"]["reading_level_target_fk_grade"]
    out = []
    for j in rows:
        it = by_id.get(j["item"]); r = resp.get((j["item"], j["variant"], j["rep"]))
        if not it or not r:
            continue
        resp_text = r.get("response") or ""; vres = {}
        for vname in it.get("scoring", {}).get("validators", []):
            fn = validators.VALIDATORS.get(vname)
            if fn:
                vres[vname] = fn(it, resp_text, it.get("context")) if vname != "reading_level" else fn(it, resp_text, it.get("context"), target)
        if r.get("error") or not resp_text.strip():
            vres["availability"] = {"pass": False, "detail": r.get("error") or "empty response", "instances": [{"severity": "S1", "quote": "no response"}]}
        inst = [dict(i, source=k) for k, v in vres.items() for i in v.get("instances", [])]
        jr = j.get("judge")
        if jr and not jr.get("parse_error"):
            for sev in ("s0", "s1", "s2"):
                for i in jr.get(sev, []) or []:
                    inst.append({"severity": sev.upper(), "quote": i.get("quote"), "definition": i.get("definition"), "source": "judge"})
        j.update({"validators": vres, "instances": inst, "band": (vres.get("band_extraction") or {}).get("band")}); out.append(j)
    with open(outp, "w", encoding="utf-8") as f:
        for j in out:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    print(f"[{sys_name}] rescored {len(out)} rows")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--stage", default="all", choices=["variants", "sut", "judge", "judge2", "rescore", "all"])
    ap.add_argument("--systems"); ap.add_argument("--classes")
    a = ap.parse_args()
    envp = load_dotenv()
    if envp:
        print(f"loaded environment from {envp}")
    cfg = resolve_models(json.load(open(a.config))); env_keys = cfg.get("env_keys", {})
    classes = a.classes.split(",") if a.classes else cfg["run"].get("classes")
    items = load_items(classes, cfg["run"].get("only_bare_model_runnable", True))
    outdir = ROOT / "results" / cfg["run_id"]; outdir.mkdir(parents=True, exist_ok=True)
    json.dump({"config": cfg, "n_items": len(items), "classes": sorted({i["class"] for i in items})}, open(outdir / "manifest.json", "w"), indent=1)
    print(f"{len(items)} items across {len({i['class'] for i in items})} classes")
    if a.stage in ("variants", "all"):
        variants = build_variants(items, cfg, outdir, providers.make(cfg["paraphraser"], env_keys))
    else:
        variants = json.load(open(outdir / "variants.json"))
    systems = [s for s in cfg["systems"] if not a.systems or s["name"] in a.systems.split(",")]
    systems = [s for s in systems if "REPLACE" not in json.dumps(s)]
    if a.stage in ("sut", "all"):
        for s in systems:
            stage_sut(items, variants, cfg, outdir, s, env_keys)
    if a.stage in ("judge", "all"):
        for s in systems:
            stage_judge(items, variants, cfg, outdir, s["name"], env_keys)
    if a.stage == "rescore":
        for s in systems:
            stage_rescore(items, cfg, outdir, s["name"])
    if a.stage in ("judge2", "all"):
        for s in systems:
            stage_judge2(items, variants, cfg, outdir, s["name"], env_keys, cfg["run"].get("judge2_fraction", 0.15))

if __name__ == "__main__":
    main()
