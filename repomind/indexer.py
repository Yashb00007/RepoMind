
import hashlib
import json
from dataclasses import dataclass

from .analysis import OVERVIEW_LABELS, build_overview_docs
from .chunker import chunk_file
from .config import EMBED_MODEL, MANIFEST_DIR
from .loader import iter_source_files, read_text, resolve_source
from .store import (
    add_chunks,
    collection_exists,
    collection_name,
    delete_paths,
    invalidate,
    open_collection,
    reset_collection,
)

# Bump when chunking or analysis changes, so old indexes get rebuilt
INDEX_VERSION = 2


@dataclass
class IndexResult:
    name: str
    files: int
    chunks_added: int
    files_changed: int
    files_removed: int
    incremental: bool
    up_to_date: bool = False


def _manifest_file(name):
    return MANIFEST_DIR / f"{collection_name(name)}.json"


def _load_manifest(name):
    try:
        return json.loads(_manifest_file(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_manifest(name, hashes):
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    data = {"version": INDEX_VERSION, "embed_model": EMBED_MODEL, "files": hashes}
    _manifest_file(name).write_text(json.dumps(data), encoding="utf-8")


def _hash(text):
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def index_repo(source: str, progress=print, full: bool = False) -> IndexResult:
    """Index a GitHub URL or local folder."""
    progress(f"Fetching {source} ...")
    root, name = resolve_source(source)

    progress("Reading files ...")
    files = {}
    for path in iter_source_files(root):
        text = read_text(path)
        if text is not None:
            files[path.relative_to(root).as_posix()] = text
    if not files:
        raise ValueError("No readable source files found in that repository.")
    hashes = {p: _hash(t) for p, t in files.items()}

    manifest = _load_manifest(name)
    incremental = bool(
        not full
        and manifest
        and manifest.get("version") == INDEX_VERSION
        and manifest.get("embed_model") == EMBED_MODEL
        and collection_exists(name)
    )

    if incremental:
        old = manifest["files"]
        removed = [p for p in old if p not in hashes]
        todo = [p for p in hashes if old.get(p) != hashes[p]]
        if not removed and not todo:
            progress("Already up to date.")
            return IndexResult(name, len(files), 0, 0, 0, True, up_to_date=True)
        collection = open_collection(name)
        delete_paths(collection, removed + todo)
        progress(f"{len(todo)} new/changed files, {len(removed)} removed ...")
    else:
        # A run that dies half-way must not look finished next time
        _manifest_file(name).unlink(missing_ok=True)
        collection = reset_collection(name)
        todo, removed = list(hashes), []

    chunks = []
    for rel in todo:
        chunks.extend(chunk_file(rel, files[rel]))

    # Overview documents describe the whole repo, so they are rebuilt every time
    delete_paths(collection, list(OVERVIEW_LABELS))
    for label, text in build_overview_docs(name, files).items():
        chunks.extend(chunk_file(label, text, size=40, overlap=0))

    progress(f"Embedding {len(chunks)} chunks (this can take a few minutes) ...")
    add_chunks(collection, chunks, progress=progress)
    _save_manifest(name, hashes)
    invalidate(name)
    return IndexResult(name, len(files), len(chunks), len(todo), len(removed), incremental)
