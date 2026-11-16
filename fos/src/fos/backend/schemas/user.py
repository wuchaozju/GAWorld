# This file describes the public user data shapes that API routes send and receive.
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str
    full_name: str | None = None
    organization: str | None = None
    phone_number: str | None = None
    is_active: bool
    is_verified: bool
    role: str
    created_at: datetime
    updated_at: datetime


class UserPublic(UserBase):
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    organization: str | None = None
    email: EmailStr
    username: str
    full_name: str
    phone_number: str
    password: str


class UserUpdate(BaseModel):
    organization: str | None = None
    full_name: str | None = None
    phone_number: str | None = None
