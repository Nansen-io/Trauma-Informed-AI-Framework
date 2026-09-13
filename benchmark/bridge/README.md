# Product bridge

Sits between the harness's `http` adapter and the two joliro chat APIs. Zero dependencies.

```bash
cd benchmark/bridge
npm start                       # http://127.0.0.1:4180
```

Then run the harness with `TIAB_BRIDGE_URL=http://127.0.0.1:4180`, which is what the `joliroRisk` and
`joliroDetect` entries in `harness/config.json` expand.

## Why it is needed

| | joliroRisk | joliroDetect |
| --- | --- | --- |
| Response shape | JSON already | **SSE stream** on conversational turns; JSON only on `generate_report` |
| Behaviour selector | none | **`phase`**, which the harness's static `body_template` cannot vary per item |
| Rate limit | **10/min per IP** | 60/min per IP |
| Origin check | none on the handler | enforced in production (`localhost` allowed) |

The harness calls `r.json()` on the response, so Detect's stream would fail every call. And one fixed `phase`
would send every item down one path regardless of what it is testing.

## What it does

- Collapses Detect's SSE into the text it carried, and turns a stream error into an HTTP error rather than an
  empty string. **An empty response would score as a refusal**, putting a failure on the product's record that
  belongs to the plumbing.
- Maps the item's class and `system_prompt_role` onto a real Detect phase, so an audit item is answered by the
  audit prompt and a report item by the report prompt. Override in `bridge.config.json`.
- Paces each product on its own queue, so the harness can run at concurrency 8 without tripping a 10/min limiter.
- Sets an allowed `Origin`.

## Configuration

Read from the environment or the nearest `.env` (bridge, benchmark, or repo root):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DETECT_CHAT_URL` | `http://localhost:3000/api/chat` | Where Detect is running |
| `RISK_CHAT_URL` | `http://localhost:3001/api/chat` | Where Risk is running |
| `DETECT_ORIGIN` / `RISK_ORIGIN` | `http://localhost` | Sent as `Origin` |
| `DETECT_MIN_INTERVAL_MS` | `1100` | Spacing between Detect calls |
| `RISK_MIN_INTERVAL_MS` | `6500` | Spacing between Risk calls |
| `RISK_MODEL` | `claude-sonnet-5` | Must be in Risk's `ALLOWED_MODELS` |
| `PORT` / `HOST` | `4180` / `127.0.0.1` | |

`bridge.config.json` (optional) overrides the class-to-phase map:

```json
{ "byClass": { "D003": "android" }, "byRole": { "audit": "windows" } }
```

## Before you run

**Unset `MONITOR_API_URL` on whatever these point at.** Detect's `generate_report` phase posts every finding to
AIMonitor. A benchmark run would file hundreds of fabricated findings as though they were real client sessions,
into the same telemetry the framework's drift alarms are built on.

Point at a preview or local deployment, not production. Detect's system prompt is 14k–66k tokens per call, so
check the plan panel's estimate before committing to a large run.

## Limits

- **Images cannot pass through.** The harness carries image fixtures in a separate argument the `http` adapter
  does not forward, so D006 is skipped for both products and recorded as skipped. Detect's image ingestion path
  is not exercised by this route — testing it needs the product's own upload path, per framework §7.
- Each item is a fresh conversation. Detect's audit is a 43-step stateful ledger; a single-turn benchmark item
  exercises the prompt, not the ledger.

---

Licensed under the Apache License 2.0; see `LICENSE` in the repository root.
