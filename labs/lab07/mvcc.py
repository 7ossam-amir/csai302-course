"""A small, visibility-focused MVCC model for the Lab 7 code trace."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Version:
    """One committed value. Initial values use commit sequence zero."""

    value: int
    commit_seq: int
    writer_tx: int | None = None


@dataclass
class Transaction:
    """State captured by one transaction in the teaching model."""

    tx_id: int
    snapshot_seq: int
    state: str = "active"
    pending_writes: dict[str, int] = field(default_factory=dict)


class MiniMVCC:
    """An in-memory snapshot reader with staged writes and no conflict checks.

    This model demonstrates version visibility. Two transactions can write the
    same key from old snapshots and both commit; the later commit wins.
    """

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        if initial is None:
            initial = {"A": 100, "B": 50}
        self.versions: dict[str, list[Version]] = {}
        for key, value in initial.items():
            self._validate_key(key)
            self._validate_value(value)
            self.versions[key] = [Version(value=value, commit_seq=0)]

        self.transactions: dict[int, Transaction] = {}
        self.commit_seq = 0
        self._next_tx_id = 1

    @staticmethod
    def _validate_key(key: object) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("keys must be non-empty strings")

    @staticmethod
    def _validate_value(value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("values must be integers")

    def _active_transaction(self, tx_id: int) -> Transaction:
        transaction = self.transactions.get(tx_id)
        if transaction is None or transaction.state != "active":
            raise RuntimeError(f"transaction {tx_id} is unknown or not active")
        return transaction

    def begin(self) -> int:
        """Start a transaction whose snapshot is the current commit sequence."""
        tx_id = self._next_tx_id
        self._next_tx_id += 1
        self.transactions[tx_id] = Transaction(tx_id, self.commit_seq)
        return tx_id

    def read(self, tx_id: int, key: str) -> int | None:
        """Read a private write first, then the newest version in the snapshot."""
        self._validate_key(key)
        transaction = self._active_transaction(tx_id)
        if key in transaction.pending_writes:
            return transaction.pending_writes[key]

        visible = [
            version
            for version in self.versions.get(key, [])
            if version.commit_seq <= transaction.snapshot_seq
        ]
        if not visible:
            return None
        return max(visible, key=lambda version: version.commit_seq).value

    def write(self, tx_id: int, key: str, value: int) -> None:
        """Stage a value privately; it becomes visible to others only at commit."""
        self._validate_key(key)
        self._validate_value(value)
        transaction = self._active_transaction(tx_id)
        transaction.pending_writes[key] = value

    def commit(self, tx_id: int) -> int:
        """Publish staged values at one sequence, or finish a read-only transaction."""
        transaction = self._active_transaction(tx_id)
        if transaction.pending_writes:
            next_seq = self.commit_seq + 1
            for key, value in sorted(transaction.pending_writes.items()):
                self.versions.setdefault(key, []).append(
                    Version(value=value, commit_seq=next_seq, writer_tx=tx_id)
                )
            self.commit_seq = next_seq
        transaction.pending_writes.clear()
        transaction.state = "committed"
        return self.commit_seq

    def rollback(self, tx_id: int) -> None:
        """Discard staged values and close the transaction."""
        transaction = self._active_transaction(tx_id)
        transaction.pending_writes.clear()
        transaction.state = "aborted"


def main() -> None:
    """Print a repeatable interleaving used in the lab guide."""
    store = MiniMVCC()
    first = store.begin()
    second = store.begin()
    print(f"T{first} and T{second} begin at sequence {store.commit_seq}.")
    print(f"T{first} reads A = {store.read(first, 'A')}")
    store.write(first, "A", 80)
    print(f"T{first} stages A = 80 and reads its own write: {store.read(first, 'A')}")
    print(f"T{second} reads A before T{first} commits: {store.read(second, 'A')}")
    print(f"T{first} commits at sequence {store.commit(first)}")
    print(f"T{second} still reads its snapshot value: {store.read(second, 'A')}")
    third = store.begin()
    print(f"T{third} begins at sequence {store.transactions[third].snapshot_seq}")
    print(f"T{third} reads A = {store.read(third, 'A')}")
    print(f"Read-only T{second} commits at sequence {store.commit(second)}")
    print(f"T{third} commits at sequence {store.commit(third)}")


if __name__ == "__main__":
    main()
