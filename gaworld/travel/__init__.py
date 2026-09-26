"""Leaving the city: business trips, family visits, holidays.

The city is not a closed box. Residents already *have* an elsewhere — the
social layer gives every one of them off-screen kin and friends with a
``city`` of their own (``gaworld/social/network.py``), and the family layer
already tells them to "call your parents, or go back and see them"
(``gaworld/family/duties.py``). Until now the second half of that sentence
was unactionable: nothing could take an agent off the map.

This package supplies the missing displacement, and nothing else:

* :mod:`~gaworld.travel.destination` — where to, how far, how long, how much
  (real coordinates, offline, reusing the twin's province table);
* :mod:`~gaworld.travel.trigger` — who leaves and why, driven by quantities
  the simulation already tracks (job, relationship obligation, cash, traits);
* :mod:`~gaworld.travel.itinerary` — what a day away looks like;
* :mod:`~gaworld.travel.plugin` — the wiring.

What "away" *means* to the rest of the world is defined once, in
:mod:`gaworld.world.away`, because the digital twin marks real out-of-town
positions the same way.

Off by default: it changes who is present in the city, so runs from before it
was switched on are not comparable.
"""

from __future__ import annotations
