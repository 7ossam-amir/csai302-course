# Practice 9 — Build a sharded, replicated vector store

## Scenario

A search service stores document embeddings on several machines. No single machine holds
everything, any machine may fail, and a batch of new documents must appear all at once or
not at all. Build an in-memory model of that store: consistent-hash placement with replicas,
a write quorum, scatter-gather k-NN search, repair after a failure, and two-phase commit for
batches. Then measure it and analyse its CAP behaviour.

This is an in-memory teaching simulator, not a production database. Use only the
Python standard library and NumPy. You may read the Lab 9 files for ideas, but write
your own classes in `student.py`; do not import `partitioning.py` or
`two_phase_commit.py`. (Your experiment may import `vector_search.py`; see below.)

## Files and API

Implement the following in `student.py`:

```python
class Unavailable(Exception): ...
class TransactionAborted(Exception): ...

class ShardedVectorStore:
    def __init__(self, nodes, dim: int, *, replication: int = 3, write_quorum: int = 2,
                 vnodes: int = 64, capacity: int | None = None): ...
    # membership and failures
    def placement(self, doc_id: str) -> list[str]: ...
    def add_node(self, name: str) -> int: ...
    def remove_node(self, name: str) -> int: ...
    def fail(self, name: str) -> None: ...
    def recover(self, name: str) -> int: ...
    def live_nodes(self) -> list[str]: ...
    # data
    def upsert(self, doc_id: str, vector, text: str = "") -> list[str]: ...
    def upsert_many(self, items) -> dict[str, list[str]]: ...
    def get(self, doc_id: str): ...
    def search(self, query, k: int) -> dict: ...
    def copies(self) -> dict[str, list[str]]: ...
```

Keep these names and signatures. Explain any small representation choices in your
`results.md`.

## Required behavior

### Construction and inputs

- `nodes` is an iterable of distinct, non-empty node names. `dim` is a positive integer.
  The constructor requires `1 <= write_quorum <= replication <= len(nodes)`; anything else raises
  `ValueError`.
- Document ids are non-empty strings. A vector must have exactly `dim` finite numbers and must
  not be all zeros; store it normalized to length 1. Invalid ids or vectors raise
  `ValueError`. An unknown node name passed to `fail`, `recover`, or `remove_node` raises
  `KeyError`.

### Placement (consistent hashing)

- Put `vnodes` points per node on a hash ring. Use a stable hash such as
  `hashlib.blake2b`, not Python's `hash()`, which changes between runs.
- `placement(doc_id)` returns the document's `replication` **distinct** nodes: walk the ring
  clockwise from the document's hash and take each new node name you meet. The first one is
  the primary. Placement depends only on the ring, not on which nodes are up.

### Writes

- `upsert(doc_id, vector, text)` writes the document to every **live** node of its placement.
  If fewer than `write_quorum` of those nodes are live, raise `Unavailable` and write
  nothing. Return the list of nodes that received the write. Writing an existing id replaces
  the document (a newer version).
- `upsert_many(items)` takes `(doc_id, vector, text)` tuples and is atomic, using two-phase
  commit across every node involved:
  - Validate everything first. A duplicate id in one batch raises `ValueError`.
  - If any document has fewer than `write_quorum` live placement nodes, raise `Unavailable`
    and write nothing.
  - Phase 1: each involved node votes. A node votes NO if accepting its share of the batch
    would give it more than `capacity` documents (when `capacity` is not `None`). If any node
    votes NO, raise `TransactionAborted`; no node may keep any document of the batch.
  - Phase 2: every node applies its share. Return `{doc_id: [nodes written]}`.
  - An empty batch returns `{}`.
- `upsert` behaves like a one-item `upsert_many`, including the capacity rule.

### Failures, repair, and membership

- `fail(name)` marks a node down. A down node keeps its stored documents (a crash, not a lost
  disk) but takes no part in writes or searches.
- `recover(name)` marks it up and runs anti-entropy repair. For every document whose placement
  includes this node, find the newest version held by any live node, and copy it to every
  live placement node whose copy is missing or older (this node, and also any replica that
  came back earlier while the newest copy was unreachable). Return the number of copies
  repaired.
- `add_node(name)` adds a node to the ring and rebalances. Each node must end up holding
  exactly the documents whose placement includes it, at their newest version. Return the
  number of copies written to nodes during the rebalance. A name already in use raises
  `ValueError`.
- `remove_node(name)` takes a node out of the ring permanently. It hands its copies over
  first, then rebalances, and returns the number of copies written. Removing a node that would
  leave fewer nodes than `replication` raises `ValueError`.
- `live_nodes()` returns the sorted names of the nodes that are up. `copies()` returns
  `{node: sorted document ids}` for every node, up or down.

### Reads

- `get(doc_id)` returns the newest text found on a live placement node. It returns `None`
  for an id that was never written, and raises `Unavailable` if the id exists but no live
  node holds it.
- `search(query, k)` validates `query` like a stored vector and requires a positive integer
  `k` (otherwise `ValueError`). It asks every live node for its local top `k` by cosine
  similarity, then merges the answers: each document appears once, at its newest version.
  It returns a dictionary:

  | Key | Value |
  |---|---|
  | `results` | up to `k` `(doc_id, score)` pairs, best first; ties broken by `doc_id` |
  | `complete` | `True` if every document ever written has at least one live copy |
  | `nodes_asked` | number of live nodes asked |
  | `distances` | total similarity computations across those nodes |

  When `complete` is `True`, `results` must equal an exact search over all documents.

The store only needs to support calls from one Python process. It does not need threads,
networking, persistence, deletes, or hinted handoff.

## Required cases to reason about

Your implementation and report should cover:

1. Where five documents are placed with `replication=3`, and what changes after `add_node`.
2. A search while one node is down (still complete) and while all replicas of some document
   are down (incomplete).
3. A write while one replica is down, followed by `recover`: which version is returned before
   and after.
4. A write that fails with `Unavailable`, and why the quorum rule exists.
5. A batch that aborts because one node is full: show that no node kept any part of it.
6. The CAP position of your store: what it gives up during a partition for reads and for
   writes, and how changing `write_quorum` moves that trade-off. Find a sequence of writes and
   failures, with `write_quorum` smaller than `replication`, after which `search` reports
   `complete` but returns an old version of a document. Explain why, and which rule about
   read and write quorums (R + W > N) would prevent it.

## Experiment

Write `experiment.py` that measures, on at least 2,000 random documents (`dim` ≥ 32):

- the fraction of copies moved when you add a node, for `vnodes` = 1, 16, and 128, against the
  ideal fraction;
- per-node document counts (balance) for the same `vnodes` values;
- for one query set, recall@10 and distances per query when each live node answers with an
  `HNSWIndex` from `labs/lab09/vector_search.py` (built over that node's documents) instead of
  exact search, for two values of `ef`. Recall is measured against your exact `search`.

Put the tables in `results.md` with a short interpretation.

## Tests and submission

Run the public tests from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab09\practice\test_student.py
```

Add at least four original tests in `test_extra.py`, including one with two failures in a row
and one edge case the public tests do not cover. Do not modify `test_student.py`.

Submit these files:

- Your implementation in `student.py`.
- Your original tests in `test_extra.py`.
- `experiment.py` and its output.
- `results.md`: a table of the six required cases with observed outcomes, the experiment
  tables and their interpretation, the CAP analysis, key invariants, known simplifications,
  and brief evidence from your test runs.
