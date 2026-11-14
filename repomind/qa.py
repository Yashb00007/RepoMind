"""STEP 4 - turn the retrieved chunks into an answer with a local LLM (Ollama).

The model never sees the whole repo, only the chunks the search found, so the
prompt tells it to stick to those.
"""
import httpx
import ollama

from .config import LLM_CONTEXT_TOKENS, LLM_MODEL, MAX_CONTEXT_CHARS
from .store import search

MAX_CHUNK_CHARS = 4500
HISTORY_MESSAGES = 6

SYSTEM_PROMPT = """You are RepoMind, an assistant that helps developers understand an \
unfamiliar codebase.

You receive snippets from the repository. Each starts with its file path and line numbers.
Snippets from PROJECT_STRUCTURE, PROJECT_DEPENDENCIES, PROJECT_API_ROUTES and \
PROJECT_IMPORT_GRAPH are auto-generated summaries of the whole repo: use them for overview \
questions and say which summary you used. They are heuristic, so treat them as hints.

Rules:
- Answer ONLY from the snippets. If they don't contain enough to answer, say what is \
missing and suggest which files or folders to look at next.
- Cite sources inline like `path/to/file.py:10-40`.
- Write for someone new to the project: clear, structured, no unnecessary jargon.
- For "how does a request flow" questions, walk through the steps in order, naming \
the file and function at each step.
- Use short code excerpts only when they make the explanation clearer."""

REWRITE_PROMPT = """Rewrite the last user question so it makes sense on its own, using the \
conversation for context. Keep file names, function names and technical terms. \
Output only the rewritten question."""


def rewrite_question(question: str, history: list[dict]) -> str:
    """Turn a follow-up like "and where is that used?" into a standalone search query."""
    if not history:
        return question
    recent = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-4:])
    try:
        resp = ollama.chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": f"Conversation:\n{recent}\n\nLast question: {question}"},
            ],
            options={"temperature": 0, "num_ctx": 2048},
        )
        text = resp["message"]["content"].strip().strip('"')
    except (ollama.ResponseError, ConnectionError, httpx.ConnectError):
        return question
    return text if 0 < len(text) < 400 else question


def retrieve(repo: str, question: str, history: list[dict] | None = None):
    """Returns (hits, the query that was actually searched)."""
    query = rewrite_question(question, history or [])
    return search(repo, query), query


def build_context(hits: list[dict], limit: int = MAX_CONTEXT_CHARS) -> str:
    parts, used = [], 0
    for h in hits:
        text = h["text"][:MAX_CHUNK_CHARS]
        if parts and used + len(text) > limit:
            break  # keep the prompt inside the model's context window
        parts.append(text)
        used += len(text)
    return "\n\n---\n\n".join(parts)


def stream_answer(question: str, hits: list[dict], history: list[dict] | None = None):
    """Yield the answer piece by piece so the UI can show it as it's written."""
    if not hits:
        yield "I couldn't find anything in the index. Did you index a repository first?"
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in (history or [])[-HISTORY_MESSAGES:]:
        messages.append({"role": m["role"], "content": m["content"][:1500]})
    messages.append(
        {
            "role": "user",
            "content": f"<context>\n{build_context(hits)}\n</context>\n\nQuestion: {question}",
        }
    )

    try:
        stream = ollama.chat(
            model=LLM_MODEL,
            messages=messages,
            options={"num_ctx": LLM_CONTEXT_TOKENS},
            stream=True,
        )
        for part in stream:
            yield part["message"]["content"]
    except ollama.ResponseError:
        yield (
            f"Ollama doesn't have the model '{LLM_MODEL}' yet.\n\n"
            f"Run this in a terminal, then ask again:\n\n    ollama pull {LLM_MODEL}"
        )
    except (ConnectionError, httpx.ConnectError):
        yield (
            "I can't reach Ollama. Install it from https://ollama.com, make sure it is "
            f"running, then run `ollama pull {LLM_MODEL}`."
        )
