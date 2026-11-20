"""A sharded document database: a query router, cross-shard ACID transactions, and tenants.

* Router (like MongoDB's mongos): each collection has a shard key and a strategy (range or
  hashed). A query that pins the shard key goes to one shard ("targeted"); any other query is
  sent to every shard and the answers are merged ("scatter-gather").
* Cross-shard transactions: two-phase commit across the shards a transaction touches.
  Each shard checks its rules, locks the documents it will change, and logs PREPARED with the
  new documents before voting YES. The coordinator logs COMMIT (the commit point) before telling
  anyone. Until then nothing is visible: readers see committed data only, and other writers that
  touch a locked document get a WriteConflict. Presumed abort, as in Lab 9.
* Tenants: TenantSession adds the tenant to every filter, insert, and pipeline, refuses to move a
  document to another tenant, and limits $lookup to the tenant's own documents. With the tenant
  id as the shard key, every tenant query is also a targeted query.

    python labs/lab10/sharding.py
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import itertools
from contextlib import contextmanager

from docdb import MISSING, DocumentDB, WriteError, apply_update, get_path, matches, project, run_pipeline, sort_key


class WriteConflict(Exception):
    """A document is locked by another transaction that has prepared but not finished."""


class TransactionAborted(Exception):
    pass


class SimulatedCrash(Exception):
    pass


# ---------------------------------------------------------------------- shard
class Shard:
    """One shard: a DocumentDB of committed data, a durable participant log, and volatile locks."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.db = DocumentDB()
        self.log: list[tuple] = []  # ("PREPARED", tx, changes) / ("COMMIT", tx) / ("ABORT", tx)
        self.locks: dict[tuple[str, object], str] = {}  # (collection, _id) -> tx
        self.staged: dict[str, list] = {}
        self.validators: dict[str, object] = {}  # collection -> function(doc) returning an error or None
        self.up = True

    def _require_up(self) -> None:
        if not self.up:
            raise ConnectionError(f"{self.name} is down")

    def check_unlocked(self, collection: str, ids, tx: str | None = None) -> None:
        for _id in ids:
            holder = self.locks.get((collection, _id))
            if holder is not None and holder != tx:
                raise WriteConflict(f"{collection}/{_id} is locked by prepared transaction {holder}")

    def prepare(self, tx: str, ops: list[tuple]) -> str:
        """Evaluate ops on a private copy of the affected documents; vote YES or NO."""
        self._require_up()
        view: dict[tuple[str, object], dict | None] = {}  # documents as this transaction sees them

        def current(coll, _id):
            key = (coll, _id)
            if key not in view:
                stored = self.db[coll].docs.get(_id)
                view[key] = copy.deepcopy(stored)
            return view[key]

        try:
            for op in ops:
                kind, coll = op[0], op[1]
                if kind == "insert":
                    doc = copy.deepcopy(op[2])
                    if current(coll, doc["_id"]) is not None:
                        return "NO"  # duplicate _id
                    view[(coll, doc["_id"])] = doc
                elif kind in ("update", "delete"):
                    query = op[2]
                    ids = [i for i, d in self.db[coll].docs.items() if matches(d, query)]
                    ids += [i for (c, i), d in view.items() if c == coll and i not in ids and d is not None
                            and matches(d, query)]
                    for _id in ids:
                        doc = current(coll, _id)
                        if doc is None or not matches(doc, query):
                            continue
                        view[(coll, _id)] = apply_update(doc, op[3]) if kind == "update" else None
            for (coll, _id), doc in view.items():
                self.check_unlocked(coll, [_id], tx)
                rule = self.validators.get(coll)
                if doc is not None and rule is not None and rule(doc):
                    return "NO"
        except (WriteConflict, WriteError):
            return "NO"
        changes = [(coll, _id, doc) for (coll, _id), doc in view.items()
                   if doc != self.db[coll].docs.get(_id)]
        for coll, _id, _ in changes:
            self.locks[(coll, _id)] = tx
        self.staged[tx] = changes
        self.log.append(("PREPARED", tx, copy.deepcopy(changes)))  # forced before the YES vote
        return "YES"

    def commit(self, tx: str) -> None:
        self._require_up()
        if ("COMMIT", tx) in self.log:
            return
        for coll, _id, doc in self.staged.pop(tx, []):
            collection = self.db[coll]
            old = collection.docs.get(_id)
            if doc is None:
                if old is not None:
                    collection._index_remove(old)
                    del collection.docs[_id]
            elif old is None:
                collection.insert_one(doc)
            else:
                collection._replace_stored(old, doc)
        self.log.append(("COMMIT", tx))
        self._unlock(tx)

    def abort(self, tx: str) -> None:
        self._require_up()
        if ("ABORT", tx) in self.log:
            return
        self.staged.pop(tx, None)
        self.log.append(("ABORT", tx))
        self._unlock(tx)

    def _unlock(self, tx: str) -> None:
        self.locks = {k: v for k, v in self.locks.items() if v != tx}

    def in_doubt(self) -> list[str]:
        decided = {r[1] for r in self.log if r[0] in ("COMMIT", "ABORT")}
        return [r[1] for r in self.log if r[0] == "PREPARED" and r[1] not in decided]

    def crash(self) -> None:
        self.up = False
        self.locks.clear()
        self.staged.clear()

    def restart(self) -> list[str]:
        self.up = True
        doubt = self.in_doubt()
        for record in self.log:
            if record[0] == "PREPARED" and record[1] in doubt:
                self.staged[record[1]] = copy.deepcopy(record[2])
                for coll, _id, _ in record[2]:
                    self.locks[(coll, _id)] = record[1]
        return doubt


# --------------------------------------------------------------------- router
def _hash(value) -> int:
    return int.from_bytes(hashlib.blake2b(repr(value).encode(), digest_size=8).digest(), "big")


class ShardedCluster:
    def __init__(self, shard_names=("shard-a", "shard-b")) -> None:
        self.shards = {name: Shard(name) for name in shard_names}
        self.names = list(shard_names)
        self.config: dict[str, dict] = {}  # collection -> {"key", "strategy", "boundaries"}
        self.coordinator_log: list[tuple] = []
        self.coordinator_up = True
        self.crash_at: str | None = None
        self.last_route: dict = {}
        self.last_votes: dict = {}
        self._tx_ids = itertools.count(1)

    # ------------------------------------------------------------ routing
    def shard_collection(self, collection: str, key: str, strategy: str = "hashed",
                         boundaries: list | None = None) -> None:
        if strategy == "range" and (not boundaries or len(boundaries) != len(self.names) - 1):
            raise ValueError("range sharding needs len(shards) - 1 boundaries")
        if strategy not in ("range", "hashed"):
            raise ValueError("strategy must be 'range' or 'hashed'")
        self.config[collection] = {"key": key, "strategy": strategy, "boundaries": boundaries}

    def _key(self, collection: str) -> str:
        if collection not in self.config:
            raise KeyError(f"collection {collection!r} is not sharded")
        return self.config[collection]["key"]

    def shard_for(self, collection: str, value) -> str:
        cfg = self.config[collection]
        if cfg["strategy"] == "range":
            return self.names[bisect.bisect_right(cfg["boundaries"], value)]
        return self.names[_hash(value) % len(self.names)]

    def target(self, collection: str, query: dict) -> list[str]:
        """Shards that may hold matches: one per pinned shard-key value, else all of them."""
        key = self._key(collection)
        condition = (query or {}).get(key, MISSING)
        values = None
        if condition is not MISSING and not isinstance(condition, dict):
            values = [condition]
        elif isinstance(condition, dict) and set(condition) == {"$eq"}:
            values = [condition["$eq"]]
        elif isinstance(condition, dict) and set(condition) == {"$in"}:
            values = list(condition["$in"])
        elif "$and" in (query or {}):
            for part in query["$and"]:
                narrowed = self.target(collection, part)
                if len(narrowed) < len(self.names):
                    return narrowed
        if values is None:
            return list(self.names)
        return sorted({self.shard_for(collection, v) for v in values}, key=self.names.index)

    # -------------------------------------------------- non-transactional ops
    def insert_one(self, collection: str, doc: dict):
        key = self._key(collection)
        if key not in doc:
            raise WriteError(f"documents in {collection} need the shard key {key!r}")
        shard = self.shards[self.shard_for(collection, doc[key])]
        shard._require_up()
        return shard.db[collection].insert_one(doc)

    def insert_many(self, collection: str, docs: list[dict]) -> list:
        return [self.insert_one(collection, d) for d in docs]

    def update_many(self, collection: str, query: dict, update: dict) -> dict:
        """Applied shard by shard, NOT atomic: a failure part-way leaves some shards updated."""
        self._forbid_shard_key_change(collection, update)
        result = {"matched": 0, "modified": 0, "shards": []}
        for name in self.target(collection, query):
            shard = self.shards[name]
            shard._require_up()
            coll = shard.db[collection]
            shard.check_unlocked(collection, [d["_id"] for d in coll.find(query)])
            r = coll.update_many(query, update)
            result["matched"] += r["matched"]
            result["modified"] += r["modified"]
            result["shards"].append(name)
        return result

    def _forbid_shard_key_change(self, collection: str, update: dict) -> None:
        key = self._key(collection)
        for op, fields in update.items():
            if op.startswith("$") and any(f == key or f.startswith(key + ".") for f in fields):
                raise WriteError(f"the shard key {key!r} cannot be changed by an update")

    def find(self, collection: str, query: dict | None = None, projection: dict | None = None, *,
             sort=None, skip: int = 0, limit: int = 0) -> list[dict]:
        query = query or {}
        targets = self.target(collection, query)
        merged = []
        for name in targets:
            shard = self.shards[name]
            shard._require_up()
            # each shard returns its first skip+limit by the same sort; the router merges
            merged += shard.db[collection].find(query, sort=sort, limit=(skip + limit) if limit else 0)
        for field, direction in reversed(sort or []):
            merged.sort(key=lambda d: sort_key(get_path(d, field, None)), reverse=direction < 0)
        merged = merged[skip:]
        if limit:
            merged = merged[:limit]
        self.last_route = {"collection": collection, "shards": targets,
                           "targeted": len(targets) < len(self.names)}
        return [project(d, projection) for d in merged]

    def count_documents(self, collection: str, query: dict | None = None) -> int:
        return len(self.find(collection, query))

    def aggregate(self, collection: str, pipeline: list[dict], *, lookup_filter: dict | None = None) -> list[dict]:
        """A leading $match is pushed to the shards (and used for targeting); the rest runs on the router."""
        first = pipeline[0].get("$match", {}) if pipeline else {}
        targets = self.target(collection, first)
        docs = []
        for name in targets:
            shard = self.shards[name]
            shard._require_up()
            docs += shard.db[collection].find(first)
        self.last_route = {"collection": collection, "shards": targets, "targeted": len(targets) < len(self.names)}
        rest = pipeline[1:] if pipeline and "$match" in pipeline[0] else pipeline
        return run_pipeline(docs, rest, lookup_source=self._all_docs, lookup_filter=lookup_filter)

    def _all_docs(self, collection: str) -> list[dict]:
        out = []
        for name in self.names:
            out += list(self.shards[name].db[collection].docs.values())
        return out

    # ------------------------------------------------------------ transactions
    @contextmanager
    def transaction(self):
        """Collect writes, then commit them atomically across shards with 2PC on exit."""
        tx = Transaction(self, f"tx{next(self._tx_ids)}")
        yield tx
        tx.commit()

    def decision(self, tx: str) -> str:
        if not self.coordinator_up:
            raise ConnectionError("coordinator is down")
        for record in self.coordinator_log:
            if record[0] in ("COMMIT", "ABORT") and record[1] == tx:
                return record[0]
        return "ABORT"  # presumed abort

    def _maybe_crash(self, point: str) -> None:
        if self.crash_at == point:
            self.crash_at = None
            self.coordinator_up = False
            raise SimulatedCrash(point)

    def two_phase_commit(self, tx: str, ops_by_shard: dict[str, list]) -> str:
        if not self.coordinator_up:
            raise ConnectionError("coordinator is down")
        votes = {}
        for name, ops in ops_by_shard.items():
            try:
                votes[name] = self.shards[name].prepare(tx, ops)
            except ConnectionError:
                votes[name] = "NO"
        self.last_votes = votes
        self._maybe_crash("after-prepare")
        if all(v == "YES" for v in votes.values()):
            self.coordinator_log.append(("COMMIT", tx, tuple(ops_by_shard)))  # the commit point
            self._maybe_crash("after-decision")
            acked = []
            for i, name in enumerate(ops_by_shard):
                acked.append(self._deliver(name, tx, "COMMIT"))
                if i == 0:
                    self._maybe_crash("after-first-commit")
            if all(acked):
                self.coordinator_log.append(("END", tx))
            return "COMMIT"
        for name, vote in votes.items():
            if vote == "YES":
                self._deliver(name, tx, "ABORT")
        return "ABORT"

    def _deliver(self, name: str, tx: str, decision: str) -> bool:
        try:
            shard = self.shards[name]
            (shard.commit if decision == "COMMIT" else shard.abort)(tx)
            return True
        except ConnectionError:
            return False

    def recover_coordinator(self) -> list[str]:
        self.coordinator_up = True
        ended = {r[1] for r in self.coordinator_log if r[0] == "END"}
        finished = []
        for record in self.coordinator_log:
            if record[0] == "COMMIT" and record[1] not in ended:
                if all([self._deliver(n, record[1], "COMMIT") for n in record[2]]):
                    self.coordinator_log.append(("END", record[1]))
                finished.append(record[1])
        return finished

    def resolve_in_doubt(self, shard_name: str) -> dict[str, str]:
        """A participant asks the coordinator about each transaction it prepared."""
        shard = self.shards[shard_name]
        outcomes = {}
        for tx in shard.in_doubt():
            decision = self.decision(tx)
            (shard.commit if decision == "COMMIT" else shard.abort)(tx)
            outcomes[tx] = decision
        return outcomes


class Transaction:
    def __init__(self, cluster: ShardedCluster, tx_id: str) -> None:
        self.cluster = cluster
        self.id = tx_id
        self.ops: dict[str, list] = {}
        self.outcome: str | None = None

    def _add(self, shards, op) -> None:
        for name in shards:
            self.ops.setdefault(name, []).append(op)

    def insert_one(self, collection: str, doc: dict) -> None:
        key = self.cluster._key(collection)
        if key not in doc or "_id" not in doc:
            raise WriteError("transactional inserts need the shard key and an explicit _id")
        self._add([self.cluster.shard_for(collection, doc[key])], ("insert", collection, copy.deepcopy(doc)))

    def update_many(self, collection: str, query: dict, update: dict) -> None:
        self.cluster._forbid_shard_key_change(collection, update)
        self._add(self.cluster.target(collection, query), ("update", collection, query, update))

    update_one = update_many  # the lab's transactional updates name single documents by _id or key

    def delete_many(self, collection: str, query: dict) -> None:
        self._add(self.cluster.target(collection, query), ("delete", collection, query))

    def commit(self) -> str:
        if not self.ops:
            self.outcome = "COMMIT"
            return self.outcome
        self.outcome = self.cluster.two_phase_commit(self.id, self.ops)
        if self.outcome == "ABORT":
            refused = sorted(n for n, v in self.cluster.last_votes.items() if v != "YES")
            raise TransactionAborted(f"{self.id} aborted: {', '.join(refused)} voted NO")
        return self.outcome


# --------------------------------------------------------------------- tenants
class TenantSession:
    """Every operation is confined to one tenant. The tenant id comes from authentication,
    never from the request body, and no filter can widen the scope."""

    def __init__(self, cluster: ShardedCluster, tenant_id: str, field: str = "tenant_id") -> None:
        if not isinstance(tenant_id, str) or not tenant_id:
            raise PermissionError("a session needs an authenticated tenant id")
        self.cluster, self.tenant, self.field = cluster, tenant_id, field

    def scope(self, query: dict | None) -> dict:
        own = {self.field: self.tenant}
        return {"$and": [own, query]} if query else own

    def _check_doc(self, doc: dict) -> dict:
        if doc.get(self.field, self.tenant) != self.tenant:
            raise PermissionError(f"cannot write a document of tenant {doc[self.field]!r}")
        return {**doc, self.field: self.tenant}

    def _check_update(self, update: dict) -> None:
        for op, fields in update.items():
            if not op.startswith("$"):
                if update.get(self.field, self.tenant) != self.tenant:
                    raise PermissionError("cannot move a document to another tenant")
            elif any(f == self.field or f.startswith(self.field + ".") for f in fields):
                raise PermissionError("the tenant id cannot be changed")

    def insert_one(self, collection: str, doc: dict):
        return self.cluster.insert_one(collection, self._check_doc(doc))

    def find(self, collection: str, query: dict | None = None, projection=None, **options) -> list[dict]:
        return self.cluster.find(collection, self.scope(query), projection, **options)

    def count_documents(self, collection: str, query: dict | None = None) -> int:
        return self.cluster.count_documents(collection, self.scope(query))

    def update_many(self, collection: str, query: dict, update: dict) -> dict:
        self._check_update(update)
        return self.cluster.update_many(collection, self.scope(query), update)

    def aggregate(self, collection: str, pipeline: list[dict]) -> list[dict]:
        return self.cluster.aggregate(collection, [{"$match": self.scope(None)}] + pipeline,
                                      lookup_filter={self.field: self.tenant})

    @contextmanager
    def transaction(self):
        session = self

        class ScopedTransaction:
            def __init__(self, tx: Transaction) -> None:
                self.tx = tx

            def insert_one(self, collection, doc):
                self.tx.insert_one(collection, session._check_doc(doc))

            def update_many(self, collection, query, update):
                session._check_update(update)
                self.tx.update_many(collection, session.scope(query), update)

            update_one = update_many

        with self.cluster.transaction() as tx:
            yield ScopedTransaction(tx)


# ------------------------------------------------------------------------ demo
def build_demo_cluster() -> ShardedCluster:
    cluster = ShardedCluster(("shard-a", "shard-b"))
    cluster.shard_collection("accounts", "owner", "range", boundaries=["m"])  # a-l on shard-a, m-z on shard-b
    cluster.shard_collection("tickets", "tenant_id", "hashed")
    for shard in cluster.shards.values():
        shard.validators["accounts"] = lambda d: "negative balance" if d["balance"] < 0 else None
        shard.db["tickets"].create_index("tenant_id")
    cluster.insert_many("accounts", [
        {"_id": "alice", "owner": "alice", "balance": 100}, {"_id": "bob", "owner": "bob", "balance": 40},
        {"_id": "nadia", "owner": "nadia", "balance": 50}, {"_id": "omar", "owner": "omar", "balance": 10}])
    n = itertools.count(1)
    for tenant, count in (("acme", 6), ("globex", 4), ("initech", 5)):
        for i in range(count):
            cluster.insert_one("tickets", {"_id": f"t{next(n)}", "tenant_id": tenant, "title": f"{tenant} issue {i}",
                                           "priority": ["low", "high"][i % 2], "owner": "alice" if i < 2 else "omar"})
    return cluster


def balances(cluster: ShardedCluster) -> dict:
    return {d["_id"]: d["balance"] for d in cluster.find("accounts", sort=[("_id", 1)])}


def transfer(cluster: ShardedCluster, src: str, dst: str, amount: int) -> str:
    with cluster.transaction() as tx:
        tx.update_one("accounts", {"owner": src}, {"$inc": {"balance": -amount}})
        tx.update_one("accounts", {"owner": dst}, {"$inc": {"balance": amount}})
    return tx.outcome


def main() -> None:
    cluster = build_demo_cluster()
    print("1. Routing")
    for name in cluster.names:
        print(f"   {name}: accounts {sorted(cluster.shards[name].db['accounts'].docs)}, "
              f"tickets of {sorted({d['tenant_id'] for d in cluster.shards[name].db['tickets'].docs.values()})}")
    cluster.find("accounts", {"owner": "nadia"})
    print(f"   find owner = nadia           -> {cluster.last_route['shards']} (targeted)")
    cluster.find("accounts", {"balance": {"$gt": 20}})
    print(f"   find balance > 20            -> {cluster.last_route['shards']} (scatter-gather)")
    top = cluster.find("accounts", sort=[("balance", -1)], limit=2)
    print(f"   top 2 balances across shards -> {[(d['_id'], d['balance']) for d in top]}")

    print("\n2. Without a transaction, a multi-shard update is not atomic")
    cluster.shards["shard-b"].up = False
    try:
        cluster.update_many("accounts", {}, {"$inc": {"balance": 1}})
    except ConnectionError as failure:
        print(f"   update_many(+1 to everyone) failed part-way: {failure}")
    cluster.shards["shard-b"].up = True
    print(f"   balances: {balances(cluster)}  <- shard-a changed, shard-b did not")
    cluster.update_many("accounts", {"owner": {"$in": ["alice", "bob"]}}, {"$inc": {"balance": -1}})

    print("\n3. Cross-shard transfer with two-phase commit")
    print(f"   alice -> nadia 30: {transfer(cluster, 'alice', 'nadia', 30)}; balances {balances(cluster)}")
    try:
        transfer(cluster, "omar", "bob", 500)
    except TransactionAborted as failure:
        print(f"   omar -> bob 500: ABORT ({failure}); balances {balances(cluster)}")

    print("\n4. Coordinator crash after PREPARE: documents stay locked, readers see the old values")
    cluster.crash_at = "after-prepare"
    try:
        transfer(cluster, "bob", "omar", 5)
    except SimulatedCrash as point:
        print(f"   crash at {point}; in doubt: a {cluster.shards['shard-a'].in_doubt()}, "
              f"b {cluster.shards['shard-b'].in_doubt()}")
    print(f"   a reader sees committed data only: {balances(cluster)}")
    try:
        cluster.update_many("accounts", {"owner": "bob"}, {"$set": {"note": "x"}})
    except WriteConflict as conflict:
        print(f"   another writer: WriteConflict ({conflict})")
    cluster.recover_coordinator()
    print(f"   coordinator back, no decision logged -> {cluster.resolve_in_doubt('shard-a')} "
          f"{cluster.resolve_in_doubt('shard-b')}; balances {balances(cluster)}")

    print("\n5. Coordinator crash after COMMIT reached only shard-a")
    cluster.crash_at = "after-first-commit"
    try:
        transfer(cluster, "bob", "omar", 5)
    except SimulatedCrash:
        pass
    print(f"   right after the crash: {balances(cluster)}  (total {sum(balances(cluster).values())})")
    print(f"   recovery resends COMMIT for {cluster.recover_coordinator()}: {balances(cluster)} "
          f"(total {sum(balances(cluster).values())})")

    print("\n6. Tenant-aware queries")
    acme = TenantSession(cluster, "acme")
    print(f"   acme sees {acme.count_documents('tickets')} tickets via shards {cluster.last_route['shards']}")
    sneaky = {"$or": [{"tenant_id": "globex"}, {"priority": "high"}]}
    print(f"   acme asks for {sneaky}: {[d['_id'] for d in acme.find('tickets', sneaky)]} (own tickets only)")
    for attempt in (lambda: acme.insert_one("tickets", {"_id": "t99", "tenant_id": "globex", "title": "x"}),
                    lambda: acme.update_many("tickets", {}, {"$set": {"tenant_id": "globex"}})):
        try:
            attempt()
        except PermissionError as refused:
            print(f"   refused: {refused}")
    per_priority = acme.aggregate("tickets", [{"$group": {"_id": "$priority", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}])
    print(f"   acme tickets per priority: {per_priority}")
    joined = acme.aggregate("tickets", [{"$lookup": {"from": "tickets", "localField": "owner",
                                                     "foreignField": "owner", "as": "same_owner"}},
                                        {"$project": {"n": "$_id", "same_owner": "$same_owner._id"}}, {"$limit": 1}])
    print(f"   $lookup inside acme only joins acme documents: {joined}")


if __name__ == "__main__":
    main()
