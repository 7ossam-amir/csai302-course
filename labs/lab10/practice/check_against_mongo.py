r"""Optional: compare your match() with a real MongoDB on the products fixture and 1,000 generated
queries. Start the Lab 10 instances first:

    docker compose -f labs/lab10/compose.lab10.yaml up -d
    .\.venv\Scripts\python.exe labs\lab10\practice\check_against_mongo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # labs/lab10, for the fixture and generator

from mongo_demo import client, random_queries  # noqa: E402
from docdb import PRODUCTS  # noqa: E402  (only the data, not the engine)
from student import QueryError, match  # noqa: E402


def in_scope(query) -> bool:
    """The assignment lets you assume comparison arguments are numbers or strings."""
    if isinstance(query, dict):
        for key, value in query.items():
            if key in ("$gt", "$gte", "$lt", "$lte") and (isinstance(value, bool) or
                                                          not isinstance(value, (int, float, str))):
                return False
            if key in ("$regex", "$options") or not in_scope(value):
                return False
    elif isinstance(query, list):
        return all(in_scope(v) for v in query)
    return True


def main() -> None:
    collection = client("shard-a")["lab10_practice"]["products"]
    collection.drop()
    collection.insert_many([dict(p) for p in PRODUCTS])
    queries = [q for q in random_queries(1000) if in_scope(q)]
    agree = shown = 0
    for query in queries:
        try:
            mine = sorted(p["_id"] for p in PRODUCTS if match(p, query))
        except (QueryError, NotImplementedError) as problem:
            mine = f"error: {problem!r}"
        theirs = sorted(d["_id"] for d in collection.find(query))
        if mine == theirs:
            agree += 1
        elif shown < 10:  # show the first few differences only
            shown += 1
            print(f"DIFFERENT {query}\n   yours   {mine}\n   MongoDB {theirs}")
    note = " (only the first 10 differences are shown)" if agree < len(queries) - 10 else ""
    print(f"{agree} of {len(queries)} queries agree with MongoDB{note}")


if __name__ == "__main__":
    main()
