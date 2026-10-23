"""Wait-for graph cycle detection and an optional PostgreSQL deadlock example."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Mapping


def has_cycle(wait_for: Mapping[int, set[int]]) -> bool:
    """Return True when a directed wait-for graph contains a cycle."""
    state: dict[int, int] = {}
    nodes = set(wait_for)
    for blockers in wait_for.values():
        nodes.update(blockers)

    def visit(node: int) -> bool:
        state[node] = 1  # On the current DFS path.
        for blocker in wait_for.get(node, set()):
            if state.get(blocker) == 1:
                return True
            if state.get(blocker, 0) == 0 and visit(blocker):
                return True
        state[node] = 2  # Fully explored.
        return False

    for node in sorted(nodes):
        if state.get(node, 0) == 0 and visit(node):
            return True
    return False


def _show_offline_examples() -> None:
    examples = {
        "acyclic": {1: {2}, 2: {3}, 3: set()},
        "two-transaction cycle": {1: {2}, 2: {1}},
        "three-transaction cycle": {1: {2}, 2: {3}, 3: {1}},
        "disconnected with a blocker-only node": {1: {8}, 4: {5}, 5: set()},
        "self-cycle": {7: {7}},
    }
    for label, graph in examples.items():
        print(f"{label}: cycle={has_cycle(graph)}  graph={graph}")


def _postgres_deadlock() -> int:
    """Use two separate sessions to create a bounded real PostgreSQL deadlock."""
    from transaction_demo import _connect

    barrier = Barrier(2)

    def lock_in_order(first_id: int, second_id: int) -> str:
        connection = _connect(autocommit=True)
        try:
            connection.execute("SET statement_timeout = '5000ms'")
            connection.execute("BEGIN")
            connection.execute(
                "SELECT id FROM lab07.accounts WHERE id = %s FOR UPDATE",
                (first_id,),
            )
            barrier.wait(timeout=3)
            connection.execute(
                "SELECT id FROM lab07.accounts WHERE id = %s FOR UPDATE",
                (second_id,),
            )
            connection.execute("COMMIT")
            return f"locks {first_id} then {second_id}: committed"
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            if sqlstate == "40P01":
                return f"locks {first_id} then {second_id}: PostgreSQL aborted this deadlock victim (40P01)"
            if sqlstate == "57014":
                return f"locks {first_id} then {second_id}: statement timeout (57014); inspect the run"
            return f"locks {first_id} then {second_id}: failed ({sqlstate or type(exc).__name__}: {exc})"
        finally:
            connection.close()

    print("Starting two sessions; each locks one account before requesting the other.")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(lock_in_order, 1, 2), pool.submit(lock_in_order, 2, 1)]
        outcomes = [future.result(timeout=8) for future in futures]
    for outcome in outcomes:
        print(outcome)
    print("The victim is chosen by PostgreSQL; this demo does not predict which session loses.")
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, balance FROM lab07.accounts WHERE id IN (1, 2) ORDER BY id"
        ).fetchall()
    print(f"Account state after the lock-only demo: {rows}")
    victims = sum("40P01" in outcome for outcome in outcomes)
    committed = sum(outcome.endswith(": committed") for outcome in outcomes)
    return 0 if victims == 1 and committed == 1 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="run the real two-session PostgreSQL example")
    args = parser.parse_args()
    if not args.postgres:
        _show_offline_examples()
        return 0
    try:
        return _postgres_deadlock()
    except Exception as exc:
        print("Could not complete the PostgreSQL deadlock example.")
        print("Start the shared course PostgreSQL service and load the Lab 7 schema and seed first.")
        print(f"Detail: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
