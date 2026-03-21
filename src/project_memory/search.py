from .db import ProjectMemoryDB
from .embeddings import hybrid_search, load_embedding_config


def search(query: str, root: str = None, limit: int = 20) -> list[dict]:
    with ProjectMemoryDB(root=root) as db:
        config = load_embedding_config()
        if config and db._has_vec:
            # Embedding available but we don't embed the query in the sync CLI path.
            # For now, fall back to keyword. Full hybrid requires async embed_texts.
            pass
        results = db.search(query, limit=limit)
        for r in results:
            r["search_mode"] = "keyword"
        return results
