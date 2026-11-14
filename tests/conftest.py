import hashlib
import os
import tempfile

import pytest

# Must happen before any repomind module is imported
os.environ["REPOMIND_DATA_DIR"] = tempfile.mkdtemp(prefix="repomind-test-")


@pytest.fixture
def fake_embed(monkeypatch):
    """Replace Ollama with a deterministic bag-of-words embedder so tests run offline."""
    from repomind import store
    from repomind.bm25 import tokenize

    def embed(model, input):
        out = []
        for text in input:
            vec = [0.0] * 64
            for tok in tokenize(text):
                vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 64] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return {"embeddings": out}

    monkeypatch.setattr(store.ollama, "embed", embed)
