"""A small BM25 keyword index (no dependencies).

Vector search is good at meaning but can miss exact names like `UserController`
or `get_user_by_id`. Keyword search is the opposite, so we use both.
"""
import math
import re
from collections import Counter, defaultdict

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = {
    "the", "an", "is", "are", "how", "does", "do", "what", "where", "which", "in", "of",
    "to", "and", "for", "this", "that", "it", "me", "about", "with", "on", "from", "by",
    "be", "can", "why", "who", "there", "its", "any",
}


def tokenize(text: str) -> list[str]:
    """Identifiers are indexed whole and split into parts: getUserName -> getusername, get, user, name."""
    tokens = []
    for word in _WORD.findall(text):
        parts = [p.lower() for p in _PARTS.findall(word)]
        candidates = [word.lower()] + (parts if len(parts) > 1 else [])
        tokens.extend(t for t in candidates if len(t) > 1 and t not in STOPWORDS)
    return tokens


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_len = [len(d) for d in docs]
        self.avg_len = (sum(self.doc_len) / len(docs)) if docs else 0.0
        self.postings = defaultdict(list)  # term -> [(doc index, term count)]
        for i, doc in enumerate(docs):
            for term, count in Counter(doc).items():
                self.postings[term].append((i, count))
        n = len(docs)
        self.idf = {
            t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()
        }

    def top(self, query_tokens: list[str], k: int) -> list[tuple[int, float]]:
        scores = defaultdict(float)
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                norm = 1 - self.b + self.b * self.doc_len[i] / (self.avg_len or 1.0)
                scores[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return sorted(scores.items(), key=lambda kv: -kv[1])[:k]
