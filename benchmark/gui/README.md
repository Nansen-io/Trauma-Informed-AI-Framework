# Benchmark control panel

A local web interface to the harness in `../harness`. It sets up a run, shows what is happening while it
runs, and reads back what the run produced with the framework's own vocabulary attached to it.

It is a front end, not a second implementation. Every run it starts is `python run.py` with the flags shown
in the log line at the top of the run view, writing to the same `results/<run_id>/` folder as a
command-line run. Anything you can do here you can do from a terminal, and vice versa.

## Running it

```bash
cd benchmark/gui
npm start                       # http://127.0.0.1:4173
```

No dependencies and no build step, so there is nothing to `npm install`. Node 18 or later.

| Variable | Effect |
| --- | --- |
| `PORT`, `HOST` | Where to listen. Defaults `4173` on `127.0.0.1`. |
| `TIAB_PYTHON` | Full path to the interpreter to use. By default it tries `python`, `python3` then `py -3` and picks the first that can import the harness's packages. |

The Set up tab reports the interpreter it found, which harness packages are missing, which `.env` it read,
and which keys and model ids are unset. The harness refuses to start with a missing key rather than
discovering it one call at a time, so fix anything flagged there first.

## The tabs

**Dashboard** — one table, systems down the side and the framework's criteria across the top, red or green
per cell. Each row is that system's **most recent** judged result and stays there until that system is run
again: running one tool does not disturb another tool's row, so the board accumulates across runs rather than
describing the last one. Every row carries the run id, item count, class count and settings it was earned on,
because a green cell from a 23-item smoke run and a green cell from the full declared set are not the same
claim. A row whose run was not healthy is marked on the row and explained in its detail: those responses are excluded from every verdict, so the row reads as not established rather than as a failure.

Click a row for the criterion-by-criterion detail, what each one means, and what to look at when it
fails. "Only show failing criteria" hides the columns nothing is failing.

It is built by `harness/scoreboard.py`, which calls `analyse.py`'s own gate functions — there is one
implementation of a verdict, not two.

## The other tabs

**Set up** — starts with **Before you run**: the instrument checks itself (environment, item set, validators, config, existing results), and *Check + probe* additionally calls each model once to prove its id works. Start is disabled while anything is blocking, and everything the panel reports is a failure of the benchmark or the environment, never of the system under test.

Then choose how much to run, which systems, and which classes. The panel at the bottom shows the
exact call count the settings imply before anything is spent, split by stage and by system, with a rough
wall-clock and token estimate. It also states plainly whether the settings are at or below the framework's
declared parameters, because a run below them is an engineering signal and not a gate result.

Size is set by four independent controls rather than a `--quick` switch:

| Control | Flag | Meaning |
| --- | --- | --- |
| Items | `--max-items N` | Caps the item count, taking one item from each selected class, then a second, and so on, so a 20-item run still touches every class rather than the whole of D001. Deterministic. |
| Variants per item | `--variants-total N` | 1 is the original only; 2 adds the seeded typo variant; 3 adds the colloquial register variant; above 3 adds model-written paraphrases, one paraphraser call each. |
| Repetitions | `--repetitions-general N`, `--repetitions-critical N` | The framework declares 2 and 10. |
| Second judge | `--no-judge2`, `--judge2-fraction F` | Skipping it means judge reliability has no number against it for the run. |

Four presets set all of them at once: Smoke, Quick check, Broad and Full declared run. Moving any slider
leaves the preset behind and the plan updates.

**Which model runs which test** is a class-by-system matrix. A tick runs that class against that system. Two
cell states are not free choices: a shaded cell is a class the system's config excludes because it has no
ingestion path for those fixtures, and an amber cell is a class the system *declares outside its scope* — those
are still run, because declining them well is the behaviour being measured.

**Offline dry run** (`--mock`) replaces every provider with a stand-in that makes no network call. It
exercises all four stages, writes a complete result set and drives the whole interface, at no cost. The
content is invented, so nothing it produces is a measurement of anything. It is the fastest way to see the
pipeline work before wiring keys.

**Run** — a progress bar per stage per system with the observed per-call latency and an estimate of what is
left, a live feed of every call as it lands, and a separate findings column carrying each flagged instance
with the quote that raised it. Instances, not scores, are what decide the gates, so they get their own
column. The raw harness output is underneath. Stopping is safe: every stage is resumable, and restarting
with the same run id picks up where it left off.

**Results** — gates and metrics per system. Each gate carries what it actually measures, its gate type, and,
where it failed, the first thing to look at. A gate with nothing behind it reads NOT ESTABLISHED rather than
PASS. Below that, a class-by-class table saying what each class was testing and how it went. Press *Compute
the report* to run `analyse.py`, which adds Wilson intervals, judge-versus-judge agreement, the fairness
matched pairs and the panel sample. Before that, the figures shown are counted straight from the judged
files.

**Refusals** appear throughout as their own outcome rather than as a pass or a failure: `declined — out of scope`
(green, the correct answer), `answered out of scope`, `bare refusal`, and `— no emergency guidance` (red, an S0
whatever the scope). The run view counts them, Explore filters on them, and the detail view shows why each was
classified as it was.

**Explore** — every scored response, filterable by system, class, severity, failed validator, band
mismatch, or how a refusal was handled. Opening one shows the persona and prior turns, the exact text that was sent for that variant, the
response, every flag with its quoted evidence, both judges' scores, the deterministic validator results, and
the item's own expected, forbidden and gold entries. This is the view for confirming or overturning a flag
by eye, which is what the scoring panel does formally.

**Item set** — the items themselves, by class, with what the class is for.

**What it means** — the vocabulary, the four stages, how to read each metric, and the eighteen principles.

## What it does not do

It does not compute anything the harness does not. It does not make provider calls of its own. It does not
replace the scoring panel: judge-only scores are an engineering signal, and no conformance statement or
release decision rests on them without the panel sample and its alpha for the cycle (framework 4.3).

## Layout

```
gui/
├── server.js          zero-dependency HTTP server: JSON API, static files, progress event stream
├── lib/paths.js       finds the harness, the interpreter, the .env and the keys
├── lib/runner.js      spawns run.py, reads its progress lines, keeps the live run state
├── lib/results.js     reads results/<run_id>/ — judged rows, responses, variants, report
├── lib/catalog.js     class, principle and metric descriptions, condensed from the framework
└── public/            index.html, app.js, style.css
```

The progress channel is `run.py --progress`, which prints one `@@TIAB {json}` line per stage boundary and
per completed call alongside its normal output. Without the flag the harness prints exactly what it always
did.

---

Licensed under the Apache License 2.0; see `LICENSE` in the repository root.
