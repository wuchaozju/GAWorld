"""Capture executable bytes once; workers import only a verified per-study bundle."""

import ast
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
_SOURCES = {p.name: p.read_bytes() for p in sorted(_ROOT.glob("*.py"))}


def sources():
    return dict(_SOURCES)


def fingerprint(values):
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(values.items())}
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"build_id": build_id, "files": hashes}


def identity():
    version = next(
        node.value.value
        for node in ast.parse(_SOURCES["protocol.py"]).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets)
    )
    current = fingerprint({p.name: p.read_bytes() for p in sorted(_ROOT.glob("*.py"))})
    manifest = fingerprint(_SOURCES)
    return {
        "version": version,
        "build_id": manifest["build_id"],
        "workspace_build_id": current["build_id"],
        "workspace_matches": current == manifest,
        "external_calls": 0,
    }


def freeze(directory):
    directory = Path(directory)
    (directory / "engine").mkdir(parents=True, exist_ok=False)
    for name, data in _SOURCES.items():
        (directory / "engine" / name).write_bytes(data)
    manifest = fingerprint(_SOURCES)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


_BOOTSTRAP = """
import hashlib, importlib.abc, importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / 'manifest.json').read_text())
expected = sys.argv[3]
computed = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
if computed != expected or manifest['build_id'] != expected:
    raise ValueError('frozen build manifest mismatch')
verified = {}
for name, expected_hash in manifest['files'].items():
    if pathlib.Path(name).name != name or not name.endswith('.py'):
        raise ValueError('invalid build file')
    data = (root / 'engine' / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('frozen build source mismatch: ' + name)
    verified[name] = data
class VerifiedLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'engine' and not fullname.startswith('engine.'):
            return None
        name = '__init__.py' if fullname == 'engine' else fullname[7:] + '.py'
        if name not in verified:
            raise ImportError('module absent from frozen build: ' + fullname)
        return importlib.util.spec_from_loader(fullname, self, is_package=fullname == 'engine')
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        name = '__init__.py' if module.__name__ == 'engine' else module.__name__[7:] + '.py'
        filename = str(root / 'engine' / name)
        module.__file__ = filename
        exec(compile(verified[name], filename, 'exec'), module.__dict__)
sys.meta_path.insert(0, VerifiedLoader())
from engine.worker import main
main(pathlib.Path(sys.argv[2]), expected, sys.argv[4:])
"""


def command(directory, database, *args):
    manifest = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
    return [
        sys.executable,
        "-I",
        "-B",
        "-c",
        _BOOTSTRAP,
        str(Path(directory).resolve()),
        str(Path(database).resolve()),
        manifest["build_id"],
        *args,
    ]
