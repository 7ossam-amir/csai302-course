# Lab 8 - Crash Recovery with ARIES

Week 8 covers crash recovery. Students trace a small ARIES implementation with
write-ahead logging (WAL), audit logging, fuzzy checkpoints, and the analysis,
redo, and undo restart phases. They crash it on purpose in several ways, measure
how checkpoint frequency changes restart work, and compare the model with
PostgreSQL's real WAL and checkpointer. The lab ends with a disaster recovery plan
for a distributed database, because a single-node restart algorithm does not
protect against losing a disk, a node, or a whole site.

## Learning outcomes

By the end of the lab, students should be able to:

- Explain the steal / no-force buffer policy and why it needs both undo and redo.
- State the two WAL rules and show what goes wrong when the first one is broken.
- Read a log and identify each record's LSN, `prevLSN`, page, before and after
  values, and, for a CLR, its `undoNextLSN`.
- Run analysis, redo, and undo by hand: rebuild the transaction table (ATT) and
  dirty page table (DPT), choose the redo start point, apply the three redo skip
  tests, and undo losers in reverse LSN order.
- Explain why CLRs make recovery safe to repeat after a crash during rollback or
  during recovery itself.
- Describe what a fuzzy checkpoint records, what it does not do, and how checkpoint
  frequency trades normal-operation cost against restart time and log size.
- Integrate an audit trail with the WAL, keep it tamper-evident, and reconcile it
  after a crash.
- Write a disaster recovery plan with RPO and RTO targets for a replicated,
  multi-site database.

## How this lab fits the course

Lab 7 asked which committed versions a transaction may see. Lab 8 asks what
"committed" means when power fails: a committed change must survive, and an
uncommitted change must disappear, even if the buffer pool held some pages and
the disk held others. The concurrency control from Lab 7 is assumed here: the
recovery model behaves as if strict two-phase locking prevents two running
transactions from changing the same page. Lab 3's shared disk and object storage
return in the disaster recovery plan as the place base backups and archived WAL
are kept.

After class, students complete the independent implementation practice.

## Why a database needs a recovery algorithm

A transfer moves 100 from account A to account B. The database changes A's page
and B's page in the buffer pool, then reports "committed". If the server loses
power, three uncomfortable situations are possible:

1. **Committed, not on disk.** Neither page was written yet. Without help, the
   transfer is lost although the client was told it succeeded (durability).
2. **Uncommitted, already on disk.** The buffer manager needed a frame and wrote
   A's page while the transaction was still running. Without help, half a
   transfer survives (atomicity).
3. **Partly both.** One page reached disk and the other did not.

Forcing every page to disk at commit would remove case 1, and forbidding the
buffer manager from writing uncommitted pages would remove case 2, but both make
the system slow and inflexible. Real systems choose **steal** (uncommitted pages
may be written) and **no-force** (committed pages need not be written at commit).
They pay for that freedom with a log that can **redo** committed work and **undo**
uncommitted work.

## Write-ahead logging

Every change is first described by a log record. The log is appended
sequentially, and each record gets a log sequence number (LSN) that only grows.
In `aries.py` the LSN is the record's position in the log, starting at 1.

Two rules make the log sufficient:

1. **Log before data (undo rule).** A data page may be written to disk only after
   every log record that changed it is on stable storage. Each page carries a
   `pageLSN`, the LSN of the last change applied to it, so the buffer manager
   checks `flushedLSN >= pageLSN` before writing. See `MiniARIES.flush_page()`.
2. **Log before commit (redo rule).** A transaction is committed when its COMMIT
   record is on stable storage. `MiniARIES.commit()` forces the log through the
   COMMIT record; it does not write any data page.

Only a log *flush* costs a disk write. Appending to the in-memory log tail is
cheap, and one flush makes every earlier record durable, which is why a busy
system can group many commits into one flush (group commit).

### LSN vocabulary

| Name | Where it lives | Meaning |
|---|---|---|
| `lsn` | each log record | position of the record in the log |
| `prev_lsn` | each transaction record | previous record of the same transaction; the backward chain undo walks |
| `page_lsn` | each page, on disk and in the buffer | last change applied to this page |
| `rec_lsn` | DPT entry for a dirty buffered page | first change that made the page dirty since it was last clean |
| `last_lsn` | ATT entry | most recent record written by the transaction |
| `flushed_lsn` | log manager | everything up to here is on stable storage |
| `undo_next_lsn` | CLR | next record of that transaction that still needs undoing |
| master record | stable storage | LSN of the last complete checkpoint |

### Log record types

| Kind | Written by | Purpose |
|---|---|---|
| `BEGIN` | `begin()` | starts the `prev_lsn` chain and records the user, for auditing |
| `UPDATE` | `write()` | page, before value (for undo), after value (for redo) |
| `COMMIT` | `commit()` | forced to disk; the moment the transaction becomes durable |
| `ABORT` | `abort()`, analysis | the transaction is rolling back |
| `CLR` | undo | compensation log record: "this update has been undone"; redo-only |
| `END` | commit, end of rollback | the transaction needs no more work |
| `CKPT_BEGIN` / `CKPT_END` | `checkpoint()` | snapshot of ATT and DPT; the master record points at `CKPT_BEGIN` |

The model stores physical values (one integer per page). Real ARIES logs
physiological records, for example "insert this tuple in slot 4 of page 17", and
PostgreSQL logs WAL records per page plus a full copy of a page the first time it
changes after a checkpoint (`full_page_writes`) to survive torn pages.

## What survives a crash

`MiniARIES.crash()` keeps exactly what a real disk would keep:

| Survives | Lost |
|---|---|
| data pages on disk, each with its `page_lsn` | the buffer pool and every dirty page in it |
| the stable log, records `1 .. flushed_lsn` | the unflushed log tail |
| the master record (`master_lsn`) | the transaction table and the dirty page table |
| the audit trail | crash points and other in-memory flags |

## ARIES restart recovery

`MiniARIES.recover()` runs three passes and returns a `RecoveryReport`.

### 1. Analysis: what was going on at the crash?

Start at the master record's checkpoint (or LSN 1 when there is none) and scan
forward to the end of the stable log.

- `CKPT_END` seeds the ATT and DPT with the checkpoint's snapshots.
- Every transaction record adds the transaction to the ATT (if needed) and
  updates its `last_lsn`. `COMMIT` marks it committed, `ABORT` marks it aborting,
  and `END` removes it.
- Every `UPDATE` or `CLR` adds its page to the DPT if the page is not already
  there, with `rec_lsn` = that record's LSN.

At the end, committed transactions without an `END` are **winners**: analysis
finishes their bookkeeping (and repairs the audit trail, below). Every other
transaction in the ATT is a **loser**; running losers get an `ABORT` record.

The DPT that analysis builds is conservative. It may list a page that was
actually flushed before the crash; the redo tests below catch that.

### 2. Redo: repeat history

Redo starts at `redo_lsn = min(rec_lsn)` over the DPT, which can be earlier than
the checkpoint. It replays every `UPDATE` **and every CLR**, for winners and
losers alike, so that the database reaches the exact state it had at the crash.
A record is skipped when any of these holds:

1. its page is not in the DPT (the page was clean at the crash),
2. its LSN is lower than the page's `rec_lsn` (that change was already on disk
   when the page became dirty again), or
3. the page's `page_lsn` on disk is already at or past the record's LSN (fetched
   from disk only when tests 1 and 2 pass).

Redo writes no log records. Because of test 3, running redo twice does nothing
the second time.

### 3. Undo: remove the losers

Put the `last_lsn` of every loser in a set and repeatedly take the largest LSN:

- `UPDATE`: restore the before value, write a CLR whose `undo_next_lsn` is the
  update's `prev_lsn`, and continue with that LSN.
- `CLR`: do nothing and jump to its `undo_next_lsn`. The work it describes was
  done before the crash and redone in pass 2.
- `ABORT`: continue with its `prev_lsn`.
- `BEGIN`: the transaction is fully undone; write `END`.

Undoing in one combined reverse-LSN order touches the log in one backward sweep.
`MiniARIES.abort()` uses the same `_undo_step()` method for a normal rollback.

### Why CLRs matter

Suppose a rollback undid C, wrote a CLR, and then the system crashed. After
restart, redo replays the CLR (C is back to its old value) and undo starts at the
CLR, jumps to its `undo_next_lsn`, and continues with B. C is never undone a
second time, and each update gets at most one CLR, so the amount of undo work is
bounded even if the system crashes repeatedly during recovery. The
`abort-crash` and `recovery-crash` scenarios show this.

## Checkpoints

Without checkpoints, analysis would read the whole log and the log could never
be shortened. `MiniARIES.checkpoint()` writes a **fuzzy** checkpoint:
`CKPT_BEGIN`, then `CKPT_END` with copies of the ATT and DPT, then a log flush
and an update of the master record. It does **not** write data pages, so normal
work does not stop.

A checkpoint moves the analysis start. It does not by itself move the redo
start, which is the oldest `rec_lsn` of a page that is still dirty. A background
writer that steadily cleans old dirty pages (PostgreSQL's background writer and
checkpointer spread this I/O out) is what lets redo begin near the checkpoint.
`checkpoint(flush_dirty=True)` writes every dirty page first, which empties the
DPT at the cost of a burst of page writes.

`truncation_point()` reports the oldest LSN that recovery might still need:
the minimum of the checkpoint, the DPT `rec_lsn` values, and the `BEGIN` of the
oldest active transaction. A long-running transaction therefore keeps old log
segments alive, even after many checkpoints.

`checkpoint_analysis.py` runs one seeded workload under six policies, crashes it,
recovers it, and checks the result against an independent record of the
committed work. On the default workload, more frequent checkpoints reduce the
records analysis scans (367 -> 16) and the redo records examined (196 -> 41), but
add checkpoint records and log flushes. Flushing dirty pages at each checkpoint
cuts redo further and costs more page writes. The truncation column stays near
the long-running batch transaction's `BEGIN`.

## Audit logging integration

The WAL and an audit trail answer different questions:

| | Write-ahead log | Audit trail |
|---|---|---|
| Question | how do we restore a consistent state? | who changed what, when, and did it take effect? |
| Readers | the recovery manager, replicas | auditors, security staff, the application |
| Retention | recycled after checkpoints and archiving | kept for months or years |
| Content | physical page changes, CLRs, checkpoints | business-level events with user identity |
| Integrity | checksums against corruption | hash chain against tampering |

In the model, `AuditLog` is a separate durable store. Each entry includes the
hash of the previous entry, so `verify()` finds the first edited or deleted
entry. `commit()` writes audit entries only *after* the COMMIT record is durable,
which means the audit trail never claims a change that recovery could remove. A
crash in the small window between the log force and the audit write
(`crash_points.add("commit:after-log-flush")`) leaves a committed transaction
without audit entries; analysis notices a committed transaction without `END`,
re-creates the missing entries from the WAL, and checks first so that it never
writes them twice. Rolled-back transactions get an `ABORT` or
`RECOVERY_ROLLBACK` entry rather than their discarded updates.

PostgreSQL's trigger-based audit table in this lab takes the other common
approach: the audit row is written in the same transaction as the change, so the
same WAL makes both durable or neither. That removes the reconciliation step but
gives up independence: anyone who can rewrite the table can rewrite its audit
rows. Production systems often ship audit data to a separate append-only store.

## Reading the Python reference

`aries.py` is organized from the bottom up:

1. `LogRecord` is frozen: a record is never changed after it is written.
   `LogManager` keeps the records, `flushed_lsn`, and a count of real flushes.
   `lose_tail()` is what a crash does to the log.
2. `AuditLog` appends hash-chained entries and verifies the chain.
3. `DiskPage` is frozen (a page on disk changes only by being replaced);
   `Frame` is a mutable buffered page with `dirty` and `rec_lsn`; `TxEntry` is
   one ATT row.
4. `MiniARIES` implements normal operation (`begin`, `read`, `write`, `commit`,
   `abort`, `flush_page`, `checkpoint`) and restart (`crash`, `recover`,
   `_analysis`, `_redo`, `_undo`).

Follow the call path for one update: `write()` reads the current value as the
before image, appends an `UPDATE` with `prev_lsn = entry.last_lsn`, then
`_apply()` changes the frame, sets its `page_lsn`, and records `rec_lsn` if the
frame was clean. Nothing reaches disk until `commit()` forces the log or
`flush_page()` writes the page.

## Files

| File | Purpose |
|---|---|
| `aries.py` | Offline ARIES reference: WAL, buffer pool, audit trail, checkpoints, analysis / redo / undo |
| `crash_demo.py` | Eight deterministic crash scenarios, including crash during abort and during recovery |
| `checkpoint_analysis.py` | Checkpoint-frequency experiment with an oracle check of the recovered state |
| `test_lab08.py` | Offline checks for WAL rules, recovery, checkpoints, and auditing |
| `postgres_recovery_demo.py` | PostgreSQL WAL volume, checkpoints, audit trigger, and an optional real crash |
| `disaster_recovery_plan.md` | Worked disaster recovery plan for a replicated, multi-site PostgreSQL deployment |
| `db/schema.sql` | Lab 8 accounts, audit table and trigger, logged / UNLOGGED tables, crash markers |
| `db/seed.sql` | Repeatable fixture: two accounts, empty demo tables |
| `db/reset.sql` | Optional destructive reset of only the `lab08` schema |
| `practice/` | After-class implementation assignment and public tests |

## Run the offline examples

These commands do not need Docker or PostgreSQL:

```powershell
.\.venv\Scripts\python.exe labs\lab08\aries.py
.\.venv\Scripts\python.exe labs\lab08\crash_demo.py --scenario all
.\.venv\Scripts\python.exe labs\lab08\checkpoint_analysis.py
.\.venv\Scripts\python.exe labs\lab08\test_lab08.py
```

`aries.py` prints one complete trace: alice's committed transaction is redone and
bob's stolen, uncommitted page is undone. Run a single scenario with
`--scenario NAME`, where `NAME` is `redo`, `undo`, `mixed`, `abort-crash`,
`recovery-crash`, `checkpoint`, `audit`, or `wal-violation`. Try
`checkpoint_analysis.py --transactions 200 --flush-every 0` to see what happens
when no background writer cleans pages.

## Prepare the PostgreSQL fixture

Use the existing `.venv`, `.env`, Docker Compose file, PostgreSQL service, and
shared `csai302` database from the repository root. Start the service if needed:

```powershell
docker compose --env-file .env -f infra/compose.yaml start postgres
docker compose --env-file .env -f infra/compose.yaml ps
```

Load the schema and fixture with `psql` inside the container:

```powershell
Get-Content .\labs\lab08\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
Get-Content .\labs\lab08\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

macOS or Linux, from the repository root:

```sh
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab08/db/schema.sql
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab08/db/seed.sql
```

The seed may be rerun. It restores accounts 1 and 2 to 1000 and empties the Lab 8
audit, WAL-comparison, and crash-marker tables. `db/reset.sql` drops the whole
`lab08` schema; it does not touch other labs' schemas or the Docker volume.

## Run the PostgreSQL examples

```powershell
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode settings
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode wal
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode checkpoint
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode audit
```

`--mode all` runs those four. What to look for:

- **settings:** `fsync` and `full_page_writes` are on, `synchronous_commit` is on
  (COMMIT waits for the WAL flush, like `MiniARIES.commit()`), and the current WAL
  LSN is a byte position such as `0/1A2B3C4`, not a record counter.
- **wal:** loading the same 20,000 rows produces megabytes of WAL for the logged
  table and almost none for the `UNLOGGED` table. An unlogged table is emptied by
  crash recovery because there is nothing to redo it from.
- **checkpoint:** after `CHECKPOINT`, `redo_lsn` in `pg_control_checkpoint()` moves
  forward. That is PostgreSQL's equivalent of the master record and redo start.
  The `csai302` user created by the container is a superuser; other users need the
  `pg_checkpoint` role.
- **audit:** alice's committed transfer leaves two audit rows with her
  application user, the database user, and one transaction ID. bob's rolled-back
  transfer leaves none, because its audit rows were in the same transaction.

### Optional instructor demo: a real crash

This kills the PostgreSQL process without a clean shutdown. It is safe for the
course database because PostgreSQL recovers from its WAL, but it interrupts every
open session, so run it only on a teaching machine.

```powershell
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode crash-prepare
```

While it waits, kill the server from a second terminal, then start it again:

```powershell
docker compose --env-file .env -f infra/compose.yaml kill -s KILL postgres
docker compose --env-file .env -f infra/compose.yaml start postgres
.\.venv\Scripts\python.exe labs\lab08\postgres_recovery_demo.py --mode crash-check
docker compose --env-file .env -f infra/compose.yaml logs --tail 40 postgres
```

The committed marker is present and the uncommitted marker is not. The server log
shows the same redo pass as the model:

- `database system was not properly shut down; automatic recovery in progress`
- `redo starts at <LSN>`: the `redo_lsn` that `--mode checkpoint` printed for the
  latest checkpoint, the counterpart of the model's master record and redo start.
- `invalid record length at <LSN>: expected at least 24, got 0`: this is normal.
  It is how PostgreSQL finds the end of the WAL that reached disk, like reaching
  `flushed_lsn` in the model.
- `redo done at <LSN>`, then `checkpoint starting: end-of-recovery`: PostgreSQL
  takes a checkpoint as soon as recovery finishes, so the next crash does not have
  to replay the same WAL. The model does not do this.

PostgreSQL has no undo pass: MVCC leaves an aborted transaction's tuple versions
in place, marked invisible by the commit log, and VACUUM removes them later.

## Disaster recovery for a distributed database

ARIES recovers one node from its own disk and log. It cannot help when that disk
is destroyed, when a site loses power for a day, or when an operator drops a table
and the drop is faithfully replicated. [disaster_recovery_plan.md](disaster_recovery_plan.md)
is a worked plan for a three-node PostgreSQL deployment across two sites with base
backups and WAL archived to object storage. Read it after the crash scenarios; it
reuses the same ideas at a larger scale: WAL shipping is redo on another machine,
point-in-time recovery is redo that stops at a chosen LSN or time, and a
standby's replay position is its `flushed_lsn`.

## Home implementation practice

After class, complete [Practice 8](practice/README.md). Implement
`RecoverableStore` in `practice/student.py`: several keys per page, savepoints
with partial rollback, ARIES recovery that survives repeated crashes, log
truncation with stable LSNs, and an audit trail that lists only changes that took
effect. Then run a checkpoint experiment and write a disaster recovery plan for
the system described in the assignment.

## Discussion and design limits

- Which recovery pass would be unnecessary under a no-steal policy? Under force?
  Why do real systems still choose steal / no-force?
- Why does redo replay losers' updates and CLRs instead of only winners' updates?
- A checkpoint was written one second before the crash, yet redo starts far
  earlier. What explains that, and what would fix it?
- What does `synchronous_commit = off` trade away, and which part of the model
  corresponds to it?
- The audit trail and the WAL are both durable logs. What has to happen when one
  was written and the other was not?
- What is the difference between RPO and RTO, and which design choices in the
  disaster recovery plan change each one?
