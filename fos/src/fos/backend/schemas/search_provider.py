# This file describes search provider settings that API routes send and receive.
from pydantic import BaseModel, ConfigDict


class SearchProviderBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    base_url: str | None = None
    has_api_key: bool = False
    config: dict | None = None


class SearchProviderCreate(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None
    config: dict | None = None


class SearchProviderUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    config: dict | None = None

