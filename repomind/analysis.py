import ast
import json
import posixpath
import re
from collections import Counter

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

OVERVIEW_LABELS = (
    "PROJECT_STRUCTURE",
    "PROJECT_DEPENDENCIES",
    "PROJECT_API_ROUTES",
    "PROJECT_IMPORT_GRAPH",
)
MAX_LINES = 400
JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
ENTRY_NAMES = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.py", "cli.py",
    "index.js", "server.js", "app.js", "main.js", "index.ts", "main.ts", "server.ts",
    "app.ts", "main.go", "main.rs", "Main.java", "Application.java", "Program.cs",
}


# ---- file tree -------------------------------------------------------------

def file_tree(name, paths):
    entries = sorted(
        (p for p in paths if posixpath.basename(p) in ENTRY_NAMES),
        key=lambda p: (p.count("/"), p),
    )[:15]
    lines = [f"Repository file tree for {name}:"]
    if entries:
        lines.append("Likely entry points: " + ", ".join(entries))
    lines += sorted(paths)[:2000]
    if len(paths) > 2000:
        lines.append(f"... and {len(paths) - 2000} more files")
    return "\n".join(lines)


# ---- dependencies ----------------------------------------------------------

def _npm(text):
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    lines = []
    if data.get("name"):
        lines.append(f"  name: {data['name']}")
    for key, label in (("dependencies", "runtime"), ("devDependencies", "dev"), ("peerDependencies", "peer")):
        deps = data.get(key)
        if isinstance(deps, dict) and deps:
            lines.append(f"  {label}: " + ", ".join(f"{k} {v}" for k, v in deps.items()))
    if isinstance(data.get("scripts"), dict) and data["scripts"]:
        lines.append("  scripts: " + ", ".join(data["scripts"]))
    return "\n".join(lines)


def _requirements(text):
    pkgs = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            pkgs.append(line)
    return ("  packages: " + ", ".join(pkgs[:80])) if pkgs else ""


def _pyproject(text):
    if tomllib is None:
        return ""
    try:
        data = tomllib.loads(text)
    except ValueError:
        return ""
    deps = list(data.get("project", {}).get("dependencies", []))
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    deps += [k for k in poetry if k.lower() != "python"]
    return ("  packages: " + ", ".join(deps[:80])) if deps else ""


def _gomod(text):
    mods = re.findall(r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+v[\w.\-+]+", text, re.M)
    return ("  modules: " + ", ".join(dict.fromkeys(mods))) if mods else ""


def _cargo(text):
    if tomllib is None:
        return ""
    try:
        data = tomllib.loads(text)
    except ValueError:
        return ""
    lines = []
    for key, label in (("dependencies", "runtime"), ("dev-dependencies", "dev")):
        deps = data.get(key)
        if isinstance(deps, dict) and deps:
            lines.append(f"  {label}: " + ", ".join(deps))
    return "\n".join(lines)


def _pom(text):
    ids = re.findall(r"<dependency>.*?<artifactId>([^<]+)</artifactId>", text, re.S)
    return ("  artifacts: " + ", ".join(dict.fromkeys(ids))) if ids else ""


def dependency_summary(files):
    sections = []
    for path in sorted(files):
        base = posixpath.basename(path)
        if base == "package.json":
            info = _npm(files[path])
        elif base.startswith("requirements") and base.endswith(".txt"):
            info = _requirements(files[path])
        elif base == "pyproject.toml":
            info = _pyproject(files[path])
        elif base == "go.mod":
            info = _gomod(files[path])
        elif base == "Cargo.toml":
            info = _cargo(files[path])
        elif base == "pom.xml":
            info = _pom(files[path])
        else:
            continue
        if info:
            sections.append(f"[{path}]\n{info}")
    if not sections:
        return ""
    return "Dependencies declared by the project:\n\n" + "\n\n".join(sections)


# ---- API routes ------------------------------------------------------------

_FLASK_ROUTE = re.compile(r"""@\w+(?:\.\w+)*\.route\(\s*['"]([^'"]+)['"](?P<rest>[^)]*)\)""")
_DECORATOR_METHOD = re.compile(r"""@\w+(?:\.\w+)*\.(get|post|put|delete|patch)\(\s*['"]([^'"]*)['"]""")
_DJANGO = re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]""")
_EXPRESS = re.compile(
    r"""\b(?:app|router|server|api|routes?|\w*Router)\.(get|post|put|delete|patch|all|use)\(\s*['"`]([^'"`]+)['"`]"""
)
_SPRING = re.compile(r'''@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*"([^"]*)"''')
_GO_HANDLE = re.compile(r'''\.(?:HandleFunc|Handle)\(\s*"([^"]+)"''')
_GO_VERB = re.compile(r'''\b\w+\.(GET|POST|PUT|DELETE|PATCH)\(\s*"([^"]+)"''')


def _line_routes(path, ext, line):
    out = []
    if ext == ".py":
        m = _FLASK_ROUTE.search(line)
        if m:
            methods = re.findall(r"['\"](GET|POST|PUT|DELETE|PATCH)['\"]", m.group("rest"), re.I) or ["GET"]
            out += [(x.upper(), m.group(1)) for x in methods]
        m = _DECORATOR_METHOD.search(line)
        if m:
            out.append((m.group(1).upper(), m.group(2)))
        if posixpath.basename(path) == "urls.py":
            m = _DJANGO.search(line)
            if m:
                out.append(("ANY", "/" + m.group(1).lstrip("/")))
    elif ext in JS_EXTS:
        m = _EXPRESS.search(line)
        if m:
            out.append(("MOUNT" if m.group(1) == "use" else m.group(1).upper(), m.group(2)))
    elif ext in (".java", ".kt"):
        m = _SPRING.search(line)
        if m:
            verb = "ANY" if m.group(1) == "Request" else m.group(1).upper()
            out.append((verb, m.group(2) or "/"))
    elif ext == ".go":
        m = _GO_VERB.search(line)
        if m:
            out.append((m.group(1), m.group(2)))
        else:
            m = _GO_HANDLE.search(line)
            if m:
                out.append(("ANY", m.group(1)))
    return out


def _next_routes(path, text):
    """Next.js derives routes from file locations."""
    m = re.search(r"(?:^|/)pages/api/(.+)\.(?:js|jsx|ts|tsx)$", path)
    if m:
        route = "/api/" + re.sub(r"(?:^|/)index$", "", m.group(1))
        return [("ANY", route.rstrip("/") or "/api", path, 1)]
    m = re.search(r"(?:^|/)app/(.*?)/?route\.(?:js|ts)$", path)
    if m:
        seg = re.sub(r"\([^/]*\)/?", "", m.group(1)).strip("/")  # drop (route-groups)
        methods = re.findall(
            r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|DELETE|PATCH)\b", text
        ) or ["ANY"]
        return [(x, "/" + seg, path, 1) for x in methods]
    return []


def find_routes(files):
    found = []
    for path in sorted(files):
        text = files[path]
        ext = posixpath.splitext(path)[1].lower()
        if ext in JS_EXTS:
            found += _next_routes(path, text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 300:  # minified code
                continue
            for method, route in _line_routes(path, ext, line):
                found.append((method, route, path, lineno))
    return found


def routes_summary(files):
    routes = find_routes(files)
    if not routes:
        return ""
    lines = [f"{m:<6} {r}  ->  {p}:{n}" for m, r, p, n in routes[:MAX_LINES]]
    if len(routes) > MAX_LINES:
        lines.append(f"... and {len(routes) - MAX_LINES} more")
    return "API routes / endpoints detected (method, path, where it is defined):\n" + "\n".join(lines)


# ---- import graph ----------------------------------------------------------

_JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\(\s*|\bimport\s+)['"]([^'"]+)['"]""")


def _py_module_map(paths):
    modmap = {}
    for p in paths:
        if not p.endswith(".py"):
            continue
        mod = p[:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        modmap[mod] = p
        if mod.startswith("src."):
            modmap.setdefault(mod[4:], p)
    return modmap


def _py_imports(path, text, modmap):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    pkg = path.split("/")[:-1]
    found = set()

    def add(dotted):
        while dotted:  # `import a.b.c` may only resolve as far as `a.b`
            if dotted in modmap:
                found.add(modmap[dotted])
                return
            dotted = dotted.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(pkg):
                    continue
                base = ".".join(pkg[: len(pkg) - (node.level - 1)])
            else:
                base = ""
            target = ".".join(x for x in (base, node.module) if x)
            if target:
                add(target)
            for alias in node.names:  # `from pkg import submodule`
                add(".".join(x for x in (target, alias.name) if x))
    found.discard(path)
    return found


def _resolve_js(spec, importer, known):
    if spec.startswith("."):
        roots = [posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))]
    elif spec.startswith(("@/", "~/")):
        roots = [spec[2:], "src/" + spec[2:]]
    else:
        return None  # third-party package
    for root in roots:
        for suffix in ("", *JS_EXTS, *(f"/index{e}" for e in JS_EXTS)):
            if root + suffix in known:
                return root + suffix
    return None


def import_graph(files):
    known = set(files)
    modmap = _py_module_map(known)
    graph = {}
    for path, text in files.items():
        ext = posixpath.splitext(path)[1].lower()
        if ext == ".py":
            deps = _py_imports(path, text, modmap)
        elif ext in JS_EXTS:
            deps = {_resolve_js(s, path, known) for s in _JS_IMPORT.findall(text)}
            deps.discard(None)
            deps.discard(path)
        else:
            continue
        graph[path] = sorted(deps)
    return graph


def import_summary(files):
    edges = {p: t for p, t in import_graph(files).items() if t}
    if not edges:
        return ""
    indegree = Counter(t for targets in edges.values() for t in targets)
    core = ", ".join(f"{p} ({n})" for p, n in indegree.most_common(15))
    lines = [
        "Most imported files (number of files importing them): " + core,
        "",
        "Internal imports (file -> files it imports):",
    ]
    rows = [f"{p} -> {', '.join(t)}" for p, t in sorted(edges.items())]
    lines += rows[:MAX_LINES]
    if len(rows) > MAX_LINES:
        lines.append(f"... and {len(rows) - MAX_LINES} more files")
    return "\n".join(lines)


def build_overview_docs(name, files):
    docs = {
        "PROJECT_STRUCTURE": file_tree(name, sorted(files)),
        "PROJECT_DEPENDENCIES": dependency_summary(files),
        "PROJECT_API_ROUTES": routes_summary(files),
        "PROJECT_IMPORT_GRAPH": import_summary(files),
    }
    return {k: v for k, v in docs.items() if v.strip()}
