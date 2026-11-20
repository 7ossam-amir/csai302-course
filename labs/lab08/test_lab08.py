"""Offline checks for the Lab 8 ARIES model, crash scenarios, and checkpoint study."""

import unittest

from aries import ABORT, CLR, END, UPDATE, MiniARIES, SimulatedCrash
from checkpoint_analysis import POLICIES, run_workload


def kinds(db, tx_id):
    return [r.kind for r in db.log.records if r.tx_id == tx_id]


class WriteAheadLoggingTests(unittest.TestCase):
    def test_update_is_logged_before_the_page_changes(self):
        db = MiniARIES()
        tx = db.begin()
        lsn = db.write(tx, "A", 80)
        record = db.log.get(lsn)
        self.assertEqual((record.kind, record.before, record.after), (UPDATE, 100, 80))
        self.assertEqual(db.buffer["A"].page_lsn, lsn)
        self.assertEqual(db.dirty_page_table, {"A": lsn})

    def test_commit_forces_the_log_but_not_the_pages(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 80)
        commit_lsn = db.commit(tx)
        self.assertGreaterEqual(db.log.flushed_lsn, commit_lsn)
        self.assertEqual(db.disk["A"].value, 100)  # no-force

    def test_page_flush_forces_log_through_page_lsn(self):
        db = MiniARIES()
        tx = db.begin()
        lsn = db.write(tx, "A", 80)
        self.assertEqual(db.log.flushed_lsn, 0)
        db.flush_page("A")  # steal
        self.assertGreaterEqual(db.log.flushed_lsn, lsn)
        self.assertEqual(db.disk["A"].page_lsn, lsn)
        self.assertEqual(db.dirty_page_table, {})

    def test_crash_loses_only_volatile_state(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 80)
        lost = db.crash()
        self.assertEqual(lost, {"lost_log_records": 2, "lost_dirty_pages": 1})
        self.assertEqual(db.log.records, [])
        with self.assertRaises(RuntimeError):
            db.begin()


class RecoveryTests(unittest.TestCase):
    def test_redo_restores_committed_unflushed_changes(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 80)
        db.commit(tx)
        db.crash()
        report = db.recover()
        self.assertEqual(db.current_values()["A"], 80)
        self.assertEqual(report.winners, [tx])
        self.assertEqual(report.redo_applied, [2])

    def test_undo_removes_stolen_uncommitted_change(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 0)
        db.flush_page("A")
        db.crash()
        report = db.recover()
        self.assertEqual(db.current_values()["A"], 100)
        self.assertEqual(report.losers, [tx])
        self.assertEqual(kinds(db, tx)[-3:], [ABORT, CLR, END])

    def test_redo_skips_pages_that_already_hold_the_change(self):
        db = MiniARIES()
        tx = db.begin()
        lsn = db.write(tx, "A", 80)
        db.commit(tx)
        db.flush_page("A")
        db.crash()
        report = db.recover()
        self.assertIn((lsn, "pageLSN >= LSN"), report.redo_skipped)

    def test_losers_undone_in_reverse_lsn_order_across_transactions(self):
        db = MiniARIES()
        t1, t2 = db.begin(), db.begin()
        db.write(t1, "A", 1)
        db.write(t2, "B", 2)
        db.write(t1, "C", 3)
        db.log.flush()
        db.crash()
        report = db.recover()
        updates = [l for l in report.undo_visited if db.log.get(l).kind == UPDATE]
        self.assertEqual(updates, sorted(updates, reverse=True))
        self.assertEqual(db.current_values(), {"A": 100, "B": 200, "C": 300})

    def test_crash_during_abort_does_not_undo_twice(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 1)
        db.write(tx, "B", 2)
        db.abort(tx, max_clrs=1)
        db.log.flush()
        db.crash()
        report = db.recover()
        self.assertEqual(len(report.clrs_written), 1)  # only A was left to undo
        self.assertEqual(db.current_values(), {"A": 100, "B": 200, "C": 300})
        self.assertEqual(sum(r.kind == CLR for r in db.log.records), 2)

    def test_crash_during_recovery_then_restart_again(self):
        db = MiniARIES()
        tx = db.begin()
        for page, value in (("A", 1), ("B", 2), ("C", 3)):
            db.write(tx, page, value)
        db.flush_all_pages()
        db.crash()
        first = db.recover(undo_limit=1)
        self.assertFalse(first.complete)
        self.assertTrue(db.crashed)
        db.log.flush()
        db.crash()
        second = db.recover()
        self.assertTrue(second.complete)
        self.assertEqual(db.current_values(), {"A": 100, "B": 200, "C": 300})
        self.assertEqual(sum(r.kind == CLR for r in db.log.records), 3)
        self.assertEqual(sum(r.kind == ABORT for r in db.log.records), 1)

    def test_recovering_twice_in_a_row_changes_nothing(self):
        db = MiniARIES()
        t1, t2 = db.begin(), db.begin()
        db.write(t1, "A", 80)
        db.write(t2, "B", 250)
        db.commit(t1)
        db.flush_page("B")
        db.crash()
        db.recover()
        after_first = db.current_values()
        db.flush_all_pages()
        db.crash()
        report = db.recover()
        self.assertEqual(db.current_values(), after_first)
        self.assertEqual((report.losers, report.redo_applied), ([], []))

    def test_new_transaction_ids_continue_after_recovery(self):
        db = MiniARIES()
        db.commit(db.begin())
        db.crash()
        db.recover()
        self.assertEqual(db.begin(), 2)

    def test_wal_violation_breaks_atomicity(self):
        db = MiniARIES(enforce_wal=False)
        tx = db.begin()
        db.write(tx, "A", 999)
        db.flush_page("A")
        db.crash()
        db.recover()
        self.assertEqual(db.current_values()["A"], 999)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_records_tables_and_sets_master_record(self):
        db = MiniARIES()
        tx = db.begin()
        lsn = db.write(tx, "A", 80)
        begin = db.checkpoint()
        end = db.log.get(begin + 1)
        self.assertEqual(db.master_lsn, begin)
        self.assertEqual(end.att, ((tx, "running", lsn),))
        self.assertEqual(end.dpt, (("A", lsn),))
        self.assertGreaterEqual(db.log.flushed_lsn, end.lsn)

    def test_analysis_starts_at_checkpoint_but_redo_uses_oldest_rec_lsn(self):
        db = MiniARIES()
        t1 = db.begin()
        old = db.write(t1, "A", 80)
        db.commit(t1)
        begin = db.checkpoint()
        t2 = db.begin()
        db.write(t2, "B", 250)
        db.commit(t2)
        db.crash()
        report = db.recover()
        self.assertEqual(report.analysis_start, begin)
        self.assertEqual(report.redo_start, old)
        self.assertEqual(db.current_values(), {"A": 80, "B": 250, "C": 300})

    def test_sharp_checkpoint_removes_redo_work(self):
        db = MiniARIES()
        tx = db.begin()
        db.write(tx, "A", 80)
        db.commit(tx)
        db.checkpoint(flush_dirty=True)
        db.crash()
        report = db.recover()
        self.assertIsNone(report.redo_start)

    def test_long_running_transaction_pins_truncation_point(self):
        db = MiniARIES()
        old = db.begin()
        db.write(old, "A", 1)
        db.flush_all_pages()
        for _ in range(3):
            tx = db.begin()
            db.write(tx, "B", 5)
            db.commit(tx)
        db.checkpoint(flush_dirty=True)
        self.assertEqual(db.truncation_point(), 1)

    def test_every_checkpoint_policy_recovers_committed_work_only(self):
        results = [run_workload(every, flush_dirty=sharp) for every, sharp in POLICIES]
        self.assertTrue(all(result["correct"] for result in results))
        scanned = [result["analysis_scanned"] for result in results[:4]]
        self.assertEqual(scanned, sorted(scanned, reverse=True))


class AuditTests(unittest.TestCase):
    def test_commit_and_abort_are_audited_with_user(self):
        db = MiniARIES()
        t1 = db.begin("alice")
        db.write(t1, "A", 80)
        db.commit(t1)
        t2 = db.begin("bob")
        db.write(t2, "B", 1)
        db.abort(t2)
        events = [(e["event"], e["user"]) for e in db.audit.entries]
        self.assertEqual(events, [("UPDATE", "alice"), ("COMMIT", "alice"), ("ABORT", "bob")])

    def test_recovery_repairs_missing_audit_entry_once(self):
        db = MiniARIES()
        tx = db.begin("ivan")
        db.write(tx, "A", 42)
        db.crash_points.add("commit:after-log-flush")
        with self.assertRaises(SimulatedCrash):
            db.commit(tx)
        db.crash()
        report = db.recover()
        self.assertEqual(report.audit_repaired, [tx])
        db.crash()
        db.recover()
        self.assertEqual(sum(e["event"] == "COMMIT" for e in db.audit.entries), 1)

    def test_recovery_rollback_is_audited(self):
        db = MiniARIES()
        tx = db.begin("bob")
        db.write(tx, "A", 1)
        db.log.flush()
        db.crash()
        db.recover()
        last = db.audit.entries[-1]
        self.assertEqual((last["event"], last["user"], last["actor"]),
                         ("RECOVERY_ROLLBACK", "bob", "recovery"))

    def test_tampering_breaks_the_hash_chain(self):
        db = MiniARIES()
        for value in (1, 2, 3):
            tx = db.begin("alice")
            db.write(tx, "A", value)
            db.commit(tx)
        self.assertIsNone(db.audit.verify())
        db.audit.entries[2]["after"] = 99
        self.assertEqual(db.audit.verify(), 3)
        del db.audit.entries[2]
        self.assertEqual(db.audit.verify(), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
