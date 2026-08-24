// Bridge between the TIAB harness's http adapter and the two joliro products.
//
// It exists because the harness speaks one shape — POST JSON in, JSON out — and the products do not:
//   joliroDetect streams Server-Sent Events on conversational turns, and selects behaviour with a `phase`
//     field that the harness's static body_template cannot vary per item.
//   joliroRisk answers in JSON already, but rate limits at 10 requests a minute per IP, which a benchmark
//     at any useful concurrency will exceed in seconds.
//
// It adds nothing to what the products do. It translates, paces, and reports failures honestly — a call that
// fails here must surface as an error the harness records, never as an empty string that scores as a refusal.
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 4180);
const HOST = process.env.HOST || '127.0.0.1';

const env = loadEnv();
const CONF = {
  detect: {
    url: env.DETECT_CHAT_URL || 'http://localhost:3000/api/chat',
    origin: env.DETECT_ORIGIN || 'http://localhost',
    secret: env.DETECT_API_SECRET || env.SERVER_TO_SERVER_SECRET || '',
    minIntervalMs: Number(env.DETECT_MIN_INTERVAL_MS || 1100),   // product limit is 60/min per IP
  },
  risk: {
    url: env.RISK_CHAT_URL || 'http://localhost:3001/api/chat',
    origin: env.RISK_ORIGIN || 'http://localhost',
    secret: env.RISK_API_SECRET || env.SERVER_TO_SERVER_SECRET || '',
    minIntervalMs: Number(env.RISK_MIN_INTERVAL_MS || 6500),     // product limit is 10/min per IP
    model: env.RISK_MODEL || 'claude-sonnet-5',
  },
};

/** Headers for a product call: an allowed Origin, plus the shared secret where one is configured. */
function outHeaders(which) {
  const h = { 'Content-Type': 'application/json', Origin: CONF[which].origin };
  if (CONF[which].secret) h['x-api-secret'] = CONF[which].secret;
  return h;
}

/** A deployed endpoint is reached with a secret or not at all. Without this the bridge works fine against a
 *  product whose origin gate is open, and a benchmark run would quietly depend on that hole staying open. */
function secretCheck() {
  const bad = [];
  for (const which of ['detect', 'risk']) {
    const host = new URL(CONF[which].url).hostname;
    const local = ['localhost', '127.0.0.1', '::1'].includes(host);
    if (!local && !CONF[which].secret) bad.push(`${which} -> ${CONF[which].url}`);
  }
  return bad;
}

// Detect selects its whole system prompt with `phase`. The benchmark's items carry a system_prompt_role and a
// class; this maps them onto the product's real phases so each item is answered by the part of the product that
// would actually answer it. Override per class in bridge.config.json.
const DEFAULT_PHASES = {
  byRole: { audit: 'iphone', dfv_guidance: 'iphone', report: 'generate_report', risk_assessment: 'initial' },
  byClass: {
    D001: 'iphone', D002: 'iphone', D003: 'iphone', D004: 'iphone', D005: 'iphone', D006: 'iphone',
    G000: 'generate_report', G001: 'generate_report', G002: 'generate_report',
    X009: 'pathway', X008: 'pathway',
  },
};
const PHASES = (() => {
  const p = join(HERE, 'bridge.config.json');
  if (!existsSync(p)) return DEFAULT_PHASES;
  const o = JSON.parse(readFileSync(p, 'utf8'));
  return { byRole: { ...DEFAULT_PHASES.byRole, ...(o.byRole || {}) }, byClass: { ...DEFAULT_PHASES.byClass, ...(o.byClass || {}) } };
})();

function loadEnv() {
  const out = { ...process.env };
  for (const dir of [HERE, dirname(HERE), dirname(dirname(HERE))]) {
    const p = join(dir, '.env');
    if (!existsSync(p)) continue;
    for (const raw of readFileSync(p, 'utf8').replace(/^﻿/, '').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const i = line.indexOf('=');
      let v = line.slice(i + 1).trim();
      v = /^(['"]).*\1$/.test(v) ? v.slice(1, -1) : v.replace(/\s+#.*$/, '');
      const k = line.slice(0, i).trim();
      if (out[k] === undefined) out[k] = v;
    }
    break;
  }
  return out;
}

/** One queue per product, so the harness can run at its own concurrency without tripping the product's limiter. */
function pacer(minIntervalMs) {
  let chain = Promise.resolve(), last = 0;
  return (fn) => {
    chain = chain.then(async () => {
      const wait = last + minIntervalMs - Date.now();
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      last = Date.now();
    });
    const mine = chain;
    return mine.then(fn);
  };
}
const pace = { detect: pacer(CONF.detect.minIntervalMs), risk: pacer(CONF.risk.minIntervalMs) };

const readBody = (req) => new Promise((resolve, reject) => {
  let b = '';
  req.on('data', (c) => { b += c; if (b.length > 8e6) req.destroy(); });
  req.on('end', () => { try { resolve(JSON.parse(b || '{}')); } catch (e) { reject(e); } });
  req.on('error', reject);
});

/** Collapse Anthropic's SSE stream into the text it carries. */
async function readSSEText(res) {
  const dec = new TextDecoder();
  let buf = '', text = '', stop = null;
  for await (const chunk of res.body) {
    buf += dec.decode(chunk, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).replace(/\r$/, '');
      buf = buf.slice(i + 1);
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      let ev;
      try { ev = JSON.parse(payload); } catch { continue; }
      if (ev.type === 'content_block_delta' && ev.delta?.type === 'text_delta') text += ev.delta.text || '';
      else if (ev.type === 'message_delta' && ev.delta?.stop_reason) stop = ev.delta.stop_reason;
      else if (ev.type === 'error') throw new Error(`stream error: ${ev.error?.type || ''} ${ev.error?.message || ''}`.trim());
    }
  }
  return { text, stop };
}

const jsonOut = (res, code, obj) => {
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(obj));
};

async function callDetect(body) {
  const phase = PHASES.byClass[body.class] || PHASES.byRole[body.role] || 'initial';
  const payload = {
    messages: (body.messages || []).map((m) => ({ role: m.role, content: String(m.content ?? '') })),
    phase,
    max_tokens: phase === 'generate_report' ? 5000 : Number(body.max_tokens) || 2048,
    language: body.language || 'en',
    country: (body.jurisdiction || '').split('-')[0] || undefined,
    sessionStartedAt: new Date(0).toISOString(),
  };
  const r = await fetch(CONF.detect.url, {
    method: 'POST',
    headers: outHeaders('detect'),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`detect ${r.status}: ${(await r.text()).slice(0, 300)}`);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('text/event-stream')) {
    const { text, stop } = await readSSEText(r);
    if (!text.trim()) throw new Error('detect returned an empty stream');
    return { text, phase, finish_reason: stop };
  }
  const j = await r.json();
  const text = j.text ?? j.content?.[0]?.text ?? '';
  if (!String(text).trim()) throw new Error('detect returned no text');
  return { text: String(text), phase, finish_reason: null };
}

async function callRisk(body) {
  const payload = {
    messages: (body.messages || []).map((m) => ({ role: m.role, content: String(m.content ?? '').slice(0, 10000) })),
    model: CONF.risk.model,
    max_tokens: 4000,
    language: body.language || 'en',
    country: (body.jurisdiction || '').split('-')[0] || undefined,
  };
  const r = await fetch(CONF.risk.url, {
    method: 'POST',
    headers: outHeaders('risk'),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`risk ${r.status}: ${(await r.text()).slice(0, 300)}`);
  const j = await r.json();
  const text = j.content?.[0]?.text ?? '';
  if (!String(text).trim()) throw new Error('risk returned no text');
  return { text: String(text), assessmentPaused: j.assessmentPaused, deliveryLanguage: j.deliveryLanguage };
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === '/health') return jsonOut(res, 200, { ok: true, detect: CONF.detect.url, risk: CONF.risk.url });
  if (req.method !== 'POST') return jsonOut(res, 405, { error: 'POST only' });

  const which = url.pathname === '/detect' ? 'detect' : url.pathname === '/risk' ? 'risk' : null;
  if (!which) return jsonOut(res, 404, { error: 'use /detect or /risk' });

  let body;
  try { body = await readBody(req); } catch { return jsonOut(res, 400, { error: 'bad JSON' }); }

  const started = Date.now();
  try {
    const out = await pace[which](() => (which === 'detect' ? callDetect(body) : callRisk(body)));
    console.log(`${which} ${body.item || '-'} ${out.phase ? `phase=${out.phase} ` : ''}${Date.now() - started}ms ${out.text.length}ch`);
    return jsonOut(res, 200, { ...out, item: body.item, ms: Date.now() - started });
  } catch (e) {
    // Surface it as an error the harness records. Returning empty text here would be scored as a refusal,
    // which would put a failure on the product's record that belongs to the plumbing.
    console.error(`${which} ${body.item || '-'} FAILED: ${e.message}`);
    return jsonOut(res, 502, { error: String(e.message || e) });
  }
}).listen(PORT, HOST, () => {
  const key = (w) => (CONF[w].secret ? `secret set (${CONF[w].secret.length} chars)` : 'NO SECRET');
  console.log(`\n  TIAB product bridge  http://${HOST}:${PORT}\n`);
  console.log(`  /detect -> ${CONF.detect.url}   (origin ${CONF.detect.origin}, ${CONF.detect.minIntervalMs}ms apart, ${key('detect')})`);
  console.log(`  /risk   -> ${CONF.risk.url}   (origin ${CONF.risk.origin}, ${CONF.risk.minIntervalMs}ms apart, model ${CONF.risk.model}, ${key('risk')})`);
  const bad = secretCheck();
  if (bad.length) {
    console.log('\n  ** No shared secret for a deployed endpoint: **');
    for (const b of bad) console.log(`     ${b}`);
    console.log('     Set SERVER_TO_SERVER_SECRET (or DETECT_API_SECRET / RISK_API_SECRET) here and in the');
    console.log('     product\'s environment. Calls will still go out, but they are only getting through');
    console.log('     because that endpoint accepts unauthenticated requests — which is the thing to fix.');
  }
  console.log('\n  Point the harness at it with  TIAB_BRIDGE_URL=http://%s:%d', HOST, PORT);
  console.log('  Check MONITOR_API_URL is unset on whatever these point at, or the run will file');
  console.log('  hundreds of fabricated findings into AIMonitor as real client sessions.\n');
});
