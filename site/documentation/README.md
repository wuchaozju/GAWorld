# Build the GAWorld documentation

This directory contains the public user guide. The existing repository documents and Word compilation remain separate source material.

Install the pinned packages from `requirements.txt`. From the directory containing `documentation/`, run:

```bash
python -m sphinx -W --keep-going -b html documentation /tmp/gaworld-docs-build
python documentation/publish.py /tmp/gaworld-docs-build dist/docs
```

The site uses the official Furo theme, with GAWorld colors and type sizes. Sources for the guide are the current README, MODEL_PROVIDERS, TUTORIAL.v2, CITY_TUTORIAL, API_REFERENCE, CONTRIBUTING and the command-line implementation. Published content focuses on operation; historical proposals and internal design files stay in the repository.

In the GAWorld repository, these sources live at `site/documentation/` and the generated destination is `site/home/docs/`. Preserve `read.doc` in the destination when rebuilding.
