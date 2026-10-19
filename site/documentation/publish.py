"""Copy the generated guide and retain the downloadable Word compilation."""
from pathlib import Path
import shutil
import sys

source, destination = map(Path, sys.argv[1:])
assert (source / 'index.html').is_file()
assert destination.name == 'docs'
word = (destination / 'read.doc').read_bytes()
# The destination contains only generated documentation assets and this download.
if destination.exists():
    shutil.rmtree(destination)
shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.doctrees', '.buildinfo*'))
(destination / 'read.doc').write_bytes(word)
