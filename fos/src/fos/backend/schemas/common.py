from datetime import datetime

from pydantic import BaseModel


class Message(BaseModel):
    message: str


def serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
