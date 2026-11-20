"""A small ARIES recovery model for Lab 8.

The model has four durable things that survive a crash:

* the stable part of the write-ahead log (records up to ``log.flushed_lsn``),
* the data pages on disk, each stamped with the LSN of the last change it holds,
* the master record (the LSN of the most recent checkpoint), and
* the audit trail, a separate append-only, hash-chained store.

Everything else (the buffer pool, the transaction table, and the unflushed log
tail) is volatile and disappears in ``crash()``. ``recover()`` then runs the
three ARIES restart phases: analysis, redo ("repeat history"), and undo with
compensation log records (CLRs).

Buffer policy is steal / no-force: a dirty page from an uncommitted transaction
may be written to disk, and committed pages do not have to be written at
commit. The WAL rule makes that safe: before a page is written, the log is
flushed at least up to that page's LSN, and a commit forces the log up to its
COMMIT record.

This is a teaching model. Each page holds one integer, there is one process and
no lock manager (assume strict two-phase locking above it), and the log is a
Python list whose index is the LSN.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass, field

BEGIN = "BEGIN"
UPDATE = "UPDATE"
COMMIT = "COMMIT"
ABORT = "ABORT"
CLR = "CLR"
END = "END"
CKPT_BEGIN = "CKPT_BEGIN"
CKPT_END = "CKPT_END"

REDOABLE = (UPDATE, CLR)


class SimulatedCrash(Exception):
    """Raised at an injected crash point. Call ``crash()`` and then ``recover()``."""


# --------------------------------------------------------------------------- log
@dataclass(frozen=True)
class LogRecord:
    """One write-ahead log record. Records are never edited after they are written."""

    lsn: int
    kind: str
    tx_id: int | None = None
    prev_lsn: int | None = None
    page_id: str | None = None
    before: int | None = None
    after: int | None = None
    undo_next_lsn: int | None = None
    user: str | None = None
    att: tuple = ()  # CKPT_END only: ((tx_id, status, last_lsn), ...)
    dpt: tuple = ()  # CKPT_END only: ((page_id, rec_lsn), ...)

    def describe(self) -> str:
        head = f"LSN {self.lsn:>3}  {self.kind:<10}"
        if self.kind == CKPT_BEGIN:
            return head
        if self.kind == CKPT_END:
            att = ", ".join(f"T{t}:{s}@{lsn}" for t, s, lsn in self.att) or "-"
            dpt = ", ".join(f"{p}:{lsn}" for p, lsn in self.dpt) or "-"
            return f"{head} ATT[{att}]  DPT[{dpt}]"
        text = f"{head} T{self.tx_id} prev={self.prev_lsn}"
        if self.kind == BEGIN:
            text += f" user={self.user}"
        elif self.kind == UPDATE:
            text += f" page={self.page_id} {self.before}->{self.after}"
        elif self.kind == CLR:
            text += f" page={self.page_id} ->{self.after} undoNext={self.undo_next_lsn}"
        return text


class LogManager:
    """An in-memory log with a durable prefix. ``records[i]`` has LSN ``i + 1``."""

    def __init__(self) -> None:
        self.records: list[LogRecord] = []
        self.flushed_lsn = 0
        self.forces = 0  # how many times a flush actually wrote something

    @property
    def last_lsn(self) -> int:
        return len(self.records)

    def append(self, kind: str, **fields) -> LogRecord:
        record = LogRecord(lsn=self.last_lsn + 1, kind=kind, **fields)
        self.records.append(record)
        return record

    def get(self, lsn: int) -> LogRecord:
        if not 1 <= lsn <= self.last_lsn:
            raise KeyError(f"no log record with LSN {lsn}")
        return self.records[lsn - 1]

    def flush(self, up_to: int | None = None) -> bool:
        """Make every record up to ``up_to`` (default: all) durable."""
        target = self.last_lsn if up_to is None else min(up_to, self.last_lsn)
        if target <= self.flushed_lsn:
            return False
        self.flushed_lsn = target
        self.forces += 1
        return True

    def scan(self, start_lsn: int):
        """Yield records from ``start_lsn`` to the end of the log, oldest first."""
        for index in range(max(start_lsn, 1) - 1, self.last_lsn):
            yield self.records[index]

    def lose_tail(self) -> int:
        """Crash: discard records that never reached stable storage."""
        lost = self.last_lsn - self.flushed_lsn
        del self.records[self.flushed_lsn:]
        return lost


# ------------------------------------------------------------------------- audit
class AuditLog:
    """A durable, append-only, hash-chained audit trail.

    The WAL answers "how do we restore a consistent state?" and may be recycled
    after a checkpoint. The audit trail answers "who changed what, and did it
    take effect?" and is kept. Each entry stores the hash of the previous one,
    so editing or deleting an old entry breaks every later hash.
    """

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self.entries: list[dict] = []

    @staticmethod
    def _digest(body: dict) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def append(self, event: str, tx_id: int, user: str, **detail) -> dict:
        body = {
            "seq": len(self.entries) + 1,
            "event": event,
            "tx_id": tx_id,
            "user": user,
            **detail,
            "prev_hash": self.entries[-1]["hash"] if self.entries else self.GENESIS,
        }
        entry = {**body, "hash": self._digest(body)}
        self.entries.append(entry)
        return entry

    def has(self, event: str, tx_id: int) -> bool:
        return any(e["event"] == event and e["tx_id"] == tx_id for e in self.entries)

    def verify(self) -> int | None:
        """Return the sequence number of the first damaged entry, or ``None`` if intact."""
        previous = self.GENESIS
        for entry in self.entries:
            body = {k: v for k, v in entry.items() if k != "hash"}
            if body.get("prev_hash") != previous or self._digest(body) != entry["hash"]:
                return entry.get("seq")
            previous = entry["hash"]
        return None


# ---------------------------------------------------------------- pages and txns
@dataclass(frozen=True)
class DiskPage:
    value: int
    page_lsn: int


@dataclass
class Frame:
    """A page held in the buffer pool."""

    value: int
    page_lsn: int
    dirty: bool = False
    rec_lsn: int | None = None  # first LSN that dirtied this frame since it was clean


@dataclass
class TxEntry:
    """One row of the transaction table (ATT)."""

    tx_id: int
    status: str  # "running", "committed", or "aborting"
    last_lsn: int
    user: str | None = None


@dataclass
class RecoveryReport:
    """What each restart phase saw and did, for printing and for tests."""

    checkpoint_lsn: int
    analysis_start: int
    analysis_scanned: int = 0
    att: dict[int, str] = field(default_factory=dict)
    dpt: dict[str, int] = field(default_factory=dict)
    winners: list[int] = field(default_factory=list)
    losers: list[int] = field(default_factory=list)
    redo_start: int | None = None
    redo_examined: int = 0
    redo_applied: list[int] = field(default_factory=list)
    redo_skipped: list[tuple[int, str]] = field(default_factory=list)
    undo_visited: list[int] = field(default_factory=list)
    clrs_written: list[int] = field(default_factory=list)
    audit_repaired: list[int] = field(default_factory=list)
    complete: bool = False


# ---------------------------------------------------------------------- database
class MiniARIES:
    """A tiny page store with write-ahead logging and ARIES restart recovery."""

    def __init__(self, initial: dict[str, int] | None = None, *, enforce_wal: bool = True) -> None:
        if initial is None:
            initial = {"A": 100, "B": 200, "C": 300}
        self.disk: dict[str, DiskPage] = {}
        for page_id, value in initial.items():
            self._validate_page_id(page_id)
            self._validate_value(value)
            self.disk[page_id] = DiskPage(value, 0)

        self.log = LogManager()
        self.audit = AuditLog()
        self.master_lsn = 0  # durable pointer to the last complete checkpoint
        self.enforce_wal = enforce_wal

        self.buffer: dict[str, Frame] = {}
        self.transactions: dict[int, TxEntry] = {}
        self.crashed = False
        self.crash_points: set[str] = set()
        self.page_writes = 0
        self._next_tx_id = 1

    # ---------------------------------------------------------------- validation
    @staticmethod
    def _validate_page_id(page_id: object) -> None:
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("page ids must be non-empty strings")

    @staticmethod
    def _validate_value(value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page values must be integers")

    def _require_running_system(self) -> None:
        if self.crashed:
            raise RuntimeError("the system crashed; call recover() first")

    def _active(self, tx_id: int) -> TxEntry:
        self._require_running_system()
        entry = self.transactions.get(tx_id)
        if entry is None or entry.status != "running":
            raise RuntimeError(f"transaction {tx_id} is unknown or not running")
        return entry

    def _crash_point(self, name: str) -> None:
        if name in self.crash_points:
            self.crash_points.discard(name)
            raise SimulatedCrash(name)

    # ------------------------------------------------------------- buffer pool
    def _fetch(self, page_id: str) -> Frame:
        frame = self.buffer.get(page_id)
        if frame is None:
            if page_id not in self.disk:
                raise KeyError(f"unknown page {page_id!r}")
            stored = self.disk[page_id]
            frame = Frame(stored.value, stored.page_lsn)
            self.buffer[page_id] = frame
        return frame

    def _apply(self, page_id: str, lsn: int, value: int) -> None:
        frame = self._fetch(page_id)
        frame.value = value
        frame.page_lsn = lsn
        if not frame.dirty:
            frame.dirty = True
            frame.rec_lsn = lsn

    def flush_page(self, page_id: str) -> bool:
        """Write one dirty page to disk (a "steal" if its writer has not committed)."""
        self._require_running_system()
        frame = self.buffer.get(page_id)
        if frame is None or not frame.dirty:
            return False
        if self.enforce_wal:
            self.log.flush(frame.page_lsn)  # the WAL rule: log first, then the page
        self.disk[page_id] = DiskPage(frame.value, frame.page_lsn)
        frame.dirty = False
        frame.rec_lsn = None
        self.page_writes += 1
        return True

    def flush_all_pages(self) -> int:
        return sum(self.flush_page(page_id) for page_id in sorted(self.buffer))

    @property
    def dirty_page_table(self) -> dict[str, int]:
        return {p: f.rec_lsn for p, f in sorted(self.buffer.items()) if f.dirty}

    def disk_values(self) -> dict[str, int]:
        return {p: page.value for p, page in sorted(self.disk.items())}

    def current_values(self) -> dict[str, int]:
        """What a reader would see now: buffered pages override disk pages."""
        values = self.disk_values()
        values.update({p: f.value for p, f in self.buffer.items()})
        return dict(sorted(values.items()))

    # ------------------------------------------------------------ transactions
    def begin(self, user: str = "app") -> int:
        self._require_running_system()
        tx_id = self._next_tx_id
        self._next_tx_id += 1
        record = self.log.append(BEGIN, tx_id=tx_id, user=user)
        self.transactions[tx_id] = TxEntry(tx_id, "running", record.lsn, user)
        return tx_id

    def read(self, tx_id: int, page_id: str) -> int:
        self._active(tx_id)
        return self._fetch(page_id).value

    def write(self, tx_id: int, page_id: str, value: int) -> int:
        """Log the change first, then apply it to the buffered page. Returns its LSN."""
        entry = self._active(tx_id)
        self._validate_value(value)
        frame = self._fetch(page_id)
        record = self.log.append(
            UPDATE, tx_id=tx_id, prev_lsn=entry.last_lsn,
            page_id=page_id, before=frame.value, after=value,
        )
        self._apply(page_id, record.lsn, value)
        entry.last_lsn = record.lsn
        return record.lsn

    def commit(self, tx_id: int) -> int:
        """Force the log through COMMIT; the transaction is durable once that returns."""
        entry = self._active(tx_id)
        record = self.log.append(COMMIT, tx_id=tx_id, prev_lsn=entry.last_lsn)
        self.log.flush(record.lsn)
        entry.status = "committed"
        entry.last_lsn = record.lsn
        self._crash_point("commit:after-log-flush")
        self._audit_commit(tx_id, entry.user)
        self.log.append(END, tx_id=tx_id, prev_lsn=record.lsn)
        del self.transactions[tx_id]
        return record.lsn

    def abort(self, tx_id: int, *, max_clrs: int | None = None) -> int:
        """Roll back with CLRs. ``max_clrs`` stops part-way to simulate a crash mid-abort."""
        entry = self._active(tx_id)
        record = self.log.append(ABORT, tx_id=tx_id, prev_lsn=entry.last_lsn)
        entry.status = "aborting"
        entry.last_lsn = record.lsn
        written = 0
        next_lsn: int | None = record.lsn
        while next_lsn is not None:
            if max_clrs is not None and written >= max_clrs:
                return written  # left "aborting"; a crash now leaves the work to recovery
            step = self.log.get(next_lsn)
            next_lsn, clr = self._undo_step(step, entry)
            written += clr is not None
        self._finish_abort(entry, actor="application")
        return written

    def _undo_step(self, record: LogRecord, entry: TxEntry) -> tuple[int | None, LogRecord | None]:
        """Undo one record of a transaction. Returns (next LSN to undo, CLR written)."""
        if record.kind == UPDATE:
            clr = self.log.append(
                CLR, tx_id=record.tx_id, prev_lsn=entry.last_lsn, page_id=record.page_id,
                after=record.before, undo_next_lsn=record.prev_lsn,
            )
            self._apply(record.page_id, clr.lsn, record.before)
            entry.last_lsn = clr.lsn
            return record.prev_lsn, clr
        if record.kind == CLR:
            return record.undo_next_lsn, None  # already compensated: skip past it
        if record.kind == BEGIN:
            return None, None
        return record.prev_lsn, None  # ABORT: keep walking back

    def _finish_abort(self, entry: TxEntry, *, actor: str) -> None:
        self.log.append(END, tx_id=entry.tx_id, prev_lsn=entry.last_lsn)
        event = "ABORT" if actor == "application" else "RECOVERY_ROLLBACK"
        self.audit.append(event, entry.tx_id, self._user_of(entry), actor=actor)
        del self.transactions[entry.tx_id]

    # ------------------------------------------------------------------- audit
    def _user_of(self, entry: TxEntry) -> str:
        if entry.user is not None:
            return entry.user
        for record in self.log.records:
            if record.kind == BEGIN and record.tx_id == entry.tx_id:
                entry.user = record.user
                return record.user
        return "unknown"

    def _audit_commit(self, tx_id: int, user: str | None) -> None:
        """Record a committed transaction's changes once. Safe to call again after a crash."""
        if self.audit.has("COMMIT", tx_id):
            return
        updates = [r for r in self.log.records if r.tx_id == tx_id and r.kind == UPDATE]
        commit = next(r for r in self.log.records if r.tx_id == tx_id and r.kind == COMMIT)
        who = user or "unknown"
        for record in updates:
            self.audit.append(
                "UPDATE", tx_id, who, page=record.page_id,
                before=record.before, after=record.after, lsn=record.lsn,
            )
        self.audit.append("COMMIT", tx_id, who, lsn=commit.lsn)

    # -------------------------------------------------------------- checkpoint
    def checkpoint(self, *, flush_dirty: bool = False) -> int:
        """Write a fuzzy checkpoint (ATT and DPT snapshots) and update the master record.

        A fuzzy checkpoint does not write data pages. ``flush_dirty=True`` first
        writes every dirty page, which moves the next redo start forward at the
        cost of extra page I/O.
        """
        self._require_running_system()
        if flush_dirty:
            self.flush_all_pages()
        begin = self.log.append(CKPT_BEGIN)
        att = tuple((t, e.status, e.last_lsn) for t, e in sorted(self.transactions.items()))
        dpt = tuple(self.dirty_page_table.items())
        end = self.log.append(CKPT_END, att=att, dpt=dpt)
        self.log.flush(end.lsn)
        self.master_lsn = begin.lsn
        return begin.lsn

    def truncation_point(self) -> int:
        """Oldest LSN recovery could still need: min(recLSN of dirty pages, oldest active BEGIN)."""
        candidates = [self.master_lsn or 1, *self.dirty_page_table.values()]
        for entry in self.transactions.values():
            lsn = entry.last_lsn
            while lsn is not None and self.log.get(lsn).kind != BEGIN:
                record = self.log.get(lsn)
                lsn = record.undo_next_lsn if record.kind == CLR else record.prev_lsn
            if lsn is not None:
                candidates.append(lsn)
        return min(candidates)

    # ----------------------------------------------------------- crash/restart
    def crash(self) -> dict[str, int]:
        """Lose all volatile state. Disk pages, the stable log, master record, and audit survive."""
        lost_dirty = sum(1 for frame in self.buffer.values() if frame.dirty)
        lost_records = self.log.lose_tail()
        self.buffer.clear()
        self.transactions.clear()
        self.crash_points.clear()
        self.crashed = True
        return {"lost_log_records": lost_records, "lost_dirty_pages": lost_dirty}

    def recover(self, *, undo_limit: int | None = None) -> RecoveryReport:
        """Run analysis, redo, and undo. ``undo_limit`` stops undo early to simulate a second crash."""
        if not self.crashed:
            raise RuntimeError("recover() is only valid after crash()")
        report = RecoveryReport(checkpoint_lsn=self.master_lsn, analysis_start=self.master_lsn or 1)
        self._analysis(report)
        self._redo(report)
        self._undo(report, undo_limit)
        if report.complete:
            self.log.flush()
            self.crashed = False
        tx_ids = [r.tx_id for r in self.log.records if r.tx_id is not None]
        self._next_tx_id = max(tx_ids, default=0) + 1
        return report

    def _analysis(self, report: RecoveryReport) -> None:
        att: dict[int, TxEntry] = {}
        dpt: dict[str, int] = {}
        for record in self.log.scan(report.analysis_start):
            report.analysis_scanned += 1
            if record.kind == CKPT_END:
                for tx_id, status, last_lsn in record.att:
                    att.setdefault(tx_id, TxEntry(tx_id, status, last_lsn))
                for page_id, rec_lsn in record.dpt:
                    dpt.setdefault(page_id, rec_lsn)
                continue
            if record.tx_id is None:
                continue
            entry = att.setdefault(record.tx_id, TxEntry(record.tx_id, "running", record.lsn))
            entry.last_lsn = record.lsn
            if record.kind == BEGIN:
                entry.user = record.user
            elif record.kind == COMMIT:
                entry.status = "committed"
            elif record.kind == ABORT:
                entry.status = "aborting"
            elif record.kind == END:
                del att[record.tx_id]
            if record.kind in REDOABLE:
                dpt.setdefault(record.page_id, record.lsn)

        report.att = {t: e.status for t, e in sorted(att.items())}
        report.dpt = dict(sorted(dpt.items()))
        self.transactions = att
        self._recovery_dpt = dpt

        for tx_id, entry in sorted(att.items()):
            if entry.status == "committed":
                # COMMIT is durable but END is not: finish the bookkeeping.
                if not self.audit.has("COMMIT", tx_id):
                    self._audit_commit(tx_id, self._user_of(entry))
                    report.audit_repaired.append(tx_id)
                self.log.append(END, tx_id=tx_id, prev_lsn=entry.last_lsn)
                del self.transactions[tx_id]
                report.winners.append(tx_id)
            else:
                if entry.status == "running":
                    abort = self.log.append(ABORT, tx_id=tx_id, prev_lsn=entry.last_lsn)
                    entry.status = "aborting"
                    entry.last_lsn = abort.lsn
                report.losers.append(tx_id)

    def _redo(self, report: RecoveryReport) -> None:
        dpt = self._recovery_dpt
        if not dpt:
            return
        report.redo_start = min(dpt.values())
        for record in self.log.scan(report.redo_start):
            if record.kind not in REDOABLE:
                continue
            report.redo_examined += 1
            page_id = record.page_id
            if page_id not in dpt:
                report.redo_skipped.append((record.lsn, "page not in DPT"))
                continue
            if record.lsn < dpt[page_id]:
                report.redo_skipped.append((record.lsn, "LSN < recLSN"))
                continue
            frame = self._fetch(page_id)
            if frame.page_lsn >= record.lsn:
                report.redo_skipped.append((record.lsn, "pageLSN >= LSN"))
                continue
            frame.value = record.after
            frame.page_lsn = record.lsn
            if not frame.dirty:
                frame.dirty = True
                frame.rec_lsn = dpt[page_id]
            report.redo_applied.append(record.lsn)

    def _undo(self, report: RecoveryReport, undo_limit: int | None) -> None:
        heap = [-entry.last_lsn for entry in self.transactions.values()]
        heapq.heapify(heap)
        while heap:
            if undo_limit is not None and len(report.clrs_written) >= undo_limit:
                return  # incomplete: the caller will crash again
            record = self.log.get(-heapq.heappop(heap))
            entry = self.transactions[record.tx_id]
            report.undo_visited.append(record.lsn)
            next_lsn, clr = self._undo_step(record, entry)
            if clr is not None:
                report.clrs_written.append(clr.lsn)
            if next_lsn is None:
                self._finish_abort(entry, actor="recovery")
            else:
                heapq.heappush(heap, -next_lsn)
        report.complete = True


def print_log(db: MiniARIES, *, title: str = "Log") -> None:
    print(f"{title} (stable through LSN {db.log.flushed_lsn}):")
    for record in db.log.records:
        mark = " " if record.lsn <= db.log.flushed_lsn else "*"
        print(f"  {mark}{record.describe()}")
    if db.log.last_lsn > db.log.flushed_lsn:
        print("  (* = still in the volatile log tail)")


def print_report(report: RecoveryReport) -> None:
    print(f"  Analysis from LSN {report.analysis_start} "
          f"(master record = {report.checkpoint_lsn}), {report.analysis_scanned} records scanned")
    print(f"    ATT after scan: {report.att or '{}'}   DPT: {report.dpt or '{}'}")
    print(f"    winners: {report.winners or '-'}   losers: {report.losers or '-'}"
          + (f"   audit repaired for: {report.audit_repaired}" if report.audit_repaired else ""))
    print(f"  Redo from LSN {report.redo_start}: {report.redo_examined} examined, "
          f"applied {report.redo_applied or '-'}")
    for lsn, reason in report.redo_skipped:
        print(f"    skip LSN {lsn}: {reason}")
    print(f"  Undo visited {report.undo_visited or '-'}, wrote CLRs {report.clrs_written or '-'}"
          + ("" if report.complete else "   ** stopped early (recovery incomplete) **"))


def main() -> None:
    """A short end-to-end trace: one winner, one loser whose page was stolen."""
    db = MiniARIES()
    t1 = db.begin("alice")
    t2 = db.begin("bob")
    db.write(t1, "A", 80)
    db.write(t2, "B", 250)
    db.flush_page("B")  # steal: bob's uncommitted value reaches disk (log forced first)
    db.write(t1, "C", 320)
    db.commit(t1)  # no-force: A and C stay only in the buffer pool
    print("Before the crash")
    print(f"  buffer view: {db.current_values()}   disk: {db.disk_values()}")
    print_log(db)
    lost = db.crash()
    print(f"\nCRASH: lost {lost['lost_dirty_pages']} dirty pages and "
          f"{lost['lost_log_records']} unflushed log records")
    print(f"  disk after crash: {db.disk_values()}")
    print("\nRestart recovery")
    print_report(db.recover())
    print(f"\nAfter recovery: {db.current_values()}  (A, C redone; B undone)")
    print_log(db, title="Log after recovery")
    print(f"Audit trail intact: {db.audit.verify() is None}, {len(db.audit.entries)} entries")


if __name__ == "__main__":
    main()
