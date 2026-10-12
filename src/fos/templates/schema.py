"""Pydantic schema models for the generic template system.

Legacy template schema.
Templates can be serialized to/from JSON or YAML and validated using these models.

Contains: GenericTemplate, export_json_schema
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from re import match

from fos.i18n import T


class CoreMechanic(BaseModel):
    type: Literal["grid", "discussion", "voting", "resources", "hierarchy", "time"] = Field(...)
    config: dict[str, Any] = Field(default_factory=dict)


class SemanticActionParameter(BaseModel):
    name: str = Field(...)
    type: Literal["str", "int", "float", "bool", "list", "dict"] = Field(...)
    description: str = Field(default="")
    required: bool = Field(default=True)
    default: Any | None = Field(default=None)

    from pydantic import field_validator

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not match(r"^[a-z_][a-z0-9_]*$", v):
            raise ValueError(T("Parameter name {v} must be snake_case", v=v))
        return v


class SemanticAction(BaseModel):
    name: str = Field(..., pattern=r"^[a-z_]+$")
    description: str = Field(...)
    instruction: str = Field(...)
    parameters: list[SemanticActionParameter] = Field(default_factory=list)
    effect: str = Field(default="")


class AgentArchetype(BaseModel):
    name: str = Field(...)
    role_prompt: str = Field(...)
    style: str = Field(default="neutral")
    user_profile: str = Field(default="")
    properties: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(default_factory=list)


class TimeConfig(BaseModel):
    start: str = Field(default="2024-01-01")
    step: str = Field(default="1h")
    format: str = Field(default="%Y-%m-%d %H:%M")


class SpaceConfig(BaseModel):
    type: Literal["grid", "network", "continuous"] = Field(default="grid")
    width: int = Field(default=10)
    height: int = Field(default=10)
    wrap_around: bool = Field(default=True)


class EnvironmentConfig(BaseModel):
    description: str = Field(default="")
    time_config: TimeConfig | None = Field(default=None)
    space_config: SpaceConfig | None = Field(default=None)
    rules: list[str] = Field(default_factory=list)


class NetworkConfig(BaseModel):
    type: Literal["complete", "random", "small_world", "scale_free", "custom"] = Field(default="complete")
    parameters: dict[str, Any] = Field(default_factory=dict)


class GenericTemplate(BaseModel):
    """A complete simulation template."""

    id: str = Field(...)
    name: str = Field(...)
    description: str = Field(...)
    version: str = Field(default="1.0.0")
    author: str = Field(default="")
    core_mechanics: list[CoreMechanic] = Field(default_factory=list)
    semantic_actions: list[SemanticAction] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    agent_archetypes: list[AgentArchetype] = Field(default_factory=list)
    environment: EnvironmentConfig | None = Field(default=None)
    default_time_config: TimeConfig | None = Field(default=None)
    default_network: NetworkConfig | None = Field(default=None)


def export_json_schema() -> dict[str, Any]:
    """Export the JSON schema for the template system."""
    schema: dict[str, Any] = GenericTemplate.model_json_schema()
    return {"$schema": "http://json-schema.org/draft-07/schema#", **schema}
