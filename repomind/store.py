"""STEP 3 - embeddings, the vector database (ChromaDB) and hybrid search.

Search combines two rankings:
  - vector search: finds chunks that *mean* something similar to the question
  - keyword search (BM25): finds chunks containing the exact names in the question
and merges them with Reciprocal Rank Fusion.
"""
import re
from functools import lru_cache

import chromadb
import httpx
import ollama

from .bm25 import BM25, tokenize
from .chunker import Chunk
from .config import DB_DIR, EMBED_MODEL, TOP_K

RRF_K = 60
_keyword_cache: dict = {}  # repo -> (chunk count, BM25 index, chunk ids)

# Broad questions also get the matching auto-generated overview chunk
_INTENTS = {
    "PROJECT_STRUCTURE": ("architecture", "structure", "overview", "folder", "organi", "layout", "entry point"),
    "PROJECT_DEPENDENCIES": ("depend", "librar", "package", "framework", "stack", "install", "tools"),
    "PROJECT_API_ROUTES": ("api", "endpoint", "route", "url", "http", "request", "rest"),
    "PROJECT_IMPORT_GRAPH": ("architecture", "overview", "module", "import", "flow", "connect"),
}


@lru_cache(maxsize=1)
def _client():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(DB_DIR))


def embed(texts: list[str], kind: str) -> list[list[float]]:
    """Turn texts into vectors. kind is 'document' (code chunks) or 'query' (a question)."""
    if "nomic" in EMBED_MODEL:
        texts = [f"search_{kind}: {t}" for t in texts]  # nomic works best with a task prefix
    try:
        return ollama.embed(model=EMBED_MODEL, input=texts)["embeddings"]
    except ollama.ResponseError as e:
        raise RuntimeError(
            f"Ollama doesn't have the embedding model '{EMBED_MODEL}'. Run: ollama pull {EMBED_MODEL}"
        ) from e
    except (ConnectionError, httpx.ConnectError) as e:
        raise RuntimeError(
            "Can't reach Ollama. Install it from https://ollama.com and make sure it is running."
        ) from e


def collection_name(repo: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", repo).strip("-_")
    return f"repo-{slug}"[:63].rstrip("-_")


def list_repos() -> list[str]:
    names = [c if isinstance(c, str) else c.name for c in _client().list_collections()]
    return sorted(n.removeprefix("repo-") for n in names if n.startswith("repo-"))


def open_collection(repo: str):
    return _client().get_collection(collection_name(repo), embedding_function=None)


def collection_exists(repo: str) -> bool:
    try:
        open_collection(repo)
        return True
    except Exception:
        return False


def invalidate(repo: str) -> None:
    _keyword_cache.pop(repo, None)


def reset_collection(repo: str):
    """Start fresh (used for a full re-index)."""
    invalidate(repo)
    try:
        _client().delete_collection(collection_name(repo))
    except Exception:
        pass  # didn't exist yet
    # embedding_function=None: we compute the vectors ourselves (see embed)
    return _client().create_collection(
        name=collection_name(repo),
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )


def delete_paths(collection, paths: list[str], batch: int = 100) -> None:
    """Remove every chunk that came from the given files."""
    for i in range(0, len(paths), batch):
        collection.delete(where={"path": {"$in": paths[i : i + batch]}})


def add_chunks(collection, chunks: list[Chunk], progress=None, batch_size: int = 32) -> None:
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embed([c.text for c in batch], "document"),
            metadatas=[
                {
                    "path": c.path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "symbols": c.symbols,
                }
                for c in batch
            ],
        )
        if progress:
            progress(f"Embedded {min(i + batch_size, len(chunks))}/{len(chunks)} chunks")


def _hit(id_, text, meta, via=""):
    return {
        "id": id_,
        "text": text,
        "path": meta["path"],
        "start_line": meta["start_line"],
        "end_line": meta["end_line"],
        "symbols": meta.get("symbols", ""),
        "via": via,
    }


def _keyword_index(repo, collection):
    count = collection.count()
    cached = _keyword_cache.get(repo)
    if cached and cached[0] == count:
        return cached[1], cached[2]
    data = collection.get(include=["documents"])
    index = BM25([tokenize(d) for d in data["documents"]])
    _keyword_cache[repo] = (count, index, data["ids"])
    return index, data["ids"]


def _with_overview(collection, question, hits, max_extra=3):
    q = question.lower()
    extra = []
    for label, words in _INTENTS.items():
        if len(extra) >= max_extra:
            break
        if not re.search(r"\b(?:" + "|".join(map(re.escape, words)) + ")", q):
            continue
        data = collection.get(where={"path": label}, include=["documents", "metadatas"])
        rows = sorted(
            zip(data["documents"], data["metadatas"], data["ids"]),
            key=lambda r: r[1]["start_line"],
        )
        if rows:
            text, meta, id_ = rows[0]
            extra.append(_hit(id_, text, meta, "overview"))
    seen = {h["id"] for h in extra}
    return extra + [h for h in hits if h["id"] not in seen]


def search(repo: str, question: str, k: int = TOP_K) -> list[dict]:
    """Return the chunks most relevant to the question (hybrid search)."""
    collection = open_collection(repo)
    total = collection.count()
    if total == 0:
        return []
    pool = min(max(k * 4, 20), total)

    res = collection.query(
        query_embeddings=embed([question], "query"),
        n_results=pool,
        include=["documents", "metadatas"],
    )
    vec_ids = res["ids"][0]
    found = {
        i: _hit(i, d, m) for i, d, m in zip(vec_ids, res["documents"][0], res["metadatas"][0])
    }

    index, all_ids = _keyword_index(repo, collection)
    kw_ids = [all_ids[i] for i, _ in index.top(tokenize(question), pool)]
    missing = [i for i in kw_ids if i not in found]
    if missing:
        extra = collection.get(ids=missing, include=["documents", "metadatas"])
        for i, d, m in zip(extra["ids"], extra["documents"], extra["metadatas"]):
            found[i] = _hit(i, d, m)

    scores: dict[str, float] = {}
    for ranking in (vec_ids, kw_ids):
        for rank, i in enumerate(ranking):
            scores[i] = scores.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)

    vec_set, kw_set = set(vec_ids), set(kw_ids)
    hits = []
    for i in sorted(scores, key=scores.get, reverse=True)[:k]:
        hit = found[i]
        hit["via"] = "+".join(n for n, s in (("vector", vec_set), ("keyword", kw_set)) if i in s)
        hits.append(hit)
    return _with_overview(collection, question, hits)
