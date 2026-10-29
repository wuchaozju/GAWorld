from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator
import re

from fos.i18n import T


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    organization: str | None = None
    email: EmailStr
    username: str
    full_name: str | None = None
    phone_number: str | None = None
    password: str

    @field_validator("email", "username", mode="before")
    @classmethod
    def _strip_ws(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if not value:
            return None
        # E.164-like: optional '+', leading non-zero, total digits 8-15
        pattern = re.compile(r"^\+?[1-9]\d{7,14}$")
        if not pattern.match(value):
            raise ValueError(T("invalid phone number format"))
        return value

    @field_validator("password")
    @classmethod
    def _check_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError(T("password must be at most 72 bytes when encoded as utf-8"))
        return value


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def _check_reset_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError(T("password must be at most 72 bytes when encoded as utf-8"))
        return value


class EmailVerification(BaseModel):
    token: str
    verified_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class VerificationRequest(BaseModel):
    token: str
