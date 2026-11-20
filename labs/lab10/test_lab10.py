"""Offline checks for Lab 10: NoSQL models, the MQL document database, sharding, 2PC, and tenants.

The same MQL behaviour is checked against a real MongoDB by `mongo_demo.py --mode compare`.
"""

import unittest

from docdb import DocumentDB, DuplicateKeyError, ORDERS, PRODUCTS, WriteError, matches
from nosql_models import BitcaskKV, PropertyGraph, QueryError, WideColumnTable
from sharding import (ShardedCluster, SimulatedCrash, TenantSession, TransactionAborted, WriteConflict,
                      balances, build_demo_cluster, transfer)


def fresh_db() -> DocumentDB:
    db = DocumentDB()
    db["products"].insert_many([dict(p) for p in PRODUCTS])
    db["orders"].insert_many([dict(o) for o in ORDERS])
    return db


def ids(docs) -> list:
    return sorted(d["_id"] for d in docs)


class KeyValueTests(unittest.TestCase):
    def test_put_get_delete_ttl_and_compaction(self):
        kv = BitcaskKV()
        kv.put("a", 1)
        kv.put("a", 2)
        kv.put("s", "x", ttl=10)
        kv.put("gone", 0)
        kv.delete("gone")
        self.assertEqual((kv.get("a"), kv.get("s"), kv.get("gone")), (2, "x", None))
        kv.now = 10
        self.assertIsNone(kv.get("s"))
        self.assertEqual(kv.compact(), (5, 1))
        self.assertEqual(kv.get("a"), 2)

    def test_keydir_is_rebuilt_from_the_log(self):
        kv = BitcaskKV()
        for i in range(5):
            kv.put("k", i)
        kv.keydir = {}
        kv.rebuild_keydir()
        self.assertEqual(kv.get("k"), 4)


class WideColumnTests(unittest.TestCase):
    def setUp(self):
        self.t = WideColumnTable("chat", ["ts"])
        for ts in (5, 1, 3, 4, 2):
            self.t.insert({"chat": "c1", "ts": ts, "text": f"m{ts}"})
        self.t.insert({"chat": "c2", "ts": 1, "text": "other"})

    def test_rows_are_sorted_and_ranges_slice_one_partition(self):
        self.assertEqual([r["ts"] for r in self.t.select("c1")], [1, 2, 3, 4, 5])
        self.assertEqual([r["ts"] for r in self.t.select("c1", start=(2,), end=(4,))], [2, 3, 4])
        self.assertEqual([r["ts"] for r in self.t.select("c1", descending=True, limit=2)], [5, 4])

    def test_insert_is_an_upsert_and_queries_need_the_partition_key(self):
        self.t.insert({"chat": "c1", "ts": 3, "text": "edited"})
        self.assertEqual(len(self.t.select("c1")), 5)
        self.assertEqual(self.t.select("c1", start=(3,), end=(3,))[0]["text"], "edited")
        with self.assertRaises(QueryError):
            self.t.select_where(lambda r: r["text"] == "other")
        self.assertEqual(len(self.t.select_where(lambda r: r["text"] == "other", allow_filtering=True)), 1)


class GraphTests(unittest.TestCase):
    def test_traversals(self):
        g = PropertyGraph()
        for n in "abcde":
            g.add_node(n, "Person", city="Cairo" if n in "ace" else "Giza")
        for a, b in ("ab", "bc", "cd", "ae", "ec"):
            g.add_edge(a, "FOLLOWS", b)
        self.assertEqual(g.shortest_path("a", "d"), ["a", "b", "c", "d"])
        self.assertIsNone(g.shortest_path("d", "a"))
        self.assertEqual(g.friends_of_friends("a"), ["c"])
        self.assertEqual(g.match("Person", "FOLLOWS", "Person", lambda x, y: x["city"] == y["city"]),
                         [("a", "e"), ("e", "c")])
        with self.assertRaises(KeyError):
            g.add_edge("a", "FOLLOWS", "zz")


class QueryLanguageTests(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        self.p = self.db["products"]

    def test_comparison_logical_and_array_operators(self):
        cases = {
            '{"price": {"$lt": 100}}': ({"price": {"$lt": 100}}, ["p2", "p4"]),
            "array contains": ({"tags": "sale"}, ["p1", "p3"]),
            "dotted path": ({"specs.ram_gb": {"$gte": 16}}, ["p1"]),
            "$exists false": ({"specs": {"$exists": False}}, ["p2", "p4"]),
            "$or + $size": ({"$or": [{"stock": 0}, {"tags": {"$size": 0}}]}, ["p2", "p5"]),
            "$all": ({"tags": {"$all": ["work", "rgb"]}}, ["p4"]),
            "$nin": ({"category": {"$nin": ["computers"]}}, ["p2", "p4"]),
            "$not": ({"price": {"$not": {"$gt": 100}}}, ["p2", "p4"]),
            "null matches missing": ({"specs.cpu": None}, ["p2", "p3", "p4", "p5"]),
            "whole-array equality": ({"ratings": [3, 4]}, ["p2"]),
            "array index": ({"ratings.0": 5}, ["p1"]),
            "$nor": ({"$nor": [{"price": {"$gt": 300}}, {"stock": 0}]}, ["p3", "p4"]),
            "type bracketing": ({"price": {"$gt": "100"}}, []),
            "$regex with options": ({"name": {"$regex": "^m", "$options": "i"}}, ["p2", "p3"]),
        }
        for label, (query, expected) in cases.items():
            self.assertEqual(ids(self.p.find(query)), expected, label)

    def test_elem_match_needs_one_element_to_satisfy_everything(self):
        orders = self.db["orders"]
        self.assertEqual(ids(orders.find({"items": {"$elemMatch": {"sku": "p4", "qty": {"$gte": 1}}}})), ["o2", "o3"])
        self.assertEqual(ids(orders.find({"items": {"$elemMatch": {"sku": "p1", "qty": 2}}})), [])
        self.assertEqual(ids(orders.find({"items.sku": "p1", "items.qty": 2})), ["o1"])  # different elements

    def test_projection_sort_skip_limit(self):
        found = self.p.find({}, {"name": 1, "_id": 0}, sort=[("price", -1)], skip=1, limit=2)
        self.assertEqual(found, [{"name": "Tablet"}, {"name": "Monitor"}])
        self.assertNotIn("specs", self.p.find_one({"_id": "p1"}, {"specs": 0}))
        with self.assertRaises(ValueError):
            self.p.find({}, {"name": 1, "price": 0})

    def test_unknown_operators_are_errors(self):
        with self.assertRaises(ValueError):
            self.p.find({"price": {"$around": 5}})
        with self.assertRaises(ValueError):
            matches({}, {"$xor": []})


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.p = fresh_db()["products"]

    def test_update_operators(self):
        self.p.update_one({"_id": "p4"}, {"$inc": {"stock": -1}, "$push": {"ratings": 5}, "$addToSet": {"tags": "work"}})
        self.assertEqual(self.p.find_one({"_id": "p4"}, {"stock": 1, "ratings": 1, "tags": 1, "_id": 0}),
                         {"stock": 29, "ratings": [4, 5], "tags": ["work", "rgb"]})
        self.p.update_one({"_id": "p1"}, {"$pull": {"ratings": {"$lt": 5}}, "$unset": {"specs.cpu": ""}})
        self.assertEqual(self.p.find_one({"_id": "p1"}, {"ratings": 1, "specs": 1, "_id": 0}),
                         {"ratings": [5, 5], "specs": {"ram_gb": 16}})
        self.p.update_one({"_id": "p3"}, {"$max": {"price": 250}, "$min": {"stock": 5}})
        self.assertEqual(self.p.find_one({"_id": "p3"}, {"price": 1, "stock": 1, "_id": 0}), {"price": 250, "stock": 5})
        self.assertEqual(self.p.update_many({"stock": 0}, {"$set": {"status": "out"}})["modified"], 1)

    def test_upsert_and_replace(self):
        result = self.p.update_one({"_id": "p9", "category": "cams"}, {"$set": {"price": 60}}, upsert=True)
        self.assertEqual(result["upserted_id"], "p9")
        self.assertEqual(self.p.find_one({"_id": "p9"}), {"_id": "p9", "category": "cams", "price": 60})
        self.p.replace_one({"_id": "p9"}, {"name": "Webcam"})
        self.assertEqual(self.p.find_one({"_id": "p9"}), {"_id": "p9", "name": "Webcam"})

    def test_invalid_updates_change_nothing(self):
        before = self.p.find(sort=[("_id", 1)])
        for update in ({"$max": {"price": 1}, "$mul": {"price": 2}}, {"$set": {"specs": {}, "specs.cpu": "x"}},
                       {"$set": {"_id": "z"}}, {"$inc": {"name": 1}}, {"$rename": {"a": "b"}}, {}):
            with self.assertRaises(WriteError, msg=str(update)):
                self.p.update_many({}, update)
        self.assertEqual(self.p.find(sort=[("_id", 1)]), before)

    def test_documents_are_copied_and_field_names_checked(self):
        doc = {"_id": "z", "nested": {"a": 1}}
        self.p.insert_one(doc)
        doc["nested"]["a"] = 99
        self.assertEqual(self.p.find_one({"_id": "z"})["nested"]["a"], 1)
        for bad in ({"$bad": 1}, {"a.b": 1}):
            with self.assertRaises(WriteError):
                self.p.insert_one(bad)
        with self.assertRaises(DuplicateKeyError):
            self.p.insert_one({"_id": "z"})


class IndexTests(unittest.TestCase):
    def test_index_is_used_and_kept_in_sync(self):
        c = DocumentDB()["items"]
        c.insert_many([{"_id": i, "color": ["red", "blue", "green"][i % 3], "tags": [f"t{i % 5}"]} for i in range(300)])
        self.assertEqual(c.explain({"color": "red"})["plan"], "COLLSCAN")
        c.create_index("color")
        c.create_index("tags")
        plan = c.explain({"color": "red"})
        self.assertEqual((plan["plan"], plan["docsExamined"], plan["nReturned"]), ("IXSCAN color", 100, 100))
        self.assertEqual(c.explain({"tags": "t1"})["docsExamined"], 60)  # multikey
        c.update_many({"color": "red"}, {"$set": {"color": "pink"}})
        self.assertEqual(c.count_documents({"color": "red"}), 0)
        self.assertEqual(c.explain({"color": "pink"})["nReturned"], 100)
        c.delete_many({"color": "pink"})
        self.assertEqual(c.explain({"color": {"$in": ["pink", "blue"]}})["nReturned"], 100)

    def test_unique_index(self):
        c = DocumentDB()["users"]
        c.create_index("email", unique=True)
        c.insert_one({"_id": 1, "email": "a@x"})
        with self.assertRaises(DuplicateKeyError):
            c.insert_one({"_id": 2, "email": "a@x"})
        c.insert_one({"_id": 3, "email": "b@x"})
        with self.assertRaises(DuplicateKeyError):
            c.update_one({"_id": 3}, {"$set": {"email": "a@x"}})
        self.assertEqual(c.find_one({"_id": 3})["email"], "b@x")


class AggregationTests(unittest.TestCase):
    def test_pipelines(self):
        db = fresh_db()
        units = db["orders"].aggregate([
            {"$match": {"status": "paid"}}, {"$unwind": "$items"},
            {"$group": {"_id": "$items.sku", "units": {"$sum": "$items.qty"}}}, {"$sort": {"units": -1, "_id": 1}}])
        self.assertEqual(units, [{"_id": "p2", "units": 2}, {"_id": "p1", "units": 1}, {"_id": "p4", "units": 1}])
        joined = db["orders"].aggregate([{"$match": {"_id": "o2"}},
                                         {"$lookup": {"from": "products", "localField": "items.sku",
                                                      "foreignField": "_id", "as": "products"}},
                                         {"$project": {"names": "$products.name"}}])
        self.assertEqual(joined, [{"_id": "o2", "names": ["Keyboard"]}])
        stats = db["products"].aggregate([{"$group": {"_id": None, "max": {"$max": "$price"}, "avg": {"$avg": "$price"},
                                                      "cats": {"$addToSet": "$category"}}}])
        self.assertEqual((stats[0]["max"], stats[0]["avg"], sorted(stats[0]["cats"])),
                         (950, 310, ["accessories", "computers"]))
        self.assertEqual(db["orders"].aggregate([{"$match": {"customer": "sara"}}, {"$count": "n"}]), [{"n": 2}])


class ShardingTests(unittest.TestCase):
    def setUp(self):
        self.cluster = build_demo_cluster()

    def test_routing_targets_one_shard_or_scatters(self):
        self.assertEqual(self.cluster.find("accounts", {"owner": "nadia"})[0]["balance"], 50)
        self.assertEqual(self.cluster.last_route["shards"], ["shard-b"])
        self.cluster.find("accounts", {"owner": {"$in": ["alice", "omar"]}})
        self.assertEqual(self.cluster.last_route["shards"], ["shard-a", "shard-b"])
        top = self.cluster.find("accounts", sort=[("balance", -1)], skip=1, limit=2)
        self.assertEqual([d["_id"] for d in top], ["nadia", "bob"])
        self.assertFalse(self.cluster.last_route["targeted"])

    def test_shard_key_rules(self):
        with self.assertRaises(WriteError):
            self.cluster.insert_one("accounts", {"_id": "x", "balance": 1})
        with self.assertRaises(WriteError):
            self.cluster.update_many("accounts", {"owner": "bob"}, {"$set": {"owner": "zed"}})

    def test_non_transactional_update_can_stop_half_way(self):
        self.cluster.shards["shard-b"].up = False
        with self.assertRaises(ConnectionError):
            self.cluster.update_many("accounts", {}, {"$inc": {"balance": 1}})
        self.cluster.shards["shard-b"].up = True
        self.assertEqual(balances(self.cluster), {"alice": 101, "bob": 41, "nadia": 50, "omar": 10})


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.cluster = build_demo_cluster()

    def test_commit_and_abort_are_atomic(self):
        self.assertEqual(transfer(self.cluster, "alice", "nadia", 30), "COMMIT")
        self.assertEqual(balances(self.cluster), {"alice": 70, "bob": 40, "nadia": 80, "omar": 10})
        with self.assertRaises(TransactionAborted):
            transfer(self.cluster, "omar", "bob", 500)
        self.assertEqual(sum(balances(self.cluster).values()), 200)
        self.assertEqual({n: s.locks for n, s in self.cluster.shards.items()}, {"shard-a": {}, "shard-b": {}})

    def test_inserts_and_updates_in_one_transaction(self):
        with self.cluster.transaction() as tx:
            tx.insert_one("accounts", {"_id": "zoe", "owner": "zoe", "balance": 0})
            tx.update_one("accounts", {"owner": "zoe"}, {"$inc": {"balance": 5}})  # sees its own insert
            tx.update_one("accounts", {"owner": "alice"}, {"$inc": {"balance": -5}})
        self.assertEqual(balances(self.cluster)["zoe"], 5)
        self.assertEqual(balances(self.cluster)["alice"], 95)

    def test_in_doubt_documents_are_locked_and_invisible(self):
        self.cluster.crash_at = "after-prepare"
        with self.assertRaises(SimulatedCrash):
            transfer(self.cluster, "bob", "omar", 5)
        self.assertEqual(balances(self.cluster)["bob"], 40)
        with self.assertRaises(WriteConflict):
            self.cluster.update_many("accounts", {"owner": "bob"}, {"$set": {"x": 1}})
        with self.assertRaises(ConnectionError):
            self.cluster.resolve_in_doubt("shard-a")
        self.cluster.recover_coordinator()
        self.assertEqual(self.cluster.resolve_in_doubt("shard-a"), {"tx1": "ABORT"})
        self.assertEqual(self.cluster.resolve_in_doubt("shard-b"), {"tx1": "ABORT"})
        self.assertEqual(sum(balances(self.cluster).values()), 200)

    def test_commit_survives_coordinator_and_participant_crashes(self):
        self.cluster.crash_at = "after-first-commit"
        with self.assertRaises(SimulatedCrash):
            transfer(self.cluster, "bob", "omar", 5)
        self.assertEqual(sum(balances(self.cluster).values()), 195)
        self.cluster.shards["shard-b"].crash()
        self.assertEqual(self.cluster.shards["shard-b"].restart(), ["tx1"])  # rebuilds its lock
        self.assertEqual(self.cluster.shards["shard-b"].locks, {("accounts", "omar"): "tx1"})
        with self.assertRaises(ConnectionError):
            self.cluster.resolve_in_doubt("shard-b")  # the coordinator is still down: blocked
        self.assertEqual(self.cluster.recover_coordinator(), ["tx1"])  # resends COMMIT
        self.assertEqual(self.cluster.shards["shard-b"].in_doubt(), [])
        self.assertEqual(self.cluster.resolve_in_doubt("shard-b"), {})
        self.assertEqual(balances(self.cluster), {"alice": 100, "bob": 35, "nadia": 50, "omar": 15})

    def test_down_shard_votes_no(self):
        self.cluster.shards["shard-b"].up = False
        with self.assertRaises(TransactionAborted):
            transfer(self.cluster, "alice", "nadia", 1)
        self.cluster.shards["shard-b"].up = True
        self.assertEqual(balances(self.cluster)["alice"], 100)


class TenantTests(unittest.TestCase):
    def setUp(self):
        self.cluster = build_demo_cluster()
        self.acme = TenantSession(self.cluster, "acme")

    def test_queries_are_scoped_and_targeted(self):
        self.assertEqual(self.acme.count_documents("tickets"), 6)
        self.assertEqual(len(self.cluster.last_route["shards"]), 1)
        sneaky = self.acme.find("tickets", {"$or": [{"tenant_id": "globex"}, {"priority": "high"}]})
        self.assertEqual({d["tenant_id"] for d in sneaky}, {"acme"})
        self.assertEqual(self.acme.find("tickets", {"tenant_id": "globex"}), [])

    def test_writes_cannot_cross_tenants(self):
        with self.assertRaises(PermissionError):
            self.acme.insert_one("tickets", {"_id": "x", "tenant_id": "globex"})
        with self.assertRaises(PermissionError):
            self.acme.update_many("tickets", {}, {"$set": {"tenant_id": "globex"}})
        self.acme.insert_one("tickets", {"_id": "x", "title": "new"})
        self.assertEqual(self.cluster.find("tickets", {"_id": "x"})[0]["tenant_id"], "acme")
        result = self.acme.update_many("tickets", {}, {"$set": {"seen": True}})
        self.assertEqual(result["matched"], 7)
        self.assertEqual(self.cluster.count_documents("tickets", {"seen": True}), 7)
        with self.assertRaises(PermissionError):
            TenantSession(self.cluster, "")

    def test_aggregate_and_lookup_stay_inside_the_tenant(self):
        rows = self.acme.aggregate("tickets", [{"$lookup": {"from": "tickets", "localField": "owner",
                                                            "foreignField": "owner", "as": "same"}},
                                               {"$project": {"tenants": "$same.tenant_id"}}])
        self.assertTrue(all(set(r["tenants"]) == {"acme"} for r in rows))
        self.assertEqual(len(rows), 6)

    def test_tenant_transaction(self):
        with self.acme.transaction() as tx:
            tx.update_many("tickets", {"priority": "high"}, {"$set": {"priority": "urgent"}})
        self.assertEqual(self.cluster.count_documents("tickets", {"priority": "urgent"}), 3)
        self.assertEqual(self.cluster.count_documents("tickets", {"priority": "high"}), 4)  # other tenants untouched


if __name__ == "__main__":
    unittest.main(verbosity=2)
