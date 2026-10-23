"""Show a small allowlist of read-only Lab 6 PostgreSQL plans as JSON."""

from pathlib import Path
import os
import sys

try:
    from dotenv import load_dotenv
    import psycopg
except ModuleNotFoundError as exc:
    print(f"Missing Python dependency: {exc.name}.")
    print("Activate the course .venv and install the packages from requirements.txt.")
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

CONNECTION = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "csai302"),
    "user": os.getenv("POSTGRES_USER", "csai302"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

# Keep this list static and read-only: no user-provided SQL is accepted.
READ_ONLY_QUERIES = {
    "rare status": "SELECT id, customer_id FROM lab06.orders WHERE status = 'cancelled'",
    "common status": "SELECT id, customer_id FROM lab06.orders WHERE status = 'paid'",
    "active customer": "SELECT id, status FROM lab06.orders WHERE customer_id = 1",
}


def _buffer_summary(node):
    labels = (
        ("Shared Hit Blocks", "shared hit"),
        ("Shared Read Blocks", "shared read"),
        ("Shared Dirtied Blocks", "shared dirtied"),
        ("Shared Written Blocks", "shared written"),
        ("Local Hit Blocks", "local hit"),
        ("Local Read Blocks", "local read"),
        ("Temp Read Blocks", "temp read"),
        ("Temp Written Blocks", "temp written"),
    )
    return ", ".join(f"{label}={node[key]}" for key, label in labels if key in node)


def _print_node(node, depth=0):
    indent = "  " * depth
    operation = node.get("Node Type", "Unknown")
    relation = node.get("Relation Name")
    index = node.get("Index Name")
    details = [operation]
    if relation:
        details.append(f"relation={relation}")
    if index:
        details.append(f"index={index}")

    planned = node.get("Plan Rows")
    actual_per_loop = node.get("Actual Rows")
    loops = node.get("Actual Loops")
    actual_total = None if actual_per_loop is None or loops is None else actual_per_loop * loops
    row_text = f"planned rows={planned}"
    if actual_per_loop is not None:
        row_text += f", actual rows/loop={actual_per_loop}, loops={loops}, actual total={actual_total}"
    cost_text = f"cost={node.get('Startup Cost', '?')}..{node.get('Total Cost', '?')}"
    timing_text = ""
    if "Actual Total Time" in node:
        timing_text = f", time={node.get('Actual Startup Time', '?')}..{node['Actual Total Time']} ms"
    buffers = _buffer_summary(node)
    buffer_text = f", {buffers}" if buffers else ""
    print(f"{indent}{' | '.join(details)}: {row_text}, {cost_text}{timing_text}{buffer_text}")

    for child in node.get("Plans", []):
        _print_node(child, depth + 1)


def main():
    try:
        with psycopg.connect(**CONNECTION) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT to_regclass('lab06.orders')")
                if cursor.fetchone()[0] is None:
                    print("Lab 6 tables are missing. Load db/schema.sql and db/seed.sql first.")
                    return 1

                for label, sql in READ_ONLY_QUERIES.items():
                    print(f"\n{label}: EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)")
                    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
                    document = cursor.fetchone()[0]
                    explain = document[0]
                    _print_node(explain["Plan"])
                    print(
                        f"  planning={explain.get('Planning Time', '?')} ms; "
                        f"execution={explain.get('Execution Time', '?')} ms"
                    )
        return 0
    except psycopg.OperationalError as exc:
        print("Could not connect to the shared csai302 PostgreSQL service.")
        print("Start it with the course Compose service, then check the .env settings.")
        print(f"Connection detail: {exc}")
        return 1
    except psycopg.errors.UndefinedTable:
        print("Lab 6 tables are missing. Load db/schema.sql and db/seed.sql first.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
