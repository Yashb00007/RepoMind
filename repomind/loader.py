"""STEP 1 - get the code onto disk and decide which files are worth reading."""
import os
import re
import subprocess
from pathlib import Path
from typing import Iterator, Optional

from .config import GITHUB_TOKEN, MAX_FILE_BYTES, REPOS_DIR

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", "target", "vendor", ".idea", ".vscode", ".pytest_cache", "coverage",
}

IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "composer.lock", "Pipfile.lock",
}

TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".java", ".go", ".rs", ".rb",
    ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".kt", ".swift", ".sql", ".sh",
    ".yml", ".yaml", ".json", ".toml", ".xml", ".gradle", ".proto", ".graphql",
    ".md", ".txt", ".html", ".css", ".mod",
}

SPECIAL_NAMES = {"Dockerfile", "Makefile", "docker-compose.yml", "go.mod"}


def _git(args: list[str], secret: Optional[str] = None) -> None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("git isn't installed or isn't on your PATH.") from None
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        if secret:
            msg = msg.replace(secret, "***")  # never leak the token in errors
        raise RuntimeError(f"git {args[0]} failed: {msg}")


def repo_name_from_url(url: str) -> str:
    """https://github.com/owner/repo(.git) -> owner-repo (avoids name clashes)."""
    cleaned = url.strip().rstrip("/").removesuffix(".git")
    parts = [p for p in re.split(r"[/:]", cleaned) if p]
    return "-".join(parts[-2:]) if len(parts) >= 2 else parts[-1]


def _with_token(url: str) -> str:
    # Only ever send the token to github.com
    if GITHUB_TOKEN and url.startswith("https://github.com/"):
        return url.replace("https://", f"https://{GITHUB_TOKEN}@", 1)
    return url


def clone_repo(url: str) -> tuple[Path, str]:
    if not re.match(r"^(https?://|git@)", url):
        raise ValueError(
            "Enter a GitHub URL (https://github.com/owner/repo) or the path to a local folder."
        )
    name = repo_name_from_url(url)
    dest = REPOS_DIR / name
    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    if (dest / ".git").exists():
        try:
            _git(["-C", str(dest), "pull", "--ff-only", _with_token(url)], GITHUB_TOKEN)
        except RuntimeError:
            pass  # offline or diverged: keep using the local copy
    else:
        _git(["clone", "--depth", "1", _with_token(url), str(dest)], GITHUB_TOKEN)
        # git stores the clone URL in .git/config; replace it so the token isn't kept on disk
        _git(["-C", str(dest), "remote", "set-url", "origin", url], GITHUB_TOKEN)
    return dest, name


def resolve_source(source: str) -> tuple[Path, str]:
    """Accept a local folder or a git URL."""
    local = Path(source).expanduser()
    if local.is_dir():
        return local.resolve(), local.resolve().name
    return clone_repo(source)


def iter_source_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            if filename in IGNORE_FILES:
                continue
            path = Path(dirpath) / filename
            if path.suffix.lower() in TEXT_EXTENSIONS or filename in SPECIAL_NAMES:
                yield path


def read_text(path: Path) -> Optional[str]:
    """Read a file as text; None means skip it (too big, unreadable, binary)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if "\x00" in text:
        return None
    return text
