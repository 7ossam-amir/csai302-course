"""Public behavioral contract for Practice 9; unfinished starter methods should fail."""

import unittest

import numpy as np

from student import ShardedVectorStore, TransactionAborted, Unavailable

NODES = ["n1", "n2", "n3", "n4", "n5"]
DIM = 8


def vectors(count, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(size=(count, DIM))


def exact_top(store_docs: dict, query, k):
    q = query / np.linalg.norm(query)
    scored = sorted(((-float(v @ q / np.linalg.norm(v)), d) for d, v in store_docs.items()))
    return [d for _, d in scored[:k]]


class PlacementTests(unittest.TestCase):
    def test_constructor_validation(self):
        for kwargs in ({"replication": 6}, {"replication": 2, "write_quorum": 3}, {"write_quorum": 0}):
            with self.assertRaises(ValueError):
                ShardedVectorStore(NODES, DIM, **kwargs)
        with self.assertRaises(ValueError):
            ShardedVectorStore(["a", "a", "b"], DIM, replication=2)
        with self.assertRaises(ValueError):
            ShardedVectorStore(NODES, 0)

    def test_placement_is_distinct_stable_and_independent_of_failures(self):
        store = ShardedVectorStore(NODES, DIM)
        again = ShardedVectorStore(NODES, DIM)
        for i in range(50):
            p = store.placement(f"doc{i}")
            self.assertEqual(len(p), 3)
            self.assertEqual(len(set(p)), 3)
            self.assertEqual(p, again.placement(f"doc{i}"))
        before = store.placement("doc7")
        store.fail(before[0])
        self.assertEqual(store.placement("doc7"), before)

    def test_documents_live_exactly_on_their_placement(self):
        store = ShardedVectorStore(NODES, DIM)
        for i, v in enumerate(vectors(40)):
            written = store.upsert(f"doc{i}", v, f"text {i}")
            self.assertEqual(sorted(written), sorted(store.placement(f"doc{i}")))
        for node, docs in store.copies().items():
            self.assertEqual(docs, sorted(d for d in (f"doc{i}" for i in range(40))
                                          if node in store.placement(d)))


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.store = ShardedVectorStore(NODES, DIM)

    def test_input_validation(self):
        for bad in (np.zeros(DIM), np.ones(DIM + 1), [float("nan")] * DIM):
            with self.assertRaises(ValueError):
                self.store.upsert("x", bad)
        with self.assertRaises(ValueError):
            self.store.upsert("", np.ones(DIM))
        with self.assertRaises(KeyError):
            self.store.fail("ghost")

    def test_write_with_one_replica_down_then_repair(self):
        self.store.upsert("doc", np.ones(DIM), "v1")
        down = self.store.placement("doc")[0]
        self.store.fail(down)
        written = self.store.upsert("doc", np.arange(1, DIM + 1), "v2")
        self.assertNotIn(down, written)
        self.assertEqual(len(written), 2)
        self.assertEqual(self.store.get("doc"), "v2")
        self.assertEqual(self.store.recover(down), 1)
        for other in self.store.placement("doc"):
            if other != down:
                self.store.fail(other)
        self.assertEqual(self.store.get("doc"), "v2")  # the repaired copy is the new version

    def test_anti_entropy_fixes_a_replica_that_came_back_early(self):
        store = ShardedVectorStore(NODES, DIM, write_quorum=1)
        a, b, c = store.placement("doc")
        store.upsert("doc", np.ones(DIM), "old")
        store.fail(a)
        store.fail(b)
        store.upsert("doc", -np.ones(DIM), "new")  # only c has it
        store.fail(c)
        store.recover(a)                               # a comes back while c is down: still old
        self.assertEqual(store.get("doc"), "old")
        self.assertEqual(store.recover(c), 1)          # c returns: a is repaired too
        store.fail(c)
        self.assertEqual(store.get("doc"), "new")

    def test_quorum_failure_writes_nothing(self):
        placement = self.store.placement("doc")
        self.store.fail(placement[0])
        self.store.fail(placement[1])
        with self.assertRaises(Unavailable):
            self.store.upsert("doc", np.ones(DIM), "never")
        self.store.recover(placement[0])
        self.assertIsNone(self.store.get("doc"))
        self.assertFalse(any("doc" in docs for docs in self.store.copies().values()))

    def test_batch_is_all_or_nothing_on_capacity(self):
        store = ShardedVectorStore(NODES, DIM, replication=2, write_quorum=1, capacity=3)
        batch = [(f"d{i}", v, "") for i, v in enumerate(vectors(12))]
        with self.assertRaises(TransactionAborted):
            store.upsert_many(batch)
        self.assertEqual(store.copies(), {n: [] for n in NODES})
        ok = store.upsert_many(batch[:2])
        self.assertEqual(set(ok), {"d0", "d1"})

    def test_batch_unavailable_and_duplicate_ids(self):
        with self.assertRaises(ValueError):
            self.store.upsert_many([("a", np.ones(DIM), ""), ("a", np.ones(DIM), "")])
        self.assertEqual(self.store.upsert_many([]), {})
        target = self.store.placement("b")
        self.store.fail(target[0])
        self.store.fail(target[1])
        with self.assertRaises(Unavailable):
            self.store.upsert_many([("a", np.ones(DIM), ""), ("b", np.ones(DIM), "")])
        self.assertEqual(sum(len(d) for d in self.store.copies().values()), 0)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.store = ShardedVectorStore(NODES, DIM)
        self.docs = {f"doc{i}": v for i, v in enumerate(vectors(60, seed=1))}
        for d, v in self.docs.items():
            self.store.upsert(d, v, d)
        self.queries = vectors(10, seed=2)

    def test_scatter_gather_equals_exact_search(self):
        for q in self.queries:
            answer = self.store.search(q, 5)
            self.assertTrue(answer["complete"])
            self.assertEqual([d for d, _ in answer["results"]], exact_top(self.docs, q, 5))
            self.assertEqual(answer["nodes_asked"], 5)
            self.assertEqual(answer["distances"], 60 * 3)  # every copy is compared once
            scores = [s for _, s in answer["results"]]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_one_node_down_is_still_complete(self):
        self.store.fail("n3")
        answer = self.store.search(self.queries[0], 5)
        self.assertTrue(answer["complete"])
        self.assertEqual(answer["nodes_asked"], 4)
        self.assertEqual([d for d, _ in answer["results"]], exact_top(self.docs, self.queries[0], 5))

    def test_all_replicas_down_is_incomplete(self):
        for n in self.store.placement("doc0"):
            self.store.fail(n)
        answer = self.store.search(self.docs["doc0"], 3)
        self.assertFalse(answer["complete"])
        self.assertNotIn("doc0", [d for d, _ in answer["results"]])
        with self.assertRaises(Unavailable):
            self.store.get("doc0")

    def test_updated_document_appears_once_with_its_new_vector(self):
        self.store.upsert("doc5", -self.docs["doc5"], "flipped")
        answer = self.store.search(-self.docs["doc5"], 60)
        ids = [d for d, _ in answer["results"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "doc5")
        self.assertAlmostEqual(answer["results"][0][1], 1.0, places=6)

    def test_bad_k(self):
        for k in (0, -1, 2.5, True):
            with self.assertRaises(ValueError):
                self.store.search(self.queries[0], k)


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.store = ShardedVectorStore(NODES, DIM, vnodes=64)
        for i, v in enumerate(vectors(300, seed=3)):
            self.store.upsert(f"doc{i}", v, str(i))

    def check_placement_invariant(self):
        for node, docs in self.store.copies().items():
            expected = sorted(f"doc{i}" for i in range(300) if node in self.store.placement(f"doc{i}"))
            self.assertEqual(docs, expected, node)

    def test_add_node_moves_a_fraction_and_restores_placement(self):
        moved = self.store.add_node("n6")
        self.assertGreater(moved, 0)
        self.assertLess(moved, 0.4 * 300 * 3)  # far from moving everything
        self.check_placement_invariant()
        self.assertTrue(self.store.search(vectors(1, seed=9)[0], 3)["complete"])
        with self.assertRaises(ValueError):
            self.store.add_node("n6")

    def test_remove_node_keeps_every_document(self):
        self.store.remove_node("n2")
        self.assertNotIn("n2", self.store.copies())
        self.check_placement_invariant()
        self.assertEqual(self.store.get("doc42"), "42")
        small = ShardedVectorStore(["a", "b", "c"], DIM)
        with self.assertRaises(ValueError):
            small.remove_node("a")

    def test_live_nodes_and_recover_counts(self):
        self.store.fail("n1")
        self.assertEqual(self.store.live_nodes(), ["n2", "n3", "n4", "n5"])
        self.assertEqual(self.store.recover("n1"), 0)  # nothing changed while it was down
        self.assertEqual(self.store.live_nodes(), NODES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
