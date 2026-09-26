"""External information sources for residents: news, social media, trade sites.

Layers, bottom up:

- :mod:`gaworld.infosources.schema` — ``Source`` (a registered place to read
  from) and ``InfoItem`` (one thing published there).
- :mod:`gaworld.infosources.registry` — ``data/info_sources.json`` → sources.
- :mod:`gaworld.infosources.channels` — fetch + parse per channel (RSS/Atom,
  Reddit, Hacker News, Weibo / Baidu / Bilibili hot lists, plain page).
- :mod:`gaworld.infosources.feed` — the real-time-TTL cache of recent items,
  and the process-wide runtime the news pipeline reads.
- :mod:`gaworld.infosources.diet` — per-resident media diet (job + interests +
  personality → weighted sources) and item selection.
- :mod:`gaworld.infosources.search` — DuckDuckGo / Brave / Tavily providers for
  the ``web_search`` engine chain.
- :mod:`gaworld.infosources.plugin` — the kernel plugin that wires it all in.

The plugin is deliberately not imported here so that importing the data layer
never pulls in the kernel.
"""

from __future__ import annotations

from gaworld.infosources.schema import CHANNELS, KIND_LABELS_ZH, KINDS, InfoItem, Source

__all__ = ["CHANNELS", "KINDS", "KIND_LABELS_ZH", "InfoItem", "Source"]
