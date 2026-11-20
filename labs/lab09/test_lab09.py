"""Offline checks for Lab 9: Raft, CAP behaviour, 2PC, partitioning, vector search, and RAG."""

import unittest

import numpy as np

from cap_demo import LWWStore, cp_partition_scenario
from partitioning import ConsistentHashRing, HashPartitioner, RangePartitioner, moved_fraction, skew, load
from raft import LEADER, Cluster
from rag import RAG, Chunk, HashingEmbedder, split_markdown
from two_phase_commit import Coordinator, Participant, SimulatedCrash, make_bank, total, transfer
from vector_search import HNSWIndex, IVFIndex, exact_knn, knn, make_dataset, recall_at_k


def elect(cluster: Cluster) -> str:
    assert cluster.run_until(lambda: len(cluster.leaders()) == 1)
    return cluster.leaders()[0]


def commit_write(cluster: Cluster, leader: str, key: str, value) -> int:
    index = cluster.write(leader, key, value)
    term = cluster.nodes[leader].current_term
    assert cluster.run_until(lambda: cluster.is_committed(leader, index, term))
    return index


class RaftTests(unittest.TestCase):
    def test_one_leader_is_elected_and_everyone_follows(self):
        cluster = Cluster(seed=1)
        leader = elect(cluster)
        cluster.run(200)
        term = cluster.nodes[leader].current_term
        self.assertTrue(all(n.current_term == term for n in cluster.nodes.values()))
        self.assertEqual([n for n, node in cluster.nodes.items() if node.state == LEADER], [leader])

    def test_election_safety_over_many_seeds_and_failures(self):
        for seed in range(30):
            cluster = Cluster(seed=seed)
            leader = elect(cluster)
            cluster.stop(leader)
            cluster.run(800)
            cluster.start(leader)
            cluster.partition(("A", "B"), ("C", "D", "E"))
            cluster.run(800)
            cluster.heal()
            cluster.run(800)
            self.assertTrue(cluster.election_safety(), f"seed {seed}: two leaders in one term")

    def test_committed_write_reaches_every_node(self):
        cluster = Cluster(seed=2)
        leader = elect(cluster)
        commit_write(cluster, leader, "x", 7)
        cluster.run(200)
        self.assertEqual({n.kv.get("x") for n in cluster.nodes.values()}, {7})

    def test_followers_reject_client_writes(self):
        cluster = Cluster(seed=3)
        leader = elect(cluster)
        follower = next(n for n in cluster.nodes if n != leader)
        self.assertIsNone(cluster.write(follower, "x", 1))

    def test_leader_failure_elects_a_new_leader_that_keeps_committed_data(self):
        cluster = Cluster(seed=4)
        leader = elect(cluster)
        commit_write(cluster, leader, "x", 1)
        cluster.stop(leader)
        self.assertTrue(cluster.run_until(lambda: any(l != leader for l in cluster.leaders())))
        new = next(l for l in cluster.leaders() if l != leader)
        node = cluster.nodes[new]
        self.assertIn(("set", "x", 1), [e.command for e in node.log])  # the entry survived the failover
        # ...but the new leader learns it is committed only after committing its own no-op
        self.assertTrue(cluster.run_until(lambda: node.commit_index == node.last_log_index))
        self.assertEqual(node.kv.get("x"), 1)
        self.assertGreater(node.current_term, cluster.nodes[leader].current_term)

    def test_minority_cannot_elect_or_commit(self):
        cluster = Cluster(seed=5)
        leader = elect(cluster)
        others = [n for n in cluster.nodes if n != leader]
        cluster.partition((leader, others[0]), tuple(others[1:]))
        index = cluster.write(leader, "x", "lost")
        term = cluster.nodes[leader].current_term
        cluster.run(1500)
        self.assertFalse(cluster.is_committed(leader, index, term))
        self.assertTrue(any(l in others[1:] for l in cluster.leaders()))
        with self.assertRaises(RuntimeError):
            cluster.read(leader, "x")

    def test_up_to_date_rule_blocks_a_stale_candidate(self):
        cluster = Cluster(seed=6)
        leader = elect(cluster)
        lagging = next(n for n in cluster.nodes if n != leader)
        cluster.stop(lagging)
        commit_write(cluster, leader, "x", 1)
        cluster.run(100)
        cluster.start(lagging)
        cluster.stop(leader)
        cluster.run(2000)
        winners = [n for n in cluster.leaders() if n not in (leader,)]
        self.assertTrue(winners)
        self.assertEqual(cluster.nodes[winners[0]].kv.get("x"), 1)


class CapTests(unittest.TestCase):
    def test_cp_refuses_minority_and_discards_its_uncommitted_write(self):
        result = cp_partition_scenario(verbose=False)
        self.assertFalse(result["minority_write_committed"])
        self.assertTrue(result["majority_write_committed"])
        self.assertTrue(str(result["linearizable_reads"][result["old_leader"]]).startswith("REFUSED"))
        self.assertEqual(set(result["after_heal_values"].values()), {"majority-write"})
        self.assertFalse(result["minority_entry_survived"])

    def test_ap_store_is_available_but_loses_a_write(self):
        store = LWWStore()
        store.write("A", "x", 0, timestamp=1)
        store.partition(("A", "B"), ("C", "D", "E"))
        store.write("A", "x", "left", timestamp=3)
        store.write("C", "x", "right", timestamp=2)
        self.assertNotEqual(store.read("A", "x"), store.read("C", "x"))
        store.heal()
        self.assertEqual({store.read(n, "x") for n in "ABCDE"}, {"left"})
        self.assertEqual([v.value for v in store.lost_writes()], ["right"])


class TwoPhaseCommitTests(unittest.TestCase):
    def test_commit_and_vote_no_are_atomic(self):
        coord, s1, s2 = make_bank()
        self.assertEqual(coord.run("T1", transfer(30)), "COMMIT")
        self.assertEqual((s1.data["alice"], s2.data["carol"]), (70, 80))
        self.assertEqual(coord.run("T2", transfer(500)), "ABORT")
        self.assertEqual((s1.data["alice"], s2.data["carol"]), (70, 80))
        self.assertEqual((s1.locks, s2.locks), ({}, {}))

    def test_down_participant_means_abort(self):
        coord, s1, s2 = make_bank()
        s2.crash()
        self.assertEqual(coord.run("T3", transfer(30)), "ABORT")
        self.assertEqual(s1.data["alice"], 100)
        self.assertEqual(s1.locks, {})

    def test_coordinator_crash_before_decision_blocks_then_presumes_abort(self):
        coord, s1, s2 = make_bank()
        coord.crash_at = "after-prepare"
        with self.assertRaises(SimulatedCrash):
            coord.run("T4", transfer(30))
        self.assertEqual(s1.in_doubt(), ["T4"])
        self.assertEqual(s1.prepare("T5", {"alice": -1}), "NO")  # the lock is still held
        with self.assertRaises(ConnectionError):
            s1.ask_coordinator(coord)
        coord.restart()
        self.assertEqual(s1.ask_coordinator(coord), {"T4": "ABORT"})
        self.assertEqual(s2.ask_coordinator(coord), {"T4": "ABORT"})
        self.assertEqual(total(s1, s2), 200)
        self.assertEqual((s1.locks, s2.locks), ({}, {}))

    def test_coordinator_crash_after_decision_finishes_commit(self):
        coord, s1, s2 = make_bank()
        coord.crash_at = "after-first-commit"
        with self.assertRaises(SimulatedCrash):
            coord.run("T6", transfer(30))
        self.assertEqual(total(s1, s2), 170)  # in flight
        self.assertEqual(coord.restart(), ["T6"])
        self.assertEqual(total(s1, s2), 200)
        self.assertIn(("END", "T6"), coord.log)

    def test_participant_restart_rebuilds_locks_and_learns_outcome(self):
        coord, s1, s2 = make_bank()
        coord.crash_at = "after-prepare"
        with self.assertRaises(SimulatedCrash):
            coord.run("T7", transfer(30))
        s2.crash()
        self.assertEqual(s2.restart(), ["T7"])
        self.assertEqual(s2.locks, {"carol": "T7"})
        coord.restart()
        self.assertEqual(s2.ask_coordinator(coord), {"T7": "ABORT"})
        self.assertEqual(s2.locks, {})

    def test_decisions_are_idempotent(self):
        coord, s1, s2 = make_bank()
        coord.run("T8", transfer(30))
        s2.commit("T8")
        self.assertEqual(s2.data["carol"], 80)
        self.assertEqual(sum(r == ("COMMIT", "T8") for r in s2.log), 1)


class PartitioningTests(unittest.TestCase):
    KEYS = list(range(20_000))

    def test_range_partitioning_and_range_queries(self):
        ranges = RangePartitioner([100, 200], ["a", "b", "c"])
        self.assertEqual([ranges.shard_for(k) for k in (0, 99, 100, 199, 200, 10**9)],
                         ["a", "a", "b", "b", "c", "c"])
        self.assertEqual(ranges.shards_for_range(150, 160), ["b"])
        self.assertEqual(ranges.shards_for_range(50, 250), ["a", "b", "c"])
        with self.assertRaises(ValueError):
            RangePartitioner([200, 100], ["a", "b", "c"])

    def test_mod_n_moves_most_keys_but_consistent_hashing_moves_few(self):
        mod = moved_fraction(self.KEYS, HashPartitioner(["a", "b", "c", "d"]), HashPartitioner(list("abcde")))
        before = ConsistentHashRing(list("abcd"), vnodes=100)
        after = ConsistentHashRing(list("abcd"), vnodes=100)
        after.add("e")
        ring = moved_fraction(self.KEYS, before, after)
        self.assertGreater(mod, 0.7)
        self.assertLess(ring, 0.3)
        moved_to = {after.shard_for(k) for k in self.KEYS if before.shard_for(k) != after.shard_for(k)}
        self.assertEqual(moved_to, {"e"})  # keys only move to the new node

    def test_removing_a_node_only_moves_its_keys(self):
        ring = ConsistentHashRing(list("abcd"), vnodes=50)
        owners = {k: ring.shard_for(k) for k in self.KEYS}
        ring.remove("b")
        for k in self.KEYS:
            if owners[k] != "b":
                self.assertEqual(ring.shard_for(k), owners[k])

    def test_vnodes_improve_balance_and_preference_lists_are_distinct(self):
        few = ConsistentHashRing(list("abcd"), vnodes=1)
        many = ConsistentHashRing(list("abcd"), vnodes=500)
        self.assertLess(skew(load(self.KEYS, many), list("abcd")), 1.15)
        self.assertGreaterEqual(skew(load(self.KEYS, few), list("abcd")), skew(load(self.KEYS, many), list("abcd")))
        for key in range(50):
            replicas = many.preference_list(key, 3)
            self.assertEqual(len(set(replicas)), 3)
            self.assertEqual(replicas[0], many.shard_for(key))


class VectorSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = make_dataset(800, 16, clusters=20, seed=1)
        cls.queries = make_dataset(30, 16, clusters=20, seed=2)
        cls.truth = [exact_knn(cls.data, q, 10) for q in cls.queries]

    def test_exact_knn_matches_full_sort(self):
        q = self.queries[0]
        expected = np.argsort(-(self.data @ q), kind="stable")[:10]
        self.assertEqual(exact_knn(self.data, q, 10).tolist(), expected.tolist())

    def test_metrics_disagree_on_unnormalized_vectors(self):
        docs = np.array([[1.0, 0.1], [10.0, 9.0], [0.2, 1.0]], dtype=np.float32)
        q = np.array([1.0, 0.0], dtype=np.float32)
        self.assertEqual(knn(docs, q, 1, "cosine")[0][0], 0)
        self.assertEqual(knn(docs, q, 1, "dot")[0][0], 1)
        with self.assertRaises(ValueError):
            knn(docs, q, 1, "manhattan")

    def test_hnsw_recall_rises_with_ef_and_beats_brute_force_on_distances(self):
        index = HNSWIndex(16, M=8, ef_construction=60, seed=0).build(self.data)
        recalls = []
        for ef in (10, 80):
            index.distance_count = 0
            recalls.append(np.mean([recall_at_k(index.search(q, 10, ef), t)
                                    for q, t in zip(self.queries, self.truth)]))
            per_query = index.distance_count / len(self.queries)
            self.assertLess(per_query, len(self.data))
        self.assertGreaterEqual(recalls[1], recalls[0])
        self.assertGreater(recalls[1], 0.9)

    def test_hnsw_layers_shrink_and_degree_is_bounded(self):
        index = HNSWIndex(16, M=6, seed=0).build(self.data)
        sizes = index.layer_sizes()
        self.assertEqual(sizes[0], len(self.data))
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertTrue(all(len(n) <= 12 for n in index.graph[0].values()))
        self.assertTrue(all(len(n) <= 6 for layer in index.graph[1:] for n in layer.values()))

    def test_ivf_nprobe_all_is_exact(self):
        ivf = IVFIndex(nlist=16).build(self.data)
        for q, t in zip(self.queries, self.truth):
            self.assertEqual(recall_at_k(ivf.search(q, 10, nprobe=16), t), 1.0)


class RagTests(unittest.TestCase):
    DOCS = {
        "raft": "Raft elects a leader with randomized election timeouts. A candidate needs votes from a "
                "majority of the cluster, and each node votes at most once per term.",
        "2pc": "Two phase commit asks every participant to prepare and vote. The coordinator forces the "
               "commit decision to its log before telling the participants the outcome.",
        "hnsw": "HNSW builds a layered graph of vectors. A search walks greedily down the layers and "
                "keeps a candidate list of size ef on the bottom layer.",
    }

    def setUp(self):
        self.chunks = [Chunk(i, name, name, text) for i, (name, text) in enumerate(self.DOCS.items())]

    def test_retrieval_finds_the_right_document_with_both_indexes(self):
        for index in ("exact", "hnsw"):
            rag = RAG(self.chunks, index=index, dim=256)
            self.assertEqual(rag.retrieve("how many votes does a raft candidate need", 1)[0][0].source, "raft")
            self.assertEqual(rag.retrieve("what does the coordinator force to its log", 1)[0][0].source, "2pc")

    def test_answer_is_grounded_and_cited(self):
        rag = RAG(self.chunks, index="exact", dim=256)
        result = rag.answer("What is the size of the candidate list in an HNSW search?", k=2, sentences=1)
        self.assertTrue(result.grounded)
        self.assertIn("ef", result.text)
        self.assertTrue(result.citations[0].endswith("hnsw / hnsw"))
        self.assertIn(result.text.split(" [")[0], " ".join(self.DOCS.values()))

    def test_unknown_question_is_refused(self):
        rag = RAG(self.chunks, index="exact", dim=256)
        result = rag.answer("best recipe for chocolate cake")
        self.assertFalse(result.grounded)
        self.assertEqual(result.citations, [])

    def test_prompt_contains_the_context_and_the_rules(self):
        rag = RAG(self.chunks, index="exact", dim=256)
        prompt = rag.build_prompt("q?", rag.retrieve("raft votes", 2))
        self.assertIn("ONLY", prompt)
        self.assertIn("[1] (raft / raft)", prompt)

    def test_markdown_splitting_drops_code_and_turns_tables_into_sentences(self):
        text = "# T\nIntro line with enough words to keep this chunk alive in the index today.\n" \
               "```python\nsecret_code()\n```\n| a | b |\n|---|---|\n| one | two |\n"
        pieces = split_markdown(text, "doc", max_words=50)
        body = " ".join(p[2] for p in pieces)
        self.assertNotIn("secret_code", body)
        self.assertIn("a: one; b: two.", body)

    def test_embedder_ignores_words_outside_the_vocabulary(self):
        embedder = HashingEmbedder(64).fit(["leader election term"])
        self.assertFalse(embedder.embed("chocolate cake").any())
        self.assertAlmostEqual(float(np.linalg.norm(embedder.embed("leader term"))), 1.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
