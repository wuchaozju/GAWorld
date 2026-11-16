from datetime import date, datetime, timedelta

from litestar import Router, get, patch
from litestar.connection import Request
from litestar.exceptions import HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user
from ...models.simulation import Simulation
from ...models.user import User
from ...schemas.simulation import SimulationBase
from ...schemas.user import UserPublic
from fos.i18n import T


class RoleUpdate(BaseModel):
    role: str


def _require_admin(user: UserPublic) -> None:
    if str(getattr(user, "role", "")) != "admin":
        raise HTTPException(status_code=403, detail=T("api.errors.admin_only"))


@get("/users")
async def admin_list_users(
    request: Request,
    q: str | None = None,
    org: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: str = "created_desc",
) -> list[UserPublic]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _require_admin(current_user)
        stmt = select(User)
        conditions = []
        if q:
            like = f"%{q}%"
            conditions.append(
                (User.full_name.ilike(like)) | (User.username.ilike(like))
            )
        if org:
            conditions.append(User.organization.ilike(f"%{org}%"))
        if created_from:
            start = datetime.fromisoformat(created_from)
            conditions.append(User.created_at >= start)
        if created_to:
            end = datetime.fromisoformat(created_to)
            conditions.append(User.created_at <= end)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        name_expr = func.coalesce(User.full_name, User.username)
        if sort == "name_asc":
            stmt = stmt.order_by(name_expr.asc())
        elif sort == "name_desc":
            stmt = stmt.order_by(name_expr.desc())
        elif sort == "org_asc":
            stmt = stmt.order_by(User.organization.asc().nulls_last())
        elif sort == "org_desc":
            stmt = stmt.order_by(User.organization.desc().nulls_last())
        elif sort == "created_asc":
            stmt = stmt.order_by(User.created_at.asc())
        else:
            stmt = stmt.order_by(User.created_at.desc())

        result = await session.execute(stmt)
        users = result.scalars().all()
        return [UserPublic.model_validate(u) for u in users]


@get("/simulations")
async def admin_list_simulations(
    request: Request,
    user: str | None = None,
    scene_type: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: str = "created_desc",
) -> list[dict]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _require_admin(current_user)
        stmt = select(Simulation, User.username).join(
            User, Simulation.owner_id == User.id
        )
        conditions = []
        if user:
            conditions.append(User.username.ilike(f"%{user}%"))
        if scene_type:
            conditions.append(Simulation.scene_type.ilike(f"%{scene_type}%"))
        if created_from:
            start = datetime.fromisoformat(created_from)
            conditions.append(Simulation.created_at >= start)
        if created_to:
            end = datetime.fromisoformat(created_to)
            conditions.append(Simulation.created_at <= end)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        if sort == "username_asc":
            stmt = stmt.order_by(User.username.asc())
        elif sort == "username_desc":
            stmt = stmt.order_by(User.username.desc())
        elif sort == "scene_asc":
            stmt = stmt.order_by(Simulation.scene_type.asc())
        elif sort == "scene_desc":
            stmt = stmt.order_by(Simulation.scene_type.desc())
        elif sort == "created_asc":
            stmt = stmt.order_by(Simulation.created_at.asc())
        else:
            stmt = stmt.order_by(Simulation.created_at.desc())

        result = await session.execute(stmt)
        rows = result.all()
        out: list[dict] = []
        for sim, username in rows:
            data = SimulationBase.model_validate(sim).model_dump()
            data["owner_username"] = username
            out.append(data)
        return out


@get("/stats")
async def admin_stats(request: Request, period: str = "day") -> dict:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _require_admin(current_user)
        now = datetime.now()

        def _floor_day(dt: datetime) -> date:
            return dt.date()

        def _floor_week(dt: datetime) -> date:
            d = dt.date()
            return d - timedelta(days=d.weekday())

        def _floor_month(dt: datetime) -> tuple[int, int]:
            d = dt.date()
            return (d.year, d.month)

        users_q = await session.execute(select(User.created_at, User.last_login_at))
        user_rows = users_q.all()
        sims_q = await session.execute(select(Simulation.created_at))
        sim_rows = sims_q.all()

        if period not in {"day", "week", "month"}:
            period = "day"

        buckets: list[str] = []
        if period == "day":
            days = [now.date() - timedelta(days=i) for i in range(29, -1, -1)]
            buckets = [d.isoformat() for d in days]
            sim_map = {k: 0 for k in buckets}
            visit_map = {k: 0 for k in buckets}
            signup_map = {k: 0 for k in buckets}
            for (created_at,) in sim_rows:
                k = _floor_day(created_at).isoformat()
                if k in sim_map:
                    sim_map[k] += 1
            for created_at, last_login_at in user_rows:
                k = _floor_day(created_at).isoformat()
                if k in signup_map:
                    signup_map[k] += 1
                if last_login_at is not None:
                    v = _floor_day(last_login_at).isoformat()
                    if v in visit_map:
                        visit_map[v] += 1
            return {
                "period": period,
                "sim_runs": [{"date": k, "count": sim_map[k]} for k in buckets],
                "user_visits": [{"date": k, "count": visit_map[k]} for k in buckets],
                "user_signups": [{"date": k, "count": signup_map[k]} for k in buckets],
            }
        if period == "week":
            weeks = [_floor_week(now - timedelta(weeks=i)) for i in range(11, -1, -1)]
            buckets = [w.isoformat() for w in weeks]
            sim_map = {k: 0 for k in buckets}
            visit_map = {k: 0 for k in buckets}
            signup_map = {k: 0 for k in buckets}
            for (created_at,) in sim_rows:
                k = _floor_week(created_at).isoformat()
                if k in sim_map:
                    sim_map[k] += 1
            for created_at, last_login_at in user_rows:
                k = _floor_week(created_at).isoformat()
                if k in signup_map:
                    signup_map[k] += 1
                if last_login_at is not None:
                    v = _floor_week(last_login_at).isoformat()
                    if v in visit_map:
                        visit_map[v] += 1
            return {
                "period": period,
                "sim_runs": [{"date": k, "count": sim_map[k]} for k in buckets],
                "user_visits": [{"date": k, "count": visit_map[k]} for k in buckets],
                "user_signups": [{"date": k, "count": signup_map[k]} for k in buckets],
            }
        months = []
        cur = now
        for _ in range(12):
            months.append((cur.year, cur.month))
            if cur.month == 1:
                cur = cur.replace(year=cur.year - 1, month=12)
            else:
                cur = cur.replace(month=cur.month - 1)
        months = list(reversed(months))
        buckets = [f"{y:04d}-{m:02d}" for (y, m) in months]
        sim_map = {k: 0 for k in buckets}
        visit_map = {k: 0 for k in buckets}
        signup_map = {k: 0 for k in buckets}
        for (created_at,) in sim_rows:
            key = f"{created_at.year:04d}-{created_at.month:02d}"
            if key in sim_map:
                sim_map[key] += 1
        for created_at, last_login_at in user_rows:
            key = f"{created_at.year:04d}-{created_at.month:02d}"
            if key in signup_map:
                signup_map[key] += 1
            if last_login_at is not None:
                v = last_login_at
                vkey = f"{v.year:04d}-{v.month:02d}"
                if vkey in visit_map:
                    visit_map[vkey] += 1
        return {
            "period": period,
            "sim_runs": [{"date": k, "count": sim_map[k]} for k in buckets],
            "user_visits": [{"date": k, "count": visit_map[k]} for k in buckets],
            "user_signups": [{"date": k, "count": signup_map[k]} for k in buckets],
        }


@patch("/users/{user_id:int}/role")
async def admin_update_user_role(
    request: Request, user_id: int, data: RoleUpdate
) -> UserPublic:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        _require_admin(current_user)
        role = (data.role or "").strip()
        if role not in {"user", "admin"}:
            raise HTTPException(status_code=400, detail=T("api.errors.invalid_role"))
        db_user = await session.get(User, int(user_id))
        if db_user is None:
            raise HTTPException(status_code=404, detail=T("api.errors.user_not_found"))
        db_user.role = role
        await session.commit()
        await session.refresh(db_user)
        return UserPublic.model_validate(db_user)


router = Router(
    path="/admin",
    route_handlers=[
        admin_list_users,
        admin_list_simulations,
        admin_stats,
        admin_update_user_role,
    ],
)
