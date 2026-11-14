import argparse
import sys

from repomind.indexer import index_repo
from repomind.qa import retrieve, stream_answer
from repomind.store import list_repos


def ask(repo: str, question: str, history: list[dict]) -> str:
    hits, query = retrieve(repo, question, history)
    if query != question:
        print(f"(searching for: {query})")
    answer = ""
    for piece in stream_answer(question, hits, history):
        answer += piece
        print(piece, end="", flush=True)
    print("\n\nSources:")
    for h in hits:
        print(f"  - {h['path']}:{h['start_line']}-{h['end_line']}  [{h['via']}]")
    return answer


def chat(repo: str) -> None:
    print(f"Chatting with '{repo}'. Type 'exit' to quit.")
    history: list[dict] = []
    while True:
        try:
            q = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"exit", "quit"}:
            break
        if q:
            print()
            answer = ask(repo, q, history)
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]


def main() -> None:
    parser = argparse.ArgumentParser(description="RepoMind - ask questions about a codebase")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index a GitHub URL or local folder")
    p_index.add_argument("source")
    p_index.add_argument("--full", action="store_true", help="rebuild instead of updating changed files")

    p_ask = sub.add_parser("ask", help="Ask one question")
    p_ask.add_argument("repo")
    p_ask.add_argument("question")

    p_chat = sub.add_parser("chat", help="Interactive chat")
    p_chat.add_argument("repo")

    sub.add_parser("list", help="List indexed repositories")

    args = parser.parse_args()
    try:
        if args.command == "index":
            r = index_repo(args.source, full=args.full)
            if r.up_to_date:
                print(f"\n'{r.name}' is already up to date.")
            else:
                print(f"\nDone: '{r.name}' -> {r.files} files, {r.chunks_added} chunks written.")
        elif args.command == "ask":
            ask(args.repo, args.question, [])
        elif args.command == "chat":
            chat(args.repo)
        elif args.command == "list":
            print("\n".join(list_repos()) or "Nothing indexed yet.")
    except (RuntimeError, ValueError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
