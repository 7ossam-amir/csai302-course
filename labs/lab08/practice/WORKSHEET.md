# Lab 8 Worksheet — Explain, Draw, Predict, Code

Do it after the [practice task](STUDENT_TASK.md), or at least after reading `aries.py`, running `crash_demo.py`, and reading `disaster_recovery_plan.md`.

Write your answers in `worksheet_answers.md`. Draw diagrams on paper (and add a photo), in ASCII, or in Mermaid. Each diagram must show the values and LSNs, not only the boxes.

Parts B and C use this fixture. In the comments, `(LSN n)` is the log record that the line writes.

```python
db = MiniARIES({"A": 100, "B": 200, "C": 300, "D": 400})
t1 = db.begin("sara")         # (LSN 1)
t2 = db.begin("omar")         # (LSN 2)
t3 = db.begin("laila")        # (LSN 3)
db.write(t1, "A", 150)        # (LSN 4)
db.write(t2, "B", 250)        # (LSN 5)
db.write(t3, "C", 350)        # (LSN 6)
db.checkpoint()               # (LSN 7 and 8)
db.write(t2, "D", 450)        # (LSN 9)
db.commit(t2)                 # (LSN 10 and 11)
db.flush_page("C")
db.write(t1, "B", 260)        # (LSN 12)
db.write(t3, "D", 470)        # (LSN 13)
db.crash()
```

Assume strict two-phase locking: T1 may write B at LSN 12 only because T2 has already committed.

## Part A — Explain the code

Answer each question in 2–4 sentences. Quote the line you are explaining.

1. **`MiniARIES.flush_page()`** calls `self.log.flush(frame.page_lsn)`. Why does it flush up to the page's LSN, and not the whole log or nothing? What does the `wal-violation` scenario in `crash_demo.py` show when this line is skipped?
2. **`MiniARIES.commit()`** forces the log but never calls `flush_page()`. Why is the transaction still durable? Which restart phase pays for this choice?
3. **`MiniARIES._apply()`** sets `frame.rec_lsn` only `if not frame.dirty`. What would go wrong during restart if every update overwrote `rec_lsn`?
4. **`MiniARIES._redo()`** checks "page not in DPT" and "LSN < recLSN" before it calls `self._fetch(page_id)`. Why are the tests in this order? What does the third test need that the first two do not?
5. **`MiniARIES._undo()`** keeps one heap of `-entry.last_lsn` for all losers instead of rolling back one transaction at a time. What does this order give a real system, and why does it still undo each transaction correctly?
6. **`AuditLog.append()`** stores `prev_hash`. Explain how deleting entry 2 of a 5-entry trail is detected by `verify()`, and which entry number it reports. Why does `commit()` write the audit entries only after `self.log.flush(record.lsn)`?

## Part B — Draw it

1. **The log and the pages at the crash.** Draw the 13 log records. For each transaction, draw its `prevLSN` chain as arrows. Draw a line at `flushedLSN` and mark the records lost in the crash. Next to the log, draw the four pages twice: in the buffer pool (value, pageLSN, dirty, recLSN) and on disk (value, pageLSN), just before `crash()`.

2. **Analysis.** Starting from the master record, draw the ATT and the DPT after each record that analysis reads. Circle the DPT entry that is wrong (the page is no longer dirty) and explain why analysis still includes it. Write down which transactions are winners and which are losers, and which records analysis writes at the end.

3. **Redo and undo.** For every UPDATE or CLR from the redo start, draw a row: page, in DPT?, recLSN, pageLSN on disk, and the decision. Then draw the undo pass: the set of LSNs to undo after each step, each CLR it writes, and that CLR's `undoNextLSN` arrow. Give the final values of A, B, C, and D, and the audit events that recovery writes.

4. **What happened to LSN 12?** T1 wrote B = 260 at LSN 12, yet B ends at 250. Draw B's history (each value with the LSN that produced it) and show where 260 disappeared. Which ACID property makes that correct?

5. **Failover in the disaster recovery plan.** Draw a timeline for the worked plan's site failover (runbook R2): pg-a1, pg-a2, and pg-b1, with the LSN each one has flushed at the moment site A is lost. Mark which commits were acknowledged to clients, which ones reach pg-b1, and the RPO window. Then draw the same timeline for a single node crash (F1) and explain why its RPO is 0.

## Part C — Predict, then run

Write your prediction first, then run the code and correct it if needed.

1. Run the fixture, then `report = db.recover()`. Predict `report.analysis_start`, `report.analysis_scanned`, `report.redo_start`, `report.redo_applied`, `report.losers`, and `len(report.clrs_written)`.

2. For each snippet, predict what the last line prints.

   ```python
   d = MiniARIES(); t = d.begin("a"); d.write(t, "A", 1); d.commit(t)
   d.checkpoint(); u = d.begin("b"); d.write(u, "B", 2)
   d.crash(); r = d.recover()
   print(r.analysis_scanned, r.redo_start, r.losers, d.current_values())
   ```

   ```python
   d = MiniARIES(); t = d.begin("a"); d.write(t, "A", 1); d.commit(t)
   d.checkpoint(flush_dirty=True); u = d.begin("b"); d.write(u, "B", 2); d.flush_page("B")
   d.crash(); r = d.recover()
   print(r.redo_start, r.redo_skipped, r.losers, r.clrs_written, d.current_values())
   ```

   ```python
   d = MiniARIES(); t = d.begin("a")
   for v in (1, 2, 3):
       d.write(t, "A", v)
   d.abort(t)
   print(d.log.flushed_lsn, d.log.last_lsn, [e["event"] for e in d.audit.entries])
   d.crash(); r = d.recover()
   print(r.analysis_scanned, d.current_values()["A"])
   ```

   In the last snippet, `abort()` never forces the log. Is that a bug? Explain using the output.

3. Before running it, predict which two columns of `checkpoint_analysis.py` change the most when you add `--flush-every 0`, and in which direction. Then run it and explain the difference.

## Part D — Write the code (`worksheet.py`)

| What | What it does |
|---|---|
| `redo_decision(record, dpt, disk_page_lsn)` | returns `"apply"`, `"not in DPT"`, `"LSN < recLSN"`, or `"pageLSN >= LSN"` for one UPDATE or CLR, testing in that order; any other record raises `ValueError` |
| `undo_chain(records, tx_id)` | the LSNs of the transaction's UPDATEs that undo still has to compensate, newest first, starting from its last record and jumping over work that CLRs already undid; a committed or unknown transaction raises `ValueError` |
| `failover_loss(commits, standby_lsn)` | for a promotion of a standby that has flushed WAL up to `standby_lsn`: the transactions whose commit is lost, and the length of the lost window in seconds |

In one sentence each, answer:

- Why can `undo_chain` stop at a CLR's `undo_next_lsn` instead of looking at every older record of the transaction?
- With a synchronous standby, why does `failover_loss` always return no lost transactions?

Check your code:

```powershell
.\.venv\Scripts\python.exe labs\lab08\practice\test_worksheet.py
```

## What to Submit

- `worksheet.py`, completed.
- `worksheet_answers.md` with Parts A–C, the two answers of Part D, your diagrams, and the output of `test_worksheet.py`.
