from repomind.indexer import index_repo
from repomind.store import list_repos, search


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def quiet(_):
    pass


def test_index_search_and_incremental_update(tmp_path, fake_embed):
    repo = tmp_path / "shop"
    write(repo, "orders.py", "def create_order(items):\n    return charge_card(items)\n")
    write(repo, "payments.py", "def charge_card(items):\n    return stripe_api_call(items)\n")
    write(repo, "utils.py", "def slugify(text):\n    return text.lower()\n")

    first = index_repo(str(repo), progress=quiet)
    assert first.name == "shop" and first.files == 3 and not first.incremental
    assert "shop" in list_repos()
    assert search("shop", "where is stripe_api_call used")[0]["path"] == "payments.py"

    # change one file, delete one, add one
    write(repo, "payments.py", "def charge_card(items):\n    return paypal_checkout(items)\n")
    (repo / "utils.py").unlink()
    write(repo, "emails.py", "def send_receipt(order):\n    return smtp_deliver(order)\n")

    second = index_repo(str(repo), progress=quiet)
    assert second.incremental and second.files_changed == 2 and second.files_removed == 1
    assert search("shop", "paypal_checkout")[0]["path"] == "payments.py"
    assert "utils.py" not in {h["path"] for h in search("shop", "slugify text lower", k=10)}

    assert index_repo(str(repo), progress=quiet).up_to_date


def test_broad_questions_get_the_overview_chunk(tmp_path, fake_embed):
    repo = tmp_path / "svc"
    write(repo, "server.js", "const app = require('express')();\napp.get('/health', (req, res) => res.send('ok'));\n")
    write(repo, "package.json", '{"dependencies": {"express": "^4"}}')
    index_repo(str(repo), progress=quiet)

    hits = search("svc", "what are the API endpoints?")
    assert hits[0]["path"] == "PROJECT_API_ROUTES"
    assert "/health" in hits[0]["text"]


def test_full_flag_rebuilds(tmp_path, fake_embed):
    repo = tmp_path / "tiny"
    write(repo, "a.py", "def a():\n    return 1\n")
    index_repo(str(repo), progress=quiet)
    again = index_repo(str(repo), progress=quiet, full=True)
    assert not again.incremental and not again.up_to_date
