# GAWorld arXiv system paper

This directory contains the long-form, single-column system paper **GAWorld:
Building Persistent and Situated LLM Agent Societies**. It is independent of
the AAAI validation manuscript in `paper/aaai27_gaworld_bench/`: the present
paper describes GAWorld as research infrastructure, while existing runs are
used only as capability cases and boundary evidence.

## Evidence policy

- No new simulation is run and no LLM API is called to prepare this paper.
- Architecture claims are checked against current source paths and assigned an
  implementation status in `artifact_ledger.md`.
- Every reported number must cite a byte-level SHA-256 snapshot in the ledger.
- A single run, incomplete treatment, or diagnostic fixture is not presented as
  statistical, causal, population-valid, or real-policy evidence.
- Architecture is frozen at repository commit `35a551e`, after completion of
  the scoped K1--K5 migration and assembly of nine built-in plugins. Runtime
  and artifact hashes identify the audited evidence.
- Author names, affiliations, email addresses, and ORCIDs remain explicit
  placeholders until supplied by the authors.

## Package map

- `main.tex`: manuscript assembly and author placeholders.
- `sections/`: twelve independently reviewable manuscript sections.
- `figures/`: original TikZ sources and generated vector PDFs.
- `references.bib`: verified primary-source bibliography.
- `artifact_ledger.md`: implementation, result, status, and hash provenance.
- `ARXIV_SUBMISSION.md`: metadata, source packaging, and upload checklist.
- `arxiv-source/`: generated clean upload tree; ignored in the working package.

## Build

From this directory:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

The command is offline once the TeX dependencies are installed. `main.pdf` and
figure PDFs are deliverables and are intentionally not ignored. Auxiliary TeX
files and the generated arXiv source tree are ignored.

## Bibliography coverage

The verified bibliography is organized around:

- generative agents and grounded or synthetic populations;
- LLM-agent memory, planning, reflection, and situated action;
- social-agent and general agent evaluation;
- agent-based models, artificial societies, and empirical validation;
- negative controls and reproducibility boundaries.

Primary papers, proceedings, publishers, DOI records, and official project
pages are preferred over surveys. A citation is included only when it supports
the specific sentence in which it appears.

## arXiv packaging

The final upload tree is generated under `arxiv-source/` and tested in
isolation. It contains the manuscript sources, bibliography inputs, and the
six figure PDFs required by `main.tex`; it excludes the compiled manuscript,
figure-generation sources, logs, caches, hidden files, repository data, and
unrelated project material. See `ARXIV_SUBMISSION.md` for the author-facing
checklist.

## Audit utilities

Verify an artifact snapshot with:

```bash
shasum -a 256 PATH
```

Verify ledger status coverage and absence of drafting placeholders with:

```bash
rg -n 'IMPLEMENTED|PARTIALLY_INTEGRATED|DESIGNED|EVIDENCE_INCOMPLETE|DIAGNOSTIC_FIXTURE' artifact_ledger.md
rg -n 'T[B]D|T[O]DO|unknown path|fill later' artifact_ledger.md
```
