# Lab 10 - NoSQL, Document Databases, and Cross-Shard Transactions

Week 10 leaves the relational model. Students build the core of four NoSQL data models
(key-value, wide-column, graph, and document), then a document database that understands the
MongoDB query language. They shard it, make transactions atomic across shards with two-phase
commit, and confine every query to one tenant. A second part runs the same ideas on two real
MongoDB instances: the lab's query engine is checked against MongoDB result by result, and a
transfer between the two instances survives a crash in the middle of two-phase commit.

## Learning outcomes

By the end of the lab, students should be able to:

- Match a workload to a NoSQL model: key lookups, partitioned time series, relationship
  traversals, or self-contained documents.
- Write MongoDB queries, updates, and aggregation pipelines, and predict their results on
  arrays, nested fields, and missing fields.
- Read `explain()` output and say when an index is used.
- Explain how a router chooses between a targeted query and scatter-gather, and why the shard
  key matters.
- Implement and trace two-phase commit across shards: votes, locks, the commit point, and
  recovery after a coordinator or shard failure.
- Build tenant-aware access: scope every read, write, and join to one tenant, and use the
  tenant as the shard key.

## How this lab fits the course

Lab 4 compared index structures and Lab 8 made one server recoverable. Lab 9 then
partitioned data and committed across machines with two-phase commit. Lab 10 applies those
pieces to a document database: the same 2PC now protects multi-document writes across shards,
and the partitioning choice becomes MongoDB's shard key. The RAG system of Lab 9 stored
documents with embeddings; most NoSQL document stores now offer exactly that.

After class, students complete the independent implementation practice.

## Part 1 - Core components of four NoSQL models

"NoSQL" is a family of data models, each built around the queries it makes cheap.
`nosql_models.py` implements the core of three; `docdb.py` is the fourth.

| Model | Lab component | Cheap query | Expensive query |
|---|---|---|---|
| Key-value | `BitcaskKV`: append-only log + in-memory keydir, TTLs, compaction | get / put by key in one lookup | anything by value ("carts that contain a pen") |
| Wide-column | `WideColumnTable`: partition key + sorted clustering keys | one partition, a range of clustering keys ("chat 3, newest 20 messages") | a query without the partition key (1,000 rows read to find 143) |
| Graph | `PropertyGraph`: adjacency lists, BFS, a tiny pattern match | follow edges: shortest path, friends of friends | aggregates over every node |
| Document | `docdb.py`: nested documents and MQL | fetch or update one self-contained document | joins across many documents |

- **Bitcask.** Every write appends; the keydir points at the latest copy, so a read is one
  lookup. A delete appends a tombstone. The keydir lives in memory, so a restart rebuilds it by
  scanning the log once (`rebuild_keydir()`), and compaction keeps only live values (6 records
  become 1 in the demo).
- **Wide-column.** Cassandra stores a partition's rows together and sorted by the clustering
  key, so "the newest 3 messages of chat3" reads exactly 3 rows. A query without the partition
  key must visit every partition, which Cassandra refuses without `ALLOW FILTERING`. The
  design rule is one table per query, accepting duplicated data.
- **Graph.** A traversal reads only the edges it follows, so its cost depends on the
  neighbourhood rather than the size of the data. In SQL each extra hop is another self-join.

## Part 2 - A document database with the MongoDB query language

A document groups data that is read together: an order embeds its items instead of joining
an `order_items` table. **Embed** what belongs to one owner and is read with it; **reference**
what is shared, large, or grows without bound. `docdb.py` stores such documents and
implements a working subset of MongoDB's query language (MQL), listed at the top of the file.

Rules that surprise people, all implemented in `matches()`:

- A condition on an array matches if the array **or any element** matches:
  `{"tags": "sale"}` finds `{"tags": ["sale", "work"]}`.
- A dotted path walks into documents and through arrays of documents: `"items.sku"`.
  `"ratings.0"` indexes an array.
- `{"field": None}` matches `null` **and missing** fields; `$ne` and `$nin` match documents
  that lack the field.
- `$gt`, `$lt`, and the other comparisons only compare values of the same type family:
  `{"price": {"$gt": "100"}}` matches no numeric price. Arrays compare as whole arrays, element
  by element.
- `{"items.sku": "p1", "items.qty": 2}` can be satisfied by **different** elements;
  `{"items": {"$elemMatch": {"sku": "p1", "qty": 2}}}` needs one element that satisfies both.

Updates (`apply_update()`) never edit in place: they build a new document, and invalid
updates change nothing. MongoDB rejects two operators on the same or overlapping paths
(`$max` and `$mul` both on `price`), any change to `_id`, and `$inc` on a string. An upsert
builds the new document from the equality parts of the filter.

**Indexes.** `create_index("category")` maps each value (each element, for arrays) to the
documents that hold it. `explain()` reports the plan: with 2,006 products, a query on
`category` examines all 2,006 documents without the index (`COLLSCAN`) and 3 with it
(`IXSCAN`). Unique indexes reject duplicates on insert and on update.

**Aggregation.** A pipeline is a list of stages, each transforming the stream of documents:
`$match`, `$unwind`, `$lookup` (a left outer join), `$project`, `$group` with accumulators,
`$sort`, `$skip`, `$limit`, `$count`. Put `$match` first so that fewer documents flow through,
and so that a sharded router can push it to the shards.

**Checked against MongoDB.** `mongo_demo.py --mode compare` runs the same 16 queries, 4 invalid
updates, 6 updates, and 4 pipelines on `docdb.py` and on MongoDB 7.0: all 25 checks agree. It
then generates 1,000 random filters that mix fields, operators, value types, and logical
operators; all 1,000 return the same documents in both. Building that comparison found three
MongoDB rules that the first version of the engine got wrong (comparing arrays with `$gt`,
`$gte` against `null`, and `$lookup` through an array field); they are fixed and covered by tests.

## Part 3 - Sharding and query routing

`sharding.py` puts two `DocumentDB` shards behind a router, as MongoDB's `mongos` does. Each
collection is sharded on a key with a strategy: `accounts` by `owner` with a range split at
`"m"` (a-l on shard-a, m-z on shard-b), and `tickets` by `tenant_id`, hashed.

- A query that pins the shard key (`{"owner": "nadia"}`, `$eq`, or `$in`) is **targeted**: only
  the owning shards run it. Any other query is **scatter-gather**: every shard runs it and the
  router merges the results. With sort and limit, each shard returns its own first
  `skip + limit` documents and the router sorts the merged list again.
- Every insert must carry the shard key, and an update may not change it (in MongoDB a shard key
  change must move the document between shards).
- Without a transaction, a multi-shard write is not atomic. The demo stops shard-b during
  `update_many` on all accounts: shard-a's two accounts are changed and shard-b's are not.

Choosing the shard key is the most important design decision: it should have many distinct
values, spread writes evenly (Lab 9's hot-spot problem), and appear in the most frequent queries.

## Part 4 - Cross-shard ACID transactions with two-phase commit

`ShardedCluster.transaction()` collects writes, routes each one to its shards, and commits them
all with 2PC on exit:

1. **Prepare.** Each shard applies the transaction's operations to private copies of the
   affected documents (a later operation sees an earlier one's result). It checks the
   collection's validator (here: no negative balance), refuses documents locked by another
   prepared transaction, locks the documents it will change, and logs `PREPARED` with the new
   documents. Then it votes YES; otherwise NO.
2. **Decide.** All YES: the coordinator logs `COMMIT` (the commit point) and tells the shards,
   which install the new documents and unlock. Otherwise the YES voters abort.

ACID across shards follows from that: **atomicity** from 2PC, **consistency** from the
validators checked at prepare, **durability** from the logs, and **isolation** at a simple read
committed level. Readers see only committed documents, and another writer touching a locked
document gets `WriteConflict` instead of waiting. The demo's scenarios:

| Scenario | Result |
|---|---|
| alice (shard-a) sends 30 to nadia (shard-b) | COMMIT on both |
| omar sends 500 to bob | shard-b votes NO (negative balance): ABORT, nothing changes |
| coordinator crashes after PREPARE | bob and omar stay locked; readers see the old balances; a writer gets `WriteConflict`; after recovery, presumed ABORT |
| coordinator crashes after COMMIT reached shard-a only | the total is briefly 195; recovery resends COMMIT; the total returns to 200 |

MongoDB itself provides multi-document transactions inside one replica set
(`mongo_demo.py --mode local-tx`). A MongoDB sharded cluster (mongos with config servers) also
runs distributed transactions, using two-phase commit between shards internally. The lab's
two MongoDB instances are deliberately independent, so the application must coordinate them,
which shows the protocol instead of hiding it:

- **Prepare:** inside a local MongoDB transaction on each instance, check the balance, mark
  the account `pending: {tx, delta}` (that is the lock), and insert a `prepared` entry into
  `participant_log`.
- **Decide:** insert `{_id: tx, decision: "commit"}` into the coordinator collection. That
  insert is the commit point.
- **Finish:** in a local transaction on each instance, apply the delta, clear `pending`, and mark
  the log entry. `--mode recover` finishes every `prepared` entry using the coordinator's
  decision, or presumes abort when there is none.

`--crash after-prepare` and `--crash after-decision` end the process at those points, so the
in-doubt state is visible in MongoDB itself (`--mode status`).

## Part 5 - Tenant-aware queries

A software-as-a-service database serves many customer companies (tenants). There are three
common layouts: a database per tenant (strong isolation, many databases), a collection per
tenant, or one shared collection with a `tenant_id` in every document (cheapest, and the one
used here). With a shared collection, isolation is enforced by code, so it must be impossible
to forget.

`TenantSession` takes the tenant from authentication, never from the request, and:

- wraps every filter as `{"$and": [{"tenant_id": t}, filter]}`. A filter such as
  `{"$or": [{"tenant_id": "globex"}, ...]}` can only narrow the result, never widen it. Merging
  keys into the user's dict would let a crafted filter replace or bypass the tenant condition;
- stamps inserts with the tenant and refuses documents that name another tenant;
- refuses any update that touches `tenant_id`;
- prepends `$match` to pipelines and limits `$lookup` to the tenant's own documents (otherwise a
  join on `owner` would pull in other tenants' tickets for the same owner name);
- shards on `tenant_id`, so every tenant query is targeted to one shard.

On MongoDB (`--mode tenants`), the same wrapper runs over PyMongo, and a compound index
`{tenant_id: 1, priority: 1}` makes the scoped query an `IXSCAN` on that index. Put the tenant
first in every compound index. A tenant that grows large becomes a hot shard (a "noisy
neighbour"); directory-based placement, used in the home practice, lets it move to its own
shard.

## Files

| File | Purpose |
|---|---|
| `nosql_models.py` | Bitcask key-value store, wide-column table, property graph, and a demo of each |
| `docdb.py` | Document database with MQL: queries, updates, projection, indexes, explain, aggregation |
| `sharding.py` | Router (targeted / scatter-gather), cross-shard 2PC transactions, tenant sessions |
| `test_lab10.py` | Offline checks for every module |
| `compose.lab10.yaml` | Two independent single-node MongoDB 7.0 replica sets: shard-a (27031), shard-b (27032) |
| `mongo_demo.py` | Engine-versus-MongoDB comparison, local transaction, 2PC across the instances with crash and recovery, tenant scoping |
| `requirements.txt` | PyMongo, needed only for `mongo_demo.py` |
| `practice/` | After-class implementation assignment, public tests, and an optional MongoDB checker |

## Run the offline examples

```powershell
.\.venv\Scripts\python.exe labs\lab10\nosql_models.py
.\.venv\Scripts\python.exe labs\lab10\docdb.py
.\.venv\Scripts\python.exe labs\lab10\sharding.py
.\.venv\Scripts\python.exe labs\lab10\test_lab10.py
```

## Run the MongoDB part

Install PyMongo into the course environment once, then start the two instances from the
repository root. The first start downloads the `mongo:7.0` image (about 1.2 GB unpacked); the
health check also initiates each one-member replica set.

```powershell
.\.venv\Scripts\python.exe -m pip install -r labs\lab10\requirements.txt
docker compose -f labs/lab10/compose.lab10.yaml up -d
docker compose -f labs/lab10/compose.lab10.yaml ps
```

Wait until both show `healthy`, then:

```powershell
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode compare
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode local-tx
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode 2pc
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode tenants
```

To see a transfer stuck in doubt and then resolved:

```powershell
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode 2pc --crash after-prepare
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode status
.\.venv\Scripts\python.exe labs\lab10\mongo_demo.py --mode recover
```

`status` shows the two accounts as `locked by tx-...`; `recover` aborts them because no decision
was recorded. With `--crash after-decision`, `recover` commits instead. In both cases the total
of the four balances is 200 afterwards. `--mode reset` drops the lab's databases;
`docker compose -f labs/lab10/compose.lab10.yaml down -v` removes the containers and their
volumes.

## Home implementation practice

After class, complete [Practice 10](practice/README.md). Students write their own MQL matcher
and updater, then a multi-tenant store with directory-based placement, tenant moves, and
cross-shard credit transfers with two-phase commit and crash recovery. With MongoDB running,
`check_against_mongo.py` compares their matcher with MongoDB on generated queries.

## Discussion and design limits

- An order with 10,000 line items: embed the items or reference them? What limit does MongoDB
  place on one document (16 MB), and what does that imply?
- Which queries in your own projects would become scatter-gather under each candidate shard key?
- Why is the coordinator's COMMIT record, not the shards' YES votes, the commit point?
- The lab's cross-shard isolation is read committed. Describe an anomaly that a reader could
  see while a transfer is half-committed after a coordinator crash, and how a snapshot read
  timestamp (as in MongoDB's sharded transactions) avoids it.
- Which is safer for tenant isolation: one shared collection with a scoping wrapper, or a
  database per tenant? What does each cost?
