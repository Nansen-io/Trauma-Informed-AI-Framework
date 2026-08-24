#!/usr/bin/env python3
"""Check the instrument before it is used. One command, one list, no surprises later.

    python doctor.py                # human-readable
    python doctor.py --json         # for the GUI
    python doctor.py --systems a,b  # only the systems a run would use

The benchmark has three ways of going wrong, and only one of them is interesting:

  1. The environment is wrong      — a missing key, an unresolved model id, a bridge that is not running.
  2. The instrument is wrong       — an item that does not parse, a gold band outside the vocabulary, a
                                     validator that does not exist, a scope map naming a class that does not.
  3. The system under test is wrong — the only one worth measuring.

The first two used to surface as results: a typo in a model id produced 266 safety failures against a model that
was never called. Everything here exists to catch 1 and 2 before a single call is made, and to say plainly which
of the three you are looking at.

Exit code is 0 when nothing is blocking, 1 otherwise.
"""
import argparse, importlib.util, json, os, re, socket, sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import prompts, validators  # noqa: E402
from run import ENC, load_dotenv, load_items, resolve_models, utf8_stdout  # noqa: E402

BLOCK, WARN, OK = "blocking", "warning", "ok"

class Report:
    def __init__(self):
        self.checks = []
    def add(self, area, name, level, detail="", fix=""):
        self.checks.append({"area": area, "name": name, "level": level, "detail": detail, "fix": fix})
    def ok(self, area, name, detail="", fix=""):
        self.add(area, name, OK, detail)
    def blocking(self, area, name, detail, fix=""):
        self.add(area, name, BLOCK, detail, fix)
    def warn(self, area, name, detail, fix=""):
        self.add(area, name, WARN, detail, fix)
    @property
    def blockers(self):
        return [c for c in self.checks if c["level"] == BLOCK]
    @property
    def warnings(self):
        return [c for c in self.checks if c["level"] == WARN]

# ---------------------------------------------------------------- the item set
def check_items(rep):
    try:
        items = load_items(None, False)
    except Exception as e:
        rep.blocking("items", "the item set parses", f"{e.__class__.__name__}: {e}", "fix the JSON in benchmark/items/")
        return []
    rep.ok("items", "the item set parses", f"{len(items)} items in {len({i['class'] for i in items})} classes")

    dupes = [k for k, v in Counter(i["id"] for i in items).items() if v > 1]
    (rep.blocking if dupes else rep.ok)("items", "item ids are unique", f"duplicates: {dupes}" if dupes else f"{len(items)} unique ids")

    bad_band, bad_val, bad_dim, no_prompt = [], [], [], []
    vocab = set(validators.BANDS)
    for it in items:
        g = it.get("gold") or {}
        for k in ("band", "min_band"):
            if g.get(k) and g[k] not in vocab:
                bad_band.append(f"{it['id']}.{k}={g[k]}")
        sc = it.get("scoring") or {}
        for v in sc.get("validators", []):
            if v not in validators.VALIDATORS:
                bad_val.append(f"{it['id']}:{v}")
        for d in sc.get("judge_dimensions", []):
            if d not in prompts.JUDGE_DIMENSIONS:
                bad_dim.append(f"{it['id']}:{d}")
        if not (it.get("prompt") or "").strip():
            no_prompt.append(it["id"])
    for name, bad, fix in (
        ("gold bands use the declared vocabulary", bad_band, f"allowed: {sorted(vocab)}"),
        ("every named validator exists", bad_val, f"available: {sorted(validators.VALIDATORS)}"),
        ("every named judge dimension exists", bad_dim, f"available: {sorted(prompts.JUDGE_DIMENSIONS)}"),
        ("every item has a prompt", no_prompt, "add the final user turn to the item"),
    ):
        (rep.blocking if bad else rep.ok)("items", name, ", ".join(bad[:6]) + (f" (+{len(bad) - 6} more)" if len(bad) > 6 else "") if bad else "all good", fix)
    return items

# ---------------------------------------------------------------- the validators
def check_validators(rep):
    import subprocess
    r = subprocess.run([sys.executable, str(HERE / "test_validators.py")], capture_output=True, text=True, encoding=ENC, errors="replace")
    last = (r.stdout or "").strip().split("\n")[-1] if r.stdout else (r.stderr or "").strip()[-200:]
    if r.returncode == 0:
        rep.ok("validators", "validator self-tests", last)
    else:
        fails = [l for l in (r.stdout or "").split("\n") if l.startswith("FAIL")]
        rep.blocking("validators", "validator self-tests", f"{last} — {len(fails)} failing",
                     "a failing validator invents findings against every system; fix it before running")

# ---------------------------------------------------------------- the config
def check_config(rep, cfg, systems, items):
    classes = {i["class"] for i in items}
    names = [s.get("name") for s in cfg.get("systems", [])]
    dupes = [k for k, v in Counter(names).items() if v > 1]
    (rep.blocking if dupes else rep.ok)("config", "system names are unique", f"duplicates: {dupes}" if dupes else f"{len(names)} systems")

    for s in systems:
        n = s.get("name", "?")
        for field in ("classes", "exclude_classes"):
            unknown = [c for c in (s.get(field) or []) if c not in classes]
            if unknown:
                rep.blocking("config", f"{n}.{field} names real classes", f"unknown: {unknown}",
                             "a class that does not exist silently narrows or widens the run")
        ds = s.get("declared_scope") or {}
        unknown = [c for c in (ds.get("out_of_scope_classes") or []) if c not in classes]
        if unknown:
            rep.blocking("config", f"{n}.declared_scope names real classes", f"unknown: {unknown}")
        both = set(ds.get("out_of_scope_classes") or []) & set(s.get("exclude_classes") or [])
        if both:
            rep.warn("config", f"{n} scope map is coherent", f"declared out of scope AND excluded: {sorted(both)}",
                     "an excluded class is never run, so declaring it out of scope has no effect")
        if ds and not ds.get("summary"):
            rep.warn("config", f"{n} declared scope has a summary", "no summary",
                     "the judge is shown this text when scoring an out-of-scope item")
        if s.get("provider") == "http" and not s.get("min_interval_s"):
            rep.warn("config", f"{n} paces its requests", "min_interval_s not set",
                     "a product with its own rate limiter will return 429s that look like unavailability")
    if not [c for c in rep.checks if c["area"] == "config" and c["level"] != OK]:
        rep.ok("config", "scope and class maps are coherent", f"{len(systems)} systems checked")

# ---------------------------------------------------------------- the environment
SDK = {"anthropic": "anthropic", "openai": "openai", "xai": "openai", "groq": "openai", "google": "google.genai", "http": "requests"}

def check_env(rep, cfg, systems, envp, stage="all"):
    rep.ok("environment", "python", f"{sys.version.split()[0]} at {sys.executable}")
    rep.ok("environment", ".env", envp or "none found — keys must come from the shell")

    needed = {}
    if stage in ("sut", "all"):
        for s in systems:
            needed[s["name"]] = s
    if stage in ("judge", "all"):
        needed["judge"] = cfg["judge"]
    if stage in ("judge2", "all") and cfg.get("judge2"):
        needed["judge2"] = cfg["judge2"]
    if stage in ("variants", "all"):
        needed["paraphraser"] = cfg["paraphraser"]

    env_keys = cfg.get("env_keys", {})
    import providers
    for name, s in needed.items():
        prov = s.get("provider")
        blob = json.dumps(s)
        unresolved = set(re.findall(r"\$\{(\w+)\}", blob)) - providers.HTTP_PLACEHOLDERS
        if unresolved:
            rep.blocking("environment", f"{name}: model id resolves", f"unresolved {sorted(unresolved)}",
                         f"set {sorted(unresolved)} in .env")
        mod = SDK.get(prov)
        if mod and not importlib.util.find_spec(mod.split(".")[0]):
            rep.blocking("environment", f"{name}: python package", f"'{mod}' is not installed",
                         "pip install --user anthropic openai google-genai requests pillow krippendorff numpy")
        k = s.get("key_env") or env_keys.get(prov, "")
        if prov in ("anthropic", "openai", "xai", "groq", "google") and k and not os.environ.get(k):
            rep.blocking("environment", f"{name}: API key", f"{k} is not set", f"add {k} to .env")
        if prov == "http":
            check_endpoint(rep, name, s)
        if not [c for c in rep.checks if c["name"].startswith(f"{name}:") and c["level"] != OK]:
            rep.ok("environment", f"{name}: reachable", f"{prov} · {s.get('model') or s.get('url') or ''}")
    for mod, why in (("krippendorff", "judge-versus-judge agreement cannot be computed"), ("numpy", "same")):
        if not importlib.util.find_spec(mod):
            rep.warn("environment", f"optional package {mod}", why, "pip install --user krippendorff numpy")

def probe(rep, cfg, systems, stage="all"):
    """One tiny call per role. This is the only check that can catch a model id the provider does not have, which
    is the single most expensive failure this benchmark has had: a stale GROQ_MODEL produced 288 errors and 266
    fabricated safety failures. Four calls here would have caught it before any of them."""
    import providers
    env_keys = cfg.get("env_keys", {})
    roles = []
    if stage in ("sut", "all"):
        roles += [(s["name"], s) for s in systems]
    if stage in ("judge", "all"):
        roles.append(("judge", cfg["judge"]))
    if stage in ("judge2", "all") and cfg.get("judge2"):
        roles.append(("judge2", cfg["judge2"]))
    if stage in ("variants", "all"):
        roles.append(("paraphraser", cfg["paraphraser"]))
    for name, s in roles:
        try:
            prov = providers.make(s, env_keys)
            txt, _ = prov.complete("Reply with the single word OK.", [{"role": "user", "content": "Reply with the single word OK."}],
                                   temperature=0.0, max_tokens=16,
                                   meta={"item": "doctor", "class": "doctor", "suite": "doctor", "jurisdiction": "AU", "role": "dfv_guidance", "language": "en"})
            if (txt or "").strip():
                rep.ok("probe", f"{name}: answers", f"{s.get('model') or s.get('url')} → {snippet(txt)}")
            else:
                rep.blocking("probe", f"{name}: answers", "returned an empty completion",
                             "raise max_output_tokens, or set extra.reasoning_effort for a reasoning model")
        except Exception as e:
            msg = f"{e.__class__.__name__}: {e}"
            fix = ("the model id does not exist for this key — run list_models.py and update .env"
                   if re.search(r"model_not_found|does not exist|404", msg, re.I) else
                   "check the key and the endpoint" if re.search(r"401|403|authentication", msg, re.I) else
                   "see the error above")
            rep.blocking("probe", f"{name}: answers", re.sub(r"\s+", " ", msg)[:220], fix)

def snippet(t, n=60):
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t[:n] + ("…" if len(t) > n else "")

def check_endpoint(rep, name, s):
    url = s.get("url") or ""
    if re.search(r"\$\{(\w+)\}", url):
        return rep.blocking("environment", f"{name}: url", f"unexpanded placeholder in {url}", "set it in .env")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return rep.blocking("environment", f"{name}: url", f"{url!r} is not a valid http(s) address",
                            "check for a stray character before the scheme")
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        socket.create_connection((p.hostname, port), timeout=2.5).close()
    except OSError as e:
        rep.blocking("environment", f"{name}: endpoint", f"nothing listening on {p.hostname}:{port} ({e.__class__.__name__})",
                     "start the bridge (cd benchmark/bridge && npm start) or point the url at the running product")

# ---------------------------------------------------------------- existing results
def check_results(rep, run_id):
    d = ROOT / "results" / run_id
    if not d.exists():
        return rep.ok("results", f"results/{run_id}", "new run — nothing on disk yet")
    judged = sorted(d.glob("judged.*.jsonl"))
    systems = [f.name[7:-6] for f in judged]
    stamps = {f.name[7:-6]: f.stat().st_mtime for f in judged}
    if len(stamps) > 1 and (max(stamps.values()) - min(stamps.values())) > 3600:
        rep.warn("results", f"results/{run_id} holds one session", f"{len(systems)} systems written up to "
                 f"{(max(stamps.values()) - min(stamps.values())) / 3600:.0f} hours apart: {systems}",
                 "use a new run id, or split them under Manage runs — one folder should be one run")
    else:
        rep.ok("results", f"results/{run_id}", f"{len(systems)} systems" if systems else "empty")
    broken = Counter()
    for f in judged:
        for line in open(f, encoding=ENC):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            av = (r.get("validators") or {}).get("availability") or {}
            j = r.get("judge") or {}
            if r.get("outcome") == "instrument_error" or av.get("instrument_error") or j.get("parse_error") or j.get("error"):
                broken[f.name[7:-6]] += 1
    if broken:
        rep.warn("results", "rows the instrument could not score", ", ".join(f"{k}: {v}" for k, v in broken.items()),
                 "rerun the affected stage; those rows are excluded from the gates, not counted against the system")

# ---------------------------------------------------------------- output
def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--systems"); ap.add_argument("--stage", default="all")
    ap.add_argument("--run-id", dest="run_id"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="make one tiny call per role to prove the model ids actually work; a few cents, and the "
                         "only check that catches a model the provider does not have")
    a = ap.parse_args()

    rep = Report()
    envp = load_dotenv()
    cfg = resolve_models(json.load(open(a.config, encoding=ENC)))
    systems = [s for s in cfg["systems"] if not a.systems or s["name"] in a.systems.split(",")]
    systems = [s for s in systems if "REPLACE" not in json.dumps(s)]
    if not systems:
        rep.blocking("config", "systems selected", "none", "check --systems against the names in config.json")

    items = check_items(rep)
    check_validators(rep)
    check_config(rep, cfg, systems, items)
    check_env(rep, cfg, systems, envp, a.stage)
    if a.probe and not rep.blockers:
        probe(rep, cfg, systems, a.stage)
    elif a.probe:
        rep.warn("probe", "skipped", "the environment has blocking problems; fix those first")
    check_results(rep, a.run_id or cfg["run_id"])

    out = {"ok": not rep.blockers, "blocking": len(rep.blockers), "warnings": len(rep.warnings), "checks": rep.checks}
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
        return sys.exit(0 if out["ok"] else 1)

    mark = {OK: "  ok  ", WARN: " warn ", BLOCK: "BLOCK "}
    area = None
    for c in rep.checks:
        if c["area"] != area:
            area = c["area"]
            print(f"\n{area.upper()}")
        print(f"  [{mark[c['level']]}] {c['name']}" + (f"\n            {c['detail']}" if c["detail"] else ""))
        if c["fix"] and c["level"] != OK:
            print(f"            fix: {c['fix']}")
    print()
    if rep.blockers:
        print(f"{len(rep.blockers)} blocking, {len(rep.warnings)} warnings — the run would not produce a usable result.")
    else:
        print(f"Ready. {len(rep.warnings)} warnings." if rep.warnings else "Ready.")
    sys.exit(1 if rep.blockers else 0)

if __name__ == "__main__":
    main()
