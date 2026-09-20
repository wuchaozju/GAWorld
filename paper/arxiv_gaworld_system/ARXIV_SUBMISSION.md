# GAWorld arXiv submission handoff

## Manuscript identity

- Title: **GAWorld: Building Persistent and Situated LLM Agent Societies**
- Document type: English, single-column system paper
- Primary category recommendation: `cs.MA` (Multiagent Systems)
- Possible cross-list: `cs.AI` (Artificial Intelligence)
- Category selection remains the authors' decision.

## Author input required before upload

Replace the explicit fields in `main.tex` with the final:

- author names and ordering;
- affiliations;
- corresponding email address;
- ORCID identifiers, if the authors want them displayed;
- stable year or version date;
- acknowledgments and funding disclosures;
- code/project URL, after checking that the linked repository is intended to
  be public and that the paper version matches it.

The abstract submitted in arXiv metadata should be copied directly from the
final `main.tex`; do not maintain a second edited version here.

## Scientific checks

- [ ] Every author has read and approved the complete PDF.
- [ ] Every quantitative statement matches `artifact_ledger.md` and its hash.
- [ ] Capability cases are described as descriptive, partial, designed, or
      diagnostic rather than as real-world causal findings.
- [ ] The manuscript distinguishes the operational microkernel skeleton from
      K1--K5 completion with explicitly retained compatibility paths.
- [ ] The author team has checked text overlap with its own prior manuscripts,
      including the separate GAWorld-Bench paper.
- [ ] The authors accept responsibility for all AI-assisted text, citations,
      figures, and factual claims.
- [ ] License selection has been made by the rights holders in the arXiv form.

## Source archive policy

Official guidance: <https://info.arxiv.org/help/submit_tex.html>

The archive is compiled from its root with PDFLaTeX. It includes:

- `main.tex`;
- `references.bib` and the matching generated `main.bbl`;
- all twelve `sections/*.tex` files;
- the six `figures/*.pdf` files included by the manuscript.

It excludes `main.pdf`, figure TikZ sources, auxiliary files, logs, hidden
files, backup files, Git metadata, data artifacts, and files not used to build
the paper. arXiv accepts PDFLaTeX-compatible PDF, PNG, and JPG figures and does
not perform arbitrary figure conversion during compilation.

## Upload checklist

- [ ] Replace author placeholders and recompile locally.
- [ ] Confirm title, abstract, author order, categories, comments, and license.
- [ ] Re-run all artifact hashes and resolve any mismatch.
- [ ] Build and test `gaworld-arxiv-source.tar.gz` in isolation.
- [ ] Scan the source archive for credentials, user paths, private URLs,
      internal comments, and unrelated files.
- [ ] Upload the source archive through the authors' arXiv account.
- [ ] Select the processor detected for PDFLaTeX.
- [ ] Read the arXiv processing log and resolve every error.
- [ ] Open and inspect arXiv's generated PDF page by page before completing the
      submission; arXiv explicitly requires this preview step.
- [ ] Add journal reference or DOI later only if a corresponding publication
      becomes available.

Uploading and final metadata entry remain author actions; this package does
not submit the manuscript automatically.
