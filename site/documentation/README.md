# GAWorld documentation

The documentation uses Sphinx 9.1.0 and Furo 2025.12.19. The reading layout follows the AgentSociety 2 documentation reference; the brand, examples, configuration and APIs describe GAWorld.

## Build

```bash
python -m pip install -r site/documentation/requirements.txt
python site/documentation/generate_api.py .
python -m sphinx -W --keep-going -b html site/documentation /tmp/gaworld-docs
python site/documentation/publish.py /tmp/gaworld-docs site/home/docs
```

`generate_api.py` reads source signatures and docstrings through Python AST without importing runtime modules. Regenerate API pages after changing public signatures. The publication helper retains `read.doc` while replacing generated HTML and assets.

Chapters follow GAWorld tasks: setup, cities and residents, simulation and observation, research and experiments, deployment and extensions, and interface references. Existing repository documents remain in their original locations. Old documentation URLs redirect to their corresponding chapters.
