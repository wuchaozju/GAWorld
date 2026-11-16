"""
Global knowledge management API routes.

Manages knowledge that is accessible to all agents in a simulation.
This includes both text entries and document-based knowledge.

Global knowledge is stored in the simulation's scene_config and
is shared across all agents during RAG retrieval.

Contains:
    - add_global_knowledge: Add text knowledge
    - upload_global_document: Upload document as knowledge
    - list_global_knowledge: Get all global knowledge
    - delete_global_knowledge: Remove knowledge entry
"""

import asyncio
import copy
import logging
from datetime import datetime, timezone

from litestar import get, post, delete
from litestar.connection import Request
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.exceptions import HTTPException
from sqlalchemy.orm.attributes import flag_modified

from fos.backend.core.database import get_session
from fos.backend.dependencies import extract_bearer_token, resolve_current_user
from fos.backend.services.documents import process_document, generate_embedding
from fos.i18n import T
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

from .helpers import get_simulation_for_owner


logger = logging.getLogger(__name__)

# Constants for document upload validation
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}


@post("/{simulation_id:str}/global-knowledge")
async def add_global_knowledge(
    request: Request,
    simulation_id: str,
    data: dict,
) -> dict:
    """
    Add text content to the global knowledge base.

    Creates a knowledge entry from text that will be accessible
    to all agents in the simulation. Generates an embedding
    for semantic search.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        data: Dictionary with:
            - content: Required text content
            - title: Optional title for the knowledge

    Returns:
        Dictionary with:
        - success: True
        - kw_id: Knowledge item ID

    Raises:
        HTTPException: If authentication fails or content missing
    """
    import uuid

    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        content = data.get("content")
        title = data.get("title", "")

        if not content:
            raise HTTPException(status_code=400, detail=T("api.errors.content_required"))

        logger.info(f"Global knowledge add initiated - sim_id={simulation_id}, source=manual_text")

        # Generate embedding using MiniLM
        logger.debug("Generating embedding for global knowledge using MiniLM")
        embedding = await asyncio.to_thread(generate_embedding, content)
        logger.info(f"Embedding generated - sim_id={simulation_id}")

        kw_id = f"gk_{uuid.uuid4().hex[:8]}"

        # Get or create global_knowledge in scene_config
        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        global_knowledge[kw_id] = {
            "id": kw_id,
            "title": title,
            "content": content,
            "source_type": "manual_text",
            "filename": None,
            "created_by": str(current_user.id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding": embedding,
        }

        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global knowledge stored - kw_id={kw_id}")

        return {"success": True, "kw_id": kw_id}


@post("/{simulation_id:str}/global-knowledge/documents")
async def upload_global_document(
    request: Request,
    simulation_id: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    Upload a document to the global knowledge base.

    Processes the uploaded file to extract text, create chunks,
    and generate embeddings. The document becomes accessible
    to all agents in the simulation.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        data: Uploaded file

    Returns:
        Dictionary with:
        - success: True
        - kw_id: Knowledge item ID
        - chunks_count: Number of chunks created
        - filename: Original filename

    Raises:
        HTTPException: If authentication fails, file invalid,
                      or processing fails
    """
    import uuid

    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        filename = data.filename
        file_content = await data.read()
        file_size = len(file_content)

        logger.info(f"Global document upload initiated - sim_id={simulation_id}, file={filename}, size={file_size}")

        # Validate file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.invalid_file_type", extensions=", ".join(ALLOWED_EXTENSIONS))
            )

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=T("api.errors.file_too_large", max_mb=MAX_FILE_SIZE // (1024*1024))
            )

        # Process document
        try:
            document = await asyncio.to_thread(
                process_document,
                file_content,
                filename,
                file_size,
            )
        except ImportError as e:
            logger.error(f"Global upload failed - sim_id={simulation_id}, reason=Missing dependency: {e}")
            raise HTTPException(
                status_code=500,
                detail=T("api.errors.sentence_transformers_missing")
            )
        except Exception as e:
            logger.exception(f"Global upload failed - sim_id={simulation_id}, reason={e}")
            raise HTTPException(
                status_code=500,
                detail=T("api.errors.document_processing_failed", error=str(e))
            )

        kw_id = f"gk_{uuid.uuid4().hex[:8]}"

        # Get or create global_knowledge in scene_config
        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        global_knowledge[kw_id] = {
            "id": kw_id,
            "content": f"Document: {filename}",
            "source_type": "document",
            "filename": filename,
            "file_size": file_size,
            "created_by": str(current_user.id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chunks": document["chunks"],
            "embeddings": document["embeddings"],
        }

        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global document stored - kw_id={kw_id}, chunks={len(document['chunks'])}")

        return {
            "success": True,
            "kw_id": kw_id,
            "chunks_count": len(document["chunks"]),
            "filename": filename,
        }


@get("/{simulation_id:str}/global-knowledge")
async def list_global_knowledge(
    request: Request,
    simulation_id: str,
) -> list[dict]:
    """
    List all items in the global knowledge base.

    Returns both text entries and documents that have been added
    to the global knowledge for this simulation.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier

    Returns:
        List of knowledge item dictionaries with metadata

    Raises:
        HTTPException: If authentication fails
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        scene_config = sim.scene_config or {}
        global_knowledge = scene_config.get("global_knowledge", {})

        return [
            {
                "id": kw["id"],
                "title": kw.get("title", kw.get("filename", "Untitled")),
                "content_preview": kw.get("content", "")[:200],
                "source_type": kw.get("source_type", "unknown"),
                "filename": kw.get("filename"),
                "created_at": kw.get("created_at"),
                "chunks_count": len(kw.get("chunks", [])) if "chunks" in kw else 0,
            }
            for kw in global_knowledge.values()
        ]


@delete("/{simulation_id:str}/global-knowledge/{kw_id:str}", status_code=200)
async def delete_global_knowledge(
    request: Request,
    simulation_id: str,
    kw_id: str,
) -> dict:
    """
    Delete an item from the global knowledge base.

    Removes the knowledge entry and updates both the database
    and any cached tree state.

    Args:
        request: Litestar request with auth token
        simulation_id: Simulation identifier
        kw_id: Knowledge item ID to delete

    Returns:
        Dictionary with:
        - success: True
        - deleted_kw_id: The knowledge ID that was deleted

    Raises:
        HTTPException: If authentication fails, simulation not found,
                      or knowledge item not found
    """
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        sim = await get_simulation_for_owner(session, current_user.id, simulation_id)

        scene_config = copy.deepcopy(sim.scene_config) if sim.scene_config else {}
        global_knowledge = scene_config.get("global_knowledge", {})

        if kw_id not in global_knowledge:
            raise HTTPException(
                status_code=404,
                detail=T("api.errors.global_knowledge_not_found", kw_id=kw_id)
            )

        del global_knowledge[kw_id]
        scene_config["global_knowledge"] = global_knowledge
        sim.scene_config = scene_config
        flag_modified(sim, "scene_config")

        await session.commit()

        # Update global knowledge in cached tree if exists
        SIM_TREE_REGISTRY.update_global_knowledge(simulation_id, global_knowledge)

        logger.info(f"Global knowledge deleted - kw_id={kw_id}, sim={simulation_id}")

        return {"success": True, "deleted_kw_id": kw_id}
