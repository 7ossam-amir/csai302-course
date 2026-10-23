"""Offline checks for Lab 7's visibility model and wait-for cycle detector."""

import unittest

from deadlock_demo import has_cycle
from mvcc import MiniMVCC


class MiniMVCCTests(unittest.TestCase):
    def test_initial_reads_use_sequence_zero(self):
        store = MiniMVCC()
        tx = store.begin()
        self.assertEqual(store.transactions[tx].snapshot_seq, 0)
        self.assertEqual(store.read(tx, "A"), 100)
        self.assertEqual(store.read(tx, "B"), 50)

    def test_snapshot_is_stable_across_another_commit(self):
        store = MiniMVCC()
        older = store.begin()
        writer = store.begin()
        store.write(writer, "A", 80)
        self.assertEqual(store.read(older, "A"), 100)
        self.assertEqual(store.commit(writer), 1)
        self.assertEqual(store.read(older, "A"), 100)
        newer = store.begin()
        self.assertEqual(store.read(newer, "A"), 80)

    def test_transaction_reads_its_own_pending_value(self):
        store = MiniMVCC()
        tx = store.begin()
        store.write(tx, "A", 75)
        self.assertEqual(store.read(tx, "A"), 75)
        self.assertEqual(store.versions["A"][-1].value, 100)

    def test_uncommitted_write_is_not_visible_to_another_transaction(self):
        store = MiniMVCC()
        writer = store.begin()
        reader = store.begin()
        store.write(writer, "A", 75)
        self.assertEqual(store.read(reader, "A"), 100)

    def test_rollback_discards_pending_value(self):
        store = MiniMVCC()
        writer = store.begin()
        store.write(writer, "A", 75)
        store.rollback(writer)
        self.assertEqual(store.versions["A"][-1].value, 100)
        with self.assertRaises(RuntimeError):
            store.read(writer, "A")

    def test_different_keys_commit_at_distinct_sequences(self):
        store = MiniMVCC()
        first = store.begin()
        second = store.begin()
        store.write(first, "A", 90)
        store.write(second, "B", 40)
        self.assertEqual(store.commit(first), 1)
        self.assertEqual(store.commit(second), 2)
        reader = store.begin()
        self.assertEqual((store.read(reader, "A"), store.read(reader, "B")), (90, 40))

    def test_unknown_and_closed_transactions_are_rejected(self):
        store = MiniMVCC()
        with self.assertRaises(RuntimeError):
            store.read(999, "A")
        tx = store.begin()
        store.commit(tx)
        with self.assertRaises(RuntimeError):
            store.write(tx, "A", 50)

    def test_reference_allows_a_stale_writer_to_overwrite_a_newer_value(self):
        store = MiniMVCC()
        first = store.begin()
        second = store.begin()
        store.write(first, "A", 90)
        store.write(second, "A", 80)
        store.commit(first)
        store.commit(second)
        reader = store.begin()
        self.assertEqual(store.read(reader, "A"), 80)


class WaitForGraphTests(unittest.TestCase):
    def test_acyclic_graph_is_not_a_deadlock(self):
        self.assertFalse(has_cycle({1: {2}, 2: {3}, 3: set()}))

    def test_two_and_three_node_cycles_are_detected(self):
        self.assertTrue(has_cycle({1: {2}, 2: {1}}))
        self.assertTrue(has_cycle({1: {2}, 2: {3}, 3: {1}}))

    def test_disconnected_graph_and_blocker_only_node(self):
        self.assertFalse(has_cycle({1: {8}, 4: {5}, 5: set()}))

    def test_self_cycle_is_detected(self):
        self.assertTrue(has_cycle({7: {7}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
