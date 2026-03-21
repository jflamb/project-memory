"""Embedding configuration, storage, and hybrid search."""

import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .db import ProjectMemoryDB, normalize_fts_query

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "project-memory"
_CONFIG_FILENAME = "config.json"


@dataclass
class EmbeddingConfig:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    dimensions: int = 384


def save_embedding_config(config: EmbeddingConfig, config_dir: Path = None) -> Path:
    """Save embedding config to a JSON file. Returns the path written."""
    config_dir = config_dir or _DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / _CONFIG_FILENAME
    data = {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model,
        "dimensions": config.dimensions,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_embedding_config(config_dir: Path = None) -> Optional[EmbeddingConfig]:
    """Load embedding config from file + env var overrides.

    Returns None if no config file and no API key env var.
    """
    config_dir = config_dir or _DEFAULT_CONFIG_DIR
    path = config_dir / _CONFIG_FILENAME

    # Start with file values if they exist
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}

    # Env vars override file values
    api_key = os.environ.get("PROJECT_MEMORY_EMBEDDING_API_KEY", data.get("api_key"))
    if not api_key:
        return None

    base_url = os.environ.get("PROJECT_MEMORY_EMBEDDING_API_BASE", data.get("base_url", "https://api.openai.com/v1"))
    model = os.environ.get("PROJECT_MEMORY_EMBEDDING_MODEL", data.get("model", "text-embedding-3-small"))
    dimensions = int(data.get("dimensions", 384))

    return EmbeddingConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dimensions=dimensions,
    )


def _serialize_vector(vec: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_vector(data: bytes, dims: int) -> list[float]:
    """Deserialize bytes back to a float vector."""
    return list(struct.unpack(f"{dims}f", data))


def store_embedding(db: ProjectMemoryDB, doc_id: int, vector: list[float]):
    """Store or update an embedding vector for a document."""
    vec_bytes = _serialize_vector(vector)
    # Delete existing if any, then insert
    db.conn.execute("DELETE FROM vec_documents WHERE rowid = ?", (doc_id,))
    db.conn.execute(
        "INSERT INTO vec_documents(rowid, embedding) VALUES (?, ?)",
        (doc_id, vec_bytes),
    )
    db.conn.commit()


def search_by_embedding(db: ProjectMemoryDB, query_vector: list[float], limit: int = 20) -> List[dict]:
    """Search documents by vector similarity. Returns list of dicts with id, path, content, distance."""
    vec_bytes = _serialize_vector(query_vector)
    cur = db.conn.execute(
        """SELECT v.rowid, v.distance, d.path, d.content
           FROM vec_documents v
           JOIN documents d ON v.rowid = d.id
           WHERE v.embedding MATCH ? AND k = ?
           ORDER BY v.distance""",
        (vec_bytes, limit),
    )
    return [{"id": row[0], "distance": row[1], "path": row[2], "content": row[3]} for row in cur.fetchall()]


def hybrid_search(
    db: ProjectMemoryDB,
    query: str,
    query_vector: Optional[list[float]] = None,
    limit: int = 20,
) -> List[dict]:
    """Hybrid search combining FTS5 bm25 and vector cosine similarity.

    Uses reciprocal rank fusion (RRF) to merge results.
    Falls back to keyword-only if no query_vector is provided.
    """
    # FTS5 keyword results
    fts_results = db.search(query, limit=limit * 2)

    if not query_vector or not db._has_vec:
        # Keyword-only mode
        for r in fts_results:
            r["search_mode"] = "keyword"
        return fts_results[:limit]

    # Vector results
    try:
        vec_results = search_by_embedding(db, query_vector, limit=limit * 2)
    except Exception:
        # Vector table might not exist or be empty
        for r in fts_results:
            r["search_mode"] = "keyword"
        return fts_results[:limit]

    # Reciprocal Rank Fusion
    k = 60  # RRF constant
    scores: dict[int, float] = {}
    doc_data: dict[int, dict] = {}

    for rank, r in enumerate(fts_results):
        doc_id = r["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        doc_data[doc_id] = r

    for rank, r in enumerate(vec_results):
        doc_id = r["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        if doc_id not in doc_data:
            doc_data[doc_id] = r

    # Sort by combined RRF score (highest first)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids[:limit]:
        entry = doc_data[doc_id].copy()
        entry["search_mode"] = "hybrid"
        entry["rrf_score"] = scores[doc_id]
        results.append(entry)

    return results


async def embed_texts(config: EmbeddingConfig, texts: List[str]) -> List[list[float]]:
    """Call the OpenAI-compatible embeddings API. Returns list of vectors.

    Batches texts in groups of 50 to minimize API calls.
    """
    import httpx

    all_embeddings = []
    batch_size = 50

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = await client.post(
                f"{config.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model,
                    "input": batch,
                },
            )
            response.raise_for_status()
            data = response.json()
            batch_embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
            all_embeddings.extend(batch_embeddings)

    return all_embeddings
