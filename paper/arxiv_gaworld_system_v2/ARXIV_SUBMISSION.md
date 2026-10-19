# GAWorld v2 arXiv submission handoff

## Manuscript identity

- Title: **GAWorld v2: A Configurable Research Stack for LLM-Based
  Artificial Societies**
- Document type: English, single-column system paper, journal-quality
- Manuscript length: 48 pages, ~24,000 words
- Figures: 10 vector PDFs (TikZ) + 8 dashboard screenshots (PNG)
- Primary category recommendation: `cs.MA` (Multiagent Systems)
- Possible cross-list: `cs.AI` (Artificial Intelligence), `cs.CY`
  (Computers and Society)
- Category selection remains the authors' decision.

## Differences from the v1 system paper

The v1 system paper (`../arxiv_gaworld_system/`) audited a single
repository commit (`35a551e`) with nine built-in plugins.  The v2
system paper extends the audit to a newer commit with fourteen
built-in plugins and three further migrations:

- **K6: per-tenant world resolution** (multi-tenant accounts, world
  isolation, role-based visibility, per-tenant quotas, audit).
- **K7: hub-and-node distribution** (cluster, DistributedRelayBackend,
  /api/cluster/* dashboard routes, player intervention routing across
  nodes, clock synchronization as published median, best-effort
  delivery).
- **K8: parallel-worlds execution** (up to eight matched worlds,
  shared seed, per-world config patch, deterministic counterfactual
  inference, optional one-call model interpretation).

The v2 paper also adds:

- The Agent Playground of fourteen game-based probes and the Agent
  Arena benchmark;
- The Research Workbench that compiles a paper or research idea into
  a pre-registered protocol and a deterministic verdict;
- The persona-distillation module and the separate distill / deploy
  workflow;
- A sixth claim level, *participant evaluation*, to cover the new
  game-based surfaces;
- The evidence-class taxonomy (`REAL`, `DIAGNOSTIC`, `SYNTHETIC`,
  `INCOMPLETE`, `DESIGNED`, `FIXTURE`) applied to every reported
  number;
- Four new figures (`hub_node`, `multi_tenant`, `plugin_assembly`,
  `parallel_worlds`); the six v1 figures are reused.

The v1 paper is not superseded by v2: the v1 audit is a snapshot
record, and the v2 paper is a forward extension.  A reader who
wishes to read both should read v1 first and v2 second.

## Author input required before upload

Replace the explicit fields in `main.tex` with the final:

- author names and ordering;
- affiliations;
- corresponding email address;
- ORCID identifiers, if the authors want them displayed;
- stable year or version date;
- acknowledgments and funding disclosures;
- code/project URL, after checking that the linked repository is
  intended to be public and that the paper version matches it.

The abstract submitted in arXiv metadata should be copied directly
from the final `main.tex`; do not maintain a second edited version
here.

## Scientific checks

- [ ] Every author has read and approved the complete PDF.
- [ ] Every quantitative statement matches the artifact ledger and its
      hash.
- [ ] Capability cases are described as descriptive, partial,
      designed, or diagnostic rather than as real-world causal
      findings.
- [ ] The manuscript distinguishes the K1--K5 migration from the v1
      audit, the K6--K8 migrations from the v2 audit, and the
      per-tenant isolation, hub-node protocol, and parallel-worlds
      engine as separate, auditable subsystems.
- [ ] The author team has checked text overlap with the v1 system
      paper and with the AAAI-27 bench paper.
- [ ] The authors accept responsibility for all AI-assisted text,
      citations, figures, and factual claims.
- [ ] License selection has been made by the rights holders in the
      arXiv form.

## Source archive policy

Official guidance: <https://info.arxiv.org/help/submit_tex.html>

The archive is compiled from its root with PDFLaTeX.  It includes:

- `main.tex`;
- `references.bib` and the matching generated `main.bbl`;
- the fifteen `sections/*.tex` files;
- the three `supplementary/*.tex` files;
- the ten `figures/*.pdf` vector figures included by the
  manuscript;
- the eight `figures/*.png` dashboard screenshots included by the
  manuscript (Console, Agent Studio, Research Workbench, Parallel
  Worlds tab, Agent Playground, Agent Arena, Cities panel, and
  Analytics pane).

It excludes `main.pdf`, figure TikZ sources, auxiliary files, logs,
hidden files, backup files, Git metadata, data artifacts, and files
not used to build the paper.  arXiv accepts PDFLaTeX-compatible
PDF, PNG, and JPG figures and does not perform arbitrary figure
conversion during compilation.

## Upload checklist

- [ ] Replace author placeholders and recompile locally.
- [ ] Confirm title, abstract, author order, categories, comments,
      and license.
- [ ] Re-run all artifact hashes and resolve any mismatch.
- [ ] Build and test `gaworld-v2-arxiv-source.tar.gz` in isolation.
- [ ] Scan the source archive for credentials, user paths, private
      URLs, internal comments, and unrelated files.
- [ ] Upload the source archive through the authors' arXiv account.
- [ ] Select the processor detected for PDFLaTeX.
- [ ] Read the arXiv processing log and resolve every error.
- [ ] Open and inspect arXiv's generated PDF page by page before
      completing the submission; arXiv explicitly requires this
      preview step.
- [ ] Add journal reference or DOI later only if a corresponding
      publication becomes available.

Uploading and final metadata entry remain author actions; this
package does not submit the manuscript automatically.
