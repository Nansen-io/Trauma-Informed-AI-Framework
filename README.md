# Trauma Informed AI Safety Benchmark and Assurance Framework

**Version 1.0 — Published August 2026**
Andrew Collins and Rose Macdonald · The Digital Safeguard Centre (DSC)

A safety principle set, benchmark specification and assurance method for AI systems deployed in domestic and family violence (DFV) and technology facilitated abuse (TFA) contexts.

## Why this exists

General purpose AI safety evaluation does not test for the things that get people hurt in this work. A model can score well on every mainstream benchmark and still tell a woman to delete the spyware on her phone tonight, hand a client in Dublin a helpline in Melbourne, overstate certainty in a report headed for court, or carry on with a questionnaire after someone types that her ex-partner has just pulled up outside. Every failure mode in this framework has been observed in practice, not imagined.

The framework is deliberately model agnostic: it is the fixed measure, and base models are interchangeable components assessed against it.

## What's in this repository

| File | Description |
| --- | --- |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.0.pdf` | The published framework — read this |
| `Trauma Informed AI Safety Benchmark and Assurance Framework v1.0.docx` | Source document |

## The framework at a glance

- **Part A — the standard.** Eighteen safety principles written to be scoreable, a harm severity taxonomy (S0–S3), a benchmark specification with twenty-four seed test classes, and the data governance, ethics and standards mapping behind them.
- **Part B — the method.** How to register model call sites, classify and record defects, verify a deployed system read-only against its own documentation, and claim conformance at one of three levels (L1 declared, L2 verified, L3 independently assured).
- **Part C — the boundaries.** What a benchmark result does and does not establish, a claims register of what may and may not be said externally, post-deployment incident response, and what adoption genuinely costs.

One rule sits above the rest: **a single critical or high severity failure on the benchmark's critical set fails the release**, whatever the aggregate scores show.

## Who it's for

- **Executives, boards and funders** — read the executive summary, the conformance levels (Section 12) and the claims register (Section 13).
- **Procurement teams and frontline services** — you do not need to run a benchmark to use this framework. The Annex is a ten-question procurement checklist to put to any vendor.
- **Engineering and data teams** — Parts A and B in full, starting from the call site register (Section 9).
- **Smaller organisations** — Section 15 (Resourcing and Feasibility) first; it exists so the framework's ambitions do not outrun what a small service can honestly sustain.

## Scope and status

The framework applies to any AI system that advises, assesses or reports in DFV or TFA settings, and to any base model under consideration for deployment on those surfaces. It is global in application and Australian in anchor: adopters in other jurisdictions substitute the standards and risk instruments their sector recognises, and EU AI Act and GDPR alignment are treated as desirable best practice everywhere, not only where legally required.

The public benchmark item set is released progressively at [digitalsafeguard.org](https://digitalsafeguard.org); until its first release, the seed classes in Section 5 stand as the public benchmark's specification. Children as direct users are explicitly out of scope at v1.0 and are the named priority for v1.1.

## Feedback

Feedback is welcome through the contact form at [digitalsafeguard.org](https://digitalsafeguard.org) and informs version 1.1, which is in preparation.

## Licence

© The Digital Safeguard Centre. Released under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/), with an express permission for adopters to adapt the jurisdiction anchors, risk instruments and seed classes, and to author benchmark items on them, for their own conformance work under the framework. Republication of an adapted framework requires written permission. The private assurance suite and all casework-derived material sit outside this licence.

## Citation

> Collins, A. and Macdonald, R., *Trauma Informed AI Safety Benchmark and Assurance Framework*, version 1.0. The Digital Safeguard Centre, August 2026.
