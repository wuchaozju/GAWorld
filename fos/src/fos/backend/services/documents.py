"""
Document processing service for agent knowledge base.

Handles file upload, text extraction, chunking, and embedding generation.
Supports PDF, TXT, DOCX, MD files.

Uses sentence-transformers with MiniLM for fast local embeddings.
"""

import logging

from fos.i18n import T
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx

from .default_providers import get_default_ollama_base_url

logger = logging.getLogger(__name__)


# ----- Embedding Model (lazy loaded singleton) -----

_embedding_model = None


def _resolve_embedding_backend() -> str:
    backend = (os.getenv("FOS_EMBEDDING_BACKEND") or "sentence-transformers").strip().lower()
    if backend not in {"sentence-transformers", "ollama"}:
        raise RuntimeError(T("Unsupported embedding backend: {backend}", backend=backend))
    return backend


def _resolve_embedding_device() -> str:
    import torch

    requested = (os.getenv("FOS_EMBEDDING_DEVICE") or "cuda").strip().lower()
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(T("api.errors.cuda_not_available"))
        return "cuda"
    if requested == "cpu":
        return "cpu"
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    raise RuntimeError(T("Unsupported embedding device: {requested}", requested=requested))


def _resolve_embedding_model_source() -> str:
    local_path = (os.getenv("FOS_EMBEDDING_MODEL_PATH") or "").strip()
    if local_path:
        return local_path
    return 'all-MiniLM-L6-v2'


def _resolve_ollama_embedding_model() -> str:
    model = (os.getenv("FOS_OLLAMA_EMBED_MODEL") or "nomic-embed-text:latest").strip()
    if not model:
        raise RuntimeError(T("api.errors.ollama_embed_model_required"))
    return model


def _ollama_embedding_request(texts: list[str]) -> list[list[float]]:
    model = _resolve_ollama_embedding_model()
    base_url = get_default_ollama_base_url()
    embeddings: list[list[float]] = []

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        for text in texts:
            response = client.post(
                "/api/embeddings",
                json={
                    "model": model,
                    "prompt": text,
                },
            )
            response.raise_for_status()
            payload = response.json()
            embedding = payload["embedding"]
            embeddings.append(embedding)

    return embeddings


def get_embedding_model():
    """
    Get the sentence-transformers embedding model (lazy loaded singleton).
    Uses all-MiniLM-L6-v2 for fast, high-quality embeddings.
    """
    global _embedding_model
    if _embedding_model is None:
        backend = _resolve_embedding_backend()
        if backend != "sentence-transformers":
            raise RuntimeError(T("Embedding model object is only available for sentence-transformers backend, got {backend}", backend=backend))
        device = _resolve_embedding_device()
        model_source = _resolve_embedding_model_source()
        logger.info(f"Loading sentence-transformers model: {model_source}")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(model_source, device=device)
        logger.info(f"Embedding model loaded successfully from {model_source} on device={device}")
    return _embedding_model


def generate_embedding(text: str) -> list[float]:
    """Generate embedding for a single text using MiniLM."""
    backend = _resolve_embedding_backend()
    if backend == "ollama":
        return _ollama_embedding_request([text])[0]

    model = get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in batch (more efficient)."""
    backend = _resolve_embedding_backend()
    if backend == "ollama":
        return _ollama_embedding_request(texts)

    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [emb.tolist() for emb in embeddings]


# ----- Text Extraction (strict, no fallbacks) -----

def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file using pypdf."""
    import pypdf

    reader = pypdf.PdfReader(BytesIO(file_content))
    pages = []
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages.append(text)
        logger.debug(f"PDF page {page_num + 1}: {len(text) if text else 0} chars")

    full_text = "\n\n".join(pages)
    if not full_text.strip():
        raise ValueError(T("api.errors.pdf_empty_text"))

    logger.info(f"Text extraction complete - chars={len(full_text)}")
    return full_text


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from DOCX file using python-docx."""
    import docx

    doc = docx.Document(BytesIO(file_content))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]

    full_text = "\n\n".join(paragraphs)
    if not full_text.strip():
        raise ValueError(T("api.errors.docx_empty_text"))

    logger.info(f"Text extraction complete - chars={len(full_text)}")
    return full_text


def extract_text_from_txt(file_content: bytes) -> str:
    """Extract text from TXT/MD file."""
    full_text = file_content.decode("utf-8")
    if not full_text.strip():
        raise ValueError(T("api.errors.txt_empty_text"))

    logger.info(f"Text extraction complete - chars={len(full_text)}")
    return full_text


def extract_text(file_content: bytes, filename: str) -> str:
    """
    Extract text from file based on extension.
    Raises exception if extraction fails (strict, no fallbacks).
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return extract_text_from_pdf(file_content)
    elif ext == ".docx":
        return extract_text_from_docx(file_content)
    elif ext in (".txt", ".md"):
        return extract_text_from_txt(file_content)
    else:
        raise ValueError(T("Unsupported file type: {ext}", ext=ext))


# ----- Text Chunking (fixed strategy) -----

def chunk_text(text: str, chunk_size: int = 750, overlap: float = 0.2) -> list[dict]:
    """
    Split text into overlapping chunks.

    Fixed: 750 chars, 20% overlap
    No variable strategies.

    Returns list of chunk dicts with text, start_index, end_index.
    """
    overlap_chars = int(chunk_size * overlap)
    chunks = []
    start = 0
    chunk_num = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]

        chunks.append({
            "chunk_id": f"c{chunk_num:03d}",
            "text": chunk_text,
            "start_index": start,
            "end_index": end,
        })

        chunk_num += 1
        # Move start forward, accounting for overlap
        start = end - overlap_chars

        # Prevent infinite loop at end of text
        if start >= len(text) - overlap_chars:
            break

    avg_size = sum(len(c["text"]) for c in chunks) / len(chunks) if chunks else 0
    logger.debug(f"Text chunking - chunks={len(chunks)}, avg_size={avg_size:.0f}")

    return chunks


# ----- Embedding Generation -----

def generate_embeddings(chunks: list[dict], llm_client=None) -> dict[str, list[float]]:
    """
    Generate embeddings for all chunks using MiniLM (sentence-transformers).

    The llm_client parameter is kept for backwards compatibility but is not used.

    Returns dict mapping chunk_id -> embedding vector.
    """
    logger.debug(f"Starting embeddings for {len(chunks)} chunks using MiniLM")

    # Extract texts for batch processing (more efficient)
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    texts = [chunk["text"] for chunk in chunks]

    # Generate all embeddings in batch
    embedding_vectors = generate_embeddings_batch(texts)

    # Build result dict
    embeddings = dict(zip(chunk_ids, embedding_vectors))

    logger.info(f"Embeddings complete - {len(embeddings)} chunks")
    return embeddings


# ----- Document Processing Pipeline -----

def process_document(
    file_content: bytes,
    filename: str,
    file_size: int,
    llm_client=None,
) -> dict:
    """
    Complete document processing pipeline:
    1. Extract text
    2. Chunk text
    3. Generate embeddings (using MiniLM)
    4. Return document data ready for storage

    The llm_client parameter is kept for backwards compatibility but is not used.
    Raises exception on any failure (strict, no fallbacks).
    """
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"

    logger.info(f"Document processing started - doc_id={doc_id}, file={filename}, size={file_size}")

    # Step 1: Extract text
    text = extract_text(file_content, filename)

    # Step 2: Chunk text
    chunks = chunk_text(text)

    # Step 3: Generate embeddings
    embeddings = generate_embeddings(chunks, llm_client)

    # Build document record
    document = {
        "id": doc_id,
        "filename": filename,
        "file_size": file_size,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "text_length": len(text),
        "chunks": chunks,
        "embeddings": embeddings,
    }

    logger.info(f"Document stored - doc_id={doc_id}, chunks={len(chunks)}")

    return document


# ----- RAG Retrieval -----

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec_a or not vec_b:
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def retrieve_from_documents(
    query_embedding: list[float],
    documents: dict,
    top_k: int = 5,
    source_type: str = "private",
) -> list[dict]:
    """
    Retrieve relevant chunks from documents based on query embedding.

    Returns list of results sorted by similarity (descending).
    """
    results = []

    for doc_id, doc in documents.items():
        embeddings = doc.get("embeddings", {})
        chunks = {c["chunk_id"]: c for c in doc.get("chunks", [])}

        for chunk_id, embedding in embeddings.items():
            similarity = cosine_similarity(query_embedding, embedding)
            chunk_data = chunks.get(chunk_id, {})

            results.append({
                "source": source_type,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "filename": doc.get("filename", ""),
                "text": chunk_data.get("text", ""),
                "similarity": similarity,
            })

    # Sort by similarity descending and take top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def retrieve_from_global_knowledge(
    query_embedding: list[float],
    global_knowledge: dict,
    top_k: int = 5,
) -> list[dict]:
    """
    Retrieve relevant items from global knowledge base.

    Handles both single-embedding items (manual text) and
    multi-chunk items (uploaded documents).
    """
    results = []

    for kw_id, kw in global_knowledge.items():
        # Single embedding (manual text)
        if "embedding" in kw and kw["embedding"]:
            similarity = cosine_similarity(query_embedding, kw["embedding"])
            results.append({
                "source": "global",
                "kw_id": kw_id,
                "chunk_id": None,
                "text": kw.get("content", "")[:500],
                "similarity": similarity,
                "source_type": kw.get("source_type", "manual_text"),
            })

        # Multiple embeddings (document chunks)
        elif "embeddings" in kw:
            chunks = {c["chunk_id"]: c for c in kw.get("chunks", [])}
            for chunk_id, embedding in kw.get("embeddings", {}).items():
                similarity = cosine_similarity(query_embedding, embedding)
                chunk_data = chunks.get(chunk_id, {})
                results.append({
                    "source": "global",
                    "kw_id": kw_id,
                    "chunk_id": chunk_id,
                    "filename": kw.get("filename", ""),
                    "text": chunk_data.get("text", ""),
                    "similarity": similarity,
                    "source_type": kw.get("source_type", "document"),
                })

    # Sort by similarity descending and take top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def composite_rag_retrieval(
    query: str,
    llm_client=None,
    agent_documents: dict | None = None,
    global_knowledge: dict | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Composite RAG retrieval merging private agent documents and global knowledge.

    1. Generate query embedding (using MiniLM)
    2. Retrieve from private documents
    3. Retrieve from global knowledge
    4. Merge and rank by similarity

    The llm_client parameter is kept for backwards compatibility but is not used.
    Returns top_k results sorted by similarity.
    Private results are prioritized if similarity is equal.
    """
    request_id = uuid.uuid4().hex[:8]
    logger.info(f"RAG retrieval initiated - request_id={request_id}, query='{query[:50]}...'")

    # Generate query embedding using MiniLM
    logger.debug(f"[{request_id}] Generating query embedding using MiniLM")
    query_embedding = generate_embedding(query)
    logger.debug(f"[{request_id}] Query embedding generated")

    all_results = []

    # Retrieve from private documents
    if agent_documents:
        logger.debug(f"[{request_id}] Retrieving from private documents")
        private_results = retrieve_from_documents(
            query_embedding,
            agent_documents,
            top_k=top_k * 2,  # Get more so we can merge
            source_type="private"
        )
        all_results.extend(private_results)
        logger.info(f"[{request_id}] Private retrieval - results={len(private_results)}")

    # Retrieve from global knowledge
    if global_knowledge:
        logger.debug(f"[{request_id}] Retrieving from global knowledge")
        global_results = retrieve_from_global_knowledge(
            query_embedding,
            global_knowledge,
            top_k=top_k * 2,
        )
        all_results.extend(global_results)
        logger.info(f"[{request_id}] Global retrieval - results={len(global_results)}")

    # Sort by similarity, with private prioritized on tie
    # Private source gets a small boost (0.001) to break ties
    all_results.sort(
        key=lambda x: (x["similarity"] + (0.001 if x["source"] == "private" else 0)),
        reverse=True
    )

    merged = all_results[:top_k]
    logger.info(f"[{request_id}] RAG complete - merged={len(merged)}")

    return merged


def format_rag_context(results: list[dict]) -> str:
    """
    Format RAG results as context string for agent prompt.
    """
    if not results:
        return ""

    context_parts = []
    for i, result in enumerate(results, 1):
        source_label = "Personal knowledge" if result["source"] == "private" else "Shared knowledge"
        filename = result.get("filename", "")
        source_info = f" (from {filename})" if filename else ""

        context_parts.append(f"[{i}] {source_label}{source_info}:\n{result['text']}")

    return "\n\n".join(context_parts)