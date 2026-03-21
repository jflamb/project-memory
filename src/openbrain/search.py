from .db import OpenBrainDB


def search(query: str, root: str = None, limit: int = 20) -> list[dict]:
    with OpenBrainDB(root=root) as db:
        return db.search(query, limit=limit)
