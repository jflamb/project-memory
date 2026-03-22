from .db import ProjectMemoryDB


def search(query: str, root: str = None, limit: int = 20) -> list[dict]:
    """Search indexed repository content using keyword search."""
    with ProjectMemoryDB(root=root) as db:
        results = db.search(query, limit=limit)
        for r in results:
            r["search_mode"] = "keyword"
        return results
