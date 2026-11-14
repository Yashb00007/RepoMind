from repomind.analysis import build_overview_docs, find_routes, import_graph

FILES = {
    "package.json": '{"name":"web","dependencies":{"express":"^4.0.0"},"devDependencies":{"jest":"^29"},"scripts":{"start":"node server.js"}}',
    "requirements.txt": "flask==3.0\n# comment\nrequests\n",
    "api/app.py": (
        "from flask import Flask\nfrom .models import User\nimport utils.helpers\n\n"
        '@app.route("/users", methods=["GET", "POST"])\ndef users(): pass\n\n'
        '@router.get("/items")\ndef items(): pass\n'
    ),
    "api/models.py": "class User: pass\n",
    "utils/helpers.py": "def h(): pass\n",
    "server.js": (
        "const app = require('express')();\nconst auth = require('./lib/auth');\n"
        "app.get('/health', (req, res) => {});\nrouter.post('/login', login);\n"
    ),
    "lib/auth.js": "module.exports = {};\n",
    "pages/api/hello.ts": "export default function handler() {}\n",
    "app/api/items/route.ts": "export async function GET() {}\nexport async function POST() {}\n",
}


def test_routes_from_several_frameworks():
    got = {(m, r) for m, r, *_ in find_routes(FILES)}
    assert {
        ("GET", "/users"), ("POST", "/users"), ("GET", "/items"),
        ("GET", "/health"), ("POST", "/login"),
        ("ANY", "/api/hello"), ("GET", "/api/items"), ("POST", "/api/items"),
    } <= got


def test_import_graph_resolves_python_and_js():
    graph = import_graph(FILES)
    assert {"api/models.py", "utils/helpers.py"} <= set(graph["api/app.py"])
    assert graph["server.js"] == ["lib/auth.js"]


def test_overview_documents():
    docs = build_overview_docs("web", FILES)
    assert set(docs) == {
        "PROJECT_STRUCTURE", "PROJECT_DEPENDENCIES", "PROJECT_API_ROUTES", "PROJECT_IMPORT_GRAPH",
    }
    deps = docs["PROJECT_DEPENDENCIES"]
    assert "express" in deps and "flask==3.0" in deps and "jest" in deps
    assert "server.js" in docs["PROJECT_STRUCTURE"]  # listed as an entry point
