import argparse
import json
import sys

from repomind.store import search


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("questions")
    parser.add_argument("--k", type=int, default=6)
    args = parser.parse_args()

    with open(args.questions, encoding="utf-8") as f:
        items = json.load(f)

    hits_at_k, reciprocal = 0, 0.0
    for item in items:
        try:
            results = search(args.repo, item["question"], k=args.k)
        except RuntimeError as e:
            sys.exit(f"error: {e}")
        expected = set(item["expected"])
        rank = next((i for i, h in enumerate(results, 1) if h["path"] in expected), None)
        hits_at_k += rank is not None
        reciprocal += 1 / rank if rank else 0
        print(f"[{'hit ' if rank else 'MISS'}] rank={rank or '-'}  {item['question']}")

    n = len(items)
    print(f"\nhit@{args.k}: {hits_at_k}/{n} = {hits_at_k / n:.0%}   MRR: {reciprocal / n:.2f}")


if __name__ == "__main__":
    main()
