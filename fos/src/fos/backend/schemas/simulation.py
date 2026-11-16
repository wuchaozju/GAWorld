# This file describes the simulation data shapes that API routes send and receive.
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class SimulationBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    scene_type: str
    scene_config: dict
    agent_config: dict
    latest_state: dict | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value: str | int) -> str:
        return str(value)


class SimulationCreate(BaseModel):
    name: str | None = None
    scene_type: str
    scene_config: dict
    agent_config: dict


class SimulationUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    notes: str | None = None
    agent_config: dict | None = None
    scene_config: dict | None = None


class SnapshotBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    turns: int
    state: dict
    created_at: datetime


class SnapshotCreate(BaseModel):
    label: str | None = None


class SimulationLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    payload: dict
    created_at: datetime
