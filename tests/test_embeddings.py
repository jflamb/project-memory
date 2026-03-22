"""Tests for embedding configuration, storage, and hybrid search."""

import json
import os
import stat
import struct

import httpx
import pytest

from project_memory.db import ProjectMemoryDB
from project_memory.embeddings import (
    EmbeddingConfig,
    embed_texts,
    load_embedding_config,
    save_embedding_config,
    store_embedding,
    search_by_embedding,
    hybrid_search,
)


@pytest.fixture
def db(tmp_path):
    with ProjectMemoryDB(root=tmp_path) as db:
        yield db


# --- config ---


def test_load_config_returns_none_when_missing(tmp_path):
    config = load_embedding_config(config_dir=tmp_path)
    assert config is None


def test_save_and_load_config(tmp_path):
    cfg = EmbeddingConfig(
        api_key="sk-test-123",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
    )
    save_embedding_config(cfg, config_dir=tmp_path)
    loaded = load_embedding_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.api_key == "sk-test-123"
    assert loaded.model == "text-embedding-3-small"
    assert stat.S_IMODE(os.stat(tmp_path).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tmp_path / "config.json").st_mode) == 0o600


def test_config_env_var_override(tmp_path, monkeypatch):
    cfg = EmbeddingConfig(
        api_key="file-key",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
    )
    save_embedding_config(cfg, config_dir=tmp_path)
    monkeypatch.setenv("PROJECT_MEMORY_EMBEDDING_API_KEY", "env-key")
    monkeypatch.setenv("PROJECT_MEMORY_EMBEDDING_MODEL", "text-embedding-3-large")
    loaded = load_embedding_config(config_dir=tmp_path)
    assert loaded.api_key == "env-key"
    assert loaded.model == "text-embedding-3-large"


def test_config_from_env_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_MEMORY_EMBEDDING_API_KEY", "env-only-key")
    loaded = load_embedding_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.api_key == "env-only-key"


# --- vector storage ---


def _make_vector(dims: int = 384, val: float = 0.1) -> list[float]:
    return [val] * dims


def test_store_embedding(db):
    db.upsert_document("test.txt", "hello world")
    doc_id = db.conn.execute("SELECT id FROM documents WHERE path = 'test.txt'").fetchone()[0]
    vec = _make_vector()
    store_embedding(db, doc_id, vec)
    # Should be retrievable
    row = db.conn.execute("SELECT rowid FROM vec_documents WHERE rowid = ?", (doc_id,)).fetchone()
    assert row is not None


def test_store_embedding_overwrites(db):
    db.upsert_document("test.txt", "hello")
    doc_id = db.conn.execute("SELECT id FROM documents WHERE path = 'test.txt'").fetchone()[0]
    store_embedding(db, doc_id, _make_vector(val=0.1))
    store_embedding(db, doc_id, _make_vector(val=0.9))
    # Should still have exactly one row
    count = db.conn.execute("SELECT COUNT(*) FROM vec_documents WHERE rowid = ?", (doc_id,)).fetchone()[0]
    assert count == 1


def test_search_by_embedding(db):
    db.upsert_document("a.txt", "alpha content")
    db.upsert_document("b.txt", "beta content")
    id_a = db.conn.execute("SELECT id FROM documents WHERE path = 'a.txt'").fetchone()[0]
    id_b = db.conn.execute("SELECT id FROM documents WHERE path = 'b.txt'").fetchone()[0]

    # Store different vectors
    store_embedding(db, id_a, _make_vector(val=0.9))
    store_embedding(db, id_b, _make_vector(val=0.1))

    # Search with a vector close to a's
    results = search_by_embedding(db, _make_vector(val=0.85), limit=5)
    assert len(results) == 2
    # a.txt should rank first (closer vector)
    assert results[0]["id"] == id_a


# --- hybrid search ---


def test_hybrid_search_combines_fts_and_vector(db):
    db.upsert_document("a.txt", "python programming language")
    db.upsert_document("b.txt", "javascript web framework")
    id_a = db.conn.execute("SELECT id FROM documents WHERE path = 'a.txt'").fetchone()[0]
    id_b = db.conn.execute("SELECT id FROM documents WHERE path = 'b.txt'").fetchone()[0]

    store_embedding(db, id_a, _make_vector(val=0.8))
    store_embedding(db, id_b, _make_vector(val=0.2))

    results = hybrid_search(db, query="python", query_vector=_make_vector(val=0.85), limit=5)
    assert len(results) >= 1
    assert results[0]["path"] == "a.txt"
    assert results[0]["search_mode"] == "hybrid"


def test_hybrid_search_without_vector_falls_back_to_keyword(db):
    db.upsert_document("a.txt", "python programming")
    results = hybrid_search(db, query="python", query_vector=None, limit=5)
    assert len(results) >= 1
    assert results[0]["path"] == "a.txt"
    assert results[0]["search_mode"] == "keyword"


def test_hybrid_search_returns_search_mode(db):
    db.upsert_document("a.txt", "test content")
    id_a = db.conn.execute("SELECT id FROM documents WHERE path = 'a.txt'").fetchone()[0]
    store_embedding(db, id_a, _make_vector(val=0.5))

    results = hybrid_search(db, query="test", query_vector=_make_vector(val=0.5), limit=5)
    assert all(r["search_mode"] == "hybrid" for r in results)


# --- embedding API client ---


@pytest.mark.anyio
async def test_embed_texts_returns_empty_for_no_input():
    config = EmbeddingConfig(api_key="sk-test")
    assert await embed_texts(config, []) == []


@pytest.mark.anyio
async def test_embed_texts_success_forwards_dimensions_and_orders_results(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.2]},
                    {"index": 0, "embedding": [0.1, 0.1]},
                ]
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_mock_transport)

    config = EmbeddingConfig(api_key="sk-test", base_url="https://example.test", dimensions=2)
    vectors = await embed_texts(config, ["first", "second"])
    assert vectors == [[0.1, 0.1], [0.2, 0.2]]
    assert requests == [{"model": "text-embedding-3-small", "input": ["first", "second"], "dimensions": 2}]


@pytest.mark.anyio
async def test_embed_texts_batches_requests(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        start = len(requests) * 50 - 50
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": idx, "embedding": [start + idx]}
                    for idx, _text in enumerate(payload["input"])
                ]
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_mock_transport)

    config = EmbeddingConfig(api_key="sk-test", base_url="https://example.test")
    texts = [f"text-{i}" for i in range(51)]
    vectors = await embed_texts(config, texts)

    assert len(requests) == 2
    assert len(requests[0]["input"]) == 50
    assert len(requests[1]["input"]) == 1
    assert vectors[0] == [0]
    assert vectors[-1] == [50]


@pytest.mark.anyio
async def test_embed_texts_raises_for_http_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_mock_transport)

    config = EmbeddingConfig(api_key="sk-test", base_url="https://example.test")
    with pytest.raises(httpx.HTTPStatusError):
        await embed_texts(config, ["first"])
