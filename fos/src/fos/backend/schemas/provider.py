# This file describes provider settings that API routes send and receive.
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProviderBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    model: str
    base_url: str | None = None
    has_api_key: bool = False
    is_active: bool = False
    is_default: bool = False
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_error: str | None = None
    config: dict | None = None


class ProviderCreate(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str
    api_key: str
    config: dict | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    config: dict | None = None
