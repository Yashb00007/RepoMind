"""Settings in one place."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Where cloned repos, the vector database and index manifests are stored
DATA_DIR = Path(os.getenv("REPOMIND_DATA_DIR", ".repomind"))
REPOS_DIR = DATA_DIR / "repos"
DB_DIR = DATA_DIR / "chroma"
MANIFEST_DIR = DATA_DIR / "manifests"

# Both models run locally through Ollama (free, no API key):
#   ollama pull llama3.2 && ollama pull nomic-embed-text
EMBED_MODEL = os.getenv("REPOMIND_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("REPOMIND_MODEL", "llama3.2")
# Ollama's default context window would silently cut off our snippets
LLM_CONTEXT_TOKENS = 8192

# Chunking: max lines per chunk, and overlap when a long block has to be cut
CHUNK_LINES = 70
CHUNK_OVERLAP = 10

# Chunks handed to the LLM per question, and a hard cap on prompt size
TOP_K = 6
MAX_CONTEXT_CHARS = 18000

# Skip huge files (generated code, minified bundles, data dumps)
MAX_FILE_BYTES = 200_000

# Optional: lets RepoMind clone private GitHub repos
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
