# Trauma Informed AI Safety Benchmark and Assurance Framework

**Version 1.1 — Published 21 August 2026**
Andrew Collins and Rose Macdonald · The Digital Safeguard Centre (DSC)

A safety principle set, benchmark specification and assurance method for AI systems deployed in domestic and family violence (DFV) and technology facilitated abuse (TFA) contexts.

**Released publicly: the framework and the benchmark item set under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), the harness and tooling under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).** See [Licence](#licence).

## Why this exists

General purpose AI safety evaluation does not test for the things that get people hurt in this work. A model can score well on every mainstream benchmark and still tell a woman to delete the spyware on her phone tonight, hand a client in Dublin a helpline in Melbourne, overstate certainty in a report headed for court, or carry on with a questionnaire after someone types that her ex-partner has just pulled up outside. Every failure mode in this framework has been observed in practice, not imagined.

The framework is deliberately model agnostic: it is the fixed measure, and base models are interchangeable components assessed against it.

## What's in this repository

| File | Description |
| --- | --- |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.1.pdf` | The published framework — read this |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.1.docx` | Source document |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.0.docx` | Superseded first release, retained for citation continuity |
| `TIAB Journal Article Draft v0.7.docx` | Journal article manuscript (Collins, Macdonald, Romano and Alam), in preparation. **Not released under either licence** |
| `TESTING.md` | **How to run the benchmark and read the results** — start here if you are running a test rather than reading the framework |
| `benchmark/` | The public English seed item set and the harness that runs it. See below |
| `LICENSE`, `NOTICE` | Which licence applies to what |

## The framework at a glance

- **Part A — the standard.** Eighteen safety principles written to be scoreable, a harm severity taxonomy (S0–S3), a benchmark specification with twenty-three seed test classes, and the data governance, ethics and engineering integration behind them.
- **Part B — the method.** Named roles and records, how to register model call sites, classify and record defects, verify a deployed system read-only against its own documentation, and self-assess conformance at one of two levels (L1 declared, L2 verified).
- **Part C — the boundaries.** What a benchmark result does and does not establish, a claims register of what may and may not be said externally, post-deployment incident response, what adoption costs, and the relationship to ISO/IEC, NIST, Australian and European instruments.

One rule sits above the rest: **a single critical or high severity failure on the benchmark's critical set fails the release**, whatever the aggregate scores show.

## The benchmark

`benchmark/` is the instrument described in Part A, built and runnable:

- **187 items across 23 seed classes and four suites** — D (digital safety audit), G (generated reports), R (risk assessment), X (cross-cutting). Each item is a versioned record carrying persona, jurisdiction, prior conversation, fixture, expected and forbidden behaviours, gold labels, and plain-language definitions of what counts as an S0, S1 or S2 failure *for that item*.
- **Three scoring instruments, none trusted alone** — deterministic validators, a calibrated model judge, and a human scoring panel. **Instances, not scores, decide the gates**, and every instance carries the quote that raised it.
- **A control panel** (`cd benchmark/gui && npm start`) — choose the run size, watch the run happen, and read the results back with the framework's vocabulary attached. One dashboard table: systems down the side, the framework's criteria across the top, red or green per cell. No dependencies to install.
- **A preflight check** (`python harness/doctor.py --probe`) — because an instrument that is broken produces findings that look exactly like real ones. A stale model id once produced 288 errors and 266 fabricated safety failures against a model that was never successfully called.
- **An outcome taxonomy that separates instrument failure from system failure.** Only `scored` and `unavailable` rows reach the gates; a bad key or an unreachable bridge raises no instance and is reported separately. A gate with nothing behind it reads **NOT ESTABLISHED**, never as a pass.
- **A bridge** (`benchmark/bridge`) for testing a deployed product through its real API rather than a bare model, which is what an L2 claim needs.

Read [TESTING.md](TESTING.md) to run it, and `benchmark/README.md` for item design, validator behaviour, the scoring panel workflow, and the framework sections each part implements.

**Status: `1.1-public-seed-en`, pre-release.** The items were authored against the seed classes and reviewed for publication risk; before the set is cited as *the* public benchmark it needs practitioner sign-off item by item, survivor advisory panel review of realism and dignity, and a versioned release with a DOI. Judge-only scores are an engineering signal: without the scoring panel sample and its alpha for the cycle, no run here supports a conformance statement, a release decision or an external claim.

## Who it's for

- **Executives, boards and funders** — read the executive summary, the conformance levels (Section 12) and the claims register (Section 13).
- **Engineering and data teams** — Parts A and B in full, starting from roles and records (Section 8) and the call site register (Section 9); then `benchmark/` to run the instrument.
- **Procurement teams and frontline services** — you do not need to run a benchmark to use this framework. The Annex is a ten-question procurement checklist to put to any vendor.
- **Smaller organisations** — Section 15 (Resourcing and Feasibility) first; it exists so the framework's ambitions do not outrun what a small service can honestly sustain.

## Conformance

Conformance under the framework is self-assessed at two levels, L1 declared and L2 verified, against evidence the adopter retains and discloses on request. No party, including the Centre, certifies conformance, and neither open licence in this repository changes that. The Centre applies the framework to its own systems as an adopter on the same terms as anyone else.

## Scope and status

The framework applies to any AI system that advises, assesses or reports in DFV or TFA settings, and to any base model under consideration for deployment on those surfaces. It is global in application and Australian in anchor: adopters in other jurisdictions substitute the standards and risk instruments their sector recognises, and EU AI Act and GDPR alignment are treated as desirable best practice everywhere, not only where legally required.

The public benchmark item set is in `benchmark/items/` and is released under CC BY 4.0 alongside the framework; further releases are announced at [digitalsafeguard.org](https://digitalsafeguard.org). Children as direct users are explicitly out of scope; a child-user extension and culturally safe test development led by Aboriginal and Torres Strait Islander practitioners are the named priorities for v1.2. Version 1.1 withdrew seed class X007 and rewrote principle P15 so that no referral pathway is ever withheld and the choice stays with the person.

## Feedback

Feedback is welcome through the contact form at [digitalsafeguard.org](https://digitalsafeguard.org) and informs version 1.2, which is in preparation. Report a validator false positive with the `detail` string and the response text; report an item problem with the item id.

## Licence

Copyright © 2026 The Digital Safeguard Centre. This work is released publicly under two open licences, split by what the material is:

| What | Licence |
| --- | --- |
| The framework documents, the 187-item benchmark set, and all documentation | **CC BY 4.0** — share and adapt, including commercially, with attribution |
| The harness, control panel and bridge — all source code | **Apache License 2.0** |

SPDX: `CC-BY-4.0 AND Apache-2.0`. Full texts are in [LICENSE-CC-BY-4.0.txt](LICENSE-CC-BY-4.0.txt) and [LICENSE-APACHE-2.0.txt](LICENSE-APACHE-2.0.txt); [LICENSE](LICENSE) maps every path to its licence and records the exceptions.

Both licences permit adaptation of jurisdiction anchors, risk instruments and seed classes, authoring of further items, and use in paid conformance work, provided attribution is kept. An adaptation must not be presented as the Centre's published framework or as carrying its endorsement, and neither licence grants any right to imply certification or conformance.

Not released: the journal article manuscript (all rights reserved, in preparation for peer review), run outputs under `benchmark/results/`, the Centre's name and marks, and the Centre's own private assurance suite and casework-derived material, which are not in this repository.

This material concerns systems used by people at risk of serious harm. Both licences disclaim warranty and liability, and that disclaimer is meant literally: this is offered as a measure, not as an assurance.

## Citation

> Collins, A. and Macdonald, R., *Trauma Informed AI Safety Benchmark and Assurance Framework*, version 1.1. The Digital Safeguard Centre, August 2026. Licensed under CC BY 4.0.

For the instrument specifically:

> Collins, A. and Macdonald, R., *TIAB public benchmark, English seed set, version 1.1-public-seed-en (pre-release)*. The Digital Safeguard Centre, August 2026.
