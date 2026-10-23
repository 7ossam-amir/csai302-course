"""Run bounded, repeatable transaction examples against the Lab 7 schema."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
from threading import Barrier

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")

CONNECTION = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "csai302"),
    "user": os.getenv("POSTGRES_USER", "csai302"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

ROLE_PERMISSIONS = {
    "reader": frozenset({"read", "commit", "rollback"}),
    "operator": frozenset({"read", "write", "commit", "rollback"}),
    "admin": frozenset({"read", "write", "delete", "commit", "rollback"}),
}


def _connect(*, autocommit: bool = False):
    """Open one connection to the existing course database."""
    if psycopg is None:
        raise RuntimeError("Psycopg 3 is missing; install the course requirements in the existing .venv")
    return psycopg.connect(**CONNECTION, autocommit=autocommit)


def _reset_accounts() -> None:
    """Reset only the two documented Lab 7 fixture rows."""
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE lab07.accounts SET balance = 1000, version = 0 WHERE id IN (1, 2)"
        )
        if cursor.rowcount != 2:
            raise RuntimeError("Lab 7 fixture is missing; run db/schema.sql and db/seed.sql first")


def _balance(account_id: int = 1) -> tuple[int, int]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT balance, version FROM lab07.accounts WHERE id = %s", (account_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Lab 7 account {account_id} is missing; run db/seed.sql first")
    return row[0], row[1]


def _run_isolation_level(level: str) -> tuple[int, int]:
    """A reads, B commits an update, then A reads again at the chosen level."""
    _reset_accounts()
    first = _connect(autocommit=True)
    second = _connect(autocommit=True)
    try:
        first.execute(f"BEGIN ISOLATION LEVEL {level}")
        before = first.execute(
            "SELECT balance FROM lab07.accounts WHERE id = 1"
        ).fetchone()[0]
        print(f"Session A ({level}) first read: {before}")

        second.execute("BEGIN")
        second.execute(
            "UPDATE lab07.accounts SET balance = balance + 100, version = version + 1 WHERE id = 1"
        )
        second.execute("COMMIT")
        print("Session B updates account 1 by 100 and commits.")

        after = first.execute(
            "SELECT balance FROM lab07.accounts WHERE id = 1"
        ).fetchone()[0]
        first.execute("COMMIT")
        print(f"Session A second read: {after}")
        return before, after
    finally:
        for connection in (first, second):
            try:
                connection.execute("ROLLBACK")
            except psycopg.Error:
                pass
            connection.close()


def run_isolation_demo() -> None:
    print("\nREAD COMMITTED: each statement gets a fresh snapshot.")
    rc_before, rc_after = _run_isolation_level("READ COMMITTED")
    print(f"Observed: {rc_before} then {rc_after}\n")

    print("REPEATABLE READ: the first query fixes the transaction snapshot.")
    rr_before, rr_after = _run_isolation_level("REPEATABLE READ")
    print(f"Observed: {rr_before} then {rr_after}")


def _atomic_withdraw(barrier: Barrier, amount: int) -> int | None:
    """Withdraw with one conditional SQL update using this thread's connection."""
    with _connect(autocommit=True) as connection:
        connection.execute("SET statement_timeout = '5000ms'")
        connection.execute("BEGIN")
        barrier.wait(timeout=3)
        row = connection.execute(
            "UPDATE lab07.accounts "
            "SET balance = balance - %s, version = version + 1 "
            "WHERE id = 1 AND balance >= %s RETURNING balance",
            (amount, amount),
        ).fetchone()
        connection.execute("COMMIT")
        return row[0] if row else None


def run_lost_update_demo() -> None:
    """Contrast an unsafe absolute write with atomic conditional updates."""
    _reset_accounts()
    first = _connect(autocommit=True)
    second = _connect(autocommit=True)
    try:
        first.execute("BEGIN")
        second.execute("BEGIN")
        first_value = first.execute(
            "SELECT balance FROM lab07.accounts WHERE id = 1"
        ).fetchone()[0]
        second_value = second.execute(
            "SELECT balance FROM lab07.accounts WHERE id = 1"
        ).fetchone()[0]
        print(f"Both sessions read {first_value} and independently compute 900.")

        first.execute(
            "UPDATE lab07.accounts SET balance = %s, version = version + 1 WHERE id = 1",
            (first_value - 100,),
        )
        first.execute("COMMIT")
        second.execute(
            "UPDATE lab07.accounts SET balance = %s, version = version + 1 WHERE id = 1",
            (second_value - 100,),
        )
        second.execute("COMMIT")
    finally:
        for connection in (first, second):
            try:
                connection.execute("ROLLBACK")
            except psycopg.Error:
                pass
            connection.close()
    print(f"Unsafe read/compute/absolute-write result: {_balance()[0]} (one withdrawal was overwritten).")

    _reset_accounts()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_atomic_withdraw, barrier, 100) for _ in range(2)]
        outcomes = [future.result(timeout=8) for future in futures]
    print(f"Atomic conditional update results: {sorted(outcomes, key=lambda value: value or 0)}")
    print(f"Final balance after both withdrawals: {_balance()[0]}")


def run_optimistic_demo() -> None:
    """Show a version-column compare-and-swap rejecting a stale update."""
    _reset_accounts()
    first = _connect(autocommit=True)
    second = _connect(autocommit=True)
    try:
        first.execute("BEGIN")
        second.execute("BEGIN")
        first_balance, first_version = first.execute(
            "SELECT balance, version FROM lab07.accounts WHERE id = 1"
        ).fetchone()
        second_balance, second_version = second.execute(
            "SELECT balance, version FROM lab07.accounts WHERE id = 1"
        ).fetchone()
        print(f"Both sessions read balance={first_balance}, version={first_version}.")

        first_row = first.execute(
            "UPDATE lab07.accounts SET balance = %s, version = version + 1 "
            "WHERE id = 1 AND version = %s RETURNING balance, version",
            (first_balance - 100, first_version),
        ).fetchone()
        first.execute("COMMIT")
        print(f"Session A compare-and-swap: {first_row}")

        second_row = second.execute(
            "UPDATE lab07.accounts SET balance = %s, version = version + 1 "
            "WHERE id = 1 AND version = %s RETURNING balance, version",
            (second_balance - 100, second_version),
        ).fetchone()
        second.execute("ROLLBACK" if second_row is None else "COMMIT")
        print("Session B stale compare-and-swap: no rows updated; retry the whole operation.")
    finally:
        for connection in (first, second):
            try:
                connection.execute("ROLLBACK")
            except psycopg.Error:
                pass
            connection.close()
    print(f"Committed state: balance={_balance()[0]}, version={_balance()[1]}")


def run_pessimistic_demo() -> None:
    """Bound a row-lock wait, then retry after the holder releases its lock."""
    _reset_accounts()
    holder = _connect(autocommit=True)
    waiter = _connect(autocommit=True)
    try:
        holder.execute("BEGIN")
        holder.execute("SELECT id FROM lab07.accounts WHERE id = 1 FOR UPDATE")
        print("Session A holds a row lock on account 1.")

        waiter.execute("BEGIN")
        waiter.execute("SET LOCAL lock_timeout = '500ms'")
        try:
            waiter.execute("SELECT id FROM lab07.accounts WHERE id = 1 FOR UPDATE")
            raise RuntimeError("Expected the bounded lock wait to time out")
        except psycopg.Error as exc:
            if exc.sqlstate != "55P03":
                raise
            print("Session B lock wait expired with SQLSTATE 55P03; rolling back B.")
            waiter.execute("ROLLBACK")

        holder.execute("COMMIT")
        print("Session A commits and releases the row lock.")
        waiter.execute("BEGIN")
        waiter.execute("SELECT id FROM lab07.accounts WHERE id = 1 FOR UPDATE")
        waiter.execute("ROLLBACK")
        print("Session B then acquired the row lock and rolled back its read-only transaction.")
    finally:
        for connection in (holder, waiter):
            try:
                connection.execute("ROLLBACK")
            except psycopg.Error:
                pass
            connection.close()


def _require_permission(role: str, operation: str) -> None:
    permissions = ROLE_PERMISSIONS.get(role)
    if permissions is None:
        raise PermissionError(f"unknown application role: {role}")
    if operation not in permissions:
        raise PermissionError(f"role {role!r} may not {operation}")


def _update_balance_as(role: str, account_id: int, balance: int) -> None:
    """Check the trusted service role before opening a database connection."""
    _require_permission(role, "write")
    with _connect() as connection:
        connection.execute(
            "UPDATE lab07.accounts SET balance = %s, version = version + 1 WHERE id = %s",
            (balance, account_id),
        )


def run_permissions_demo() -> None:
    _reset_accounts()
    try:
        _update_balance_as("reader", 1, 900)
    except PermissionError as exc:
        print(f"Rejected before SQL: {exc}")
    _update_balance_as("operator", 1, 900)
    print(f"Trusted operator update succeeded; account 1 balance={_balance()[0]}.")
    print("These are application checks, not PostgreSQL GRANT/REVOKE roles.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("isolation", "lost-update", "optimistic", "pessimistic", "permissions", "all"),
        default="all",
    )
    args = parser.parse_args()
    if psycopg is None or load_dotenv is None:
        print("The PostgreSQL demos need Psycopg 3 and python-dotenv from the course requirements.")
        print("Activate the existing .venv and run: python -m pip install -r requirements.txt")
        return 1
    modes = {
        "isolation": run_isolation_demo,
        "lost-update": run_lost_update_demo,
        "optimistic": run_optimistic_demo,
        "pessimistic": run_pessimistic_demo,
        "permissions": run_permissions_demo,
    }
    selected = modes.values() if args.mode == "all" else (modes[args.mode],)
    try:
        for run in selected:
            run()
        return 0
    except psycopg.OperationalError as exc:
        print("Could not connect to the shared course PostgreSQL service.")
        print("Start it with docker compose --env-file .env -f infra/compose.yaml start postgres.")
        print("Check the repository .env settings, then load the Lab 7 schema and seed.")
        print(f"Connection detail: {exc}")
        return 1
    except psycopg.Error as exc:
        if isinstance(exc, psycopg.errors.UndefinedTable):
            print("Lab 7 tables are missing. Load db/schema.sql and db/seed.sql first.")
        else:
            print(f"PostgreSQL reported SQLSTATE {exc.sqlstate}: {exc}")
        return 1
    except (RuntimeError, TimeoutError) as exc:
        print(f"The demo could not finish safely: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
