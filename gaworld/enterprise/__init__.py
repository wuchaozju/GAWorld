"""Enterprise user data → anonymised GAWorld agents, packed as one zip.

CLI: ``python -m gaworld.enterprise users.csv -o agents.zip`` — see
:mod:`gaworld.enterprise.pack` for what is kept, replaced and dropped.
"""

from gaworld.enterprise.pack import anonymise, build_package, prepare

__all__ = ["anonymise", "build_package", "prepare"]
