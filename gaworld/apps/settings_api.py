"""Dashboard backend for the 配置 panel — the whole CONFIG tree in one place.

Until now the project's configuration was spread across four surfaces with no
single view of any of them: the Python defaults in ``gaworld/settings/*.py``,
the ``dashboard_config.json`` override file, the ``GAWORLD_CONFIG_OVERRIDES``
env blob, and ``data/environment_config.json`` — which, per
``settings/overrides.py``, is applied *last* and therefore silently wins over
the other two for the keys it names. Four design points:

**Every value is reported with its provenance.** A panel that shows only the
effective value invites the most expensive kind of confusion: you edit a knob,
the save succeeds, and nothing changes because a later override layer wins.
Each leaf carries ``source`` (default / dashboard / env / env_file) and its
untouched default, so an ineffective edit is visible *before* you make it.

**Writes go to ``dashboard_config.json``, never to the Python source.** The
defaults are code — versioned, reviewed, and imported at process start. The
override file is the mechanism the project already has for "change this run",
and ``_effective_config`` already layers it. Reset therefore means *removing*
a key from the override file, not writing a default back into it.

**Patches are shape-coerced, not whitelisted.** ~600 leaves; a per-field
validator would be longer than this module and would rot on the next knob. The
coercion in ``external_systems_api`` already solves this, so it is reused
rather than reimplemented — one behaviour, one place to fix it.

**Secrets are reported as present/absent, never echoed.** Env vars come back
masked and read-only; the panel links to ``.env`` instead of editing it. A
dashboard bound to 0.0.0.0 should not be a key-exfiltration endpoint.
"""

from __future__ import annotations

import os
import re
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.settings import config_docs
from gaworld.settings.defaults import build_default_config
from gaworld.settings.overrides import load_env_override, load_environment_config

_LOG = get_logger("gaworld.dashboard.settings")

#: Top-level keys the generic tree editor refuses to write even though they are
#: in the tree. ``llm.providers`` holds inline ``api_key`` values for local
#: backends, so a free-form patch into it is a credential write path; the rest
#: of ``llm`` (routing) stays editable. Providers are edited instead through
#: :func:`save_provider`, which takes a fixed field set and no key material.
_READ_ONLY_PATHS: frozenset[str] = frozenset({"llm.providers"})

#: Env var names whose value must never be echoed, matched case-insensitively
#: as a substring. Everything else (log level, base URLs) shows in full.
_SECRET_HINT = re.compile(r"key|token|secret|password|auth", re.IGNORECASE)

#: A provider name becomes a dotted config path and a DOM id, so keep it to the
#: characters that are unambiguous in both.
_PROVIDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

#: Editable keys per backend type, with the coercion each one needs. Anything
#: else in an incoming provider block is dropped rather than written through —
#: same stance as ``_coerce_like``: a typo must not plant a key the router
#: never reads.
#:
#: ``api_key`` is deliberately absent. ``dashboard_config.json`` is a tracked
#: file, so a key typed into this panel would land in git; the panel takes an
#: env var *name* instead and reports whether it is set.
_PROVIDER_FIELDS: dict[str, dict[str, str]] = {
    "ollama": {"url": "str", "model": "str", "timeout": "int"},
    "openai": {
        "base_url": "str",
        "model": "str",
        "api_key_env": "str",
        "timeout": "int",
        "stream": "bool",
        "max_tokens": "int",
        "temperature": "float",
    },
    "anthropic": {
        "base_url": "str",
        "model": "str",
        "api_key_env": "str",
        "timeout": "int",
        "max_tokens": "int",
    },
}

#: Which field carries the endpoint, per type — required alongside ``model``.
_PROVIDER_ENDPOINT = {"ollama": "url", "openai": "base_url", "anthropic": "base_url"}


def _ds():
    from gaworld.apps import dashboard_server

    return dashboard_server


def _repo_root() -> str:
    return _ds().REPO_ROOT


def _wire_safe(value: Any) -> Any:
    """Reuse the External Systems wire encoding (``Infinity`` → ``"Infinity"``)."""
    from gaworld.apps.external_systems_api import _wire_safe as encode

    return encode(value)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts to dotted paths. Lists are leaves, not containers."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict) and item:
                out.update(_flatten(item, path))
            else:
                out[path] = item
        return out
    if prefix:
        out[prefix] = value
    return out


def _override_layers() -> dict[str, dict[str, Any]]:
    """The three layers stacked on top of the Python defaults, in apply order.

    Mirrors ``settings.overrides.apply_runtime_overrides``: dashboard file
    first, then the env blob, then ``environment_config.json`` — which is why
    ``env_file`` beats ``env`` for the handful of keys it carries.
    """
    ds = _ds()
    defaults = build_default_config()
    env_file_path = defaults.get("environment_config_path")
    return {
        "dashboard": ds._dashboard_config(),
        "env": load_env_override(),
        "env_file": load_environment_config(env_file_path),
    }


def _source_map() -> dict[str, str]:
    """Dotted path -> the name of the layer that produced the effective value."""
    sources: dict[str, str] = {}
    for layer, payload in _override_layers().items():
        for path in _flatten(payload):
            sources[path] = layer
    return sources


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def _doc_map(tree: dict[str, Any]) -> dict[str, dict[str, str]]:
    """``path -> {label, help}`` for every node that has either.

    Container nodes are included too: a group header carries the explanation of
    what the whole subtree is for, which is usually the sentence a user needs
    before any individual leaf makes sense.
    """
    docs: dict[str, dict[str, str]] = {}

    def visit(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                entry: dict[str, str] = {}
                label = config_docs.label_for(path)
                if label != path.rsplit(".", 1)[-1]:
                    entry["label"] = label
                help_text = config_docs.help_for(path)
                if help_text:
                    entry["help"] = help_text
                # Both languages travel together and the browser picks, so this
                # payload stays locale-agnostic and cacheable. An absent *_en
                # means no English exists; the panel then shows the Chinese,
                # which is the truth rather than a guess.
                label_en = config_docs.label_en_for(path)
                if label_en and label_en != label:
                    entry["label_en"] = label_en
                help_en = config_docs.help_en_for(path)
                if help_en:
                    entry["help_en"] = help_en
                if entry:
                    docs[path] = entry
                visit(item, path)

    visit(tree, "")
    return docs


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------


def _parse_env_example(path: str) -> list[dict[str, str]]:
    """Read ``.env.example`` as the catalogue of env vars, with its comments.

    The example file is already maintained as documentation — reusing it means
    a new variable shows up in the panel the moment someone documents it, with
    no second list to keep in sync.
    """
    entries: list[dict[str, str]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return entries
    comment: list[str] = []
    group = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            comment = []
            continue
        if line.startswith("#"):
            text = line.lstrip("#").strip()
            banner = re.match(r"^-{2,}\s*(.+?)\s*-{2,}$", text)
            if banner:
                group = banner.group(1)
                comment = []
            elif text and not set(text) <= {"=", "-"}:
                comment.append(text)
            continue
        if "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if not name:
            continue
        entries.append({"name": name, "group": group, "help": " ".join(comment)})
        comment = []
    return entries


def _mask(name: str, value: str) -> str:
    if not value:
        return ""
    if not _SECRET_HINT.search(name):
        return value if len(value) <= 120 else value[:117] + "…"
    if len(value) <= 8:
        return "•" * len(value)
    return value[:3] + "…" + value[-4:]


def _env_snapshot() -> dict[str, Any]:
    """Documented env vars plus their presence — values masked when secret."""
    catalogue = _parse_env_example(os.path.join(_repo_root(), ".env.example"))
    known = {item["name"] for item in catalogue}
    # Anything a provider names but the example file forgot still matters.
    for provider in build_default_config().get("llm", {}).get("providers", {}).values():
        if not isinstance(provider, dict):
            continue
        names = list(provider.get("api_key_envs") or [])
        if provider.get("api_key_env"):
            names.append(provider["api_key_env"])
        for name in names:
            if name not in known:
                known.add(name)
                catalogue.append({"name": name, "group": "LLM providers", "help": ""})
    vars_out = []
    for item in catalogue:
        raw = os.environ.get(item["name"], "")
        vars_out.append(
            {
                "name": item["name"],
                "group": item.get("group", ""),
                "help": item.get("help", ""),
                "set": bool(raw),
                "value": _mask(item["name"], raw),
                "secret": bool(_SECRET_HINT.search(item["name"])),
            }
        )
    return {
        "vars": vars_out,
        "env_file": os.path.join(_repo_root(), ".env"),
        "env_file_exists": os.path.exists(os.path.join(_repo_root(), ".env")),
    }


# ---------------------------------------------------------------------------
# Raw config files
# ---------------------------------------------------------------------------


def _raw_file(path: str, *, max_chars: int = 200_000) -> dict[str, Any]:
    info: dict[str, Any] = {"path": path, "exists": os.path.exists(path), "text": ""}
    if not info["exists"]:
        return info
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(max_chars + 1)
    except OSError as exc:
        info["error"] = str(exc)
        return info
    if len(text) > max_chars:
        text = text[:max_chars] + "\n… (truncated)"
    info["text"] = text
    return info


def _raw_files() -> dict[str, Any]:
    root = _repo_root()
    defaults = build_default_config()
    env_config = defaults.get("environment_config_path") or "data/environment_config.json"
    if not os.path.isabs(env_config):
        env_config = os.path.join(root, env_config)
    return {
        "dashboard_config": _raw_file(_ds().DASHBOARD_CONFIG_PATH),
        "environment_config": _raw_file(env_config),
    }


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------


def _providers(tree: dict[str, Any]) -> dict[str, Any]:
    block = (tree.get("llm") or {}).get("providers")
    return block if isinstance(block, dict) else {}


def _redact(tree: dict[str, Any]) -> dict[str, Any]:
    """Copy ``tree`` with inline provider keys masked.

    Two local backends ship a literal ``api_key`` in the Python defaults, so the
    unredacted tree hands them to every browser that opens the panel — against
    this module's own "secrets are reported as present/absent" rule. Masking on
    the wire only; :func:`save_config` still coerces against the real config.
    """
    providers = _providers(tree)
    if not any(isinstance(cfg, dict) and cfg.get("api_key") for cfg in providers.values()):
        return tree
    out = dict(tree)
    out["llm"] = dict(out["llm"])
    out["llm"]["providers"] = {
        name: (dict(cfg, api_key="••••••") if isinstance(cfg, dict) and cfg.get("api_key") else cfg)
        for name, cfg in providers.items()
    }
    return out


def _choice_map(tree: dict[str, Any]) -> dict[str, list[str]]:
    """Dotted path -> the closed set of values it may take.

    Only routing today. Routing values *are* provider names, and a free-text box
    for one is a trap: a typo reads as a valid config right up until the run
    dies on "Provider 'ollama_gemm4' not found".
    """
    names = sorted(_providers(tree))
    if not names:
        return {}
    routing = (tree.get("llm") or {}).get("routing") or {}
    choices = {"llm.routing.default": names}
    for task in (routing.get("tasks") or {}):
        choices[f"llm.routing.tasks.{task}"] = names
    for agent in (routing.get("agents") or {}):
        choices[f"llm.routing.agents.{agent}"] = names
    return choices


def _provider_view(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Provider rows for the picker card: what it is, where it points, is it usable.

    The key is reported as *which env var* and *is it set* — never the value.
    """
    routing = (tree.get("llm") or {}).get("routing") or {}
    layer = _ds()._dashboard_config()
    added = set(_providers(layer))
    rows = []
    for name, cfg in sorted(_providers(tree).items()):
        if not isinstance(cfg, dict):
            continue
        p_type = str(cfg.get("type") or "")
        envs = [str(item) for item in (cfg.get("api_key_envs") or []) if item]
        if cfg.get("api_key_env") and str(cfg["api_key_env"]) not in envs:
            envs.insert(0, str(cfg["api_key_env"]))
        rows.append(
            {
                "name": name,
                "type": p_type,
                "model": str(cfg.get("model") or ""),
                "endpoint": str(cfg.get(_PROVIDER_ENDPOINT.get(p_type, "base_url")) or ""),
                "timeout": cfg.get("timeout"),
                "api_key_envs": envs,
                # Inline keys are the local-backend placeholders; "has a key" is
                # all the browser needs to know about them.
                "key_ready": bool(cfg.get("api_key")) or any(os.environ.get(n) for n in envs),
                "needs_key": p_type in ("openai", "anthropic", "claude"),
                "editable": name in added,
                "is_default": name == routing.get("default"),
            }
        )
    return rows


def _coerce_field(value: Any, kind: str, path: str) -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        raise ValueError(f"{path} 必须是 true/false")
    if kind in ("int", "float"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{path} 必须是数字") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{path} 必须是有限数字")
        return int(number) if kind == "int" else number
    return str(value)


def _clean_provider(payload: Any) -> tuple[str, dict[str, Any]]:
    """Validate an incoming provider block down to ``(name, config)``.

    Raises :class:`ValueError` with a message meant to be shown as-is.
    """
    if not isinstance(payload, dict):
        raise ValueError("provider 必须是一个对象")
    name = str(payload.get("name") or "").strip()
    if not _PROVIDER_NAME.match(name):
        raise ValueError("后端名称只能用字母、数字、下划线和短横线，且以字母或数字开头。")
    body = payload.get("config")
    if not isinstance(body, dict):
        raise ValueError("provider 配置必须是一个对象")
    p_type = str(body.get("type") or "").strip().lower()
    if p_type == "claude":
        p_type = "anthropic"
    if p_type not in _PROVIDER_FIELDS:
        raise ValueError("后端类型只支持：" + "、".join(sorted(_PROVIDER_FIELDS)))
    fields = _PROVIDER_FIELDS[p_type]
    cfg: dict[str, Any] = {"type": p_type}
    for key, kind in fields.items():
        if key not in body:
            continue
        value = body[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue  # an empty box means "leave it to the code default"
        cfg[key] = _coerce_field(value, kind, f"{name}.{key}")
    if "api_key" in body:
        raise ValueError(
            "不接受在这里填密钥：dashboard_config.json 会进版本库。"
            "请填「密钥环境变量」的名字，并在 .env 里配好它的值。"
        )
    if not cfg.get("model"):
        raise ValueError("必须填模型名（model）。")
    endpoint = _PROVIDER_ENDPOINT[p_type]
    if not cfg.get(endpoint):
        raise ValueError(f"必须填接口地址（{endpoint}）。")
    return name, cfg


def save_provider(payload: dict[str, Any]) -> dict[str, Any]:
    """Add or replace one ``llm.providers`` entry in the override file.

    Replaces rather than deep-merges: a provider block is a single coherent
    unit, and merging would leave the previous ``api_key_env`` or ``stream``
    behind after the user cleared the box.
    """
    name, cfg = _clean_provider(payload)
    ds = _ds()
    current = ds._dashboard_config()
    current.setdefault("llm", {}).setdefault("providers", {})[name] = cfg
    ds._atomic_write_json(ds.DASHBOARD_CONFIG_PATH, current)
    _LOG.info("llm provider saved: %s (%s)", name, cfg["type"])
    return _wire_safe({"saved": True, "name": name, **overview()})


def test_provider(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one real generation against a saved provider or an unsaved draft.

    The draft path is the point: it lets someone find out the endpoint or model
    name is wrong *before* committing it to the config file.
    """
    from gaworld.llm.providers import probe_provider

    if not isinstance(payload, dict):
        raise ValueError("请求体必须是一个对象")
    if isinstance(payload.get("config"), dict):
        # A draft is tested before it has a name; borrow one so the shared
        # validation still runs on everything that does matter.
        name, cfg = _clean_provider(dict(payload, name=payload.get("name") or "draft"))
    else:
        name = str(payload.get("name") or "").strip()
        cfg = _providers(_ds()._effective_config()).get(name)
        if not isinstance(cfg, dict):
            raise ValueError(f"没有名为 {name} 的后端。")
    result = probe_provider(cfg)
    _LOG.info("llm provider probe: %s ok=%s", name, result.get("ok"))
    return _wire_safe({"name": name, **result})


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def overview() -> dict[str, Any]:
    ds = _ds()
    effective = ds._effective_config()
    defaults = build_default_config()
    index = config_docs.section_index()
    sections = []
    for meta in config_docs.section_meta():
        keys = sorted(key for key, section in index.items() if section == meta["id"] and key in effective)
        sections.append({**meta, "keys": keys})
    # A key added to CONFIG outside the known fragments would otherwise be
    # invisible; park it in a catch-all rather than silently dropping it.
    claimed = {key for section in sections for key in section["keys"]}
    extra = sorted(key for key in effective if key not in claimed)
    if extra:
        sections.append(
            {
                "id": "other",
                "title": "其他",
                "help": "不属于任何已知配置片段的键（多半来自覆盖文件或临时注入）。",
                "keys": extra,
            }
        )
    layers = _override_layers()
    return _wire_safe(
        {
            "sections": sections,
            "tree": _redact(effective),
            "defaults": _redact(defaults),
            "sources": _source_map(),
            "layers": layers,
            "docs": _doc_map(effective),
            "read_only": sorted(_READ_ONLY_PATHS),
            "choices": _choice_map(effective),
            "providers": _provider_view(effective),
            "provider_types": sorted(_PROVIDER_FIELDS),
            "env": _env_snapshot(),
            "files": _raw_files(),
        }
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _reject_read_only(patch: dict[str, Any]) -> list[str]:
    """Strip read-only subtrees from a patch, returning what was removed."""
    removed = []
    for path in sorted(_READ_ONLY_PATHS):
        parts = path.split(".")
        node = patch
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                node = None
                break
        if isinstance(node, dict) and parts[-1] in node:
            node.pop(parts[-1])
            removed.append(path)
    return removed


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a patch against the effective config and merge it into the override file."""
    from gaworld.apps.external_systems_api import _coerce_like

    if not isinstance(payload, dict):
        raise ValueError("config patch must be an object")
    ds = _ds()
    effective = ds._effective_config()
    dropped: list[str] = []
    patch: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in effective:
            dropped.append(str(key))
            continue
        coerced = _coerce_like(effective[key], value, str(key), dropped)
        if coerced is not None:
            patch[key] = coerced
    blocked = _reject_read_only(patch)
    patch = {key: value for key, value in patch.items() if value not in ({}, None)}
    if not patch:
        return _wire_safe(
            {"saved": False, "dropped": dropped, "blocked": blocked, **overview()}
        )
    current = ds._dashboard_config()
    ds._deep_update(current, patch)
    ds._atomic_write_json(ds.DASHBOARD_CONFIG_PATH, current)
    _LOG.info("settings patch applied: %s", sorted(_flatten(patch)))
    return _wire_safe(
        {
            "saved": True,
            "dropped": dropped,
            "blocked": blocked,
            "applied": sorted(_flatten(patch)),
            **overview(),
        }
    )


def _prune(node: dict[str, Any], parts: list[str]) -> bool:
    """Delete ``parts`` from ``node``, dropping dicts left empty. True if removed."""
    head, rest = parts[0], parts[1:]
    if head not in node:
        return False
    if not rest:
        node.pop(head)
        return True
    child = node[head]
    if not isinstance(child, dict):
        return False
    removed = _prune(child, rest)
    if removed and not child:
        node.pop(head)
    return removed


def reset_paths(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove dotted paths from ``dashboard_config.json`` so defaults apply again.

    Resetting is deletion, not "write the default back": leaving the default
    value in the override file would pin it, so a later change to the Python
    default would silently not take effect.
    """
    ds = _ds()
    paths = payload.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        raise ValueError("paths must be a list of dotted config paths")
    current = ds._dashboard_config()
    removed = [
        path
        for path in paths
        if isinstance(path, str) and path and _prune(current, path.split("."))
    ]
    if removed:
        ds._atomic_write_json(ds.DASHBOARD_CONFIG_PATH, current)
        _LOG.info("settings override reset: %s", removed)
    return _wire_safe({"removed": removed, **overview()})


def reset_all() -> dict[str, Any]:
    """Empty the override file entirely — back to the Python defaults."""
    ds = _ds()
    before = sorted(_flatten(ds._dashboard_config()))
    ds._atomic_write_json(ds.DASHBOARD_CONFIG_PATH, {})
    _LOG.info("settings overrides cleared (%d paths)", len(before))
    return _wire_safe({"removed": before, **overview()})


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    if path == "/api/settings/overview":
        return overview(), 200
    return {"error": "Unknown settings endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/settings/save":
            return save_config(payload.get("config", payload)), 200
        if path == "/api/settings/reset":
            return reset_paths(payload), 200
        if path == "/api/settings/reset-all":
            return reset_all(), 200
        if path == "/api/settings/llm/provider":
            return save_provider(payload), 200
        if path == "/api/settings/llm/test":
            return test_provider(payload), 200
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400
    except OSError as exc:
        return {"error": f"写入配置文件失败：{exc}"}, 500
    return {"error": "Unknown settings endpoint"}, 404


__all__ = [
    "handle_get",
    "handle_post",
    "overview",
    "reset_all",
    "reset_paths",
    "save_config",
    "save_provider",
    "test_provider",
]
