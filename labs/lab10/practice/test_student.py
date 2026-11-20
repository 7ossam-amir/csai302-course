"""Public behavioral contract for Practice 10; unfinished starter functions should fail.

Every Part A expectation below was checked against a real MongoDB 7.0 server.
"""

import copy
import unittest

from student import (QueryError, SimulatedCrash, TenantStore, TransactionAborted, WriteError, apply_update,
                     match)

DOCS = [
    {"_id": "p1", "name": "Laptop", "price": 950, "tags": ["sale", "work"], "specs": {"ram_gb": 16, "cpu": "i7"},
     "ratings": [5, 4, 5]},
    {"_id": "p2", "name": "Mouse", "price": 15, "stock": 0, "tags": ["work"], "ratings": [3, 4]},
    {"_id": "p3", "name": "Monitor", "price": 210, "stock": 12, "tags": ["sale"], "specs": {"size_in": 27},
     "ratings": []},
    {"_id": "p4", "name": "Keyboard", "price": 45, "stock": 30, "tags": ["work", "rgb"], "ratings": [4]},
    {"_id": "p5", "name": "Tablet", "price": 330, "stock": 7, "tags": [], "specs": {"ram_gb": 8}},
]
ORDER = {"_id": "o1", "items": [{"sku": "p1", "qty": 1}, {"sku": "p2", "qty": 2}]}


def hits(query):
    return [d["_id"] for d in DOCS if match(d, query)]


class MatchTests(unittest.TestCase):
    def test_comparisons_and_logic(self):
        self.assertEqual(hits({"price": {"$lt": 100}}), ["p2", "p4"])
        self.assertEqual(hits({"price": {"$gte": 210, "$lte": 330}}), ["p3", "p5"])
        self.assertEqual(hits({"price": {"$in": [15, 330]}, "stock": {"$gt": 0}}), ["p5"])
        self.assertEqual(hits({"$or": [{"stock": 0}, {"tags": {"$size": 0}}]}), ["p2", "p5"])
        self.assertEqual(hits({"$nor": [{"price": {"$gt": 300}}, {"stock": 0}]}), ["p3", "p4"])
        self.assertEqual(hits({"$and": [{"price": {"$gt": 10}}, {"price": {"$lt": 50}}]}), ["p2", "p4"])
        self.assertEqual(hits({"price": {"$not": {"$gt": 100}}}), ["p2", "p4"])

    def test_arrays_and_paths(self):
        self.assertEqual(hits({"tags": "sale"}), ["p1", "p3"])
        self.assertEqual(hits({"tags": {"$all": ["work", "rgb"]}}), ["p4"])
        self.assertEqual(hits({"ratings": [3, 4]}), ["p2"])
        self.assertEqual(hits({"ratings.0": 5}), ["p1"])
        self.assertEqual(hits({"ratings": {"$gt": 4}}), ["p1"])
        self.assertEqual(hits({"specs.ram_gb": {"$gte": 16}}), ["p1"])
        self.assertTrue(match(ORDER, {"items.sku": "p2"}))

    def test_null_missing_and_ne(self):
        self.assertEqual(hits({"specs.cpu": None}), ["p2", "p3", "p4", "p5"])
        self.assertEqual(hits({"stock": {"$exists": False}}), ["p1"])
        self.assertEqual(hits({"stock": {"$ne": 0}}), ["p1", "p3", "p4", "p5"])
        self.assertEqual(hits({"tags": {"$nin": ["work"]}}), ["p3", "p5"])

    def test_type_bracketing(self):
        self.assertEqual(hits({"price": {"$gt": "100"}}), [])
        self.assertEqual(hits({"name": {"$gt": "M"}}), ["p2", "p3", "p5"])
        self.assertFalse(match({"x": True}, {"x": 1}))
        self.assertFalse(match({"x": 1}, {"x": {"$gt": False}}))

    def test_elem_match_versus_separate_conditions(self):
        self.assertFalse(match(ORDER, {"items": {"$elemMatch": {"sku": "p1", "qty": 2}}}))
        self.assertTrue(match(ORDER, {"items.sku": "p1", "items.qty": 2}))
        self.assertTrue(match(ORDER, {"items": {"$elemMatch": {"sku": "p2", "qty": {"$gte": 2}}}}))
        self.assertEqual(hits({"ratings": {"$elemMatch": {"$gte": 5}}}), ["p1"])

    def test_invalid_queries(self):
        for query in ({"price": {"$around": 1}}, {"$xor": [{}]}, {"$or": []}, {"$and": {"a": 1}},
                      {"price": {"$in": 15}}):
            with self.assertRaises(QueryError, msg=str(query)):
                match(DOCS[0], query)


class UpdateTests(unittest.TestCase):
    def test_operators_return_a_new_document(self):
        doc = copy.deepcopy(DOCS[3])
        new = apply_update(doc, {"$inc": {"stock": -1}, "$push": {"ratings": 5}, "$addToSet": {"tags": "work"},
                                 "$set": {"specs.layout": "US"}})
        self.assertEqual(doc, DOCS[3])
        self.assertEqual((new["stock"], new["ratings"], new["tags"], new["specs"]),
                         (29, [4, 5], ["work", "rgb"], {"layout": "US"}))

    def test_pull_unset_each(self):
        new = apply_update(DOCS[0], {"$pull": {"ratings": {"$lt": 5}}, "$unset": {"specs.cpu": ""}})
        self.assertEqual((new["ratings"], new["specs"]), ([5, 5], {"ram_gb": 16}))
        new = apply_update(ORDER, {"$pull": {"items": {"sku": "p1"}}})
        self.assertEqual(new["items"], [{"sku": "p2", "qty": 2}])
        new = apply_update(DOCS[4], {"$addToSet": {"tags": {"$each": ["new", "new", "tablet"]}},
                                     "$inc": {"views": 1}})
        self.assertEqual((new["tags"], new["views"]), (["new", "tablet"], 1))

    def test_invalid_updates(self):
        for update in ({}, {"price": 1}, {"$rename": {"a": "b"}}, {"$set": {"specs": {}, "specs.cpu": "x"}},
                       {"$inc": {"price": 1}, "$set": {"price": 2}}, {"$set": {"_id": "z"}},
                       {"$inc": {"name": 1}}, {"$inc": {"price": "1"}}, {"$push": {"name": "x"}}):
            with self.assertRaises(WriteError, msg=str(update)):
                apply_update(DOCS[0], update)


def make_store():
    store = TenantStore(("s1", "s2"))
    store.place_tenant("acme", "s1")
    store.place_tenant("globex", "s2")
    store.place_tenant("initech", "s2")
    for tenant, credits in (("acme", 100), ("globex", 50), ("initech", 10)):
        store.insert(tenant, "wallet", {"_id": "wallet", "balance": credits})
        for i in range(3):
            store.insert(tenant, "tickets", {"_id": f"{tenant}-{i}", "priority": ["low", "high"][i % 2]})
    return store


def balances(store):
    return {t: store.find(t, "wallet")[0]["balance"] for t in ("acme", "globex", "initech")}


class PlacementTests(unittest.TestCase):
    def test_directory_routing_and_validation(self):
        store = make_store()
        store.find("globex", "tickets")
        self.assertEqual(store.last_shards, ["s2"])
        self.assertEqual(store.shard_of("acme"), "s1")
        with self.assertRaises(ValueError):
            store.place_tenant("acme", "s2")
        with self.assertRaises(KeyError):
            store.place_tenant("umbrella", "s9")
        with self.assertRaises(KeyError):
            store.shard_of("umbrella")
        with self.assertRaises(ValueError):
            TenantStore(("only",))

    def test_move_tenant(self):
        store = make_store()
        self.assertEqual(store.move_tenant("initech", "s1"), 4)
        self.assertEqual(store.shard_of("initech"), "s1")
        self.assertEqual(len(store.find("initech", "tickets")), 3)
        self.assertEqual(store.last_shards, ["s1"])
        self.assertEqual(store.move_tenant("initech", "s1"), 0)
        store.fail("s2")
        self.assertEqual(len(store.find("initech", "tickets")), 3)  # no longer depends on s2
        with self.assertRaises(ConnectionError):
            store.find("globex", "tickets")


class IsolationTests(unittest.TestCase):
    def test_reads_and_writes_stay_in_the_tenant(self):
        store = make_store()
        self.assertEqual(store.find("acme", "tickets", {"tenant_id": "globex"}), [])
        sneaky = store.find("acme", "tickets", {"$or": [{"tenant_id": "globex"}, {"priority": "high"}]})
        self.assertEqual([d["_id"] for d in sneaky], ["acme-1"])
        with self.assertRaises(PermissionError):
            store.insert("acme", "tickets", {"tenant_id": "globex", "x": 1})
        with self.assertRaises(PermissionError):
            store.update("acme", "tickets", {}, {"$set": {"tenant_id": "globex"}})
        self.assertEqual(store.update("acme", "tickets", {"priority": "low"}, {"$set": {"seen": True}}), 2)
        self.assertEqual(store.find("globex", "tickets", {"seen": True}), [])
        with self.assertRaises(WriteError):
            store.insert("acme", "tickets", {"_id": "acme-0"})

    def test_update_is_all_or_nothing(self):
        store = make_store()
        store.insert("acme", "tickets", {"_id": "odd", "priority": 7})
        with self.assertRaises(WriteError):
            store.update("acme", "tickets", {}, {"$push": {"priority": "x"}})  # fails on every document
        store.update("acme", "tickets", {}, {"$set": {"n": 1}})
        with self.assertRaises(WriteError):
            store.update("acme", "tickets", {}, {"$inc": {"priority": 1}})  # fails on the strings only
        self.assertEqual(store.find("acme", "tickets", {"_id": "odd"})[0]["priority"], 7)


class TransferTests(unittest.TestCase):
    def test_commit_abort_and_validation(self):
        store = make_store()
        self.assertEqual(store.transfer("acme", "globex", 30), "COMMIT")
        self.assertEqual(balances(store), {"acme": 70, "globex": 80, "initech": 10})
        self.assertEqual(store.transfer("initech", "acme", 500), "ABORT")
        self.assertEqual(store.transfer("acme", "nobody", 5), "ABORT")
        self.assertEqual(balances(store), {"acme": 70, "globex": 80, "initech": 10})
        for args in (("acme", "acme", 5), ("acme", "globex", 0), ("acme", "globex", -3)):
            with self.assertRaises(ValueError):
                store.transfer(*args)

    def test_in_doubt_transfer_locks_the_wallet(self):
        store = make_store()
        store.crash_at = "after-prepare"
        with self.assertRaises(SimulatedCrash):
            store.transfer("acme", "globex", 30)
        self.assertEqual(balances(store), {"acme": 100, "globex": 50, "initech": 10})
        self.assertEqual(len(store.in_doubt()), 1)
        with self.assertRaises(ConnectionError):
            store.transfer("initech", "acme", 1)  # the coordinator is down
        with self.assertRaises(TransactionAborted):
            store.move_tenant("acme", "s2")
        decisions = store.recover()
        self.assertEqual(list(decisions.values()), ["ABORT"])
        self.assertEqual(store.in_doubt(), [])
        self.assertEqual(store.transfer("initech", "acme", 1), "COMMIT")
        self.assertEqual(sum(balances(store).values()), 160)

    def test_crash_after_decision_with_a_shard_down(self):
        store = make_store()
        store.crash_at = "after-decision"
        with self.assertRaises(SimulatedCrash):
            store.transfer("acme", "globex", 30)
        store.fail("s2")
        self.assertEqual(balances_up(store), {"acme": 100})
        store.recover()                       # resolves s1 only: COMMIT
        self.assertEqual(balances_up(store), {"acme": 70})
        self.assertEqual(len(store.restart("s2")), 1)  # globex's transfer is still in doubt on s2
        with self.assertRaises(TransactionAborted):
            store.update("globex", "wallet", {}, {"$inc": {"balance": 1}})
        self.assertEqual(store.transfer("globex", "initech", 5), "ABORT")  # globex's wallet is locked
        store.recover()
        self.assertEqual(balances(store), {"acme": 70, "globex": 80, "initech": 10})
        self.assertEqual(store.in_doubt(), [])


def balances_up(store):
    out = {}
    for tenant in ("acme", "globex", "initech"):
        try:
            out[tenant] = store.find(tenant, "wallet")[0]["balance"]
        except ConnectionError:
            pass
    return out


if __name__ == "__main__":
    unittest.main(verbosity=2)
