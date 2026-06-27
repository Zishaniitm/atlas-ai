"""
ChromaDB vector memory store — semantic recall via embeddings.
SRS: FR-048, FR-049, FR-050, NFR-009 (<=200ms), NFR-028 (1M+ scale)
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path
from typing import Any

from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_client: Any = None
_collection: Any = None


def init_vector_store() -> None:
    """
    Initialise ChromaDB persistent client and collection.
    SRS: NFR-017 (local embeddings), NFR-028 (HNSW indexing)
    """
    global _client, _collection
    import chromadb  # type: ignore[import]
    path = Path(get_config().memory.vector_db_path).expanduser()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(path))
    _collection = _client.get_or_create_collection(
        name="atlas_episodic_memory",
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("vector_store_init", path=str(path))


async def store_memory_async(
    text: str,
    category: str = "general",
    confidence: float = 1.0,
) -> str:
    """
    Store a fact or preference. Caller must fire-and-forget (BUG-09).
    SRS: FR-048, FR-052, BUG-09
    """
    if _collection is None:
        raise RuntimeError("Call init_vector_store() first.")
    memory_id = str(uuid.uuid4())
    _collection.add(
        documents=[text],
        metadatas=[{"category": category, "confidence": confidence, "timestamp": time.time()}],
        ids=[memory_id],
    )
    logger.debug("memory_stored", category=category, id=memory_id)
    return memory_id


async def search_memory(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """
    Semantic similarity search. SRS: FR-049, NFR-009 (<=200ms P95)
    """
    if _collection is None:
        raise RuntimeError("Call init_vector_store() first.")
    results = _collection.query(query_texts=[query], n_results=n_results)
    docs  = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    return [
        {"text": doc, "category": m.get("category"), "confidence": m.get("confidence"),
         "timestamp": m.get("timestamp"), "distance": d}
        for doc, m, d in zip(docs, metas, dists)
    ]


async def delete_all_memory() -> None:
    """Purge all episodic memory. SRS: FR-051, NFR-044"""
    global _collection
    if _client is None:
        raise RuntimeError("Call init_vector_store() first.")
    _client.delete_collection("atlas_episodic_memory")
    _collection = _client.get_or_create_collection(
        name="atlas_episodic_memory",
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("all_episodic_memory_deleted")
