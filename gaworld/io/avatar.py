"""SVG avatar generation for agents.

Canonical home: :mod:`gaworld.io.avatar`.
Legacy callers should use the ``avatar_generator`` shim at the project root.
"""

from __future__ import annotations

import hashlib
import os
from html import escape


PALETTES = [
    ("#f1c27d", "#2f4858", "#0d8a73", "#fff6e8"),
    ("#e0ac69", "#4a2c2a", "#dc7d2d", "#fdf3e1"),
    ("#c68642", "#1f3340", "#5a67a8", "#fff1df"),
    ("#8d5524", "#243b4a", "#c84c61", "#fde7d5"),
    ("#f4c58a", "#314e52", "#7b8f27", "#fff4e3"),
    ("#d8a06d", "#5e3c58", "#0083a8", "#f8eadb"),
]


def _seed_int(agent):
    blob = "|".join(
        str(agent.get(key, "")).strip()
        for key in ("id", "name", "job", "personality", "age", "gender", "hukou")
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _pick_face_shape(seed):
    return ["round", "soft-square", "oval"][seed % 3]


def _mood(seed, agent):
    text = " ".join(str(agent.get(key, "")) for key in ("personality", "daily_life", "values"))
    stress = float(agent.get("state", {}).get("stress", 0.5) or 0.5) if isinstance(agent.get("state"), dict) else 0.5
    if any(k in text for k in ["严肃", "克制", "谨慎", "内向"]) or stress > 0.68:
        return "calm"
    if any(k in text for k in ["热情", "开朗", "外向", "乐观"]):
        return "smile"
    return ["calm", "smile", "focused"][seed % 3]


def _hair_style(seed, agent):
    text = " ".join(str(agent.get(key, "")) for key in ("job", "personality", "daily_life"))
    if any(k in text for k in ["学生", "年轻", "活跃", "设计", "创意"]):
        return ["short", "messy", "bob"][seed % 3]
    return ["short", "parted", "bun", "bob"][seed % 4]


def _accessory(seed, agent):
    text = " ".join(str(agent.get(key, "")) for key in ("job", "daily_life", "personality"))
    if any(k in text for k in ["老师", "研究", "程序", "工程", "阅读", "医生"]):
        return "glasses"
    choices = ["none", "glasses", "earring"]
    return choices[seed % len(choices)]


def _shirt_pattern(seed):
    return ["solid", "stripe", "dot"][seed % 3]


def _initial(name):
    text = str(name or "").strip()
    return text[:1] if text else "A"


def build_agent_avatar_svg(agent, size=128):
    seed = _seed_int(agent)
    skin, hair, accent, bg = PALETTES[seed % len(PALETTES)]
    face_shape = _pick_face_shape(seed)
    mood = _mood(seed, agent)
    hair_style = _hair_style(seed, agent)
    accessory = _accessory(seed, agent)
    shirt_pattern = _shirt_pattern(seed)
    initials = escape(_initial(agent.get("name", "")))
    name = escape(str(agent.get("name", "agent")))

    if face_shape == "soft-square":
        face = '<rect x="31" y="27" width="66" height="72" rx="22" fill="{skin}" />'
    elif face_shape == "oval":
        face = '<ellipse cx="64" cy="63" rx="31" ry="37" fill="{skin}" />'
    else:
        face = '<circle cx="64" cy="62" r="34" fill="{skin}" />'

    hair_svg = {
        "short": f'<path d="M28 54c2-18 17-32 36-32 20 0 35 14 37 33-8-5-16-9-37-9-18 0-27 3-36 8z" fill="{hair}" />',
        "messy": f'<path d="M25 56c5-21 18-35 39-35 17 0 31 8 39 30-10-7-19-11-38-11-17 0-27 6-40 16z" fill="{hair}" />',
        "parted": f'<path d="M27 55c4-20 19-33 38-33 19 0 33 13 36 33-10-9-19-12-31-12-15 0-27 5-43 12z" fill="{hair}" />',
        "bun": f'<circle cx="64" cy="23" r="12" fill="{hair}" /><path d="M29 57c4-20 17-33 35-33 20 0 34 13 36 33-8-7-17-10-36-10-17 0-26 3-35 10z" fill="{hair}" />',
        "bob": f'<path d="M28 48c4-16 18-28 36-28 18 0 32 11 36 28v24c-8-10-17-14-36-14-17 0-27 4-36 14z" fill="{hair}" />',
    }[hair_style]

    if mood == "smile":
        mouth = '<path d="M50 76c3 5 8 8 14 8s11-3 14-8" fill="none" stroke="#7b3f32" stroke-width="3" stroke-linecap="round" />'
    elif mood == "focused":
        mouth = '<path d="M51 79c4-2 8-3 13-3 5 0 9 1 13 3" fill="none" stroke="#7b3f32" stroke-width="3" stroke-linecap="round" />'
    else:
        mouth = '<path d="M52 79h24" fill="none" stroke="#7b3f32" stroke-width="3" stroke-linecap="round" />'

    accessory_svg = ""
    if accessory == "glasses":
        accessory_svg = (
            '<rect x="41" y="57" width="16" height="10" rx="4" fill="none" stroke="#2b3c42" stroke-width="2" />'
            '<rect x="71" y="57" width="16" height="10" rx="4" fill="none" stroke="#2b3c42" stroke-width="2" />'
            '<path d="M57 62h14" stroke="#2b3c42" stroke-width="2" />'
        )
    elif accessory == "earring":
        accessory_svg = '<circle cx="90" cy="73" r="3" fill="{accent}" />'

    shirt_base = f'<path d="M24 128c4-18 16-30 40-30s36 12 40 30z" fill="{accent}" />'
    if shirt_pattern == "stripe":
        shirt_overlay = (
            '<path d="M38 101v27M50 99v29M64 98v30M78 99v29M90 101v27" '
            'stroke="rgba(255,255,255,0.35)" stroke-width="3" stroke-linecap="round" />'
        )
    elif shirt_pattern == "dot":
        shirt_overlay = (
            '<circle cx="48" cy="110" r="2" fill="rgba(255,255,255,0.35)" />'
            '<circle cx="63" cy="106" r="2" fill="rgba(255,255,255,0.35)" />'
            '<circle cx="79" cy="111" r="2" fill="rgba(255,255,255,0.35)" />'
            '<circle cx="57" cy="119" r="2" fill="rgba(255,255,255,0.35)" />'
            '<circle cx="73" cy="121" r="2" fill="rgba(255,255,255,0.35)" />'
        )
    else:
        shirt_overlay = ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{int(size)}" height="{int(size)}" viewBox="0 0 128 128" role="img" aria-label="{name} avatar">
  <defs>
    <clipPath id="avatarClip">
      <circle cx="64" cy="64" r="60" />
    </clipPath>
  </defs>
  <g clip-path="url(#avatarClip)">
    <rect width="128" height="128" fill="{bg}" />
    <circle cx="26" cy="21" r="18" fill="rgba(255,255,255,0.35)" />
    <circle cx="104" cy="23" r="12" fill="rgba(255,255,255,0.20)" />
    <path d="M0 92c16-19 35-28 60-28 28 0 46 10 68 34v30H0z" fill="rgba(255,255,255,0.12)" />
    {shirt_base}
    {shirt_overlay}
    <ellipse cx="64" cy="98" rx="18" ry="11" fill="{skin}" />
    {face.format(skin=skin)}
    {hair_svg}
    <circle cx="51" cy="62" r="3.3" fill="#1e2c34" />
    <circle cx="77" cy="62" r="3.3" fill="#1e2c34" />
    <path d="M64 64l-3 8h6z" fill="rgba(137,88,68,0.35)" />
    {mouth}
    {accessory_svg.format(accent=accent) if "{accent}" in accessory_svg else accessory_svg}
    <circle cx="100" cy="102" r="17" fill="rgba(24,38,42,0.14)" />
    <text x="100" y="108" text-anchor="middle" font-family="Manrope, sans-serif" font-size="16" font-weight="800" fill="#1f3340">{initials}</text>
  </g>
  <circle cx="64" cy="64" r="60" fill="none" stroke="rgba(24,38,42,0.12)" stroke-width="2" />
</svg>
"""


def ensure_agent_avatar(agent, output_dir, filename=None):
    os.makedirs(output_dir, exist_ok=True)
    agent_id = int(agent.get("id", 0) or 0)
    target_name = filename or f"agent_{agent_id}.svg"
    path = os.path.join(output_dir, target_name)
    svg = build_agent_avatar_svg(agent)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return path
