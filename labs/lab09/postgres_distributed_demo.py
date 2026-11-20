"""PostgreSQL side of Lab 9: declarative partitioning, two-phase commit, and exact vector search.

Modes (run from the repository root with the course .venv):

    partitioning  rows per partition and EXPLAIN plans that show partition pruning
    twophase      PREPARE TRANSACTION on two "shards", an in-doubt transaction, COMMIT PREPARED
    vectors       load the RAG chunks as float8[] embeddings and run exact k-NN in SQL
    cleanup       roll back any prepared transaction this lab left behind
    all           partitioning, twophase, vectors
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")

CONNECTION = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "csai302"),
    "user": os.getenv("POSTGRES_USER", "csai302"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}


def _connect(*, autocommit: bool = True):
    if psycopg is None:
        raise RuntimeError("Psycopg 3 is missing; install the course requirements in the existing .venv")
    return psycopg.connect(**CONNECTION, autocommit=autocommit, connect_timeout=5)


def _require_fixture(connection) -> None:
    if not connection.execute("SELECT to_regclass('lab09.orders') IS NOT NULL").fetchone()[0]:
        raise RuntimeError("Lab 9 schema is missing; run db/schema.sql and db/seed.sql first")


def _plan(connection, sql: str, params=()) -> list[str]:
    rows = connection.execute("EXPLAIN (COSTS OFF) " + sql, params).fetchall()
    return [row[0] for row in rows]


def partitioning() -> None:
    print("== Declarative partitioning")
    with _connect() as connection:
        _require_fixture(connection)
        for table in ("orders", "customers", "stores"):
            rows = connection.execute(
                f"SELECT tableoid::regclass::text, count(*) FROM lab09.{table} GROUP BY 1 ORDER BY 1").fetchall()
            print(f"  {table:<10} " + ", ".join(f"{name.split('.')[-1]}={count:,}" for name, count in rows))
        cases = [
            ("range key, one month", "SELECT sum(amount) FROM lab09.orders "
             "WHERE order_date BETWEEN '2026-05-01' AND '2026-05-31'"),
            ("range table, no key", "SELECT sum(amount) FROM lab09.orders WHERE customer_id = 42"),
            ("hash key equality", "SELECT * FROM lab09.customers WHERE id = 42"),
            ("hash key range", "SELECT count(*) FROM lab09.customers WHERE id BETWEEN 100 AND 200"),
            ("list key", "SELECT * FROM lab09.stores WHERE region = 'Alexandria'"),
        ]
        for label, sql in cases:
            plan = _plan(connection, sql)
            scanned = sorted({m for line in plan for m in re.findall(r" on (\w+)", line)})
            print(f"\n  {label}: partitions scanned {scanned}")
            for line in plan:
                print(f"    {line}")
    print("\n  The planner prunes partitions it can rule out from the WHERE clause. A hash-partitioned")
    print("  table can prune an equality on its key, but a range on that key must visit every partition.")


def _max_prepared(connection) -> int:
    return int(connection.execute("SHOW max_prepared_transactions").fetchone()[0])


def twophase() -> None:
    print("\n== Two-phase commit with PREPARE TRANSACTION")
    with _connect() as admin:
        _require_fixture(admin)
        if _max_prepared(admin) == 0:
            print("  max_prepared_transactions = 0, so PREPARE TRANSACTION is disabled (PostgreSQL's default).")
            print("  An instructor can enable it once for the course database (restart required):")
            print("    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 "
                  "-c \"ALTER SYSTEM SET max_prepared_transactions = 10\"")
            print("    docker compose --env-file .env -f infra/compose.yaml restart postgres")
            try:
                with _connect(autocommit=False) as probe:
                    probe.execute("UPDATE lab09.shard1_accounts SET balance = balance WHERE owner = 'alice'")
                    probe.execute("PREPARE TRANSACTION 'lab09-probe'")
            except psycopg.Error as failure:
                print(f"  What PREPARE TRANSACTION says now: {failure.diag.message_primary}")
            return
        admin.execute("UPDATE lab09.shard1_accounts SET balance = 100 WHERE owner = 'alice'")
        admin.execute("UPDATE lab09.shard2_accounts SET balance = 50 WHERE owner = 'carol'")

    # Phase 1: each "shard" session does its part and PREPAREs. The coordinator is this script.
    shard1 = _connect(autocommit=False)
    shard2 = _connect(autocommit=False)
    try:
        shard1.execute("UPDATE lab09.shard1_accounts SET balance = balance - 30 WHERE owner = 'alice'")
        shard2.execute("UPDATE lab09.shard2_accounts SET balance = balance + 30 WHERE owner = 'carol'")
        shard1.execute("PREPARE TRANSACTION 'lab09-t1-shard1'")
        shard2.execute("PREPARE TRANSACTION 'lab09-t1-shard2'")
        print("  both shards voted YES (PREPARE TRANSACTION succeeded)")
    finally:
        shard1.close()
        shard2.close()  # the sessions are gone, but the prepared transactions are durable

    with _connect() as coordinator:
        rows = coordinator.execute(
            "SELECT gid, prepared::time(0)::text, owner FROM pg_prepared_xacts WHERE gid LIKE 'lab09-%' ORDER BY gid"
        ).fetchall()
        print(f"  after both sessions disconnected, pg_prepared_xacts still lists: {rows}")
        coordinator.execute("SET lock_timeout = '300ms'")
        try:
            coordinator.execute("UPDATE lab09.shard1_accounts SET balance = balance - 1 WHERE owner = 'alice'")
        except psycopg.errors.LockNotAvailable:
            print("  another transaction touching alice waits and times out: the in-doubt transaction holds the lock")
        coordinator.execute("RESET lock_timeout")
        balances = coordinator.execute(
            "SELECT (SELECT balance FROM lab09.shard1_accounts WHERE owner = 'alice'), "
            "(SELECT balance FROM lab09.shard2_accounts WHERE owner = 'carol')").fetchone()
        print(f"  committed balances while in doubt: alice={balances[0]}, carol={balances[1]} (not changed yet)")
        # Phase 2: the coordinator's decision is COMMIT; it may come from a different session.
        coordinator.execute("COMMIT PREPARED 'lab09-t1-shard1'")
        coordinator.execute("COMMIT PREPARED 'lab09-t1-shard2'")
        balances = coordinator.execute(
            "SELECT (SELECT balance FROM lab09.shard1_accounts WHERE owner = 'alice'), "
            "(SELECT balance FROM lab09.shard2_accounts WHERE owner = 'carol')").fetchone()
        print(f"  after COMMIT PREPARED on both: alice={balances[0]}, carol={balances[1]}")


def vectors(k: int = 5) -> None:
    from rag import RAG, load_course_chunks  # local import: only this mode needs NumPy and the corpus

    print("\n== Exact k-NN in SQL")
    chunks = load_course_chunks(REPO_ROOT)
    rag = RAG(chunks, index="exact")
    question = "Why must the log be flushed before a dirty page is written?"
    q = rag.embedder.embed(question)
    with _connect() as connection:
        _require_fixture(connection)
        connection.execute("TRUNCATE lab09.doc_chunks")
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO lab09.doc_chunks (id, source, heading, body, embedding) VALUES (%s, %s, %s, %s, %s)",
                [(c.id, c.source, c.heading, c.text, rag.vectors[c.id].astype(float).tolist()) for c in chunks])
        sql = ("SELECT id, source, heading, round(lab09.cosine(embedding, %s)::numeric, 3) AS score "
               "FROM lab09.doc_chunks ORDER BY lab09.cosine(embedding, %s) DESC LIMIT %s")
        params = (q.astype(float).tolist(), q.astype(float).tolist(), k)
        rows = connection.execute(sql, params).fetchall()
        plan = _plan(connection, sql, params)
    python_ids = [c.id for c, _ in rag.retrieve(question, k)]
    print(f"  loaded {len(chunks)} chunks with {rag.embedder.dim}-d embeddings")
    print(f"  question: {question}")
    for chunk_id, source, heading, score in rows:
        print(f"    {score}  {source} / {heading}")
    print(f"  same top-{k} as Python's exact search: {[r[0] for r in rows] == python_ids}")
    nodes = [re.sub(r"^->\s*", "", line.strip()) for line in plan if not line.strip().startswith("Sort Key")]
    print("  plan: " + " -> ".join(nodes))
    print("  Without a vector index PostgreSQL computes the cosine for every row and sorts. The pgvector")
    print("  extension (not in the course image) adds a vector type and 'CREATE INDEX ... USING hnsw'.")


def cleanup() -> None:
    with _connect() as connection:
        if _max_prepared(connection) == 0:
            print("No prepared transactions are possible (max_prepared_transactions = 0)")
            return
        gids = [row[0] for row in connection.execute(
            "SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'lab09-%' AND database = current_database()")]
        for gid in gids:
            connection.execute(f"ROLLBACK PREPARED '{gid}'")
        print(f"Rolled back {gids or 'nothing'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", default="all", choices=["partitioning", "twophase", "vectors", "cleanup", "all"])
    args = parser.parse_args()
    try:
        if args.mode in ("partitioning", "all"):
            partitioning()
        if args.mode in ("twophase", "all"):
            twophase()
        if args.mode in ("vectors", "all"):
            vectors()
        if args.mode == "cleanup":
            cleanup()
    except (RuntimeError, OSError) as problem:
        raise SystemExit(f"PostgreSQL demo stopped: {problem}") from None
    except Exception as problem:
        if psycopg is not None and isinstance(problem, psycopg.Error):
            raise SystemExit(f"PostgreSQL demo stopped: {problem}") from None
        raise


if __name__ == "__main__":
    main()
