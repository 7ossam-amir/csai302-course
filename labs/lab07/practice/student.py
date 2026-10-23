"""Starter API for Practice 7. Complete the methods without changing their signatures."""


class WriteConflict(Exception):
    """A committed change is newer than this transaction's snapshot."""


class SnapshotStore:
    """Snapshot store with role checks, tombstones, and atomic conflict handling."""

    def __init__(self, initial: dict[str, int] | None = None):
        self._commit_seq = 0
        self._next_tx_id = 1
        self._versions = {}
        self._transactions = {}
        raise NotImplementedError("Initialize version history from the assignment contract")

    def begin(self, role: str) -> int:
        raise NotImplementedError("Implement trusted role validation and snapshot creation")

    def read(self, tx_id: int, key: str) -> int | None:
        raise NotImplementedError("Implement snapshot visibility and read-your-writes")

    def write(self, tx_id: int, key: str, value: int) -> None:
        raise NotImplementedError("Implement permission checks and staged writes")

    def delete(self, tx_id: int, key: str) -> None:
        raise NotImplementedError("Implement permission checks and staged tombstones")

    def commit(self, tx_id: int) -> int:
        raise NotImplementedError("Implement first-committer-wins and atomic publication")

    def rollback(self, tx_id: int) -> None:
        raise NotImplementedError("Implement rollback and transaction state checks")
