"""
This file exposes the host environment routes.

Each function here does one small job:
- `_parse_node_id_param` reads an optional node id from the request.
- suggestion endpoints expose grounded environment suggestions.
- event endpoints list, create, apply, and seed external events.
- rules endpoints keep the simple in-memory rule list for now.
"""

from typing import Any
import logging
from litestar import Router, get, post
from litestar.connection import Request
from litestar.exceptions import HTTPException
import sqlalchemy.orm

from fos.i18n import T
from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.services.external_event_application import (
    apply_external_event_record,
    create_external_event_record,
)
from fos.backend.services.environment_suggestion_service import (
    get_simulation_state,
    generate_environment_suggestions,
    broadcast_environment_event,
    dismiss_suggestions,
)
from fos.core.event_queue import EventQueue
from fos.core.external_event import ExternalEvent, ExternalEventType, EventSource, Severity

logger = logging.getLogger(__name__)


def _parse_node_id_param(request: Request) -> int | None:
    node_id_param = request.query_params.get("node_id")
    if node_id_param is None:
        return None
    try:
        return int(node_id_param)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=T("api.errors.invalid_node_id_param"))


@get("/simulations/{simulation_id:str}/suggestions/status")
async def get_suggestion_status(
    simulation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Check if environment suggestions are available for the current turn."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        node_id = _parse_node_id_param(request)
        state = await get_simulation_state(simulation_id, session, current_user.id, node_id)

        if not state:
            return {"available": False, "turn": None, "enabled": False}

        config = state["config"]
        if not config.get("enabled"):
            return {"available": False, "turn": None, "enabled": False}

        turns = state["turns"]
        interval = config.get("turn_interval", 5)
        current_interval_milestone = (turns // interval) * interval
        viewed_intervals = state.get("_suggestions_viewed_intervals", set())

        available = (
            turns > 0
            and turns >= interval
            and current_interval_milestone not in viewed_intervals
        )

        return {"available": available, "turn": turns if available else None, "enabled": True}


@post("/simulations/{simulation_id:str}/suggestions/generate")
async def generate_suggestions(
    simulation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Generate environment event suggestions based on current simulation context."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        node_id = _parse_node_id_param(request)
        suggestions = await generate_environment_suggestions(simulation_id, session, current_user.id, node_id)

        # Ensure suggestions are JSON-serializable (convert to list of dicts with str values)
        cleaned_suggestions = [
            {
                "event_type": str(s.get("event_type", "")),
                "description": str(s.get("description", "")),
                "severity": str(s.get("severity", "mild")),
            }
            for s in suggestions
        ]
        return {"suggestions": cleaned_suggestions}


@post("/simulations/{simulation_id:str}/events/environment")
async def apply_environment_event(
    simulation_id: str,
    data: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Apply an environment event to the simulation."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        try:
            await broadcast_environment_event(
                simulation_id,
                data,
                session,
                current_user.id,
            )
            return {"success": True, "message": T('api.environment.event_broadcast')}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@post("/simulations/{simulation_id:str}/suggestions/dismiss")
async def dismiss_suggestions_endpoint(
    simulation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Dismiss environment suggestions for the current interval."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        try:
            await dismiss_suggestions(simulation_id, session, current_user.id)
            return {"success": True, "message": T('api.environment.suggestions_dismissed')}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


# In-memory rules store for MVP (persists until server restart)
_rules_store: list[Any] = []

@get("/rules")
async def get_rules(request: Request) -> dict[str, Any]:
    """Get all configured rules."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)
    return {"rules": _rules_store}

@post("/rules")
async def save_rules(
    data: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Save/replace all rules."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)
    global _rules_store
    _rules_store = data.get("rules", [])
    return {"saved": len(_rules_store)}


# Per-simulation event queues to avoid leaking events across simulations
_simulation_event_queues: dict[str, EventQueue] = {}

# Default queue for non-simulation contexts
_default_event_queue: EventQueue | None = None


def _get_default_queue() -> EventQueue:
    global _default_event_queue
    if _default_event_queue is None:
        _default_event_queue = EventQueue(max_size=1000, dedup_window_hours=24)
    return _default_event_queue


def _get_simulation_queue(simulation_id: str) -> EventQueue:
    """Get or create an event queue for a specific simulation."""
    if simulation_id not in _simulation_event_queues:
        _simulation_event_queues[simulation_id] = EventQueue(max_size=1000, dedup_window_hours=24)
    return _simulation_event_queues[simulation_id]


@get("/events/external")
async def get_external_events(
    request: Request,
    simulation_id: str | None = None,
    type: str | None = None,
    min_severity: str | None = None,
    status: str | None = "pending",
    limit: int = 50,
    source: str | None = None,
) -> dict[str, Any]:
    """Get external events for a simulation from DB.

    Args:
        simulation_id: Optional simulation ID to scope events
        type: Optional event type filter (policy, market, news, custom, manual)
        min_severity: Optional minimum severity filter (low, medium, high, critical)
        status: Optional status filter (pending, applied, dismissed) — default "pending"
        limit: Maximum number of events to return (default 50)
        source: Optional data source ID filter (filters by ExternalEventRecord.source field)
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

        from sqlalchemy import select, desc
        from fos.backend.models.external_event_record import ExternalEventRecord

        stmt = select(ExternalEventRecord).options(
            sqlalchemy.orm.selectinload(ExternalEventRecord.data_source)
        )

        # Apply filters
        if simulation_id:
            stmt = stmt.where(ExternalEventRecord.simulation_id == simulation_id)
        if type:
            stmt = stmt.where(ExternalEventRecord.event_type == type)
        if min_severity:
            severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            min_level = severity_order.get(min_severity, 0)
            stmt = stmt.where(
                ExternalEventRecord.severity.in_(
                    [k for k, v in severity_order.items() if v >= min_level]
                )
            )
        if status:
            stmt = stmt.where(ExternalEventRecord.status == status)
        if source:
            # 'source' param filters by data_source_id (UUID foreign key)
            stmt = stmt.where(ExternalEventRecord.data_source_id == source)

        stmt = stmt.order_by(desc(ExternalEventRecord.event_timestamp)).limit(limit)

        result = await session.execute(stmt)
        records = result.scalars().all()

        events = [
            {
                "id": r.id,
                "event_type": r.event_type,
                "source": r.source,
                "source_name": r.data_source.name if r.data_source else (r.source if r.source != "manual" else None),
                "title": r.title,
                "content": r.content,
                "severity": r.severity,
                "url": r.url,
                "timestamp": r.event_timestamp.isoformat(),
                "status": r.status,
            }
            for r in records
        ]

        return {"events": events, "total": len(events)}


@post("/events/external")
async def add_external_event(
    data: dict[str, Any],
    request: Request,
    simulation_id: str | None = None,
) -> dict[str, Any]:
    """Add an external event to DB.

    This endpoint allows manual injection of events or forwarding
    from external sources (webhook push).
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        await resolve_current_user(session, token)

        try:
            record = await create_external_event_record(
                session,
                simulation_id=simulation_id.upper() if simulation_id else None,
                payload=data,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to persist external event: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=T("api.errors.external_event_save_failed")) from exc

        return {
            "success": True,
            "event_id": record.id,
            "message": "Event added to DB",
        }


@post("/events/external/{event_id:str}/apply")
async def apply_saved_external_event(
    event_id: str,
    request: Request,
    simulation_id: str,
) -> dict[str, Any]:
    """Apply one saved external event row to the selected simulation node."""
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        node_id = _parse_node_id_param(request)
        try:
            result = await apply_external_event_record(
                simulation_id,
                event_id,
                db=session,
                user_id=current_user.id,
                node_id=node_id,
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@post("/events/seed")
async def seed_demo_events(
    request: Request,
    simulation_id: str | None = None,
) -> dict[str, Any]:
    """Seed demo events for testing the event panel UI."""
    try:
        token = extract_bearer_token(request)
        async with get_session() as session:
            await resolve_current_user(session, token)

        queue = _get_simulation_queue(simulation_id) if simulation_id else _get_default_queue()
        logger.info(f"Seed auth OK, queue created, simulation_id={simulation_id}")

        demo_events = [
            ExternalEvent.create(
                event_type=ExternalEventType.MARKET,
                source=EventSource.YAHOO_FINANCE,
                title="股市大幅波动",
                content="上证指数单日下跌 3.2%，市场恐慌情绪蔓延",
                severity=Severity.HIGH,
                metadata={"index": "000001.SS", "change_pct": -3.2},
            ),
            ExternalEvent.create(
                event_type=ExternalEventType.POLICY,
                source=EventSource.NATIONAL_BUREAU,
                title="政府发布新能源汽车补贴政策",
                content="财政部宣布延续新能源汽车购置税减免政策至 2027 年",
                severity=Severity.MEDIUM,
                metadata={"region": "全国", "category": "industrial"},
            ),
            ExternalEvent.create(
                event_type=ExternalEventType.NEWS,
                source=EventSource.NEWS_API,
                title="社交媒体舆论风暴",
                content="某企业家微博发言引发广泛讨论，相关话题阅读量突破 5 亿",
                severity=Severity.HIGH,
                metadata={"platform": "微博", "views": 500000000},
            ),
            ExternalEvent.create(
                event_type=ExternalEventType.MARKET,
                source=EventSource.YAHOO_FINANCE,
                title="银行利率上调",
                content="央行宣布一年期存贷款利率上调 25 个基点",
                severity=Severity.MEDIUM,
                metadata={"rate_change_bp": 25},
            ),
            ExternalEvent.create(
                event_type=ExternalEventType.MANUAL,
                source=EventSource.MANUAL,
                title="突发自然灾害",
                content="某地区发生 5.1 级地震，暂无人员伤亡报告",
                severity=Severity.CRITICAL,
                metadata={"magnitude": 5.1, "region": "某地区"},
            ),
        ]

        added = 0
        for event in demo_events:
            if queue.enqueue(event):
                added += 1

        logger.info(f"Seed complete: added={added}, total={queue.size()}")
        return {"added": added, "total": queue.size()}
    except Exception as e:
        logger.error(f"Seed error: {type(e).__name__}: {e}", exc_info=True)
        raise


def get_external_event_queue(simulation_id: str | None = None) -> EventQueue:
    """Get the event queue for a simulation, or a default queue if none specified.

    DEPRECATED: This function returns in-memory EventQueue which is no longer
    used for DB-backed external events. It is retained for backward compatibility
    with code that may still use in-memory queues for non-DB purposes.
    """
    logger.warning(
        "get_external_event_queue is deprecated and returns in-memory EventQueue. "
        "External events are now stored in DB (external_event_records table)."
    )
    if simulation_id:
        return _get_simulation_queue(simulation_id)
    # Return a module-level default queue for backward compatibility
    return _external_event_queue


# Backward compatibility - module-level default queue
_external_event_queue: EventQueue = EventQueue(max_size=1000, dedup_window_hours=24)


router = Router(
    path="",
    route_handlers=[
        get_suggestion_status,
        generate_suggestions,
        apply_environment_event,
        dismiss_suggestions_endpoint,
        get_rules,
        save_rules,
        get_external_events,
        add_external_event,
        apply_saved_external_event,
        seed_demo_events,
    ],
)
