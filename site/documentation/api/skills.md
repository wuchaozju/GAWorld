# Skills 模块

技能数据结构、注册、提示词选择与经验提炼。

接口签名与说明由当前仓库源代码生成。

## gaworld.skills.schemas

:::{py:currentmodule} gaworld.skills.schemas
:::

:::{py:class} Skill

```{eval-rst}
A reusable capability an agent can hold and apply.

:ivar skill_id: Stable identifier; usually the filename basename.
:ivar name: Short human-readable title shown in prompts.
:ivar description: One-line summary used both for trigger matching and the agent's
                   prompt-time skill list.
:ivar body: Free-form Markdown body — the "how to use this skill" detail
            passed into work-adapter prompts.
:ivar triggers: Keyword hints. The registry uses these (plus ``description``
                and ``name``) for cheap substring matching against
                action/activity text.
:ivar source: ``"global"`` for hand-authored library skills,
              ``"private"`` for agent-summarised skills.
:ivar owner_agent_id: The agent that owns a private skill (None for global skills).
:ivar origin: Optional provenance string (e.g. ``"consolidation"``,
              ``"seed"``) — kept for debugging and analysis.
:ivar created_day: Simulation day the skill was created, when known.

```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L46`

:::

:::{py:attribute} Skill.skill_id
:type: str
:::

:::{py:attribute} Skill.name
:type: str
:::

:::{py:attribute} Skill.description
:type: str
:::

:::{py:attribute} Skill.body
:type: str
:::

:::{py:attribute} Skill.triggers
:type: list[str]
:::

:::{py:attribute} Skill.source
:type: SkillSource
:::

:::{py:attribute} Skill.owner_agent_id
:type: int | None
:::

:::{py:attribute} Skill.origin
:type: str
:::

:::{py:attribute} Skill.created_day
:type: int | None
:::

:::{py:method} Skill.to_dict() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L90`

:::

:::{py:method} Skill.from_dict(payload: dict[str, Any]) -> Skill
:classmethod:

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L94`

:::

:::{py:method} Skill.matches(text: str) -> bool

```{eval-rst}
Cheap relevance check: does ``text`` mention any trigger/name?
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L109`

:::

:::{py:function} slugify_skill_id(name: str, fallback: str='skill') -> str

```{eval-rst}
Turn a human-readable name into a filesystem-safe skill_id.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L128`

:::

:::{py:function} parse_skill_markdown(skill_id: str, text: str) -> Skill

```{eval-rst}
Parse a Skill markdown file (frontmatter + body).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L218`

:::

:::{py:function} dump_skill_markdown(skill: Skill) -> str

```{eval-rst}
Serialise a :class:`Skill` to ``---``-framed markdown.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/schemas.py#L267`

:::

## gaworld.skills.registry

:::{py:currentmodule} gaworld.skills.registry
:::

:::{py:class} SkillRegistry(*, global_dir: str | None=None, memory_dir: str | None=None)

```{eval-rst}
Read/write surface over the global library + per-agent skills.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L43`

:::

:::{py:method} SkillRegistry.reload() -> None

```{eval-rst}
Drop caches so the next access re-reads disk.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L115`

:::

:::{py:method} SkillRegistry.list_global() -> list[Skill]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L122`

:::

:::{py:method} SkillRegistry.list_private(agent_id: int) -> list[Skill]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L126`

:::

:::{py:method} SkillRegistry.list_for_agent(agent: dict[str, Any] | int) -> list[Skill]

```{eval-rst}
All skills available to one agent: attached global + private.

``agent`` may be either an Agent dict (we read ``skill_ids``)
or a bare agent_id (we return *all* private skills they own
but no global skills, since attachment is unknown).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L130`

:::

:::{py:method} SkillRegistry.get(skill_id: str, *, agent_id: int | None=None) -> Skill | None

```{eval-rst}
Look up by id. If ``agent_id`` is given, private wins.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L162`

:::

:::{py:method} SkillRegistry.save_private(agent_id: int, skill: Skill) -> Skill

```{eval-rst}
Persist a private skill and return the stored copy.

The id is normalised through :func:`slugify_skill_id`; if a
skill with that id already exists for this agent, the body and
metadata are overwritten in place.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L175`

:::

:::{py:method} SkillRegistry.attach_to_agent(agent: dict[str, Any], skill_id: str) -> bool

```{eval-rst}
Add a global skill to the agent's ``skill_ids`` list.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L198`

:::

:::{py:method} SkillRegistry.detach_from_agent(agent: dict[str, Any], skill_id: str) -> bool

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L217`

:::

:::{py:function} get_default_registry() -> SkillRegistry

```{eval-rst}
Return a process-wide registry instance, creating it on first use.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L233`

:::

:::{py:function} reset_default_registry() -> None

```{eval-rst}
Drop the module-level cache (mainly for tests).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L241`

:::

:::{py:function} iter_global_skill_ids(registry: SkillRegistry | None=None) -> Iterable[str]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py#L247`

:::

## gaworld.skills.prompt_helpers

:::{py:currentmodule} gaworld.skills.prompt_helpers
:::

:::{py:function} render_agent_skills(skills: Sequence[Skill], *, max_skills: int=6, include_body: bool=False) -> str

```{eval-rst}
Format a list of Skills for inclusion in an LLM prompt.

Returns an empty string when no skills are available — callers
should branch on the string rather than always concatenating it,
so prompts stay clean when an agent has no skills.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/prompt_helpers.py#L19`

:::

:::{py:function} relevant_skills_for_text(skills: Iterable[Skill], text: str, *, limit: int=3) -> list[Skill]

```{eval-rst}
Pick at most ``limit`` skills whose triggers/name match ``text``.

Used by the work router and adapter helpers to focus the brief on
the handful of skills that actually apply to the current action.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/prompt_helpers.py#L48`

:::

## gaworld.skills.consolidation

:::{py:currentmodule} gaworld.skills.consolidation
:::

:::{py:function} summarize_experience_to_skill(agent: dict[str, Any], *, llm: LlmFn, registry: SkillRegistry | None=None, today: int | None=None, lookback_days: int | None=None, min_episodes: int=4) -> Skill | None

```{eval-rst}
Try to derive one new private Skill from the agent's recent episodes.

Returns the saved :class:`Skill` on success, or ``None`` if no
pattern was extracted. Idempotent on the slug: a returned LLM
payload whose name slugifies to an existing private skill id is
silently overwritten (the LLM is allowed to refine the same skill
over time).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/consolidation.py#L97`

:::

:::{py:function} run_skill_consolidation(agent: dict[str, Any], *, llm: LlmFn, today: int | None=None, registry: SkillRegistry | None=None) -> Skill | None

```{eval-rst}
Lifecycle entrypoint: gated by config, otherwise calls into
:func:`summarize_experience_to_skill`.

Kept as a thin shim so :mod:`gaworld.memory.lifecycle` can call us
without re-reading the config block itself.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/consolidation.py#L182`

:::
