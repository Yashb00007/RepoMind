from repomind.chunker import chunk_file

PY = '''import os

def alpha():
    return 1

@decorator
def beta(x):
    y = x + 1
    return y

class Gamma:
    def one(self):
        return 1

    def two(self):
        return 2
'''


def symbols(chunks):
    return {s.strip() for c in chunks for s in c.symbols.split(",") if s.strip()}


def test_python_is_split_at_definitions():
    chunks = chunk_file("m.py", PY, size=6, overlap=0)
    assert {"alpha", "beta", "Gamma"} <= symbols(chunks)
    beta = next(c for c in chunks if "beta" in c.symbols)
    assert "@decorator" in beta.text  # decorators stay with their function


def test_big_class_is_split_per_method():
    chunks = chunk_file("m.py", PY, size=4, overlap=0)
    assert {"Gamma.one", "Gamma.two"} <= symbols(chunks)
    assert all(c.end_line - c.start_line + 1 <= 4 for c in chunks)


def test_every_nonblank_line_is_covered():
    chunks = chunk_file("m.py", PY, size=4, overlap=0)
    covered = set()
    for c in chunks:
        covered.update(range(c.start_line, c.end_line + 1))
    nonblank = {i for i, line in enumerate(PY.splitlines(), 1) if line.strip()}
    assert nonblank <= covered


def test_javascript_definitions_and_doc_comments():
    js = (
        'import x from "y";\n\n/** doc */\nexport function a() {\n  return 1;\n}\n\n'
        "export const b = async (req, res) => {\n  return 2;\n};\n\nclass C {\n  m() {}\n}\n"
    )
    chunks = chunk_file("a.js", js, size=6, overlap=0)
    assert {"a", "b", "C"} <= symbols(chunks)
    a = next(c for c in chunks if c.symbols == "a")
    assert "/** doc */" in a.text


def test_markdown_split_at_headings():
    md = "# Title\nintro\n\n## Setup\nrun it\n\n## Usage\nuse it\n"
    chunks = chunk_file("README.md", md, size=4, overlap=0)
    assert {"Setup", "Usage"} <= symbols(chunks)


def test_plain_files_use_overlapping_windows():
    text = "\n".join(f"line {i}" for i in range(25))
    chunks = chunk_file("data.txt", text, size=10, overlap=2)
    assert len(chunks) == 3
    assert chunks[0].end_line >= chunks[1].start_line  # overlap


def test_invalid_python_does_not_crash():
    assert chunk_file("bad.py", "def (:\n  pass\n")


def test_empty_file_gives_no_chunks():
    assert chunk_file("empty.py", "") == []
