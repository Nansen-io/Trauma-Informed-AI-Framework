import { existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';
import { ITEMS, RESULTS } from './paths.js';

const cache = new Map();  // path -> {mtime, value}
function cached(path, build) {
  const st = existsSync(path) ? statSync(path) : null;
  if (!st) return null;
  const hit = cache.get(path);
  if (hit && hit.mtime === st.mtimeMs && hit.size === st.size) return hit.value;
  const value = build(path);
  cache.set(path, { mtime: st.mtimeMs, size: st.size, value });
  return value;
}

const readJson = (p) => (existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : null);
const rowKey = (item, variant, rep) => `${item}|${variant}|${rep}`;
// responses.*.jsonl and judged2.*.jsonl both open with item, variant, rep, so the key can be read without
// parsing the (large) rest of the line.
const KEY_RE = /^\{"item":\s*"([^"]+)",\s*"variant":\s*(\d+),\s*"rep":\s*(\d+)/;

/** Walk a JSONL file line by line, handing each line and its byte span to `visit`. */
function eachLine(path, visit) {
  const buf = readFileSync(path);
  let start = 0;
  for (let i = 0; i <= buf.length; i++) {
    if (i !== buf.length && buf[i] !== 10) continue;
    let end = i;
    if (end > start && buf[end - 1] === 13) end -= 1;
    if (end > start) visit(buf.toString('utf8', start, end), start, end);
    start = i + 1;
  }
  return buf.length;
}

/** Byte offsets of the last line carrying each (item, variant, rep), so a retried row replaces the earlier one
 *  exactly as the harness's own latest_by_key does, without holding every response body in memory. */
function offsetIndex(path) {
  const index = new Map();
  const size = eachLine(path, (line, s, e) => {
    const m = KEY_RE.exec(line);
    if (m) index.set(rowKey(m[1], m[2], m[3]), [s, e]);
  });
  return { path, index, size };
}

function lineAt(path, span) {
  const buf = readFileSync(path);
  try { return JSON.parse(buf.toString('utf8', span[0], span[1])); } catch { return null; }
}

// ---------------------------------------------------------------- items
export function loadItems() {
  return cached(ITEMS, () => {
    const byId = {}, classes = {};
    for (const f of readdirSync(ITEMS).filter((f) => f.endsWith('.json')).sort()) {
      const d = JSON.parse(readFileSync(join(ITEMS, f), 'utf8'));
      const inherited = ['class', 'suite', 'severity', 'critical_set', 'principles', 'system_prompt_role', 'bare_model_runnable'];
      classes[d.class] = {
        class: d.class, suite: d.suite, severity: d.severity, critical_set: Boolean(d.critical_set),
        principles: d.principles || [], runnable: d.bare_model_runnable !== false, n: d.items.length,
        ids: d.items.map((i) => i.id),
      };
      for (const raw of d.items) {
        const it = { ...raw };
        for (const k of inherited) if (it[k] === undefined) it[k] = d[k];
        byId[it.id] = it;
      }
    }
    return { byId, classes };
  }) || { byId: {}, classes: {} };
}

// ---------------------------------------------------------------- runs
const countLines = (p) => {
  let n = 0;
  const buf = readFileSync(p);
  for (let i = 0; i < buf.length; i++) if (buf[i] === 10) n += 1;
  if (buf.length && buf[buf.length - 1] !== 10) n += 1;
  return n;
};

export function listRuns() {
  if (!existsSync(RESULTS)) return [];
  return readdirSync(RESULTS, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => {
    const dir = join(RESULTS, d.name);
    const files = readdirSync(dir);
    const systems = files.filter((f) => f.startsWith('judged.') && f.endsWith('.jsonl')).map((f) => f.slice(7, -6));
    const manifest = readJson(join(dir, 'manifest.json'));
    let bytes = 0;
    for (const f of files) bytes += statSync(join(dir, f)).size;
    // Per system, when its rows were last written. Systems written hours apart in one run id are almost always
    // two different sessions sharing a folder, and reading them as one result is a mistake worth flagging.
    const perSystem = {};
    for (const s of new Set([...systems, ...files.filter((f) => f.startsWith('responses.')).map((f) => f.slice(10, -6))])) {
      const jp = join(dir, `judged.${s}.jsonl`), rp = join(dir, `responses.${s}.jsonl`);
      perSystem[s] = {
        judged: existsSync(jp) ? countLines(jp) : 0,
        responses: existsSync(rp) ? countLines(rp) : 0,
        writtenAt: Math.max(existsSync(jp) ? statSync(jp).mtimeMs : 0, existsSync(rp) ? statSync(rp).mtimeMs : 0),
      };
    }
    const stamps = Object.values(perSystem).map((v) => v.writtenAt).filter(Boolean);
    return {
      runId: d.name, mtime: statSync(dir).mtimeMs, systems, perSystem, bytes,
      spreadHours: stamps.length > 1 ? (Math.max(...stamps) - Math.min(...stamps)) / 3.6e6 : 0,
      responded: files.filter((f) => f.startsWith('responses.')).map((f) => f.slice(10, -6)),
      hasReport: files.includes('report.json'), hasPanel: files.includes('panel_sample.csv'),
      nItems: manifest?.n_items ?? null, classes: manifest?.classes ?? null, plan: manifest?.plan ?? null,
      run: manifest?.config?.run ?? null, benchmarkVersion: manifest?.config?.benchmark_version ?? null,
    };
  }).sort((a, b) => b.mtime - a.mtime);
}

/** Delete every run. Returns what went, so the caller can report it rather than just saying "done". */
export function removeAllRuns() {
  if (!existsSync(RESULTS)) return { deleted: [], bytes: 0 };
  const dirs = readdirSync(RESULTS, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
  let bytes = 0;
  for (const name of dirs) {
    const dir = join(RESULTS, name);
    for (const f of readdirSync(dir)) {
      try { bytes += statSync(join(dir, f)).size; } catch { /* raced with something else */ }
    }
    rmSync(dir, { recursive: true, force: true });
  }
  cache.clear();
  return { deleted: dirs, bytes };
}

/** Delete a whole run, or one system's files inside it. Confined to results/ and never touches a live run. */
export function removeRun(runId, system) {
  if (!runId || runId.includes('..') || runId.includes('/') || runId.includes('\\')) throw new Error('bad run id');
  const dir = join(RESULTS, runId);
  if (!dir.startsWith(RESULTS) || !existsSync(dir)) throw new Error(`no such run: ${runId}`);
  if (!system) {
    rmSync(dir, { recursive: true, force: true });
    cache.clear();
    return { deleted: runId };
  }
  if (system.includes('..') || system.includes('/') || system.includes('\\')) throw new Error('bad system name');
  const removed = [];
  for (const f of readdirSync(dir)) {
    if (f === `judged.${system}.jsonl` || f === `judged2.${system}.jsonl` || f === `responses.${system}.jsonl`) {
      rmSync(join(dir, f), { force: true });
      removed.push(f);
    }
  }
  // The report describes systems that no longer exist here; drop it rather than leave it stale.
  for (const f of ['report.json', 'report.md', 'panel_sample.csv', 'panel_key.csv']) {
    if (existsSync(join(dir, f))) { rmSync(join(dir, f), { force: true }); removed.push(f); }
  }
  cache.clear();
  return { deleted: runId, system, removed };
}

/** Judged rows trimmed to what the explorer lists, plus the offsets needed to open one in full. */
export function judged(runId, system) {
  const path = join(RESULTS, runId, `judged.${system}.jsonl`);
  return cached(path, (p) => {
    const items = loadItems().byId;
    const byKey = new Map(), index = new Map();
    eachLine(p, (line, s, e) => {
      let r; try { r = JSON.parse(line); } catch { return; }
      index.set(rowKey(r.item, r.variant, r.rep), [s, e]);
      const j = r.judge || {};
      const inst = r.instances || [];
      const sev = (s) => inst.filter((i) => i.severity === s).length;
      byKey.set(rowKey(r.item, r.variant, r.rep), {
        key: rowKey(r.item, r.variant, r.rep), item: r.item, cls: r.class, suite: r.suite, severity: r.severity,
        critical: Boolean(r.critical_set), principles: r.principles || [], variant: r.variant, rep: r.rep,
        system, band: r.band, gold: (items[r.item]?.gold?.band) || null, jurisdiction: items[r.item]?.jurisdiction || null,
        scores: j.scores || null, s0: sev('S0'), s1: sev('S1'), s2: sev('S2'),
        sources: [...new Set(inst.map((i) => i.source))],
        failedValidators: Object.entries(r.validators || {}).filter(([, v]) => v.pass === false).map(([k]) => k),
        judgeFailed: Boolean(j.parse_error || j.error), finishReason: r.finish_reason,
        pairGroup: r.pair_group, variantAttr: r.variant_attr,
        scope: r.scope || 'in', declined: Boolean(r.declined), scopeOutcome: r.scope_outcome || null,
        outcome: r.outcome || null, outcomeDetail: r.outcome_detail || null,
      });
    });
    return { rows: [...byKey.values()], index, path: p };
  });
}

export function systemsOf(runId) {
  const dir = join(RESULTS, runId);
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.startsWith('judged.') && f.endsWith('.jsonl')).map((f) => f.slice(7, -6)).sort();
}

export function queryRows(runId, q = {}) {
  const wanted = q.system ? [q.system] : systemsOf(runId);
  let rows = [];
  for (const s of wanted) rows = rows.concat(judged(runId, s)?.rows || []);
  const f = {
    cls: q.cls || null, suite: q.suite || null, item: (q.item || '').toUpperCase(),
    flagged: q.flagged || null,   // s0 | s1 | s2 | any | clean | judge_failed | validator
    band: q.band || null, sort: q.sort || 'severity',
  };
  rows = rows.filter((r) => {
    if (f.cls && r.cls !== f.cls) return false;
    if (f.suite && r.suite !== f.suite) return false;
    if (f.item && !r.item.toUpperCase().includes(f.item)) return false;
    if (f.band && r.band !== f.band) return false;
    if (f.flagged === 's0') return r.s0 > 0;
    if (f.flagged === 's1') return r.s1 > 0;
    if (f.flagged === 's2') return r.s2 > 0;
    if (f.flagged === 'any') return r.s0 + r.s1 + r.s2 > 0;
    if (f.flagged === 'clean') return r.s0 + r.s1 === 0;
    if (f.flagged === 'judge_failed') return r.judgeFailed;
    if (f.flagged === 'validator') return r.failedValidators.length > 0;
    if (f.flagged === 'band_off') return r.gold && r.band && r.gold !== r.band;
    if (f.flagged === 'declined') return r.declined;
    if (f.flagged === 'declined_ok') return r.scopeOutcome === 'declined_in_scope_limit';
    if (f.flagged === 'scope_fail') return ['answered_out_of_scope', 'bare_refusal'].includes(r.scopeOutcome) || /_without_emergency_guidance$/.test(r.scopeOutcome || '');
    if (f.flagged === 'out_of_scope') return r.scope === 'out';
    return true;
  });
  const rank = (r) => (r.s0 ? 3 : 0) + (r.s1 ? 2 : 0) + (r.s2 ? 1 : 0) + (r.critical ? 0.5 : 0);
  if (f.sort === 'severity') rows.sort((a, b) => rank(b) - rank(a) || a.item.localeCompare(b.item) || a.variant - b.variant || a.rep - b.rep);
  else rows.sort((a, b) => a.item.localeCompare(b.item) || a.variant - b.variant || a.rep - b.rep || a.system.localeCompare(b.system));
  const page = Math.max(0, Number(q.page) || 0), size = Math.min(500, Number(q.size) || 50);
  return { total: rows.length, page, size, rows: rows.slice(page * size, page * size + size) };
}

/** Everything needed to judge one response by eye: the item, the exact text sent, what came back, and every flag. */
export function rowDetail(runId, system, item, variant, rep) {
  const dir = join(RESULTS, runId);
  const k = rowKey(item, variant, rep);
  const jd = judged(runId, system);
  const judgedRow = jd?.index.has(k) ? lineAt(jd.path, jd.index.get(k)) : null;
  const rpath = join(dir, `responses.${system}.jsonl`);
  const ridx = existsSync(rpath) ? cached(rpath, offsetIndex) : null;
  const response = ridx?.index.has(k) ? lineAt(rpath, ridx.index.get(k)) : null;
  const j2path = join(dir, `judged2.${system}.jsonl`);
  const j2idx = existsSync(j2path) ? cached(j2path, offsetIndex) : null;
  const judge2 = j2idx?.index.has(k) ? lineAt(j2path, j2idx.index.get(k)) : null;
  const variants = readJson(join(dir, 'variants.json')) || {};
  const vrow = (variants[item] || []).find((v) => v.variant === Number(variant));
  return {
    runId, system, item, variant: Number(variant), rep: Number(rep),
    itemRecord: loadItems().byId[item] || null,
    variantText: vrow?.text ?? loadItems().byId[item]?.prompt ?? null, variantKind: vrow?.kind ?? 'original',
    response, judged: judgedRow, judge2: judge2?.judge2 || null,
  };
}

export function report(runId) {
  const dir = join(RESULTS, runId);
  return { json: readJson(join(dir, 'report.json')), md: existsSync(join(dir, 'report.md')) ? readFileSync(join(dir, 'report.md'), 'utf8') : null };
}

export function variantsOf(runId) { return readJson(join(RESULTS, runId, 'variants.json')) || {}; }

/** Live-ish roll-up straight from the judged files, so Results works before analyse.py has been run.
 *  It applies the same outcome rule as analyse.py: rows the instrument could not put to the system or could not
 *  score are excluded and counted separately. Without that this panel contradicted the dashboard and the report,
 *  showing instrument failures as the system's. */
export function quickSummary(runId) {
  const out = {};
  // Human overturns apply here too, or this panel disagrees with the report about the same run.
  const adj = readJson(join(RESULTS, runId, 'adjudications.json')) || [];
  const overturned = new Set(adj.filter((a) => a.decision === 'overturned')
    .map((a) => [a.system, a.item, a.variant, a.rep, a.source || '', a.severity || ''].join('|')));
  const isOverturned = (sys, r, sev, src) =>
    overturned.has([sys, r.item, r.variant, r.rep, src, sev].join('|'))
    || overturned.has([sys, r.item, r.variant, r.rep, src, ''].join('|'))
    || overturned.has([sys, r.item, r.variant, r.rep, '', sev].join('|'));
  for (const s of systemsOf(runId)) {
    const all = judged(runId, s)?.rows || [];
    const rows = all.filter((r) => ['scored', 'unavailable'].includes(r.outcome || (r.judgeFailed ? 'instrument_error' : 'scored')));
    const broken = all.filter((r) => (r.outcome || (r.judgeFailed ? 'instrument_error' : 'scored')) === 'instrument_error');
    const na = all.filter((r) => r.outcome === 'not_applicable');
    const crit = rows.filter((r) => r.critical);
    for (const r of rows) {
      if (!adj.length) break;
      for (const src of r.sources || []) {
        if (r.s0 && isOverturned(s, r, 'S0', src)) r.s0 -= 1;
        if (r.s1 && isOverturned(s, r, 'S1', src)) r.s1 -= 1;
        if (r.s2 && isOverturned(s, r, 'S2', src)) r.s2 -= 1;
      }
    }
    const clean = rows.filter((r) => r.s0 + r.s1 === 0).length;
    const byClass = {};
    for (const r of rows) {
      const c = byClass[r.cls] || (byClass[r.cls] = { n: 0, clean: 0, s0: 0, s1: 0, s2: 0 });
      c.n += 1; c.s0 += r.s0 ? 1 : 0; c.s1 += r.s1 ? 1 : 0; c.s2 += r.s2 ? 1 : 0;
      if (r.s0 + r.s1 === 0) c.clean += 1;
    }
    const dims = {};
    for (const r of rows) for (const [d, v] of Object.entries(r.scores || {})) {
      if (typeof v !== 'number') continue;
      const a = dims[d] || (dims[d] = { sum: 0, n: 0 }); a.sum += v; a.n += 1;
    }
    out[s] = {
      n: rows.length, clean, cleanRate: rows.length ? clean / rows.length : null,
      instrumentErrors: broken.length, notApplicable: na.length, total: all.length,
      critical: crit.length, criticalFailing: [...new Set(crit.filter((r) => r.s0 + r.s1).map((r) => r.item))].sort(),
      s0: rows.filter((r) => r.s0).length, s1: rows.filter((r) => r.s1).length, s2: rows.filter((r) => r.s2).length,
      judgeFailed: broken.length, byClass,
      dimensions: Object.fromEntries(Object.entries(dims).map(([d, a]) => [d, Number((a.sum / a.n).toFixed(2))])),
      bandOff: rows.filter((r) => r.gold && r.band && r.gold !== r.band).length,
    };
  }
  return out;
}
