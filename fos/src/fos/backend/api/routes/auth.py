from datetime import datetime, timezone

from jose import JWTError, jwt
from litestar import Router, get, post
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy import delete, select

from fos.i18n import T
from ...core.config import get_settings
from ...core.database import get_session
from ...core.security import create_access_token, create_refresh_token, hash_password, verify_password
from ...dependencies import extract_bearer_token, get_email_sender, resolve_current_user
from ...models.token import RefreshToken
from ...models.user import User
from ...schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    VerificationRequest,
)
from ...schemas.common import Message
from ...schemas.user import UserPublic
from ...services.verification import get_verification_token, issue_verification_token


settings = get_settings()


@post("/register", status_code=201)
async def register(data: RegisterRequest) -> UserPublic:
    if settings.require_email_verification:
        if not settings.email_enabled:
            raise HTTPException(status_code=500, detail=T("api.errors.auth.smtp_missing"))
        if not settings.app_base_url:
            raise HTTPException(status_code=500, detail=T("api.errors.auth.app_url_missing"))

    async with get_session() as session:
        if (await session.execute(select(User).where(User.email == data.email))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail=T("api.errors.auth.email_registered"))
        if (await session.execute(select(User).where(User.username == data.username))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail=T("api.errors.auth.username_registered"))

        user = User(
            organization=data.organization,
            email=data.email,
            username=data.username,
            full_name=data.full_name,
            phone_number=data.phone_number,
            hashed_password=hash_password(data.password),
            is_active=True,
            is_verified=not settings.require_email_verification,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        if settings.require_email_verification:
            token = await issue_verification_token(session, user)
            sender = get_email_sender()
            verification_link = f"{settings.app_base_url.rstrip('/')}/auth/verify?token={token.token}"
            await sender.send_verification_email(user.email, verification_link)

        return UserPublic.model_validate(user)


@post("/login")
async def login(data: LoginRequest) -> TokenPair:
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.email == data.email).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail=T("api.errors.invalid_credentials"))
        if not user.is_active:
            raise HTTPException(status_code=403, detail=T("api.errors.auth.user_disabled"))
        if settings.require_email_verification and not user.is_verified:
            raise HTTPException(status_code=403, detail=T("api.errors.auth.email_not_verified"))

        access_token, access_exp = create_access_token(str(user.id))
        refresh_token, refresh_exp = create_refresh_token(str(user.id))

        await session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user.id)
        )

        session.add(
            RefreshToken(
                user_id=user.id,
                token=refresh_token,
                expires_at=refresh_exp,
                created_at=datetime.now(timezone.utc),
            )
        )
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()

        # Fire-and-forget auto-discovery for local LLM providers
        import asyncio
        from fos.backend.services.default_providers import (
            ensure_default_ollama_providers,
            ensure_default_lmstudio_providers,
        )

        async def _run_provider_auto_discovery(session_factory, user_id: int, user):
            """Discover Ollama and LM Studio providers after login. Never throws."""

            for discover_fn in [ensure_default_ollama_providers, ensure_default_lmstudio_providers]:
                try:
                    async with session_factory() as discovery_session:
                        await discover_fn(discovery_session, user_id, user)
                except Exception:
                    pass  # Silently fail — user can add providers manually

        asyncio.create_task(
            _run_provider_auto_discovery(get_session, user.id, user)
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int((access_exp - datetime.now(timezone.utc)).total_seconds()),
        )


@post("/verify")
async def verify_email(data: VerificationRequest) -> Message:
    async with get_session() as session:
        token = await get_verification_token(session, data.token)
        if token is None:
            raise HTTPException(status_code=400, detail=T("api.errors.auth.invalid_expired_token"))

        expiry = token.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry < datetime.now(timezone.utc):
            await session.delete(token)
            await session.commit()
            raise HTTPException(status_code=400, detail=T("api.errors.auth.invalid_expired_token"))

        user = await session.get(User, token.user_id)
        if user is None:
            await session.delete(token)
            await session.commit()
            raise HTTPException(status_code=400, detail=T("api.errors.auth.account_missing"))

        user.is_verified = True
        user.updated_at = datetime.now(timezone.utc)
        await session.delete(token)
        await session.commit()

        return Message(message=T('api.auth.email_verified'))


@get("/me")
async def read_me(request: Request) -> UserPublic:
    token = extract_bearer_token(request)
    async with get_session() as session:
        return await resolve_current_user(session, token)


@post("/token/refresh")
async def refresh_token(data: RefreshRequest) -> TokenPair:
    try:
        decoded = jwt.decode(
            data.refresh_token,
            key=settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=T("api.errors.auth.invalid_refresh_token")) from exc

    if decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail=T("api.errors.auth.invalid_token_type"))

    subject = decoded.get("sub")
    if subject is None:
        raise HTTPException(status_code=401, detail=T("api.errors.auth.invalid_token_subject"))

    async with get_session() as session:
        token_q = await session.execute(select(RefreshToken).where(RefreshToken.token == data.refresh_token))
        token_db = token_q.scalar_one_or_none()
        if token_db is None or token_db.revoked_at is not None:
            raise HTTPException(status_code=401, detail=T("api.errors.auth.token_revoked"))

        # Handle timezone-aware and naive datetimes
        expires_at = token_db.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail=T("api.errors.auth.token_expired"))

        access_token, access_exp = create_access_token(subject)
        refresh_token, refresh_exp = create_refresh_token(subject)

        token_db.token = refresh_token
        token_db.expires_at = refresh_exp
        await session.commit()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int((access_exp - datetime.now(timezone.utc)).total_seconds()),
        )


router = Router(
    path="/auth",
    route_handlers=[
        register,
        login,
        verify_email,
        read_me,
        refresh_token,
    ],
)
