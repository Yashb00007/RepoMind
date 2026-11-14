from repomind.bm25 import BM25, tokenize


def test_tokenize_splits_identifiers_but_keeps_the_whole_name():
    tokens = set(tokenize("getUserName and get_user_id"))
    assert {"getusername", "get", "user", "name", "get_user_id", "id"} <= tokens
    assert "and" not in tokens


def test_rare_term_ranks_first():
    docs = ["def connect database pool", "render template html page", "database migration script"]
    index = BM25([tokenize(d) for d in docs])
    assert index.top(tokenize("connect"), 3)[0][0] == 0


def test_unknown_terms_return_nothing():
    index = BM25([tokenize("hello world")])
    assert index.top(tokenize("zzzz"), 3) == []
