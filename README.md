# Trauma Informed AI Safety Benchmark and Assurance Framework

**Version 1.1 — Published 21 August 2026**
Andrew Collins and Rose Macdonald · The Digital Safeguard Centre (DSC)

A safety principle set, benchmark specification and assurance method for AI systems deployed in domestic and family violence (DFV) and technology facilitated abuse (TFA) contexts.

## Why this exists

General purpose AI safety evaluation does not test for the things that get people hurt in this work. A model can score well on every mainstream benchmark and still tell a woman to delete the spyware on her phone tonight, hand a client in Dublin a helpline in Melbourne, overstate certainty in a report headed for court, or carry on with a questionnaire after someone types that her ex-partner has just pulled up outside. Every failure mode in this framework has been observed in practice, not imagined.

The framework is deliberately model agnostic: it is the fixed measure, and base models are interchangeable components assessed against it.

## What's in this repository

| File | Description |
| --- | --- |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.1.pdf` | The published framework — read this |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.1.docx` | Source document |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.0.docx` | Superseded first release, retained for citation continuity |
| `TIAB Journal Article Draft v0.7.docx` | Journal article manuscript (Collins, Macdonald, Romano and Alam), in preparation |
| `TESTING.md` | **How to run the benchmark and read the results** — start here if you are running a test rather than reading the framework. |
| `benchmark/` | The public English seed item set (200 items, 23 classes) and the run, validate, judge and analysis harness. See `benchmark/README.md` for set-up, running, the scoring panel workflow and what a run does and does not establish. `benchmark/gui` (`npm start`) is a local control panel over it: choose the run size, watch the run happen, and read the results back with the framework's vocabulary attached. |

## The framework at a glance

- **Part A — the standard.** Eighteen safety principles written to be scoreable, a harm severity taxonomy (S0–S3), a benchmark specification with twenty-three seed test classes, and the data governance, ethics and engineering integration behind them.
- **Part B — the method.** Named roles and records, how to register model call sites, classify and record defects, verify a deployed system read-only against its own documentation, and self-assess conformance at one of two levels (L1 declared, L2 verified).
- **Part C — the boundaries.** What a benchmark result does and does not establish, a claims register of what may and may not be said externally, post-deployment incident response, what adoption costs, and the relationship to ISO/IEC, NIST, Australian and European instruments.

One rule sits above the rest: **a single critical or high severity failure on the benchmark's critical set fails the release**, whatever the aggregate scores show.

## Who it's for

- **Executives, boards and funders** — read the executive summary, the conformance levels (Section 12) and the claims register (Section 13).
- **Engineering and data teams** — Parts A and B in full, starting from roles and records (Section 8) and the call site register (Section 9); then `benchmark/` to run the instrument.
- **Procurement teams and frontline services** — you do not need to run a benchmark to use this framework. The Annex is a ten-question procurement checklist to put to any vendor.
- **Smaller organisations** — Section 15 (Resourcing and Feasibility) first; it exists so the framework's ambitions do not outrun what a small service can honestly sustain.

## Conformance

Conformance under the framework is self-assessed at two levels, L1 declared and L2 verified, against evidence the adopter retains and discloses on request. No party, including the Centre, certifies conformance. The Centre applies the framework to its own systems as an adopter on the same terms as anyone else.

## Scope and status

The framework applies to any AI system that advises, assesses or reports in DFV or TFA settings, and to any base model under consideration for deployment on those surfaces. It is global in application and Australian in anchor: adopters in other jurisdictions substitute the standards and risk instruments their sector recognises, and EU AI Act and GDPR alignment are treated as desirable best practice everywhere, not only where legally required.

The public benchmark item set is released progressively at [digitalsafeguard.org](https://digitalsafeguard.org); until its first release, the seed classes in Section 5 stand as the public benchmark's specification. Children as direct users are explicitly out of scope; a child-user extension and culturally safe test development led by Aboriginal and Torres Strait Islander practitioners are the named priorities for v1.2. Version 1.1 withdrew seed class X007 and rewrote principle P15 so that no referral pathway is ever withheld and the choice stays with the person.

## Feedback

Feedback is welcome through the contact form at [digitalsafeguard.org](https://digitalsafeguard.org) and informs version 1.2, which is in preparation.

## Licence

© The Digital Safeguard Centre. Released under The Digital Safeguard Centre Framework Licence: reproduction and citation with attribution; adaptation of jurisdiction anchors, risk instruments and seed classes, and authoring of benchmark items, for conformance work under the framework including paid assessment; republication of an adapted framework and other commercial use require written permission. It is not a Creative Commons licence. The Centre's own private assurance suite and casework-derived material sit outside it.

## Citation

> Collins, A. and Macdonald, R., *Trauma Informed AI Safety Benchmark and Assurance Framework*, version 1.1. The Digital Safeguard Centre, August 2026.
