"""Public behavioral contract for Practice 7; unfinished starter methods should fail."""

import unittest

from student import SnapshotStore, WriteConflict


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = SnapshotStore({"A": 100, "B": 50})

    def test_initial_snapshot_and_read_your_write(self):
        tx = self.store.begin("writer")
        self.assertEqual(self.store.read(tx, "A"), 100)
        self.store.write(tx, "A", 90)
        self.assertEqual(self.store.read(tx, "A"), 90)

    def test_no_dirty_or_future_version_reads(self):
        writer = self.store.begin("writer")
        reader = self.store.begin("reader")
        self.store.write(writer, "A", 80)
        self.assertEqual(self.store.read(reader, "A"), 100)
        self.store.commit(writer)
        self.assertEqual(self.store.read(reader, "A"), 100)
        newer = self.store.begin("reader")
        self.assertEqual(self.store.read(newer, "A"), 80)

    def test_rollback_and_read_only_commit(self):
        tx = self.store.begin("writer")
        self.store.write(tx, "A", 75)
        self.store.rollback(tx)
        check = self.store.begin("reader")
        self.assertEqual(self.store.read(check, "A"), 100)
        sequence = self.store.commit(check)
        self.assertEqual(sequence, 0)

    def test_tombstone_is_private_until_commit_and_old_snapshot_keeps_value(self):
        deleter = self.store.begin("admin")
        older = self.store.begin("reader")
        self.store.delete(deleter, "A")
        self.assertIsNone(self.store.read(deleter, "A"))
        self.assertEqual(self.store.read(older, "A"), 100)
        self.store.commit(deleter)
        self.assertEqual(self.store.read(older, "A"), 100)
        newer = self.store.begin("reader")
        self.assertIsNone(self.store.read(newer, "A"))

    def test_unknown_role_and_forbidden_operations(self):
        with self.assertRaises(PermissionError):
            self.store.begin("guest")
        reader = self.store.begin("reader")
        with self.assertRaises(PermissionError):
            self.store.write(reader, "A", 1)
        self.assertEqual(self.store.read(reader, "A"), 100)
        writer = self.store.begin("writer")
        with self.assertRaises(PermissionError):
            self.store.delete(writer, "A")
        self.assertEqual(self.store.read(writer, "A"), 100)

    def test_invalid_key_value_and_inactive_transaction(self):
        with self.assertRaises(ValueError):
            SnapshotStore({"": 1})
        with self.assertRaises(ValueError):
            SnapshotStore({"A": True})
        tx = self.store.begin("writer")
        with self.assertRaises(ValueError):
            self.store.write(tx, "", 1)
        with self.assertRaises(ValueError):
            self.store.write(tx, "A", True)
        with self.assertRaises(RuntimeError):
            self.store.read(999, "A")
        self.store.commit(tx)
        with self.assertRaises(RuntimeError):
            self.store.rollback(tx)

    def test_stale_writer_conflicts_and_aborts(self):
        first = self.store.begin("writer")
        stale = self.store.begin("writer")
        self.store.write(first, "A", 90)
        self.store.write(stale, "A", 80)
        self.store.commit(first)
        with self.assertRaises(WriteConflict):
            self.store.commit(stale)
        with self.assertRaises(RuntimeError):
            self.store.read(stale, "A")

    def test_two_concurrent_creations_conflict(self):
        first = self.store.begin("writer")
        second = self.store.begin("writer")
        self.store.write(first, "C", 1)
        self.store.write(second, "C", 2)
        self.store.commit(first)
        with self.assertRaises(WriteConflict):
            self.store.commit(second)

    def test_write_delete_conflict(self):
        writer = self.store.begin("writer")
        deleter = self.store.begin("admin")
        self.store.write(writer, "A", 90)
        self.store.delete(deleter, "A")
        self.store.commit(deleter)
        with self.assertRaises(WriteConflict):
            self.store.commit(writer)

    def test_conflict_on_one_key_prevents_a_two_key_partial_commit(self):
        multi = self.store.begin("writer")
        competing = self.store.begin("writer")
        self.store.write(multi, "A", 90)
        self.store.write(multi, "B", 40)
        self.store.write(competing, "A", 80)
        self.store.commit(competing)
        with self.assertRaises(WriteConflict):
            self.store.commit(multi)
        check = self.store.begin("reader")
        self.assertEqual(self.store.read(check, "A"), 80)
        self.assertEqual(self.store.read(check, "B"), 50)

    def test_transaction_and_commit_sequences_are_ordered(self):
        first = self.store.begin("writer")
        second = self.store.begin("writer")
        self.assertLess(first, second)
        self.store.write(first, "A", 90)
        self.assertEqual(self.store.commit(first), 1)
        self.assertEqual(self.store.commit(second), 1)

    def test_write_skew_can_pass_snapshot_isolation(self):
        store = SnapshotStore({"on_call_A": 1, "on_call_B": 1})
        first = store.begin("writer")
        second = store.begin("writer")
        self.assertEqual((store.read(first, "on_call_A"), store.read(first, "on_call_B")), (1, 1))
        self.assertEqual((store.read(second, "on_call_A"), store.read(second, "on_call_B")), (1, 1))
        store.write(first, "on_call_A", 0)
        store.write(second, "on_call_B", 0)
        store.commit(first)
        store.commit(second)
        check = store.begin("reader")
        self.assertEqual((store.read(check, "on_call_A"), store.read(check, "on_call_B")), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
