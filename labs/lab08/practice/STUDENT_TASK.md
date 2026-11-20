# Practice 8 — Build a recoverable page store

## Scenario

The Lab 8 reference recovers pages that each hold one integer. Real pages hold
many records, real transactions roll back part of their work, and a real log
cannot grow forever. Extend the ideas from `aries.py` into a store with several
keys per page, savepoints, log truncation, and an audit trail that reports only
changes that actually took effect. Then measure checkpoint policies and write a
disaster recovery plan for a distributed deployment.

This is an in-memory teaching simulator, not a production database. Use only the
Python standard library. You may read `aries.py` for ideas, but do not import it:
write your own classes in `student.py`.

## Files and API

Implement the following in `student.py`:

```python
class SimulatedCrash(Exception): ...

class RecoverableStore:
    crash_points: set[str]
    def __init__(self, pages: dict[str, dict[str, int]] | None = None): ...
    # normal operation
    def begin(self, user: str) -> int: ...
    def read(self, tx_id: int, key: str) -> int: ...
    def write(self, tx_id: int, key: str, value: int) -> int: ...
    def savepoint(self, tx_id: int) -> int: ...
    def rollback_to(self, tx_id: int, savepoint: int) -> int: ...
    def commit(self, tx_id: int) -> int: ...
    def abort(self, tx_id: int) -> None: ...
    # storage
    def flush_log(self) -> None: ...
    def flush_page(self, page_id: str) -> bool: ...
    def checkpoint(self) -> int: ...
    def truncate_log(self) -> int: ...
    def crash(self) -> None: ...
    def recover(self, undo_limit: int | None = None) -> dict: ...
    # audit and inspection
    def audit_entries(self) -> list[dict]: ...
    def verify_audit(self, entries: list[dict] | None = None) -> int | None: ...
    def snapshot(self) -> dict[str, int]: ...
    def disk_snapshot(self) -> dict[str, int]: ...
    def log_records(self) -> list[dict]: ...
```

Keep these names and signatures. Explain any small representation choices in
your `results.md`.

## Required behavior

### Pages, keys, and inputs

- `pages` maps a page ID to that page's keys and integer values, for example
  `{"P1": {"alice": 100, "bob": 50}, "P2": {"carol": 70, "dave": 30}}`, which is
  also the default when `pages` is `None`. Every page starts on disk with page
  LSN 0.
- Page IDs, keys, and users must be non-empty strings. A key may appear on only
  one page. Values must be integers; reject `bool`. Invalid input raises
  `ValueError`. Reading or writing a valid but unknown key raises `KeyError`, and
  so does flushing an unknown page.
- Writes change existing keys only; there are no inserts or deletes.
- A nonexistent or finished transaction cannot be used: raise `RuntimeError`.
- Callers follow strict two-phase locking: two running transactions never write
  the same key. You do not need a lock manager.

### Log records and LSNs

- LSNs start at 1 and increase by one per record. Truncation never renumbers
  records. After a crash, the LSNs of the lost tail may be reused.
- `log_records()` returns the log that is still present, oldest first. Each
  record is a dictionary with at least `lsn`, `kind`, `tx`, `prev`, `page`, `key`,
  `before`, `after`, and `undo_next` (use `None` where a field does not apply).
- Use these kinds: `BEGIN`, `UPDATE`, `COMMIT`, `ABORT`, `CLR`, `END`,
  `CKPT_BEGIN`, `CKPT_END`. A CLR records the restored value in `after` and the
  next LSN to undo in `undo_next`.

### Normal operation and the WAL rules

- `begin(user)` logs `BEGIN` and returns a transaction ID larger than every ID
  used before, including before a crash.
- `write()` logs an `UPDATE` with the before and after values, then applies it to
  the buffered page and sets that page's LSN. It returns the record's LSN.
- `commit()` appends `COMMIT` and makes the log durable through it before it does
  anything else. If `"commit:after-log-flush"` is in `crash_points`, remove it
  and raise `SimulatedCrash` right after that flush: the transaction is durable
  but has no audit entries and no `END`. Otherwise write the audit entries, then
  `END`, and return the `COMMIT` LSN. A commit never writes data pages.
- `abort()` appends `ABORT`, undoes the transaction's remaining updates newest
  first with one CLR each, appends `END`, and writes an `ABORT` audit entry.
- `flush_page()` returns `False` for a clean or unbuffered page. Otherwise it
  first makes the log durable through the page's LSN, then writes the whole page
  (all of its keys and its page LSN) to disk, and returns `True`.
- `flush_log()` makes every record durable. It is also allowed while the system
  is crashed or recovery is incomplete.

### Savepoints

- `savepoint(tx)` returns an integer token for the transaction's current
  position. `rollback_to(tx, token)` undoes, newest first, every update made after
  that savepoint that is still in effect, writing one CLR each, and returns the
  number of CLRs. The transaction stays running and may keep writing, roll back
  again, commit, or abort.
- Rolling back to a savepoint releases savepoints created after it; the target
  savepoint stays usable. A token that this transaction did not receive, or one
  that was released, raises `ValueError`.
- An update that was compensated by a CLR must never be undone again: not by a
  later `abort()`, and not by recovery.

### Checkpoints and truncation

- `checkpoint()` writes `CKPT_BEGIN` and `CKPT_END`. `CKPT_END` carries copies of
  the transaction table and the dirty page table (choose your own format). Make the
  log durable through `CKPT_END`, set the master record to the `CKPT_BEGIN` LSN,
  and return that LSN. A checkpoint writes no data pages.
- `truncate_log()` removes old records and returns the first LSN kept. It must
  never remove a record that is not durable, the master checkpoint or anything
  after it, anything at or after the oldest `recLSN` in the dirty page table, or
  any record of a running transaction from its `BEGIN` onward. With no
  checkpoint yet, it removes nothing. Recovery must work after truncation.

### Crash and recovery

- `crash()` discards the unflushed log tail, the buffer pool, the transaction
  table, and `crash_points`. Disk pages, the durable log, the master record, and
  the audit trail survive. Until recovery completes, every method except
  `crash()`, `flush_log()`, `recover()`, and the audit and inspection methods
  raises `RuntimeError`.
- `recover()` raises `RuntimeError` unless the system is crashed. It runs
  analysis from the master record (or the oldest record present), redo from the
  oldest `recLSN` using the three ARIES skip tests, and undo of all losers in one
  reverse-LSN pass with CLRs. It returns a dictionary with:

  | Key | Value |
  |---|---|
  | `winners` | committed transactions that analysis found without `END` |
  | `losers` | transactions that were rolled back by this recovery |
  | `redo_applied` | LSNs actually reapplied by redo |
  | `clrs_written` | LSNs of the CLRs written by undo |
  | `complete` | `True` when undo finished |

- `undo_limit` stops undo after that many CLRs, as if the system failed again.
  Then `complete` is `False` and the system stays crashed. Calling `crash()` and
  `recover()` again must finish the job without undoing anything twice.
- After a completed recovery, `snapshot()` contains exactly the effects of
  committed transactions, and recovering again does no undo work.

### Audit trail

- The audit trail is a separate durable list. Each entry is a dictionary with at
  least `seq` (1, 2, 3, …), `event`, `tx`, `user`, `prev_hash`, and `hash`.
  `UPDATE` entries also have `key`, `before`, and `after`.
- Events: `UPDATE` and `COMMIT` for a commit, `ABORT` for `abort()`, and
  `RECOVERY_ROLLBACK` for a loser finished by recovery. The user is the one given
  to `begin()`, also after a crash.
- A commit writes one `UPDATE` entry for each update that is still in effect at
  commit (not one undone by `rollback_to`), oldest first, then one `COMMIT`.
- If a crash happened after the `COMMIT` record was durable but before the audit
  entries were written, recovery writes them. Every committed transaction has
  exactly one `COMMIT` entry, however many crashes occur.
- `hash` is the SHA-256 hex digest of `json.dumps(entry_without_hash,
  sort_keys=True)`. The first entry's `prev_hash` is `"0" * 64`; every later one
  is the previous entry's `hash`.
- `audit_entries()` returns copies, so changing them cannot change the store.
  `verify_audit(entries)` checks the given list (default: the store's own) and
  returns the `seq` of the first entry whose hash or `prev_hash` is wrong, or
  `None`.

The store only needs to support interleaved calls in one Python process. It does
not need threads, locks, SQL, media recovery, torn-page protection, or files.

## Required cases to reason about

Your implementation and report should cover:

1. A committed change that is only in the buffer pool at the crash (redo).
2. An uncommitted change that reached disk through `flush_page()` (undo).
3. One committed and one uncommitted transaction writing different keys on the
   same page, with the page flushed between them.
4. A savepoint rollback followed by commit, and a savepoint rollback followed by
   a crash before commit. Show the CLR chain in both cases.
5. A crash during recovery (`undo_limit`) followed by a second recovery.
6. Truncation with a long-running transaction: which LSN is kept and why.
7. A crash between the commit log force and the audit write.

## Checkpoint experiment

Write `experiment.py`. Run one seeded workload of at least 100 transactions, with
at least one long-running transaction, under at least three checkpoint policies
(for example none, every 20 transactions, every 5 transactions). After each run,
call `truncate_log()`, crash, and recover. Record, for each policy: log records
written, records kept after truncation, records your analysis pass scanned (add a
counter), records redone, CLRs written, and whether the recovered state matched
an independent record of the committed work. Present the results as a table in
`results.md` and explain the trade-off in your own words.

## Disaster recovery plan

Read `labs/lab08/disaster_recovery_plan.md`, then write your own `dr_plan.md` for
this different system. Do not copy the worked example.

> **CampusPay** handles student wallet top-ups and payments for a university. Its
> PostgreSQL data is split into two shards (wallets A–M and N–Z). Each shard has a
> primary and a synchronous standby in the campus data center, and an
> asynchronous standby in a cloud region in another country. A payment between two
> students on different shards uses two-phase commit. Finance requires audit
> records for 5 years. Targets: no lost payments when one server fails, at most one
> minute of payments lost if the campus data center is lost, service back within
> 15 minutes for a server failure and within 2 hours for a site loss. The budget
> covers the cloud region and object storage, but not a third site.

Your plan must include: scope and an architecture sketch; an RPO/RTO table with a
reason for each row; at least six failure scenarios with detection, response, and
expected RPO/RTO, including an in-doubt two-phase-commit transaction and a
logical-corruption event; the backup and WAL-archiving strategy; the replication
settings and what happens when the synchronous standby fails; runbooks for site
failover and for point-in-time recovery of *both* shards to one consistent
point; how split brain is prevented without a third site; monitoring signals; a
test schedule; roles; and one paragraph connecting at least three ideas from the
ARIES lab (for example WAL, redo, LSNs, checkpoints, CLRs) to your plan.

## Tests and submission

Run the public tests from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab08\practice\test_student.py
```

Add at least four original tests in `test_extra.py`, including one with two
crashes in a row and one edge case the public tests do not cover. Do not modify
`test_student.py`.

Submit these files:

- Your implementation in `student.py`.
- Your original tests in `test_extra.py`.
- `experiment.py` and its output.
- `results.md`: a table of at least six scenarios from the required cases with
  observed outcomes and the CLR or LSN evidence, the checkpoint experiment table
  and interpretation, key invariants, known simplifications, and brief evidence
  from your test runs.
- `dr_plan.md`: your disaster recovery plan for CampusPay.

When you finish, continue with the [worksheet](WORKSHEET.md): explain code, draw diagrams, predict output, and write three short recovery functions.
