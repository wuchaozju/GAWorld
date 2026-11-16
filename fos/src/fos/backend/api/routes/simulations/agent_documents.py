"""
Agent document management API routes.

Handles RAG (Retrieval-Augmented Generation) document operations
for agents. Supports uploading, listing, and deleting documents
associated with specific agents.

Documents are processed to extract text, create chunks, and
generate embeddings for semantic search.

File constraints:
- Allowed types: PDF, TXT, DOCX, MD
- Maximum size: 10 MB
- Storage: Associated with agent in agent_config

Contains:
    - upload_agent_document: Upload and process document for agent
    - list_agent_documents: Get all documents for agent
    - delete_agent_document: Remove document from agent
    - get_agent_memory: Get agent's message memory (for social network testing)
"""

import asyncio
import copy
import logging
from urllib.parse import unquote

from litestar import get, post, delete
from litestar.connection import Request
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.exceptions import HTTPException
from sqlalchemy.orm.attributes import flag_modified

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.services.documents import process_document
from fos.i18n import T
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY
from fos.backend.services.simtree_runtime import get_runtime_agent_count, get_runtime_agent_map

from .helpers import get_simulation_for_owner


logger = logging.getLogger(__name__)

# Constants for document upload validation
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}


def _resolve_social_network_connections(simulator, agent_name: str) -> list[str]:
    """Return neighbor names from either scene.state or scene.config.social_network."""
    scene = getattr(simulator, "scene", None)
    state = getattr(scene, "state", None)
    if isinstance(state, dict):
        social_network = state.get("social_network", {}) or {}
        direct = social_network.get(agent_name)
        if isinstance(direct, list):
            return [str(name).strip() for name in direct if str(name).strip()]

    config_network = getattr(getattr(scene, "config", None), "social_network", {}) or {}
    edges = config_network.get("edges") if isinstance(config_network, dict) else None
    if not isinstance(edges, list):
        return []

    neighbors: list[str] = []
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        left = str(edge[0] or "").strip()
        right = str(edge[1] or "").strip()
        if left == agent_name and right:
            neighbors.append(right)
        elif right == agent_name and left:
            neighbors.append(left)
    return neighbors


@post("/{simulation_id:str}/agents/{agent_name:str}/documents")
async def upload_agent_document(
    request: Request,
    simulation_id: str,
    agent_name: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    Upload a document to an agent's private knowledge base.

    Processes the uploaded file to extract text, create chunks,
    and generate embeddings using the configured embedding model.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        agent_name: Name of the agent to attach document to
        data: Uploaded file

    Returns:
        Dictionary with:
        - success: Boolean indicating success
        - doc_id: Unique document identifier
        - chunks_count: Number of chunks created
        - agent_name: Name of agent
        - filename: Original filename

    Raises:
        HTTPException: If authentication fails, file invalid,
                      or processing fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        filename = data.filename
        file_content = await data.read()
        file_size = len(file_content)

        logger.info(f"File upload initiated - sim_id={simulation_id}, agent={agent_name}, file={filename}, size={file_size}")

        # Validate file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=Invalid file type {ext}")
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.invalid_file_type", extensions=", ".join(ALLOWED_EXTENSIONS))
            )

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=File too large ({file_size} bytes)")
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.file_too_large", max_mb=MAX_FILE_SIZE // (1024*1024))
            )

        logger.debug(f"File validation - type={ext}, size_ok={file_size <= MAX_FILE_SIZE}")

        # Process document (extract, chunk, embed)
        try:
            document = await asyncio.to_thread(
                process_document,
                file_content,
                filename,
                file_size,
            )
        except ImportError as e:
            logger.error(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason=Missing dependency: {e}")
            raise HTTPException(
                status_code=500,
                detail=T("api.errors.sentence_transformers_missing")
            )
        except Exception as e:
            logger.exception(f"Upload failed - sim_id={simulation_id}, agent={agent_name}, reason={e}")
            raise HTTPException(
                status_code=500,
                detail=T("api.errors.document_processing_failed", error=str(e))
            )

        # Update simulation agent_config with the new document
        agent_config = copy.deepcopy(sim.agent_config) if sim.agent_config else {}
        agents = agent_config.get("agents", [])

        # Find the target agent
        agent_found = False
        for agent in agents:
            if agent.get("name") == agent_name:
                agent_found = True
                if "documents" not in agent:
                    agent["documents"] = {}
                agent["documents"][document["id"]] = document
                break

        if not agent_found:
            raise HTTPException(status_code=404, detail=T("api.errors.agent_not_found", agent_name=agent_name))

        agent_config["agents"] = agents
        sim.agent_config = agent_config
        flag_modified(sim, "agent_config")

        await session.commit()

        # Update cached tree if exists
        SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, agent_config)

        logger.info(f"Document stored - doc_id={document['id']}, chunks={len(document['chunks'])}")

        return {
            "success": True,
            "doc_id": document["id"],
            "chunks_count": len(document["chunks"]),
            "agent_name": agent_name,
            "filename": filename,
        }


@get("/{simulation_id:str}/agents/{agent_name:str}/documents")
async def list_agent_documents(
    request: Request,
    simulation_id: str,
    agent_name: str,
) -> list[dict]:
    """
    List all documents uploaded to an agent's private knowledge base.

    Can fetch from in-memory tree node or database config depending
    on whether node_id query parameter is provided.

    Query params:
        node_id: Optional node ID to fetch documents from in-memory tree.
                 If provided, fetches from the tree node's agent.
                 If not provided, fetches from database config.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        agent_name: Name of the agent (URL-decoded automatically)

    Returns:
        List of document metadata dictionaries

    Raises:
        HTTPException: If authentication fails
    """
    # URL-decode the agent_name to handle spaces and special characters
    agent_name = unquote(agent_name)

    token = extract_bearer_token(request)
    node_id_param = request.query_params.get("node_id")

    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        # If node_id is provided, try to fetch from in-memory tree first
        if node_id_param is not None:
            try:
                node_id = int(node_id_param)
                record = SIM_TREE_REGISTRY.get(simulation_id)
                if record is not None:
                    node = record.tree.nodes.get(node_id)
                    if node is not None:
                        simulator = node["sim"]
                        agent = get_runtime_agent_map(simulator).get(agent_name)
                        if agent is not None:
                            documents = getattr(agent, "documents", {})
                            return [
                                {
                                    "id": doc["id"],
                                    "filename": doc["filename"],
                                    "file_size": doc["file_size"],
                                    "uploaded_at": doc["uploaded_at"],
                                    "chunks_count": len(doc.get("chunks", [])),
                                }
                                for doc in documents.values()
                            ]
            except (ValueError, KeyError):
                pass  # Fall through to database lookup

        # Fall back to database config
        agent_config = sim.agent_config or {}
        agents = agent_config.get("agents", [])

        for agent in agents:
            if agent.get("name") == agent_name:
                documents = agent.get("documents", {})
                return [
                    {
                        "id": doc["id"],
                        "filename": doc["filename"],
                        "file_size": doc["file_size"],
                        "uploaded_at": doc["uploaded_at"],
                        "chunks_count": len(doc.get("chunks", [])),
                    }
                    for doc in documents.values()
                ]

        # Return empty list for agents with no documents
        return []


@delete("/{simulation_id:str}/agents/{agent_name:str}/documents/{doc_id:str}", status_code=200)
async def delete_agent_document(
    request: Request,
    simulation_id: str,
    agent_name: str,
    doc_id: str,
) -> dict:
    """
    Delete a document from an agent's private knowledge base.

    Removes the document from the agent's configuration and
    updates both the database and any cached tree state.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        agent_name: Name of the agent
        doc_id: Document identifier to delete

    Returns:
        Dictionary with:
        - success: True
        - deleted_doc_id: The document ID that was deleted

    Raises:
        HTTPException: If authentication fails, agent not found,
                      or document not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        agent_config = copy.deepcopy(sim.agent_config) if sim.agent_config else {}
        agents = agent_config.get("agents", [])

        for agent in agents:
            if agent.get("name") == agent_name:
                documents = agent.get("documents", {})
                if doc_id not in documents:
                    raise HTTPException(status_code=404, detail=T("api.errors.document_not_found", doc_id=doc_id))

                del documents[doc_id]
                agent["documents"] = documents
                agent_config["agents"] = agents
                sim.agent_config = agent_config
                flag_modified(sim, "agent_config")

                await session.commit()

                # Update cached tree if exists
                SIM_TREE_REGISTRY.update_agent_knowledge(simulation_id, agent_config)

                logger.info(f"Document deleted - doc_id={doc_id}, agent={agent_name}, sim={simulation_id}")

                return {"success": True, "deleted_doc_id": doc_id}

        raise HTTPException(status_code=404, detail=T("api.errors.agent_not_found", agent_name=agent_name))


@get("/{simulation_id:str}/agents/{agent_name:str}/memory")
async def get_agent_memory(
    request: Request,
    simulation_id: str,
    agent_name: str,
) -> dict:
    """
    Get an agent's memory to see what messages they have received.

    This helps verify that social network filtering is working correctly -
    agents should only have messages from agents they share an edge with.

    Query params:
        node_id: Optional node ID to fetch from in-memory tree.
                 If not provided, returns error message about needing node_id.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        agent_name: Name of the agent (URL-decoded automatically)

    Returns:
        Dictionary with agent memory info:
        - name: Agent name
        - node_id: Node ID (if from tree)
        - env_feedback_count: Number of environment feedback messages
        - env_feedback_preview: Last 10 feedback messages
        - seen_messages_from: Dictionary of message senders and counts
        - social_network_connections: Agent's connections in social network
        - total_agents: Total number of agents in simulation

    Raises:
        HTTPException: If authentication fails
    """
    # URL-decode the agent_name
    agent_name = unquote(agent_name)

    token = extract_bearer_token(request)
    node_id_param = request.query_params.get("node_id")

    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        await get_simulation_for_owner(session, current_user.id, simulation_id)

        agent_data = None

        # If node_id is provided, try to fetch from in-memory tree
        if node_id_param is not None:
            try:
                node_id = int(node_id_param)
                record = SIM_TREE_REGISTRY.get(simulation_id)
                if record is not None:
                    node = record.tree.nodes.get(node_id)
                    if node is not None:
                        simulator = node["sim"]
                        agent = get_runtime_agent_map(simulator).get(agent_name)
                        if agent is not None:
                            env_feedback = list(
                                getattr(agent, "env_feedback", [])
                                or getattr(agent, "feedback_buffer", [])
                                or []
                            )
                            seen_messages_from = _extract_senders_from_feedback(env_feedback)
                            connections = _resolve_social_network_connections(simulator, agent_name)

                            agent_data = {
                                "name": agent_name,
                                "node_id": node_id,
                                "env_feedback_count": len(env_feedback),
                                "env_feedback_preview": env_feedback[-10:] if env_feedback else [],
                                "seen_messages_from": seen_messages_from,
                                "social_network_connections": connections,
                                "total_agents": get_runtime_agent_count(simulator),
                            }
            except (ValueError, KeyError):
                pass  # Fall through to error response

        # If no agent_data from tree, return error message
        if agent_data is None:
            return {
                "name": agent_name,
                "error": T('api.errors.agent_memory_unavailable'),
                "hint": T('api.documents.memory_not_available'),
            }

        return agent_data


def _extract_senders_from_feedback(env_feedback: list) -> dict:
    """
    Extract unique senders from environment feedback messages.

    Parses feedback strings to extract agent names from message formats.
    Format is typically: "[HH:MM] SenderName: message"

    Args:
        env_feedback: List of feedback message strings

    Returns:
        Dictionary mapping sender names to message counts
    """
    seen_from = {}
    for feedback in env_feedback:
        feedback_str = str(feedback)
        parts = feedback_str.split(":", 1)
        if len(parts) >= 2:
            # Extract name from the first part (after timestamp if present)
            first_part = parts[0].strip()
            # Remove [HH:MM] timestamp if present
            if "] " in first_part:
                first_part = first_part.split("] ", 1)[1] if "] " in first_part else first_part
            if first_part and first_part not in seen_from:
                seen_from[first_part] = seen_from.get(first_part, 0) + 1
            # Count all messages from this sender
            seen_from[first_part] = seen_from.get(first_part, 0) + 1
    return seen_from
