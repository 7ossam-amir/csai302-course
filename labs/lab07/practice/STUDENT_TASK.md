# Practice 7 — Build a conflict-safe snapshot store

## Scenario

Two service clients can read and update the same records at nearly the same time.
The Lab 7 reference explains which committed versions a transaction can see, but it
does not reject stale writes. Extend that model with deletes, write-conflict checks,
and application-level role permissions. This is an in-memory teaching simulator,
not a production database.

Plan for approximately 4–7 hours. Use only the Python standard library. You may
reuse the reference's public `Version` or `Transaction` data types, but do not import
or call `MiniMVCC` methods as part of your solution.

## Files and API

Implement the following in `student.py`:

```python
class WriteConflict(Exception):
    """A committed change is newer than this transaction's snapshot."""

class SnapshotStore:
    def __init__(self, initial: dict[str, int] | None = None): ...
    def begin(self, role: str) -> int: ...
    def read(self, tx_id: int, key: str) -> int | None: ...
    def write(self, tx_id: int, key: str, value: int) -> None: ...
    def delete(self, tx_id: int, key: str) -> None: ...
    def commit(self, tx_id: int) -> int: ...
    def rollback(self, tx_id: int) -> None: ...
```

Keep these method names and signatures. Explain any small representation changes in
your `results.md`.

## Required behavior

### Snapshots and versions

- Initial values are committed at sequence 0. A missing `initial` argument uses
  `{"A": 100, "B": 50}`. Every `begin()` captures the current commit sequence and
  returns a strictly increasing transaction ID.
- A read first returns that transaction's own staged write or staged delete. If it
  has no pending change for the key, it returns the newest committed value whose
  sequence is no later than the transaction's snapshot. Other transactions' pending
  changes and later commits stay invisible. A missing key reads as `None`.
- Writing a missing key creates it at commit. Deleting a missing key is allowed and
  stages a tombstone; it remains missing. Either action counts as touching that key
  for conflict detection.
- A delete stages a tombstone. The deleting transaction reads the key as missing;
  transactions with older snapshots can still read its previous committed value.
- A successful transaction that writes or deletes one or more keys publishes all of
  them at the same next commit sequence. `commit()` returns that sequence. A
  read-only commit returns the current sequence without incrementing it.
- `rollback()` discards pending changes and publishes nothing.

### Conflicts and atomic commit

Use first-committer-wins. Before publishing, check every key the transaction has
written or deleted. If any of those keys has a committed version newer than the
transaction's snapshot, raise `WriteConflict`, mark the transaction aborted, and
discard all of its pending changes. Do not partially commit a transaction that has
one conflicting key and another non-conflicting key.

This rule must also reject two transactions creating the same previously missing
key and a write that races with a delete. It is not a complete serializability
check: snapshot isolation can still allow write skew on two different keys.

### Roles and permissions

The role is supplied by a trusted application caller, not by an untrusted network
client. These are application checks, not PostgreSQL roles.

| Role | Allowed operations |
|---|---|
| `reader` | begin, read, commit, rollback |
| `writer` | reader operations plus write |
| `admin` | writer operations plus delete |

An unknown role raises `PermissionError` from `begin()`. An unauthorized operation
raises `PermissionError` and leaves pending and committed state unchanged.

### Inputs and transaction state

- Initial keys and operation keys must be non-empty strings; invalid keys raise
  `ValueError`.
- Values must be integers. Reject `bool` even though Python treats it as an integer.
  Negative values are allowed; business rules belong to the caller. Invalid values
  in the constructor or `write()` raise `ValueError`.
- A nonexistent or finished transaction cannot be read, written, deleted, committed,
  or rolled back. Raise `RuntimeError` consistently.
- A conflict aborts the transaction. Its pending changes are discarded, and later
  operations on it raise `RuntimeError`.

The engine only needs to support interleaved calls in one Python process. It does not
need thread safety, SQL support, persistence, deadlock prevention, WAL, or vacuum.

## Required cases to reason about

Your implementation and report should cover:

1. Snapshot visibility, repeatable reads, read-your-writes, and no dirty reads.
2. Rollback, read-only commit, transaction IDs, and commit sequence behavior.
3. Two writers changing one existing key, including a stale snapshot.
4. Two transactions creating the same missing key.
5. A write racing with a delete.
6. A transaction changing two keys where only one conflicts; neither change may
   commit.
7. A write-skew example where two transactions read the same invariant over two
   keys, then update different keys. Explain why first-committer-wins may allow both
   to commit and why that is not serializability. Do not add a serializability
   checker; explaining the limitation is enough.

## Tests and submission

Run the public tests from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab07\practice\test_student.py
```

Add at least three original tests in `test_extra.py`. Include an edge case that the
public tests do not cover. Do not modify `test_student.py`.

Submit these files:

- Your implementation in `student.py`.
- Your original tests in `test_extra.py`.
- Your own `results.md`, with a table of at least four scenarios and their observed
  outcomes, key invariants, one write-skew explanation, known simplifications, and
  brief evidence from your test runs.
