"""Lab 10 on real MongoDB: two independent instances (shard-a, shard-b) from compose.lab10.yaml.

Modes (run from the repository root after `docker compose -f labs/lab10/compose.lab10.yaml up -d`):

    compare    run the same MQL queries, updates, and pipelines on docdb.py and on MongoDB
    local-tx   MongoDB's own multi-document transaction inside one replica set
    2pc        a transfer between accounts on the two instances with two-phase commit
    status     pending (prepared) documents and coordinator decisions on both instances
    recover    finish or roll back every in-doubt transfer (run after a --crash)
    tenants    tenant-scoped collection wrapper, index use, and a cross-tenant attempt
    reset      drop this lab's databases on both instances
    all        compare, local-tx, 2pc, tenants

`2pc --crash after-prepare` (or after-decision) stops the process at that point, leaving the
transaction in doubt in MongoDB itself; `status` shows it and `recover` resolves it.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from pymongo import MongoClient, ReturnDocument
    from pymongo.errors import PyMongoError
except ModuleNotFoundError:
    MongoClient = None

from docdb import ORDERS, PRODUCTS, DocumentDB

SHARDS = {"shard-a": os.getenv("LAB10_SHARD_A", "mongodb://localhost:27031/?directConnection=true"),
          "shard-b": os.getenv("LAB10_SHARD_B", "mongodb://localhost:27032/?directConnection=true")}
DB = "lab10"


def client(name: str):
    if MongoClient is None:
        raise RuntimeError("pymongo is missing: pip install -r labs/lab10/requirements.txt")
    c = MongoClient(SHARDS[name], serverSelectionTimeoutMS=3000)
    c.admin.command("ping")
    return c


# -------------------------------------------------------------------- compare
COMPARE_QUERIES = [
    {"price": {"$lt": 100}},
    {"tags": "sale"},
    {"specs.ram_gb": {"$gte": 16}},
    {"specs": {"$exists": False}},
    {"$or": [{"stock": 0}, {"tags": {"$size": 0}}]},
    {"ratings": {"$elemMatch": {"$gte": 5}}},
    {"name": {"$regex": "^m", "$options": "i"}},
    {"tags": {"$all": ["work", "rgb"]}},
    {"price": {"$in": [15, 330]}, "stock": {"$gt": 0}},
    {"price": {"$not": {"$gt": 100}}},
    {"category": {"$nin": ["computers"]}},
    {"specs.cpu": None},
    {"ratings": [3, 4]},
    {"ratings.0": 5},
    {"$nor": [{"price": {"$gt": 300}}, {"stock": 0}]},
    {"price": {"$gt": "100"}},
]
COMPARE_UPDATES = [
    ({"_id": "p4"}, {"$inc": {"stock": -1}, "$push": {"ratings": 5}, "$addToSet": {"tags": "work"}}),
    ({"stock": 0}, {"$set": {"status": "sold out", "specs.discontinued": True}}),
    ({"_id": "p1"}, {"$pull": {"ratings": {"$lt": 5}}, "$unset": {"specs.cpu": ""}}),
    ({"_id": "p3"}, {"$max": {"price": 250}, "$min": {"stock": 5}}),
    ({"_id": "p2"}, {"$mul": {"price": 2}, "$set": {"specs": {"wireless": True}}}),
    ({"_id": "p5"}, {"$push": {"tags": {"$each": ["new", "tablet"]}}}),
]
REJECTED_UPDATES = [  # both systems must refuse these and leave the documents unchanged
    ({"_id": "p3"}, {"$max": {"price": 250}, "$mul": {"price": 2}}),  # two operators on one path
    ({"_id": "p1"}, {"$set": {"specs": {}, "specs.cpu": "i9"}}),      # a path and its parent
    ({"_id": "p1"}, {"$set": {"_id": "p100"}}),                       # _id is immutable
    ({"_id": "p1"}, {"$inc": {"name": 1}}),                           # $inc on a string
]
COMPARE_PIPELINES = [
    [{"$match": {"status": "paid"}}, {"$unwind": "$items"},
     {"$lookup": {"from": "products", "localField": "items.sku", "foreignField": "_id", "as": "product"}},
     {"$unwind": "$product"},
     {"$project": {"sku": "$items.sku", "qty": "$items.qty", "price": "$product.price"}},
     {"$group": {"_id": "$sku", "units": {"$sum": "$qty"}, "unit_price": {"$first": "$price"}}},
     {"$sort": {"units": -1, "_id": 1}}],
    [{"$unwind": "$items"}, {"$group": {"_id": "$customer", "lines": {"$sum": 1}, "skus": {"$push": "$items.sku"}}},
     {"$sort": {"_id": 1}}],
    [{"$match": {"status": {"$ne": "cancelled"}}}, {"$count": "orders"}],
    [{"$lookup": {"from": "products", "localField": "items.sku", "foreignField": "_id", "as": "p"}},
     {"$project": {"names": "$p.name"}}, {"$sort": {"_id": 1}}],
]


def random_queries(count: int, seed: int = 10) -> list[dict]:
    """Generated filters mixing fields, operators, and value types, for a differential test."""
    import random
    rng = random.Random(seed)
    fields = ["price", "stock", "tags", "category", "specs.ram_gb", "ratings", "name", "specs", "missing"]
    values = [0, 15, 45, 100, 210, 950, "sale", "work", "computers", "Mouse", None, 5, 4, True, [3, 4]]

    def condition():
        op = rng.choice(["eq", "$gt", "$gte", "$lt", "$lte", "$ne", "$in", "$nin", "$exists", "$size"])
        if op == "eq":
            return rng.choice(values)
        if op in ("$in", "$nin"):
            return {op: rng.sample(values, 3)}
        if op == "$exists":
            return {op: rng.choice([True, False])}
        if op == "$size":
            return {op: rng.choice([0, 1, 2, 3])}
        return {op: rng.choice(values)}

    out = []
    for _ in range(count):
        parts = [{rng.choice(fields): condition()} for _ in range(rng.randint(1, 3))]
        shape = rng.choice(["and", "or", "flat", "nor"])
        if shape == "flat":
            query = {}
            for part in parts:
                query.update(part)
        else:
            query = {"$" + shape: parts}
        out.append(query)
    return out


def compare() -> None:
    print("== docdb.py versus MongoDB")
    mongo = client("shard-a")[DB + "_compare"]
    mine = DocumentDB()
    for name, docs in (("products", PRODUCTS), ("orders", ORDERS)):
        mongo[name].drop()
        mongo[name].insert_many([dict(d) for d in docs])
        mine[name].insert_many([dict(d) for d in docs])
    same = 0
    total = 0

    def check(label, ours, theirs):
        nonlocal same, total
        total += 1
        ok = ours == theirs
        same += ok
        print(f"  {'same' if ok else 'DIFFERENT':<10} {label}")
        if not ok:
            print(f"      docdb  : {ours}\n      MongoDB: {theirs}")

    for query in COMPARE_QUERIES:
        ours = sorted(d["_id"] for d in mine["products"].find(query))
        theirs = sorted(d["_id"] for d in mongo["products"].find(query))
        check(f"find {query}", ours, theirs)
    for query, update in COMPARE_UPDATES:
        mine["products"].update_many(query, update)
        mongo["products"].update_many(query, update)
    for query, update in REJECTED_UPDATES:
        refused = []
        for target in (mine["products"], mongo["products"]):
            try:
                target.update_many(query, update)
                refused.append(False)
            except Exception:
                refused.append(True)
        check(f"both refuse {update}", refused[0], refused[1])
    check(f"documents after {len(COMPARE_UPDATES)} update_many calls",
          sorted(mine["products"].find(), key=lambda d: d["_id"]),
          sorted(mongo["products"].find(), key=lambda d: d["_id"]))
    for pipeline in COMPARE_PIPELINES:
        check(f"aggregate {[next(iter(s)) for s in pipeline]}",
              mine["orders"].aggregate(pipeline), list(mongo["orders"].aggregate(pipeline)))
    differences = 0
    generated = random_queries(1000)
    for query in generated:
        if sorted(d["_id"] for d in mine["products"].find(query)) !=                 sorted(d["_id"] for d in mongo["products"].find(query)):
            differences += 1
            print(f"  DIFFERENT  generated {query}")
    print(f"  {same} of {total} checks give identical results; "
          f"{len(generated) - differences} of {len(generated)} generated queries agree")


# ------------------------------------------------------------------- local tx
def local_transaction() -> None:
    print("\n== MongoDB's own transaction inside one replica set (shard-a)")
    c = client("shard-a")
    accounts = c[DB].local_accounts
    accounts.drop()
    accounts.insert_many([{"_id": "alice", "balance": 100}, {"_id": "bob", "balance": 40}])

    def move(amount):
        with c.start_session() as session:
            with session.start_transaction():
                src = accounts.find_one_and_update({"_id": "alice"}, {"$inc": {"balance": -amount}},
                                                   session=session, return_document=ReturnDocument.AFTER)
                accounts.update_one({"_id": "bob"}, {"$inc": {"balance": amount}}, session=session)
                if src["balance"] < 0:
                    raise ValueError("overdraft")  # leaving the block with an error aborts the transaction

    move(30)
    print(f"  after moving 30: {list(accounts.find({}, {'_id': 1, 'balance': 1}))}")
    try:
        move(500)
    except ValueError as problem:
        print(f"  moving 500 raised {problem!r}; both updates were rolled back: "
              f"{list(accounts.find({}, {'_id': 1, 'balance': 1}))}")
    print("  This is atomic only inside one replica set. Across two independent instances we need 2PC.")


# ------------------------------------------------------------------------ 2PC
ACCOUNT_HOME = {"alice": "shard-a", "bob": "shard-a", "nadia": "shard-b", "omar": "shard-b"}


def seed_accounts() -> None:
    for name in SHARDS:
        db = client(name)[DB]
        db.accounts.drop()
        db.participant_log.drop()
        db.accounts.insert_many([{"_id": owner, "balance": start, "pending": None}
                                 for owner, start in (("alice", 100), ("bob", 40), ("nadia", 50), ("omar", 10))
                                 if ACCOUNT_HOME[owner] == name])
    client("shard-a")[DB + "_coordinator"].decisions.drop()


def prepare(shard: str, tx: str, owner: str, delta: int) -> bool:
    """Phase 1 on one instance, inside a local transaction: lock the document by marking it
    pending, check the rule, and record PREPARED durably. Returns the vote."""
    c = client(shard)
    db = c[DB]
    with c.start_session() as session:
        with session.start_transaction():
            account = db.accounts.find_one({"_id": owner}, session=session)
            if account is None or account["pending"] is not None or account["balance"] + delta < 0:
                db.participant_log.insert_one({"_id": tx, "state": "aborted", "owner": owner}, session=session)
                return False  # unknown account, locked by another transaction, or overdraft
            db.accounts.update_one({"_id": owner, "pending": None},
                                   {"$set": {"pending": {"tx": tx, "delta": delta}}}, session=session)
            db.participant_log.insert_one({"_id": tx, "state": "prepared", "owner": owner, "delta": delta},
                                          session=session)
    return True


def finish(shard: str, tx: str, decision: str) -> None:
    """Phase 2 on one instance: apply or drop the pending change, then mark the log entry."""
    c = client(shard)
    db = c[DB]
    with c.start_session() as session:
        with session.start_transaction():
            entry = db.participant_log.find_one({"_id": tx}, session=session)
            if entry is None or entry["state"] != "prepared":
                return  # already finished: phase 2 is idempotent
            if decision == "commit":
                db.accounts.update_one({"_id": entry["owner"], "pending.tx": tx},
                                       {"$inc": {"balance": entry["delta"]}, "$set": {"pending": None}},
                                       session=session)
            else:
                db.accounts.update_one({"_id": entry["owner"], "pending.tx": tx},
                                       {"$set": {"pending": None}}, session=session)
            db.participant_log.update_one({"_id": tx}, {"$set": {"state": {"commit": "committed",
                                                                           "abort": "aborted"}[decision]}},
                                          session=session)


def transfer(src: str, dst: str, amount: int, crash: str | None = None) -> str:
    tx = "tx-" + uuid.uuid4().hex[:8]
    plan = [(ACCOUNT_HOME[src], src, -amount), (ACCOUNT_HOME[dst], dst, amount)]
    votes = [prepare(shard, tx, owner, delta) for shard, owner, delta in plan]
    if crash == "after-prepare":
        print(f"  CRASH after prepare of {tx}: no decision was recorded", flush=True)
        os._exit(1)  # no cleanup at all, like a killed process
    decisions = client("shard-a")[DB + "_coordinator"].decisions
    decision = "commit" if all(votes) else "abort"
    if decision == "commit":  # the commit point: a durable decision document (majority write)
        decisions.insert_one({"_id": tx, "decision": "commit", "shards": [p[0] for p in plan], "done": False})
    if crash == "after-decision":
        print(f"  CRASH after recording COMMIT for {tx}: no shard has been told", flush=True)
        os._exit(1)
    for shard, _, _ in plan:
        finish(shard, tx, decision)
    if decision == "commit":
        decisions.update_one({"_id": tx}, {"$set": {"done": True}})
    return decision


def balances() -> dict:
    out = {}
    for name in SHARDS:
        for doc in client(name)[DB].accounts.find():
            out[doc["_id"]] = doc["balance"] if doc["pending"] is None else f"{doc['balance']} (locked by {doc['pending']['tx']})"
    return dict(sorted(out.items()))


def two_phase(crash: str | None) -> None:
    print("\n== Two-phase commit across shard-a and shard-b")
    seed_accounts()
    print(f"  start: {balances()}", flush=True)
    print(f"  alice (shard-a) -> nadia (shard-b), 30: {transfer('alice', 'nadia', 30)}  {balances()}")
    print(f"  omar (shard-b) -> bob (shard-a), 500:  {transfer('omar', 'bob', 500)}  {balances()}", flush=True)
    if crash:
        transfer("bob", "omar", 5, crash=crash)


def status() -> None:
    print("== In-doubt state")
    print(f"  balances: {balances()}")
    for name in SHARDS:
        prepared = [e["_id"] for e in client(name)[DB].participant_log.find({"state": "prepared"})]
        print(f"  {name}: prepared, not finished: {prepared}")
    print(f"  coordinator decisions not done: "
          f"{[d['_id'] for d in client('shard-a')[DB + '_coordinator'].decisions.find({'done': False})]}")


def recover() -> None:
    print("== Recovery")
    decisions = client("shard-a")[DB + "_coordinator"].decisions
    for name in SHARDS:
        for entry in client(name)[DB].participant_log.find({"state": "prepared"}):
            record = decisions.find_one({"_id": entry["_id"]})
            decision = "commit" if record and record["decision"] == "commit" else "abort"  # presumed abort
            finish(name, entry["_id"], decision)
            print(f"  {name}: {entry['_id']} -> {decision}")
    decisions.update_many({"done": False}, {"$set": {"done": True}})
    print(f"  balances: {balances()}  total {sum(v for v in balances().values() if isinstance(v, int))}")


# --------------------------------------------------------------------- tenants
class TenantCollection:
    """A pymongo collection wrapper that confines every call to one tenant."""

    def __init__(self, collection, tenant_id: str) -> None:
        self.collection, self.tenant = collection, tenant_id

    def _scope(self, query):
        return {"$and": [{"tenant_id": self.tenant}, query]} if query else {"tenant_id": self.tenant}

    def find(self, query=None, *args, **kwargs):
        return self.collection.find(self._scope(query), *args, **kwargs)

    def insert_one(self, doc):
        if doc.get("tenant_id", self.tenant) != self.tenant:
            raise PermissionError("cannot insert a document of another tenant")
        return self.collection.insert_one({**doc, "tenant_id": self.tenant})

    def update_many(self, query, update):
        if any(f == "tenant_id" for fields in update.values() for f in fields):
            raise PermissionError("the tenant id cannot be changed")
        return self.collection.update_many(self._scope(query), update)

    def aggregate(self, pipeline):
        return self.collection.aggregate([{"$match": {"tenant_id": self.tenant}}] + pipeline)


def tenants() -> None:
    print("\n== Tenant-aware queries on MongoDB (shard-b)")
    tickets = client("shard-b")[DB].tickets
    tickets.drop()
    tickets.insert_many([{"tenant_id": t, "priority": ["low", "high"][i % 2], "n": i}
                         for t in ("acme", "globex", "initech") for i in range(400)])
    tickets.create_index([("tenant_id", 1), ("priority", 1)])
    acme = TenantCollection(tickets, "acme")
    sneaky = {"$or": [{"tenant_id": "globex"}, {"priority": "high"}]}
    found = list(acme.find(sneaky))
    print(f"  acme asks for {sneaky}: {len(found)} documents, tenants {sorted({d['tenant_id'] for d in found})}")
    plan = acme.find({"priority": "high"}).explain()["queryPlanner"]["winningPlan"]
    stage = plan
    while "inputStage" in stage:
        stage = stage["inputStage"]
    print(f"  plan for acme + priority=high: {plan['stage']} <- {stage['stage']} on {stage.get('keyPattern')}")
    print(f"  per priority: {list(acme.aggregate([{'$group': {'_id': '$priority', 'n': {'$sum': 1}}}, {'$sort': {'_id': 1}}]))}")
    try:
        acme.update_many({}, {"$set": {"tenant_id": "globex"}})
    except PermissionError as refused:
        print(f"  refused: {refused}")


def reset() -> None:
    for name in SHARDS:
        c = client(name)
        for db_name in (DB, DB + "_compare", DB + "_coordinator"):
            c.drop_database(db_name)
    print("Dropped the lab10 databases on both instances")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", default="all", choices=["compare", "local-tx", "2pc", "status", "recover",
                                                          "tenants", "reset", "all"])
    parser.add_argument("--crash", choices=["after-prepare", "after-decision"])
    args = parser.parse_args()
    try:
        if args.mode in ("compare", "all"):
            compare()
        if args.mode in ("local-tx", "all"):
            local_transaction()
        if args.mode in ("2pc", "all"):
            two_phase(args.crash)
        if args.mode == "status":
            status()
        if args.mode == "recover":
            recover()
        if args.mode in ("tenants", "all"):
            tenants()
        if args.mode == "reset":
            reset()
    except RuntimeError as problem:
        raise SystemExit(f"MongoDB demo stopped: {problem}") from None
    except Exception as problem:
        if MongoClient is not None and isinstance(problem, PyMongoError):
            raise SystemExit(f"MongoDB demo stopped: {problem}\nStart the instances with: docker compose "
                             "-f labs/lab10/compose.lab10.yaml up -d") from None
        raise


if __name__ == "__main__":
    main()
