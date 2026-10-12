"""
Hybrid vector store supporting ChromaDB with JSON fallback.

When ChromaDB is available and enabled, uses it for efficient similarity search.
Otherwise, falls back to in-memory cosine similarity on JSON embeddings.
"""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Singleton instance
_vector_store_instance: Optional["VectorStore"] = None


def get_vector_store() -> Optional["VectorStore"]:
    """Get the global vector store instance, or None if not configured."""
    global _vector_store_instance
    return _vector_store_instance


def initialize_vector_store(use_chromadb: bool = False, persist_dir: str = "./chroma_db") -> Optional["VectorStore"]:
    """
    Initialize the global vector store instance.

    Call this during application startup if ChromaDB is desired.
    """
    global _vector_store_instance

    if _vector_store_instance is not None:
        return _vector_store_instance

    if use_chromadb:
        try:
            _vector_store_instance = VectorStore(use_chromadb=True, persist_dir=persist_dir)
            logger.info(f"Vector store initialized: ChromaDB at {persist_dir}")
            return _vector_store_instance
        except Exception as e:
            logger.warning(f"Failed to initialize ChromaDB: {e}. Falling back to JSON.")

    # Not using ChromaDB or initialization failed
    _vector_store_instance = VectorStore(use_chromadb=False)
    logger.info("Vector store initialized: JSON fallback mode")
    return _vector_store_instance


class VectorStore:
    """
    Hybrid vector store with ChromaDB support and JSON fallback.

    Usage:
        # Initialize at startup
        vector_store = initialize_vector_store(use_chromadb=True)

        # Store document
        vector_store.add_document("agent_1", "doc_123", chunks, embeddings)

        # Search
        results = vector_store.search("agent_1", query_embedding, top_k=5)

    If ChromaDB operations fail or return None, caller should use JSON cosine similarity.
    """

    def __init__(self, use_chromadb: bool = False, persist_dir: str = "./chroma_db"):
        self.use_chromadb = use_chromadb
        self.persist_dir = persist_dir
        self._chroma_client = None
        self._collections: Dict[str, Any] = {}

        if use_chromadb:
            self._init_chromadb()

    def _init_chromadb(self):
        """Initialize ChromaDB persistent client."""
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=self.persist_dir)
            logger.info(f"ChromaDB initialized at {self.persist_dir}")
        except ImportError:
            logger.warning("ChromaDB package not installed")
            self.use_chromadb = False
        except Exception as e:
            logger.warning(f"ChromaDB initialization failed: {e}")
            self.use_chromadb = False

    def _get_collection(self, collection_name: str):
        """Get or create a ChromaDB collection."""
        if not self._chroma_client:
            return None

        if collection_name not in self._collections:
            try:
                self._collections[collection_name] = self._chroma_client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
            except Exception as e:
                logger.warning(f"Failed to get collection {collection_name}: {e}")
                return None

        return self._collections[collection_name]

    def add_document(
        self,
        agent_id: str,
        doc_id: str,
        chunks: List[dict],
        embeddings: List[List[float]]
    ) -> bool:
        """
        Store document chunks in vector store.

        Returns True if stored in ChromaDB, False for JSON fallback.
        """
        if not self.use_chromadb or not self._chroma_client:
            return False

        collection_name = f"agent_{agent_id}"
        collection = self._get_collection(collection_name)

        if not collection:
            return False

        try:
            ids = [f"{doc_id}_{c['chunk_id']}" for c in chunks]
            texts = [c['text'] for c in chunks]
            metadatas = [
                {"doc_id": doc_id, "chunk_id": c['chunk_id'], "filename": c.get("filename", "")}
                for c in chunks
            ]

            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )
            logger.info(f"Added {len(chunks)} chunks to collection {collection_name}")
            return True

        except Exception as e:
            logger.warning(f"ChromaDB add failed for {doc_id}: {e}")
            return False

    def search(
        self,
        agent_id: str,
        query_embedding: List[float],
        top_k: int = 5,
        doc_ids: Optional[List[str]] = None
    ) -> Optional[List[dict]]:
        """
        Search for similar chunks.

        Returns results if found in ChromaDB, None for JSON fallback.

        Args:
            agent_id: Agent identifier
            query_embedding: Query vector (MiniLM embedding)
            top_k: Number of results to return
            doc_ids: Optional list of document IDs to filter by
        """
        if not self.use_chromadb or not self._chroma_client:
            return None

        collection_name = f"agent_{agent_id}"
        collection = self._get_collection(collection_name)

        if not collection:
            return None

        try:
            query_params = {
                "query_embeddings": [query_embedding],
                "n_results": top_k
            }

            # Optional document filtering
            if doc_ids:
                query_params["where"] = {"doc_id": {"$in": doc_ids}}

            results = collection.query(**query_params)

            if not results or not results["documents"]:
                return []

            # Convert to our expected format
            formatted_results = []
            for doc, dist, meta in zip(
                results["documents"][0],
                results["distances"][0],
                results["metadatas"][0]
            ):
                formatted_results.append({
                    "text": doc,
                    "similarity": 1.0 - dist,  # Chroma returns distance, convert to similarity
                    "doc_id": meta.get("doc_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "filename": meta.get("filename", ""),
                    "source": "private"
                })

            return formatted_results

        except Exception as e:
            logger.warning(f"ChromaDB search failed: {e}")
            return None

    def delete_document(self, agent_id: str, doc_id: str) -> bool:
        """Delete all chunks for a document."""
        if not self.use_chromadb or not self._chroma_client:
            return False

        collection_name = f"agent_{agent_id}"
        collection = self._get_collection(collection_name)

        if not collection:
            return False

        try:
            # Delete all chunks for this document
            collection.delete(where={"doc_id": doc_id})
            logger.info(f"Deleted document {doc_id} from {collection_name}")
            return True
        except Exception as e:
            logger.warning(f"ChromaDB delete failed: {e}")
            return False

    def delete_agent(self, agent_id: str) -> bool:
        """Delete all data for an agent."""
        if not self.use_chromadb or not self._chroma_client:
            return False

        collection_name = f"agent_{agent_id}"

        try:
            self._chroma_client.delete_collection(collection_name)
            self._collections.pop(collection_name, None)
            logger.info(f"Deleted collection {collection_name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete collection {collection_name}: {e}")
            return False
