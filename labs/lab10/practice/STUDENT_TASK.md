# Practice 10 — A query language and a multi-tenant sharded store

## Scenario

A software-as-a-service company keeps each customer company (a tenant) on one of several
database shards. Large tenants are moved to a shard of their own when they grow, and tenants
can send each other credits. You will write the two pieces the lab gave you ready-made: the
MongoDB-style matcher and updater (Part A), and then a tenant-aware store that uses them, with
directory-based placement, tenant moves, and cross-shard credit transfers with two-phase
commit (Part B).

This is an in-memory teaching simulator, not a production database. Use only the
Python standard library. You may read the Lab 10 files for ideas, but write your own
code in `student.py`; do not import `docdb.py` or `sharding.py`.

## Files and API

Implement the following in `student.py`:

```python
class QueryError(ValueError): ...
class WriteError(Exception): ...
class TransactionAborted(Exception): ...
class SimulatedCrash(Exception): ...

def match(doc: dict, query: dict) -> bool: ...
def apply_update(doc: dict, update: dict) -> dict: ...

class TenantStore:
    crash_at: str | None
    last_shards: list[str]
    def __init__(self, shards=("s1", "s2")): ...
    def place_tenant(self, tenant: str, shard: str) -> None: ...
    def shard_of(self, tenant: str) -> str: ...
    def move_tenant(self, tenant: str, target: str) -> int: ...
    def insert(self, tenant: str, collection: str, doc: dict): ...
    def find(self, tenant: str, collection: str, query: dict | None = None) -> list[dict]: ...
    def update(self, tenant: str, collection: str, query: dict, update: dict) -> int: ...
    def transfer(self, from_tenant: str, to_tenant: str, amount) -> str: ...
    def fail(self, shard: str) -> None: ...
    def restart(self, shard: str) -> list[str]: ...
    def recover(self) -> dict[str, str]: ...
    def in_doubt(self) -> list[str]: ...
```

Keep these names and signatures. Explain any small representation choices in your
`results.md`.

## Part A — The query language

### `match(doc, query)`

Return whether a document matches a MongoDB-style filter. Support:

| Kind | Operators |
|---|---|
| comparison | implicit equality, `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin` |
| element | `$exists` |
| array | `$size`, `$all`, `$elemMatch` |
| logical | `$and`, `$or`, `$nor` (top level, non-empty lists), `$not` (field level) |

Follow MongoDB's rules, which `docdb.py` also follows and which were checked against a real
MongoDB server:

- A **dotted path** such as `"specs.ram_gb"` walks into nested documents. A path through an array
  of documents (`"items.sku"`) reaches the field in every element, and a numeric part
  (`"ratings.0"`) indexes an array.
- A condition on an **array** field matches if the whole array or any element satisfies it:
  `{"tags": "sale"}` matches `{"tags": ["sale", "work"]}`.
- `{"field": None}` matches documents where the field is `null` **or missing**. `$ne` matches
  documents without the field. `$nin` is the negation of `$in`.
- `$gt`, `$gte`, `$lt`, `$lte` compare numbers with numbers and strings with strings only:
  `{"price": {"$gt": "100"}}` matches no document whose price is a number. Booleans are not
  numbers. You may assume their arguments are numbers or strings.
- `$elemMatch` needs **one** element to satisfy every condition. Compare this with
  `{"items.sku": "p1", "items.qty": 2}`, where different elements may satisfy each part.
- An unknown operator, a top-level `$and` / `$or` / `$nor` that is not a non-empty list, or a
  `$in` / `$nin` without a list raises `QueryError`.

### `apply_update(doc, update)`

Return an updated **copy**; never change `doc`. Support `$set`, `$unset`, `$inc`, `$push` (with
`$each`), `$addToSet` (with `$each`), and `$pull` (a value, an operator condition such as
`{"$lt": 5}`, or a sub-document filter). Dotted paths create missing nested documents. Raise
`WriteError`, leaving nothing changed, for: an empty update or one without `$` operators; an
unknown operator; two paths where one equals or contains the other (`"a"` and `"a.b"`); any
change to `_id`; `$inc` with a non-number argument or on a non-number field; and `$push`,
`$addToSet`, or `$pull` on a field that exists but is not an array.

## Part B — The tenant-aware sharded store

### Placement (directory-based sharding)

- The constructor takes at least two distinct shard names (otherwise `ValueError`).
- `place_tenant(tenant, shard)` records the tenant's shard in a directory (a lookup table). A
  tenant id is a non-empty string (`ValueError`); an unknown shard raises `KeyError`; placing a
  tenant twice raises `ValueError`. `shard_of(tenant)` reads the directory (`KeyError` for an
  unknown tenant).
- Every data operation for a tenant goes to its shard only. After each one, `last_shards` is
  the list of shard names that the operation touched.
- `move_tenant(tenant, target)` moves all of the tenant's documents to the target shard and
  updates the directory. Return the number of documents moved (0 if it is already there).
  Refuse with `TransactionAborted` while the tenant has an unfinished transfer.

### Tenant-scoped operations

The tenant id comes from the caller's authentication, never from a document or a filter.

- `insert(tenant, collection, doc)` stores a copy with `tenant_id` set to the tenant. A document
  that names another tenant raises `PermissionError`. If `_id` is missing, generate one; a
  duplicate `_id` in the tenant's collection raises `WriteError`. Return the `_id`.
- `find(tenant, collection, query)` returns copies of the tenant's matching documents. No filter
  can reach another tenant's documents, even `{"tenant_id": "other"}` or an `$or` naming one.
- `update(tenant, collection, query, update)` applies `apply_update` to every matching document
  of that tenant and returns how many matched. It is all-or-nothing: if the update fails for any
  document, none changes. Changing `tenant_id` raises `PermissionError`.
- A shard that is down (`fail`) makes its tenants' operations raise `ConnectionError`.

### Credit transfers (cross-shard two-phase commit)

- Each tenant may have one wallet: a document with `_id` `"wallet"` in the collection
  `"wallet"`, with a numeric `balance`.
- `transfer(from_tenant, to_tenant, amount)` moves a positive amount atomically and returns
  `"COMMIT"` or `"ABORT"`. A non-positive amount or the same tenant twice raises `ValueError`.
- Phase 1: each participant shard votes. It votes NO if the tenant is unknown or has no wallet,
  the shard is down, the wallet is locked by another unfinished transfer, or the new balance
  would be negative. A YES vote locks the wallet and records the prepared new balance in the
  shard's durable log.
- Phase 2: if every vote is YES, the coordinator records COMMIT in its own durable log (the
  commit point) and tells the shards; otherwise every YES voter aborts. Readers never see a
  prepared balance, only committed ones.
- `crash_at` injects a coordinator failure: `"after-prepare"` (before any decision) or
  `"after-decision"` (after recording COMMIT, before telling any shard). Raise `SimulatedCrash`
  at that point; the coordinator stays down until `recover()`.
- `fail(shard)` loses that shard's volatile state (locks and staged balances) but keeps its data
  and log. `restart(shard)` brings it back, rebuilds the locks of its in-doubt transfers from the
  log, and returns their ids.
- `recover()` brings the coordinator back and resolves every in-doubt transfer on every up
  shard: COMMIT if the coordinator logged COMMIT, otherwise ABORT (presumed abort). Return
  `{transaction id: decision}` for the ones it resolved. `in_doubt()` lists unresolved transfer
  ids on all shards.
- The total of all wallet balances never changes once every transfer is resolved.

## Required cases to reason about

1. Three queries where your matcher's result depends on MongoDB's array rules, and one where
   it depends on `null` / missing.
2. `$elemMatch` versus two separate conditions on the same array.
3. A `move_tenant` between two queries: show the directory and `last_shards` before and after.
4. A filter that tries to read another tenant's data, and why scoping by wrapping the filter
   (`{"$and": [{"tenant_id": t}, filter]}`) is safe while merging keys is not.
5. A transfer that commits, one that aborts on a negative balance, and one in doubt after
   `"after-prepare"`, including what another transfer touching the same wallet does meanwhile.
6. A crash `"after-decision"` while one shard is also down: the order of `restart` and
   `recover` calls that finishes the transfer, and the balances at each step.

## Tests and submission

Run the public tests from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab10\practice\test_student.py
```

If you started the Lab 10 MongoDB instances, also compare your matcher with MongoDB on 1,000
generated queries:

```powershell
.\.venv\Scripts\python.exe labs\lab10\practice\check_against_mongo.py
```

Add at least four original tests in `test_extra.py`, including one for a query edge case and one
with two failures in a row. Do not modify `test_student.py`.

Submit these files:

- Your implementation in `student.py`.
- Your original tests in `test_extra.py`.
- `results.md`: a table of the six required cases with observed outcomes, a comparison of
  directory-based placement with the hash and range placement of Lab 9 (when each fits a
  multi-tenant service), key invariants, known simplifications, the output of
  `check_against_mongo.py` if you ran it, and brief evidence from your test runs.
