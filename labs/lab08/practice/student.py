"""Starter API for Practice 8. Complete the methods without changing their signatures."""


class SimulatedCrash(Exception):
    """Raised at an injected crash point (see crash_points in STUDENT_TASK.md)."""


class RecoverableStore:
    """A multi-key page store with WAL, savepoints, ARIES recovery, truncation, and auditing."""

    def __init__(self, pages: dict[str, dict[str, int]] | None = None):
        self.crash_points: set[str] = set()
        raise NotImplementedError("Validate pages and build the disk, log, and volatile state")

    # ------------------------------------------------------------ normal operation
    def begin(self, user: str) -> int:
        raise NotImplementedError("Log BEGIN with the user and add the transaction to the ATT")

    def read(self, tx_id: int, key: str) -> int:
        raise NotImplementedError("Return the key's current value through the buffer pool")

    def write(self, tx_id: int, key: str, value: int) -> int:
        raise NotImplementedError("Log an UPDATE, then apply it to the buffered page; return its LSN")

    def savepoint(self, tx_id: int) -> int:
        raise NotImplementedError("Return a token that marks the transaction's current position")

    def rollback_to(self, tx_id: int, savepoint: int) -> int:
        raise NotImplementedError("Undo later updates with CLRs; return the number of CLRs written")

    def commit(self, tx_id: int) -> int:
        raise NotImplementedError("Force the log through COMMIT, audit, then write END")

    def abort(self, tx_id: int) -> None:
        raise NotImplementedError("Roll back the whole transaction with CLRs")

    # -------------------------------------------------------------------- storage
    def flush_log(self) -> None:
        raise NotImplementedError("Make every log record durable")

    def flush_page(self, page_id: str) -> bool:
        raise NotImplementedError("Obey the WAL rule, then write the dirty page to disk")

    def checkpoint(self) -> int:
        raise NotImplementedError("Write a fuzzy checkpoint and update the master record")

    def truncate_log(self) -> int:
        raise NotImplementedError("Discard log records recovery can no longer need")

    def crash(self) -> None:
        raise NotImplementedError("Lose all volatile state")

    def recover(self, undo_limit: int | None = None) -> dict:
        raise NotImplementedError("Run analysis, redo, and undo")

    # ---------------------------------------------------------------------- audit
    def audit_entries(self) -> list[dict]:
        raise NotImplementedError("Return copies of the audit entries")

    def verify_audit(self, entries: list[dict] | None = None) -> int | None:
        raise NotImplementedError("Return the seq of the first damaged entry, or None")

    # ----------------------------------------------------------------- inspection
    def snapshot(self) -> dict[str, int]:
        raise NotImplementedError("Current value of every key: buffered pages override disk")

    def disk_snapshot(self) -> dict[str, int]:
        raise NotImplementedError("Value of every key as stored on disk")

    def log_records(self) -> list[dict]:
        raise NotImplementedError("Return the log that is still present, oldest first")
