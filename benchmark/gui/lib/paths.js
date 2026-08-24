import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const GUI = dirname(dirname(fileURLToPath(import.meta.url)));   // benchmark/gui
export const BENCH = dirname(GUI);                                     // benchmark
export const HARNESS = join(BENCH, 'harness');
export const RESULTS = join(BENCH, 'results');
export const ITEMS = join(BENCH, 'items');
export const CONFIG = join(HARNESS, 'config.json');

/** The first interpreter that can import the harness's own dependencies, so a run does not fail 20 seconds in. */
export function findPython() {
  const probe = 'import sys,json;'
    + 'mods={};\n'
    + 'import importlib\n'
    + "for m in ('anthropic','openai','requests','PIL','krippendorff','numpy','google.genai'):\n"
    + '    try: importlib.import_module(m); mods[m]=True\n'
    + '    except Exception: mods[m]=False\n'
    + 'print(json.dumps({"version":sys.version.split()[0],"exe":sys.executable,"modules":mods}))';
  const candidates = process.env.TIAB_PYTHON
    ? [[process.env.TIAB_PYTHON, []]]
    : [['python', []], ['python3', []], ['py', ['-3']]];
  for (const [cmd, pre] of candidates) {
    const r = spawnSync(cmd, [...pre, '-c', probe], { encoding: 'utf8', windowsHide: true });
    if (r.status === 0 && r.stdout.trim().startsWith('{')) {
      try {
        return { cmd, pre, ...JSON.parse(r.stdout.trim().split('\n').pop()) };
      } catch { /* fall through to the next candidate */ }
    }
  }
  return null;
}

// Substituted by the http adapter at call time from the item being sent, not from the environment. Mirrors
// providers.HTTP_PLACEHOLDERS; a body_template is a request shape, not a list of things to put in .env.
const RUNTIME_PLACEHOLDERS = new Set(['messages', 'prompt', 'system', 'max_tokens', 'item', 'class', 'suite', 'jurisdiction', 'role', 'language']);

/** Which provider keys are actually set, read the same way the harness reads them (nearest .env, no override). */
export function envStatus(config) {
  const found = {};
  for (const dir of [HARNESS, BENCH, dirname(BENCH)]) {
    const p = join(dir, '.env');
    if (!existsSync(p)) continue;
    found.file = p;
    for (const raw of readFileSync(p, 'utf8').replace(/^﻿/, '').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const i = line.indexOf('=');
      let v = line.slice(i + 1).trim();
      v = /^(['"]).*\1$/.test(v) ? v.slice(1, -1) : v.replace(/\s+#.*$/, '');
      found[line.slice(0, i).trim()] = v;
    }
    break;
  }
  const value = (name) => process.env[name] || found[name] || '';
  const keys = {};
  for (const [provider, name] of Object.entries(config?.env_keys || {})) keys[provider] = { name, set: Boolean(value(name)) };
  // Which systems each unresolved placeholder actually belongs to, so a bridge URL is not reported as a blocker
  // for a run that has no product system in it.
  const models = {}, usedBy = {};
  for (const s of config?.systems || []) {
    for (const m of JSON.stringify(s).matchAll(/\$\{(\w+)\}/g)) {
      if (RUNTIME_PLACEHOLDERS.has(m[1])) continue;
      (usedBy[m[1]] ||= new Set()).add(s.name);
    }
  }
  for (const m of JSON.stringify(config || {}).matchAll(/\$\{(\w+)\}/g)) {
    if (RUNTIME_PLACEHOLDERS.has(m[1])) continue;
    models[m[1]] = value(m[1]) || null;
  }
  return { envFile: found.file || null, keys, models, usedBy: Object.fromEntries(Object.entries(usedBy).map(([k, v]) => [k, [...v]])) };
}
