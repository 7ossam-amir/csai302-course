"""Public checks for worksheet.py (Part D of WORKSHEET.md). No server is needed."""
import unittest

from worksheet import failover_loss, redo_decision, undo_chain  # also puts labs/lab08 on sys.path

from aries import CKPT_BEGIN, UPDATE, MiniARIES


def worksheet_fixture():
    """The fixture of WORKSHEET.md, stopped just before the crash."""
    db = MiniARIES({"A": 100, "B": 200, "C": 300, "D": 400})
    t1, t2, t3 = db.begin("sara"), db.begin("omar"), db.begin("laila")
    db.write(t1, "A", 150)
    db.write(t2, "B", 250)
    db.write(t3, "C", 350)
    db.checkpoint()
    db.write(t2, "D", 450)
    db.commit(t2)
    db.flush_page("C")
    db.write(t1, "B", 260)
    db.write(t3, "D", 470)
    return db, (t1, t2, t3)


class RedoDecisionTests(unittest.TestCase):
    def test_each_rule(self):
        db, _ = worksheet_fixture()
        update = db.log.get(6)  # T3 writes C at LSN 6
        self.assertEqual(redo_decision(update, {"A": 4}, 0), "not in DPT")
        self.assertEqual(redo_decision(update, {"C": 7}, 0), "LSN < recLSN")
        self.assertEqual(redo_decision(update, {"C": 6}, 6), "pageLSN >= LSN")
        self.assertEqual(redo_decision(update, {"C": 6}, 5), "apply")

    def test_order_of_the_tests(self):
        db, _ = worksheet_fixture()
        update = db.log.get(6)
        self.assertEqual(redo_decision(update, {"C": 9}, 99), "LSN < recLSN")

    def test_matches_the_reference_redo_pass(self):
        db, _ = worksheet_fixture()
        db.crash()
        disk_lsn = {page: stored.page_lsn for page, stored in db.disk.items()}
        report = db.recover()
        expected = {lsn: "apply" for lsn in report.redo_applied}
        expected.update(report.redo_skipped)
        self.assertEqual(len(expected), report.redo_examined)
        for lsn, decision in expected.items():
            record = db.log.get(lsn)
            self.assertEqual(redo_decision(record, report.dpt, disk_lsn[record.page_id]), decision)

    def test_other_records_are_rejected(self):
        db, _ = worksheet_fixture()
        for lsn in (1, 7, 10):  # BEGIN, CKPT_BEGIN, COMMIT
            with self.assertRaises(ValueError):
                redo_decision(db.log.get(lsn), {"A": 1}, 0)


class UndoChainTests(unittest.TestCase):
    def test_running_transactions(self):
        db, (t1, t2, t3) = worksheet_fixture()
        self.assertEqual(undo_chain(db.log.records, t1), [12, 4])
        self.assertEqual(undo_chain(db.log.records, t3), [13, 6])

    def test_matches_the_reference_undo_pass(self):
        db, (t1, _, t3) = worksheet_fixture()
        db.crash()
        before = {t: undo_chain(db.log.records, t) for t in (t1, t3)}
        report = db.recover()
        updates = [lsn for lsn in report.undo_visited if db.log.get(lsn).kind == UPDATE]
        self.assertEqual(sorted(before[t1] + before[t3], reverse=True), updates)

    def test_clrs_are_jumped_over(self):
        db = MiniARIES()
        tx = db.begin()
        for page in "ABC":
            db.write(tx, page, 1)  # LSN 2, 3, 4
        db.abort(tx, max_clrs=1)    # ABORT 5, CLR 6 (undoes 4, undoNext 3)
        self.assertEqual(undo_chain(db.log.records, tx), [3, 2])
        done = MiniARIES()
        other = done.begin()
        done.write(other, "A", 5)
        done.abort(other)
        self.assertEqual(undo_chain(done.log.records, other), [])

    def test_works_on_a_slice_of_the_log(self):
        db, (t1, _, _) = worksheet_fixture()
        tail = [r for r in db.log.records if r.lsn >= 4 and r.kind != CKPT_BEGIN] + [db.log.get(1)]
        self.assertEqual(undo_chain(tail, t1), [12, 4])

    def test_committed_and_unknown_transactions(self):
        db, (_, t2, _) = worksheet_fixture()
        with self.assertRaises(ValueError):
            undo_chain(db.log.records, t2)
        with self.assertRaises(ValueError):
            undo_chain(db.log.records, 99)


class FailoverLossTests(unittest.TestCase):
    COMMITS = [(1, 10, 0.0), (2, 25, 4.0), (3, 40, 9.5), (4, 52, 12.0)]

    def test_async_standby_loses_the_tail(self):
        self.assertEqual(failover_loss(self.COMMITS, 30), ([3, 4], 8.0))
        self.assertEqual(failover_loss(self.COMMITS, 51), ([4], 2.5))

    def test_nothing_lost(self):
        self.assertEqual(failover_loss(self.COMMITS, 52), ([], 0.0))
        self.assertEqual(failover_loss([], 0), ([], 0.0))

    def test_standby_with_no_commits(self):
        self.assertEqual(failover_loss(self.COMMITS, 5), ([1, 2, 3, 4], 12.0))
        self.assertEqual(failover_loss([(7, 3, 2.0)], 0), ([7], 0.0))

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            failover_loss(self.COMMITS, -1)
        with self.assertRaises(ValueError):
            failover_loss([(1, 10, 0.0), (2, 10, 1.0)], 5)


if __name__ == "__main__":
    unittest.main()
