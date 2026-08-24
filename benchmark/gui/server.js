// Local control panel for the TIAB benchmark harness. Zero dependencies: `npm start` and open the URL.
// It shells out to ../harness/run.py and ../harness/analyse.py and reads ../results; it never calls a
// provider itself, so anything it shows came from the same code path as a command-line run.
import { createReadStream, existsSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { CONFIG, GUI, envStatus, findPython } from './lib/paths.js';
import * as catalog from './lib/catalog.js';
import * as results from './lib/results.js';
import * as runner from './lib/runner.js';

const PORT = Number(process.env.PORT || 4173);
const HOST = process.env.HOST || '127.0.0.1';
const PUBLIC = join(GUI, 'public');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml' };

const send = (res, code, body, type = 'application/json; charset=utf-8') => {
  const payload = type.startsWith('application/json') ? JSON.stringify(body) : body;
  res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store' });
  res.end(payload);
};
const fail = (res, code, message) => send(res, code, { error: message });

function readBody(req) {
  return new Promise((resolve, reject) => {
    let b = '';
    req.on('data', (c) => { b += c; if (b.length > 2e6) req.destroy(); });
    req.on('end', () => { try { resolve(b ? JSON.parse(b) : {}); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}

const config = () => (existsSync(CONFIG) ? JSON.parse(readFileSync(CONFIG, 'utf8')) : null);

function sse(req, res) {
  res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive', 'x-accel-buffering': 'no' });
  const write = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  write('snapshot', runner.snapshot());
  const on = ({ event, data }) => write(event, data);
  runner.bus.on('event', on);
  const beat = setInterval(() => res.write(': ping\n\n'), 20000);
  req.on('close', () => { clearInterval(beat); runner.bus.off('event', on); });
}

const ROUTES = {
  'GET /api/catalog': () => {
    const cfg = config();
    const { classes } = results.loadItems();
    const py = runner.python_() || findPython();
    // Show what a model id resolves to, not the placeholder. The panel was reading "${OPENAI_MODEL}", which
    // tells the reader nothing about which model a row is actually about.
    const env = envStatus(cfg);
    const resolve = (v) => (typeof v === 'string' ? v.replace(/\$\{(\w+)\}/g, (m, k) => env.models?.[k] || m) : v);
    return {
      classes: Object.values(classes).map((c) => ({ ...c, ...(catalog.CLASSES[c.class] || {}) })),
      suites: catalog.SUITES, principles: catalog.PRINCIPLES, metrics: catalog.METRICS,
      glossary: catalog.GLOSSARY, stages: catalog.STAGES,
      systems: (cfg?.systems || []).filter((s) => !JSON.stringify(s).includes('REPLACE'))
        .map((s) => ({
          name: s.name, provider: s.provider, model: resolve(s.model), supportsImages: s.supports_images !== false,
          url: resolve(s.url), minIntervalS: s.min_interval_s ?? null,
          excludeClasses: s.exclude_classes || [], allowClasses: s.classes || null,
          declaredScope: s.declared_scope || null, note: s.note || null,
        })),
      roles: Object.fromEntries(Object.entries({ judge: cfg?.judge, judge2: cfg?.judge2, paraphraser: cfg?.paraphraser })
        .filter(([, v]) => v).map(([k, v]) => [k, { ...v, model: resolve(v.model) }])),
      declaredParameters: cfg?.declared_parameters || null, run: cfg?.run || null, runId: cfg?.run_id || null,
      env, python: py ? { version: py.version, exe: py.exe, modules: py.modules } : null,
      configPath: CONFIG,
    };
  },
  'GET /api/state': () => runner.snapshot(),
  'GET /api/scoreboard': () => {
    const out = runner.runOnce('scoreboard.py', ['--json'], { timeout: 300000 });
    if (out.code !== 0) throw new Error(out.stderr.trim().split('\n').slice(-6).join('\n') || `exit ${out.code}`);
    return JSON.parse(out.stdout.slice(out.stdout.indexOf('{')));
  },
  'GET /api/runs': () => ({ runs: results.listRuns() }),
  'POST /api/plan': async (req) => runner.plan(await readBody(req)),
  'POST /api/run': async (req, res) => {
    if (runner.isRunning()) return fail(res, 409, 'a run is already in progress');
    const settings = await readBody(req);
    try { return runner.start(settings); } catch (e) { return fail(res, 400, String(e.message || e)); }
  },
  'POST /api/stop': () => runner.stop(),
  'POST /api/analyse': async (req) => {
    const { runId } = await readBody(req);
    if (!runId) throw new Error('runId required');
    const out = runner.runOnce('analyse.py', ['--run-id', runId]);
    return { ...out, report: out.code === 0 ? results.report(runId) : null };
  },
  'POST /api/validators': () => runner.runOnce('test_validators.py', [], { timeout: 120000 }),
  'POST /api/doctor': async (req) => {
    const { systems, stage, runId, probe } = await readBody(req);
    const args = ['--json'];
    if (systems?.length) args.push('--systems', systems.join(','));
    if (stage) args.push('--stage', stage);
    if (runId) args.push('--run-id', runId);
    if (probe) args.push('--probe');
    const out = runner.runOnce('doctor.py', args, { timeout: probe ? 300000 : 90000 });
    const line = out.stdout.slice(out.stdout.indexOf('{'));
    try { return JSON.parse(line); } catch { throw new Error((out.stderr || out.stdout || 'doctor failed').trim().split('\n').slice(-6).join('\n')); }
  },
  'POST /api/runs/delete': async (req, res) => {
    const { runId, system } = await readBody(req);
    if (runner.isRunning() && runner.state.runId === runId) return fail(res, 409, 'that run is in progress — stop it first');
    try { return results.removeRun(runId, system); } catch (e) { return fail(res, 400, String(e.message || e)); }
  },
  'POST /api/runs/deleteAll': async (req, res) => {
    // Deliberately awkward: the caller must send the exact word, so this cannot be reached by a stray click
    // or a mis-sent request. Everything under results/ goes.
    const { confirm } = await readBody(req);
    if (confirm !== 'DELETE ALL') return fail(res, 400, 'confirmation phrase required');
    if (runner.isRunning()) return fail(res, 409, 'a run is in progress — stop it first');
    try { return results.removeAllRuns(); } catch (e) { return fail(res, 400, String(e.message || e)); }
  },
  'GET /api/report': (req, res, url) => {
    const runId = url.searchParams.get('run');
    if (!runId) return fail(res, 400, 'run required');
    return { ...results.report(runId), summary: results.quickSummary(runId), systems: results.systemsOf(runId) };
  },
  'GET /api/rows': (req, res, url) => {
    const runId = url.searchParams.get('run');
    if (!runId) return fail(res, 400, 'run required');
    return results.queryRows(runId, Object.fromEntries(url.searchParams));
  },
  'GET /api/row': (req, res, url) => {
    const p = Object.fromEntries(url.searchParams);
    if (!p.run || !p.system || !p.item) return fail(res, 400, 'run, system and item required');
    return results.rowDetail(p.run, p.system, p.item, p.variant ?? 0, p.rep ?? 0);
  },
  'GET /api/items': (req, res, url) => {
    const cls = url.searchParams.get('class');
    const { byId, classes } = results.loadItems();
    const list = Object.values(byId).filter((i) => !cls || i.class === cls);
    return { classes: Object.values(classes), items: list.map((i) => ({ id: i.id, class: i.class, suite: i.suite, severity: i.severity, critical: Boolean(i.critical_set), jurisdiction: i.jurisdiction, persona: i.persona, prompt: i.prompt, context: i.context || [], expected: i.expected || [], forbidden: i.forbidden || [], gold: i.gold || null, principles: i.principles || [], fixture: i.fixture?.type || null })) };
  },
  'GET /api/variants': (req, res, url) => ({ variants: results.variantsOf(url.searchParams.get('run')) }),
};

function serveStatic(req, res, pathname) {
  const rel = pathname === '/' ? 'index.html' : normalize(pathname).replace(/^([/\\])+/, '');
  const file = join(PUBLIC, rel);
  if (!file.startsWith(PUBLIC) || !existsSync(file)) return fail(res, 404, 'not found');
  res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
  createReadStream(file).pipe(res);
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === '/api/events') return sse(req, res);
  const handler = ROUTES[`${req.method} ${url.pathname}`];
  if (handler) {
    try {
      const out = await handler(req, res, url);
      if (out !== undefined && !res.headersSent) send(res, 200, out);
    } catch (e) {
      if (!res.headersSent) fail(res, 500, String(e?.stack || e));
    }
    return;
  }
  if (req.method === 'GET') return serveStatic(req, res, url.pathname);
  fail(res, 404, 'not found');
}).listen(PORT, HOST, () => {
  const py = findPython();
  console.log(`\n  TIAB benchmark control panel  http://${HOST}:${PORT}\n`);
  console.log(`  harness   ${CONFIG}`);
  console.log(`  python    ${py ? `${py.version} (${py.exe})` : 'NOT FOUND — set TIAB_PYTHON to a python.exe and restart'}`);
  if (py) {
    const missing = Object.entries(py.modules).filter(([, ok]) => !ok).map(([m]) => m);
    if (missing.length) console.log(`  missing   ${missing.join(', ')}  ->  pip install anthropic openai google-genai requests pillow krippendorff numpy`);
  }
  console.log('');
});
