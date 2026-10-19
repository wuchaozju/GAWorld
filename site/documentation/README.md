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

## Visitor map

The sidebar uses the owner's MapMyVisitors map-counter embed. The component is enabled for `https://s2014628.github.io/gaworld-bench/world/docs/` only. The script stays inert inside a template until `_static/visitors.js` verifies the hostname, HTTPS scheme and documentation path; local previews and the private mirror send no counter requests.

1. The site owner creates a map counter at <https://mapmyvisitors.com/> for `https://s2014628.github.io/gaworld-bench/world/docs/` and supplies the public embed code. Account passwords are not needed.
2. Put that site's official embed in `_templates/sidebar/visitor-embed.html`. Keep its site identifier and required script element ID intact. Match the map size and colors using the provider's supported options.
3. Set `html_context['visitor_widget_enabled']` in `conf.py` to `True`.
4. Build and verify the actual widget, its metric labels, its dashboard destination, and the sidebar at desktop and mobile widths before publishing. Use the provider's distinction between visits, pageviews, and unique visitors.

The component lives below the left navigation. An absent embed keeps it hidden even when the enable flag is set. Test the registered hostname through local request interception, mocking the provider's traffic so QA does not inflate statistics. Tracking begins when the configured widget is deployed; there is no imported historical count. Configure other hostnames separately if they should have their own statistics. The provider supplies the count and map; the documentation does not generate visitor numbers.

## Homepage logo animation

`_static/brand-reveal.js` introduces the existing G logo as interacting resident nodes, then forms the letter and returns to the original SVG. It runs on the documentation homepage once per tab session. On mobile, opening the navigation reveals the logo and starts the animation. Reduced-motion preferences show the static logo immediately. No animation library or additional network request is required.

Browser regression checks use `tests/docs-widgets.test.cjs`. Set `GAWORLD_DOCS_BUILD` to the HTML build directory. The checks use Playwright (`GAWORLD_PLAYWRIGHT_MODULE` optionally selects its installed module; `GAWORLD_BROWSER` optionally selects a Chromium executable) and intercept all network requests, including the visitor provider.
