from jose import JWTError, jwt
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config import get_settings
from fos.i18n import T
from .models.user import User
from .schemas.user import UserPublic
from .services.email import EmailSender


settings = get_settings()


def get_email_sender() -> EmailSender:
    return EmailSender(settings)


def extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if header is None or not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=T("api.errors.missing_bearer_token"))
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail=T("api.errors.missing_bearer_token"))
    return token


async def resolve_current_user(session: AsyncSession, token: str) -> UserPublic:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=401, detail=T("api.errors.auth.could_not_validate")
        ) from exc

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(status_code=401, detail=T("api.errors.auth.invalid_token_subject"))

    user = await session.get(User, int(subject))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail=T("api.errors.auth.inactive_user"))
    return UserPublic.model_validate(user)
