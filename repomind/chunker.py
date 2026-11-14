
import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .config import CHUNK_LINES, CHUNK_OVERLAP

CODE_SUFFIXES = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".java", ".kt", ".go", ".rs",
    ".rb", ".php", ".cs", ".swift",
}

_DEF = re.compile(
    r"^(?:(?:export|default|pub(?:\([\w:]+\))?|public|private|protected|internal|static|"
    r"async|abstract|final|sealed|open|data|partial|unsafe|extern)\s+)*"
    r"(?:function\*?|class|interface|enum|struct|trait|impl|fn|func|def|type|object|"
    r"module|namespace|record)\s+([A-Za-z_$][\w$]*)"
)
_GO_METHOD = re.compile(r"^func\s+\([^)]*\)\s*([A-Za-z_]\w*)")
_ARROW = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?="
    r"\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?\s*=>"
)
_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*#*\s*$")
_COMMENT_STARTS = ("@", "//", "/*", "*", "#")


@dataclass
class Chunk:
    id: str
    text: str
    path: str
    start_line: int
    end_line: int
    symbols: str = ""


# A segment is (start, end, name): lines[start:end], 0-based, end exclusive.

def _fill_gaps(spans, n):
    out, pos = [], 0
    for s, e, name in sorted(spans):
        if s < pos:
            continue
        if s > pos:
            out.append((pos, s, ""))
        out.append((s, e, name))
        pos = e
    if pos < n:
        out.append((pos, n, ""))
    return out


def _node_start(node):
    return min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1


def _split_class(cls, start, end):
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not methods:
        return [(start, end, cls.name)]
    spans = [(start, _node_start(methods[0]), cls.name)]
    for m in methods:
        spans.append((_node_start(m), m.end_lineno, f"{cls.name}.{m.name}"))
    return spans


def _py_segments(tree, n, max_lines):
    spans = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start, end = _node_start(node), node.end_lineno
            if isinstance(node, ast.ClassDef) and end - start > max_lines:
                spans.extend(_split_class(node, start, end))
            else:
                spans.append((start, end, node.name))
    return _fill_gaps(spans, n)


def _spans_from_starts(starts, n):
    if not starts:
        return [(0, n, "")]
    spans = []
    if starts[0][0] > 0:
        spans.append((0, starts[0][0], ""))
    for k, (s, name) in enumerate(starts):
        e = starts[k + 1][0] if k + 1 < len(starts) else n
        spans.append((s, e, name))
    return spans


def _boundary_name(line):
    for pattern in (_DEF, _GO_METHOD, _ARROW):
        m = pattern.match(line)
        if m:
            return m.group(1)
    return None


def _regex_segments(lines):
    starts, floor = [], 0
    for i, line in enumerate(lines):
        if not line.strip() or line[0].isspace():
            continue  # only top-level definitions start a segment
        name = _boundary_name(line)
        if name:
            j = i
            # keep decorators / doc comments attached to the definition below them
            while j > floor and lines[j - 1].lstrip().startswith(_COMMENT_STARTS):
                j -= 1
            starts.append((j, name))
            floor = i + 1
    return _spans_from_starts(starts, len(lines))


def _markdown_segments(lines):
    starts, in_fence = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            m = _HEADING.match(line)
            if m:
                starts.append((i, m.group(1)))
    return _spans_from_starts(starts, len(lines))


def _segments(rel_path, text, lines, max_lines):
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix == ".py":
        try:
            return _py_segments(ast.parse(text), len(lines), max_lines)
        except (SyntaxError, ValueError):
            return _regex_segments(lines)
    if suffix in CODE_SUFFIXES:
        return _regex_segments(lines)
    if suffix == ".md":
        return _markdown_segments(lines)
    return [(0, len(lines), "")]


def _pack(rel_path, lines, segments, max_lines, overlap):
    chunks = []
    step = max(max_lines - overlap, 1)

    def emit(start, end, syms):
        body = "\n".join(lines[start:end])
        if not body.strip():
            return
        header = f"# File: {rel_path} (lines {start + 1}-{end})"
        names = list(dict.fromkeys(s for s in syms if s))[:8]
        if names:
            header += "\n# Defines: " + ", ".join(names)
        chunks.append(
            Chunk(
                id=f"{rel_path}:{start + 1}-{end}",
                text=f"{header}\n{body}",
                path=rel_path,
                start_line=start + 1,
                end_line=end,
                symbols=", ".join(names),
            )
        )

    cur_start = cur_end = None
    cur_syms = []
    for s, e, name in segments:
        if e - s > max_lines:  # too big for one chunk: cut into overlapping windows
            if cur_start is not None:
                emit(cur_start, cur_end, cur_syms)
                cur_start, cur_syms = None, []
            for ws in range(s, e, step):
                we = min(ws + max_lines, e)
                emit(ws, we, [name])
                if we == e:
                    break
        elif cur_start is None:
            cur_start, cur_end, cur_syms = s, e, [name]
        elif e - cur_start > max_lines:
            emit(cur_start, cur_end, cur_syms)
            cur_start, cur_end, cur_syms = s, e, [name]
        else:
            cur_end = e
            cur_syms.append(name)
    if cur_start is not None:
        emit(cur_start, cur_end, cur_syms)
    return chunks


def chunk_file(
    rel_path: str,
    text: str,
    size: int = CHUNK_LINES,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    # Same line numbering as Python's parser (splitlines() also splits on form feeds etc.)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return []
    return _pack(rel_path, lines, _segments(rel_path, text, lines, size), size, overlap)
