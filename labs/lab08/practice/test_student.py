"""Public behavioral contract for Practice 8; unfinished starter methods should fail."""

import unittest

from student import RecoverableStore, SimulatedCrash

PAGES = {"P1": {"alice": 100, "bob": 50}, "P2": {"carol": 70, "dave": 30}}


def kinds(store, tx_id=None):
    return [r["kind"] for r in store.log_records() if tx_id is None or r["tx"] == tx_id]


def restart(store, **kwargs):
    store.crash()
    return store.recover(**kwargs)


class NormalOperationTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_reads_writes_and_log_records(self):
        tx = self.store.begin("alice")
        self.assertEqual(self.store.read(tx, "bob"), 50)
        lsn = self.store.write(tx, "bob", 60)
        record = self.store.log_records()[-1]
        self.assertEqual((record["lsn"], record["kind"], record["page"], record["key"]),
                         (lsn, "UPDATE", "P1", "bob"))
        self.assertEqual((record["before"], record["after"]), (50, 60))
        self.assertEqual(self.store.read(tx, "bob"), 60)

    def test_commit_is_durable_without_writing_pages(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "alice", 90)
        self.store.commit(tx)
        self.assertEqual(self.store.disk_snapshot()["alice"], 100)
        restart(self.store)
        self.assertEqual(self.store.snapshot()["alice"], 90)

    def test_abort_restores_values_and_writes_clrs(self):
        tx = self.store.begin("bob")
        self.store.write(tx, "alice", 1)
        self.store.write(tx, "carol", 2)
        self.store.abort(tx)
        self.assertEqual(self.store.snapshot(), {"alice": 100, "bob": 50, "carol": 70, "dave": 30})
        self.assertEqual(kinds(self.store, tx).count("CLR"), 2)
        self.assertEqual(kinds(self.store, tx)[-1], "END")

    def test_invalid_inputs_and_closed_transactions(self):
        with self.assertRaises(ValueError):
            self.store.begin("")
        tx = self.store.begin("alice")
        with self.assertRaises(KeyError):
            self.store.write(tx, "zoe", 1)
        with self.assertRaises(ValueError):
            self.store.write(tx, "alice", True)
        self.store.commit(tx)
        with self.assertRaises(RuntimeError):
            self.store.write(tx, "alice", 1)

    def test_operations_rejected_while_crashed(self):
        self.store.crash()
        with self.assertRaises(RuntimeError):
            self.store.begin("alice")
        self.store.recover()
        with self.assertRaises(RuntimeError):
            self.store.recover()


class WalAndPageTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_page_flush_obeys_wal_and_steal_is_undone(self):
        tx = self.store.begin("mallory")
        self.store.write(tx, "bob", 0)
        self.assertTrue(self.store.flush_page("P1"))
        self.assertEqual(self.store.disk_snapshot()["bob"], 0)
        restart(self.store)
        self.assertEqual(self.store.snapshot()["bob"], 50)

    def test_two_keys_on_one_page_redo_and_undo_independently(self):
        winner = self.store.begin("alice")
        loser = self.store.begin("bob")
        self.store.write(winner, "alice", 111)
        self.store.write(loser, "bob", 222)
        self.store.commit(winner)
        self.store.flush_page("P1")  # both changes share page P1 on disk
        result = restart(self.store)
        self.assertEqual(result["losers"], [loser])
        self.assertEqual(self.store.snapshot()["alice"], 111)
        self.assertEqual(self.store.snapshot()["bob"], 50)

    def test_unflushed_tail_disappears(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "dave", 99)
        result = restart(self.store)
        self.assertEqual(result["losers"], [])  # nothing of the transaction reached the log
        self.assertNotIn("UPDATE", kinds(self.store))
        self.assertEqual(self.store.snapshot()["dave"], 30)


class SavepointTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_partial_rollback_keeps_transaction_running(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "alice", 90)
        point = self.store.savepoint(tx)
        self.store.write(tx, "bob", 60)
        self.store.write(tx, "carol", 80)
        self.assertEqual(self.store.rollback_to(tx, point), 2)
        self.assertEqual(self.store.read(tx, "bob"), 50)
        self.store.write(tx, "dave", 40)
        self.store.commit(tx)
        restart(self.store)
        self.assertEqual(self.store.snapshot(), {"alice": 90, "bob": 50, "carol": 70, "dave": 40})

    def test_loser_with_partial_rollback_is_not_undone_twice(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "alice", 1)
        point = self.store.savepoint(tx)
        self.store.write(tx, "bob", 2)
        self.store.rollback_to(tx, point)
        self.store.flush_log()
        result = restart(self.store)
        self.assertEqual(len(result["clrs_written"]), 1)  # only alice's update is left
        self.assertEqual(self.store.snapshot()["alice"], 100)
        self.assertEqual(kinds(self.store, tx).count("CLR"), 2)

    def test_unknown_savepoint_is_rejected(self):
        first = self.store.begin("alice")
        second = self.store.begin("bob")
        self.store.write(first, "alice", 1)
        point = self.store.savepoint(first)
        with self.assertRaises(ValueError):
            self.store.rollback_to(second, point)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_crash_during_recovery_then_restart_again(self):
        tx = self.store.begin("erin")
        for key, value in (("alice", 1), ("bob", 2), ("carol", 3)):
            self.store.write(tx, key, value)
        self.store.flush_page("P1")
        self.store.flush_page("P2")
        first = restart(self.store, undo_limit=1)
        self.assertFalse(first["complete"])
        self.store.flush_log()
        second = restart(self.store)
        self.assertTrue(second["complete"])
        self.assertEqual(self.store.snapshot(), {"alice": 100, "bob": 50, "carol": 70, "dave": 30})
        self.assertEqual(kinds(self.store, tx).count("CLR"), 3)

    def test_recovering_a_recovered_system_does_no_work(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "alice", 5)
        self.store.commit(tx)
        restart(self.store)
        result = restart(self.store)
        self.assertEqual(result["losers"], [])
        self.assertEqual(self.store.snapshot()["alice"], 5)

    def test_transaction_ids_keep_increasing_after_restart(self):
        first = self.store.begin("alice")
        self.store.commit(first)
        restart(self.store)
        self.assertGreater(self.store.begin("bob"), first)


class CheckpointAndTruncationTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_truncation_keeps_lsns_stable_and_recovery_correct(self):
        for value in range(1, 6):
            tx = self.store.begin("alice")
            self.store.write(tx, "alice", value)
            self.store.commit(tx)
        self.store.flush_page("P1")
        active = self.store.begin("bob")
        self.store.write(active, "carol", 999)
        self.store.checkpoint()
        lsns_before = [r["lsn"] for r in self.store.log_records()]
        first_kept = self.store.truncate_log()
        lsns_after = [r["lsn"] for r in self.store.log_records()]
        self.assertGreater(first_kept, 1)
        self.assertEqual(lsns_after, [l for l in lsns_before if l >= first_kept])
        restart(self.store)
        self.assertEqual(self.store.snapshot()["alice"], 5)
        self.assertEqual(self.store.snapshot()["carol"], 70)

    def test_active_transaction_pins_truncation(self):
        old = self.store.begin("batch")
        begin_lsn = self.store.log_records()[-1]["lsn"]
        self.store.write(old, "dave", 1)
        for _ in range(3):
            tx = self.store.begin("alice")
            self.store.write(tx, "alice", 7)
            self.store.commit(tx)
        self.store.flush_page("P1")
        self.store.flush_page("P2")
        self.store.checkpoint()
        self.assertLessEqual(self.store.truncate_log(), begin_lsn)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoverableStore(PAGES)

    def test_audit_lists_only_effective_changes(self):
        tx = self.store.begin("alice")
        self.store.write(tx, "alice", 90)
        point = self.store.savepoint(tx)
        self.store.write(tx, "bob", 0)
        self.store.rollback_to(tx, point)
        self.store.commit(tx)
        events = [(e["event"], e.get("key")) for e in self.store.audit_entries()]
        self.assertEqual(events, [("UPDATE", "alice"), ("COMMIT", None)])

    def test_missing_audit_entry_is_repaired_once_after_crash(self):
        tx = self.store.begin("ivan")
        self.store.write(tx, "carol", 1)
        self.store.crash_points.add("commit:after-log-flush")
        with self.assertRaises(SimulatedCrash):
            self.store.commit(tx)
        self.assertEqual(self.store.audit_entries(), [])
        restart(self.store)
        restart(self.store)
        commits = [e for e in self.store.audit_entries() if e["event"] == "COMMIT"]
        self.assertEqual([(e["tx"], e["user"]) for e in commits], [(tx, "ivan")])
        self.assertEqual(self.store.snapshot()["carol"], 1)

    def test_recovery_rollback_is_audited_and_chain_verifies(self):
        tx = self.store.begin("bob")
        self.store.write(tx, "bob", 1)
        self.store.flush_log()
        restart(self.store)
        last = self.store.audit_entries()[-1]
        self.assertEqual((last["event"], last["tx"], last["user"]), ("RECOVERY_ROLLBACK", tx, "bob"))
        self.assertIsNone(self.store.verify_audit())

    def test_tampering_is_detected(self):
        for value in (1, 2):
            tx = self.store.begin("alice")
            self.store.write(tx, "alice", value)
            self.store.commit(tx)
        entries = self.store.audit_entries()
        entries[0]["after"] = 500
        self.assertEqual(self.store.verify_audit(entries), 1)
        self.assertIsNone(self.store.verify_audit())  # the store's own copy is unchanged


if __name__ == "__main__":
    unittest.main(verbosity=2)
