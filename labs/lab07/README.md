# Lab 7 - Transaction Processing and MVCC

**Duration:** 2 hours in class, followed by an independent 4-7 hour home practice.

Week 7 covers transaction processing and concurrency control. In this lab, students
trace a small version-visibility model, observe concurrent behavior in PostgreSQL,
and then extend the model with conflict checks and permissions. The syllabus also
lists the broader project milestone; this lab prepares for its transaction work
without attempting the full query engine or TPC-H deliverable.

## Learning outcomes

By the end of the lab, students should be able to:

- Explain how a transaction snapshot determines which committed row version it can
  read, and why a transaction sees its own writes.
- Trace interleaved transactions and describe dirty reads, repeatable reads, stale
  writes, and write skew.
- Compare optimistic version checks with pessimistic row locks.
- Find a cycle in a wait-for graph and explain how PostgreSQL reports a deadlock.
- Explain why a better query plan must preserve the query's transactional meaning.
- Implement and test a small snapshot store with first-committer-wins, atomic
  commits, tombstones, and application-level role checks.

## How this lab fits the course

Lab 5's query operators and service access patterns, then Lab 6's plan choices,
lead into this week's question: how should concurrent executions observe and change
data? A faster access path must still return rows under the transaction's required
visibility rules. The syllabus's project milestone includes a transactional query
engine; this lab supplies a small concurrency-control foundation without taking on
the full engine, multiple join algorithms, visualization, or TPC-H queries.

The two-hour session is organized as follows:

| Time | Activity |
|---|---|
| 0-20 min | Instructor discussion of ACID isolation, versions, anomalies, locks, deadlocks, and authorization |
| 20-45 min | Guided Python and PostgreSQL examples using the reference simulator |
| 45-110 min | Individual code-tracing and documentation assessment; no code writing |
| 110-120 min | Debrief on invariants, edge cases, and control trade-offs |

After class, students complete the independent implementation practice.

## Why transactions need version visibility

Consider an account with a balance of 100. Transaction A starts and reads that
balance. Transaction B changes it to 80 and commits. If A reads again, should it see
80 or 100? The answer depends on the isolation level and snapshot rules. A system
that stores only one in-place value cannot give A its earlier view after B replaces
that value. Multi-Version Concurrency Control (MVCC) keeps committed versions so a
reader can select the newest version visible in its snapshot.

There is a second problem when an application reads a value, computes a replacement,
then writes that absolute value. If two clients both read 1000 and both compute 900,
their two writes can leave 900 even though two withdrawals were requested. A single
SQL update such as `balance = balance - 100` lets PostgreSQL apply each change to the
current row version. The transaction demos contrast those approaches.

## Transactions, versions, and snapshots

A transaction begins, reads and stages changes, then commits or rolls back. In the
reference simulator, each committed `Version` contains an integer value, a commit
sequence, and the transaction that wrote it. Initial values are at sequence 0. Each
`Transaction` has an ID, a snapshot sequence, a state, and private pending writes.

The simulator captures a snapshot when `MiniMVCC.begin()` runs. A read first checks
that transaction's pending writes. Otherwise, it returns the latest committed
version whose sequence is less than or equal to the saved snapshot. A pending write
from another transaction is invisible. A later commit does not change an existing
transaction's snapshot.

For example, T1 and T2 both begin at sequence 0. T1 stages `A = 80`, so T1 reads 80
while T2 still reads the committed value 100. T1 commits at sequence 1. T2 continues
to read 100 because its snapshot is still 0. A new T3 begins at sequence 1 and reads
80. This is the simulator's begin-time snapshot rule; it is not PostgreSQL's
READ COMMITTED rule.

The reference `MiniMVCC` is intentionally limited. It does not check write-write
conflicts, so two stale transactions may both commit changes to the same key and the
later commit wins. It does not implement deletes, durable storage, WAL, vacuum,
physical tuple headers, SQL, or a database lock manager. It demonstrates visibility,
not a complete database.

## Reading the Python reference

`Version` is a frozen dataclass: once a committed value and its sequence are recorded,
that version is not edited in place. `Transaction` is mutable because its state and
pending-write dictionary change while it runs. `MiniMVCC.versions` maps each key to
an ordered list of versions; `MiniMVCC.transactions` maps transaction IDs to their
current state.

Follow this call path in `mvcc.py`:

1. `begin()` saves the current commit sequence as the transaction's snapshot and
   assigns the next transaction ID.
2. `read()` checks the transaction's pending-write dictionary first. If it has no
   private value, it filters the key's version list to versions visible in the
   snapshot, then uses `max()` to select the newest one. An unknown key returns
   `None`.
3. `write()` stages an integer in that transaction's dictionary. It does not edit
   committed history.
4. `commit()` assigns one new sequence to all staged writes, appends immutable
   versions in key order, and marks the transaction committed. A read-only commit
   does not advance the sequence. `rollback()` clears the pending dictionary and
   marks the transaction aborted.

`_active_transaction()` raises an exception when a transaction is missing or already
finished. The `if __name__ == "__main__"` block prints a deterministic event trace;
the state-changing methods themselves do not print. The reference intentionally
allows a stale writer to overwrite a newer value. Students should identify that gap
before they study the home assignment's first-committer-wins rule.

## PostgreSQL isolation behavior

The PostgreSQL demo uses two connections to the course PostgreSQL 17 service. The
important behaviors to observe are:

- **READ COMMITTED:** each statement gets a new snapshot. If B commits an update
  between A's two `SELECT` statements, A's later statement can see it.
- **REPEATABLE READ:** PostgreSQL fixes the transaction snapshot at the first
  statement that needs one. A later `SELECT` in the same transaction continues to
  see the earlier row version, even if B commits an update.
- PostgreSQL treats **READ UNCOMMITTED** as READ COMMITTED; it does not expose dirty
  reads at that level. PostgreSQL's REPEATABLE READ also prevents phantoms, unlike
  some generic isolation-level tables.
- **SERIALIZABLE** can reject a transaction with SQLSTATE `40001`. Applications
  need to retry the whole transaction. PostgreSQL can abort one deadlock participant
  with SQLSTATE `40P01`; the application must not assume which transaction is chosen.

These PostgreSQL rules are distinct from the simulator's snapshot captured in
`begin()`. PostgreSQL READ COMMITTED takes a fresh snapshot per statement, and its
REPEATABLE READ snapshot is established at the first relevant statement rather than
merely by issuing `BEGIN`.

## Optimistic checks, locks, and authorization

The optimistic demo reads an account's `version`, then updates only if that version
is still current:

```sql
UPDATE lab07.accounts
SET balance = %s, version = version + 1
WHERE id = %s AND version = %s
RETURNING balance, version;
```

Psycopg supplies the three `%s` values separately from the SQL text.

If no row is returned, another transaction changed the row first. The application
can reload the state and retry the full operation. Optimistic control does not hold
a row lock while the application computes its proposed change.

The pessimistic demo uses `SELECT ... FOR UPDATE` to hold a row lock. A second
connection waits for at most 500 ms because of a transaction-local
`lock_timeout`; PostgreSQL reports SQLSTATE `55P03`. The demo rolls back that failed
transaction, commits the lock holder, and shows the second session acquiring the
row afterward. A latch is a short-lived mechanism for protecting an internal data
structure; a transaction lock coordinates access to a database resource; an MVCC
snapshot decides which committed versions a reader can see. They solve different
problems.

The permission example checks a trusted service role before it opens a connection
or sends a write. `reader`, `operator`, and `admin` are application roles for this
teaching example. They are not PostgreSQL `GRANT`/`REVOKE` roles, and they do not
protect a database exposed directly to a client that can bypass the service.

## Deadlocks and wait-for graphs

In a wait-for graph, an edge `T1 -> T2` means T1 is waiting for a resource held by
T2. A cycle means each transaction in that cycle is waiting on another transaction
in the cycle. `deadlock_demo.py` uses depth-first search with three states for each
node: unseen, active on the current search path, and fully explored. Finding an edge
back to an active node identifies a cycle. A cycle in this simplified graph is a
deadlock; cycle detection does not prevent or avoid one.

The optional PostgreSQL demo starts two independent sessions. Each locks one account
row, then both request the other row. A barrier makes sure both first locks are held
before the second requests. PostgreSQL detects the cycle and aborts one unspecified
victim. The graph checker is only a teaching model; PostgreSQL's lock manager tracks
more than this simple adjacency list.

In `deadlock_demo.py`, `threading.Barrier(2)` is only a rendezvous: each worker opens
its own database connection, acquires its first row lock, and waits until the other
worker has done the same. Then both request the opposite row. The barrier does not
implement locking or choose the victim. Session-local statement timeouts and a
bounded thread wait keep the demonstration from hanging.

## Files

| File | Purpose |
|---|---|
| `mvcc.py` | Offline, visibility-focused MVCC reference and deterministic trace |
| `transaction_demo.py` | PostgreSQL isolation, lost update, atomic update, optimistic and pessimistic control, and application-role examples |
| `deadlock_demo.py` | Offline wait-for cycle detector and optional bounded PostgreSQL deadlock |
| `test_lab07.py` | Offline checks for MVCC visibility and graph cycle detection |
| `code_trace_task.docx` | Individual, supervised code-tracing and documentation assessment; no answers |
| `db/schema.sql` | Lab 7 accounts table inside the `lab07` schema |
| `db/seed.sql` | Repeatable two-account fixture for the demos |
| `db/reset.sql` | Optional destructive reset of only the `lab07` schema |
| `practice/` | After-class implementation assignment and public tests |

## Run the offline examples

These commands do not need Docker or PostgreSQL:

```powershell
.\.venv\Scripts\python.exe labs\lab07\mvcc.py
.\.venv\Scripts\python.exe labs\lab07\test_lab07.py
.\.venv\Scripts\python.exe labs\lab07\deadlock_demo.py
```

The deterministic simulator trace should show two transactions starting at sequence
0, a staged write visible only to its owner, a commit at sequence 1, an old value
still visible to the older snapshot, and a new transaction reading the committed
value.

## Prepare the PostgreSQL fixture

Use the existing `.venv`, `.env`, Docker Compose file, PostgreSQL service, and shared
`csai302` database from the repository root. If the service has already been created,
start it with:

```powershell
docker compose --env-file .env -f infra/compose.yaml start postgres
docker compose --env-file .env -f infra/compose.yaml ps
```

For a first-time setup, follow the root README's `up -d postgres` command. Then load
the schema and fixture. These commands use `psql` inside the existing container, so
`psql` does not need to be installed on Windows:

```powershell
Get-Content .\labs\lab07\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
Get-Content .\labs\lab07\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

macOS or Linux, from the repository root:

```sh
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab07/db/schema.sql
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab07/db/seed.sql
```

The seed inserts accounts 1 and 2 and may be rerun; it restores only those two
fixture rows to 1000 units and version 0. Each demo also resets only accounts 1 and 2
before its scenario. Do not run `db/reset.sql` unless you intend to drop all objects
and data in schema `lab07`; it does not drop the shared database or Docker volume.

## Run the PostgreSQL examples

From the repository root, with the course `.venv` active:

```powershell
.\.venv\Scripts\python.exe labs\lab07\transaction_demo.py --mode isolation
.\.venv\Scripts\python.exe labs\lab07\transaction_demo.py --mode lost-update
.\.venv\Scripts\python.exe labs\lab07\transaction_demo.py --mode optimistic
.\.venv\Scripts\python.exe labs\lab07\transaction_demo.py --mode pessimistic
.\.venv\Scripts\python.exe labs\lab07\transaction_demo.py --mode permissions
.\.venv\Scripts\python.exe labs\lab07\deadlock_demo.py --postgres
```

`transaction_demo.py --mode all` runs each transaction example. The isolation mode
should show A reading the changed balance under READ COMMITTED and the original
balance under REPEATABLE READ. The unsafe application read/compute/absolute-write
sequence ends at 900 after two requested withdrawals of 100 from 1000; the atomic
conditional updates end at 800. The optimistic mode should reject the second update
using the stale version. The lock mode waits no longer than its local timeout before
rolling back and retrying. The deadlock mode reports SQLSTATE `40P01` for one
unspecified victim. Intermediate outcomes and timing can vary; use the printed state
and SQLSTATE rather than assuming which session wins.

The demos use separate connections for separate sessions and short statement or lock
timeouts. They do not change server-wide settings, create roles, or touch data outside
`lab07.accounts`. If PostgreSQL is unavailable, the offline simulator and graph tests
still run.

Manually orchestrated sessions close connections in `finally` blocks and roll back
failed transactions; the remaining connections use context managers. The
atomic-update example uses a two-party barrier to start two independent clients near
the same time; each worker has its own Psycopg connection. No connection object is
shared between the worker threads.

## In-class code-tracing assessment

The 65-minute assessment is an individual code-reading and documentation task. It
does not ask students to write or edit code. Students predict behavior before they
verify it, trace the actual `mvcc.py` methods and the wait-for graph checker, and
explain failure cases and design limits in their own words. The worksheet is worth
100 points across architecture, manual tracing, code reasoning, edge cases, a graph
trace, and engineering judgment. Generative AI and code assistants are not allowed
during this supervised activity. Submit the completed file as
`CSAI302_Lab07_CodeTrace_<StudentID>.docx`.

## Home implementation practice

After class, complete [Practice 7](practice/README.md). Implement the stronger
`SnapshotStore` contract in `practice/student.py`: snapshot reads, read-your-writes,
tombstones, role checks, first-committer-wins conflicts, and all-or-nothing
multi-key commits. The public tests are a starting point, not a solution. Add at
least three of your own tests and submit a short `results.md` with scenario outcomes,
invariants, write-skew reasoning, simplifications, and test evidence.

## Discussion and design limits

- How can PostgreSQL REPEATABLE READ keep a row version available to an older reader?
- Which is preferable for a low-contention account update: an optimistic version
  check or a pessimistic row lock? What changes if conflicts are frequent?
- If a transaction's estimated or planned work changes after a commit, what must
  remain true about the query's results and transactional guarantees?
- What signal in PostgreSQL output would reveal that a stale application value or
  blocked lock caused a problem?
- Why does first-committer-wins prevent some lost updates but still allow write skew?

The in-memory reference has no durability or real parallel execution. The home
assignment adds write-conflict checks, but still uses snapshot isolation: two
transactions can read the same invariant and write different keys, so both may
commit and violate that invariant. PostgreSQL SERIALIZABLE adds further checks and
may ask an application to retry. These examples teach selected behaviors; they are
not substitutes for PostgreSQL's transaction manager.
