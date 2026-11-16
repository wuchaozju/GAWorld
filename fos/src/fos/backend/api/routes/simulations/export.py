"""
Simulation export API route.

Provides clean CSV/JSON export with scenario parameters and simplified column structure.
"""
import logging

from litestar import get, Request
from litestar.exceptions import HTTPException
from litestar.response import Response

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.services.export_service import export_events, generate_export_filename
from fos.core.scenarios.registry import get_scenario
from fos.i18n import T

from .helpers import get_simulation_and_tree_for_owner


logger = logging.getLogger(__name__)


@get("/{simulation_id:str}/export")
async def export_simulation(
    request: Request,
    simulation_id: str,
    format: str = "csv",
    node_id: str | None = None,
) -> Response:
    """Export simulation logs in CSV or JSON format.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        format: Export format ("csv" or "json")
        node_id: Optional node filter for branch-specific export

    Returns:
        File download response with proper filename
    """
    logger.info(f"Export request - simulation_id={simulation_id}, format={format}, node_id={node_id}")

    # Extract bearer token
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        # Fetch simulation and tree from memory (logs are stored in SimTree, not database)
        sim, record = await get_simulation_and_tree_for_owner(session, current_user.id, simulation_id)
        logger.info(f"Found simulation: {sim.id}, owner_id={current_user.id}")

        if not sim:
            raise HTTPException(status_code=404, detail=T("api.errors.simulation_not_found"))

        # Get scenario config
        scene_config = sim.scene_config or {}
        scenario_id = scene_config.get("scenario_id", "unknown")

        # Fetch scenario parameters from registry
        scenario_def = get_scenario(scenario_id) or {}
        param_defs = scenario_def.get("parameters", [])

        # Extract scenario parameter values from scene_config
        scenario_params = {"scenario_id": scenario_id}
        for param_def in param_defs:
            key = param_def.get("key", param_def.get("id"))
            if key in scene_config:
                scenario_params[key] = scene_config[key]
            elif "default" in param_def:
                scenario_params[key] = param_def["default"]

        logger.info(f"Base scenario params: {scenario_params}")

        # Build per-node scenario params by walking the tree and applying
        # config_params_patch operations. This ensures experiment variants
        # with different parameters (e.g., multiplier=1.6) export correctly.
        node_params_cache: dict[int, dict] = {}

        def get_node_params(nid: int) -> dict:
            """Build scenario params for a node, inheriting from parent and applying own patches."""
            if nid in node_params_cache:
                return node_params_cache[nid]

            node = record.tree.nodes.get(nid)
            if not node:
                return scenario_params

            parent_id = node.get("parent")
            if parent_id is not None and parent_id in record.tree.nodes:
                base = dict(get_node_params(parent_id))
            else:
                base = dict(scenario_params)

            for op in (node.get("ops") or []):
                if op.get("op") == "config_params_patch":
                    base.update(op.get("updates", {}))

            node_params_cache[nid] = base
            return base

        # Collect logs from tree nodes (logs are stored in memory, not database)
        all_logs = []

        if node_id:
            # Export logs for specific node
            target_node_id = int(node_id)
            node = record.tree.nodes.get(target_node_id)
            if node is None:
                raise HTTPException(status_code=404, detail=T("api.errors.node_export_not_found", node_id=node_id))
            node_logs = node.get("logs", [])
            all_logs.extend(node_logs)
            logger.info(f"Found {len(node_logs)} logs for node {node_id}")
        else:
            # Export logs for all nodes
            for nid, node in record.tree.nodes.items():
                node_logs = node.get("logs", [])
                all_logs.extend(node_logs)

        logger.info(f"Found {len(all_logs)} total logs across all nodes")

        # Sort logs by sequence if available, otherwise by node then sequence
        def get_sort_key(log_entry):
            # Logs have format: {"type": kind, "data": data, "node": int(node_id)}
            node_seq = log_entry.get("node", 0)
            data = log_entry.get("data", {})
            # Try to get sequence from data
            seq = data.get("sequence", data.get("turn", 0))
            return (node_seq, seq)

        all_logs.sort(key=get_sort_key)

        # Log sample for debugging
        if all_logs:
            for i, log in enumerate(all_logs[:3]):
                logger.info(f"Sample log {i}: type={log.get('type')}, data keys={list(log.get('data', {}).keys()) if log.get('data') else 'None'}")

        # Convert to format expected by export_service
        # export_service expects events with: sequence, tree_node_id, event_type, payload, created_at
        events = []
        for seq_num, log in enumerate(all_logs):
            log_data = log.get("data", {})
            nid = log.get("node")
            events.append({
                "sequence": seq_num,
                "tree_node_id": nid,
                "event_type": log.get("type"),
                "payload": log_data,
                "created_at": log.get("timestamp") or log_data.get("created_at") or log_data.get("timestamp"),
                "_node_scenario_params": get_node_params(nid) if nid is not None else scenario_params,
            })

        # Export
        content = export_events(events, scenario_params, format)
        filename = generate_export_filename(scenario_id, format)
        logger.info(f"Export content length: {len(content)} chars, first 500 chars: {content[:500]}")

        # Return with proper headers
        media_type = "text/csv" if format == "csv" else "application/json"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
