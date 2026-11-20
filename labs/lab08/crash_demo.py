"""Deterministic crash scenarios for the Lab 8 ARIES model.

Run one scenario or all of them:

    python labs/lab08/crash_demo.py --scenario all
"""

import argparse

from aries import MiniARIES, SimulatedCrash, print_log, print_report


def _heading(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _crash_and_recover(db: MiniARIES, **kwargs):
    lost = db.crash()
    print(f"CRASH -> lost {lost['lost_dirty_pages']} dirty page(s), "
          f"{lost['lost_log_records']} unflushed log record(s); disk = {db.disk_values()}")
    report = db.recover(**kwargs)
    print_report(report)
    return report


def scenario_redo() -> None:
    _heading("1. Committed but not on disk -> REDO (no-force)")
    db = MiniARIES()
    tx = db.begin("alice")
    db.write(tx, "A", 50)
    db.write(tx, "B", 250)
    db.commit(tx)
    print(f"T{tx} committed. Buffer {db.current_values()}, disk {db.disk_values()}")
    _crash_and_recover(db)
    print(f"Result: {db.current_values()}  -> the committed transfer survived")


def scenario_undo() -> None:
    _heading("2. Uncommitted page stolen to disk -> UNDO (steal)")
    db = MiniARIES()
    tx = db.begin("bob")
    db.write(tx, "A", 0)
    db.flush_page("A")
    print(f"T{tx} is still running, but its page A was written: disk {db.disk_values()}")
    print(f"WAL rule forced the log through LSN {db.log.flushed_lsn} before that page write")
    _crash_and_recover(db)
    print(f"Result: {db.current_values()}  -> the uncommitted write was rolled back")


def scenario_mixed() -> None:
    _heading("3. Winners and losers interleaved")
    db = MiniARIES({"A": 100, "B": 200, "C": 300, "D": 400})
    t1, t2, t3 = db.begin("alice"), db.begin("bob"), db.begin("carol")
    db.write(t1, "A", 110)
    db.write(t2, "B", 210)
    db.write(t3, "C", 310)
    db.write(t2, "D", 410)
    db.commit(t1)
    db.flush_page("D")
    db.write(t3, "A", 120)
    db.commit(t3)
    db.write(t2, "C", 999)  # never flushed: lost with the log tail
    print_log(db)
    _crash_and_recover(db)
    print(f"Result: {db.current_values()}  -> T1 and T3 kept, T2 removed")


def scenario_abort_crash() -> None:
    _heading("4. Crash in the middle of a rollback -> CLRs prevent double undo")
    db = MiniARIES()
    tx = db.begin("dave")
    db.write(tx, "A", 1)
    db.write(tx, "B", 2)
    db.write(tx, "C", 3)
    db.abort(tx, max_clrs=1)  # undoes C only, then "crashes"
    db.log.flush()  # the CLR reached stable storage before the failure
    print_log(db)
    report = _crash_and_recover(db)
    print(f"Undo resumed at the CLR's undoNext and wrote {len(report.clrs_written)} more CLR(s)")
    print(f"Result: {db.current_values()}")


def scenario_recovery_crash() -> None:
    _heading("5. Crash during recovery itself -> restart is idempotent")
    db = MiniARIES()
    tx = db.begin("erin")
    db.write(tx, "A", 11)
    db.write(tx, "B", 22)
    db.write(tx, "C", 33)
    db.flush_all_pages()
    print("First restart, stopped after one CLR:")
    _crash_and_recover(db, undo_limit=1)
    db.log.flush()  # some CLRs were made durable before the second failure
    print("Second restart:")
    _crash_and_recover(db)
    print(f"Result: {db.current_values()}")
    print_log(db, title="Final log")


def scenario_checkpoint() -> None:
    _heading("6. Fuzzy checkpoint: analysis starts at the master record")
    db = MiniARIES()
    t1 = db.begin("frank")
    db.write(t1, "A", 70)
    db.commit(t1)
    t2 = db.begin("grace")
    db.write(t2, "B", 260)
    db.checkpoint()  # A and B are dirty and t2 is active: both appear in the checkpoint
    db.write(t2, "C", 330)
    t3 = db.begin("heidi")
    db.write(t3, "A", 75)
    db.commit(t3)
    print_log(db)
    _crash_and_recover(db)
    print(f"Result: {db.current_values()}")
    print("Note: redo started before the checkpoint because page A's recLSN is older.")


def scenario_audit() -> None:
    _heading("7. Audit integration: crash between log force and audit write")
    db = MiniARIES()
    tx = db.begin("ivan")
    db.write(tx, "A", 42)
    db.crash_points.add("commit:after-log-flush")
    try:
        db.commit(tx)
    except SimulatedCrash as failure:
        print(f"SimulatedCrash at {failure}: COMMIT is durable, audit entry is not")
    print(f"Audit entries before restart: {len(db.audit.entries)}")
    report = _crash_and_recover(db)
    print(f"Recovery wrote the missing audit entries for {report.audit_repaired}")
    for entry in db.audit.entries:
        print(f"  #{entry['seq']} {entry['event']:<18} T{entry['tx_id']} user={entry['user']}"
              f" {entry.get('page', '')} hash={entry['hash'][:12]}...")
    print(f"Chain verifies: {db.audit.verify() is None}")
    db.audit.entries[0]["after"] = 4200  # tamper with history
    print(f"After editing entry #1, verify() reports first bad entry: #{db.audit.verify()}")


def scenario_wal_violation() -> None:
    _heading("8. Why the WAL rule matters: flush a page before its log record")
    for enforce in (True, False):
        db = MiniARIES(enforce_wal=enforce)
        tx = db.begin("mallory")
        db.write(tx, "A", 999)
        db.flush_page("A")
        db.crash()
        db.recover()
        print(f"  enforce_wal={enforce!s:<5} -> after recovery A = {db.current_values()['A']}"
              + ("   (correct)" if db.current_values()["A"] == 100
                 else "   (uncommitted value survived: atomicity broken)"))


SCENARIOS = {
    "redo": scenario_redo,
    "undo": scenario_undo,
    "mixed": scenario_mixed,
    "abort-crash": scenario_abort_crash,
    "recovery-crash": scenario_recovery_crash,
    "checkpoint": scenario_checkpoint,
    "audit": scenario_audit,
    "wal-violation": scenario_wal_violation,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    for name, run in SCENARIOS.items():
        if args.scenario in (name, "all"):
            run()


if __name__ == "__main__":
    main()
