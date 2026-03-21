from .db import ProjectMemoryDB


def search(query: str, root: str = None, limit: int = 20) -> list[dict]:
    with ProjectMemoryDB(root=root) as db:
        return db.search(query, limit=limit)
