# Lab 9 - Distributed Databases and Vector Search

Week 9 has two halves. The first half is about running one database on many machines:
electing a leader with Raft, keeping data correct when the network splits, committing a
transaction across shards with two-phase commit, and choosing how to partition data. The
second half is about a new kind of query: find the stored vectors closest to a query
vector. Students compare exact k-nearest-neighbour search with approximate indexes (IVF and
HNSW) and use them in a small Retrieval-Augmented Generation (RAG) system that answers
questions from this course's own lab guides.

## Learning outcomes

By the end of the lab, students should be able to:

- Trace a Raft election: terms, votes, the "log at least as up to date" rule, randomized
  timeouts, heartbeats, and the majority rule for committing entries.
- Explain what a network partition does to a CP system and to an AP system, and measure
  the trade-off: refused requests versus stale reads and lost writes.
- Run two-phase commit, name its commit point, and explain why a participant that voted
  YES can block when the coordinator fails.
- Compare range, hash, and consistent-hash partitioning on balance, range queries, hot
  spots, and the data moved when a node is added.
- Compute exact k-NN with cosine, dot-product, and L2 metrics, and explain why exact search
  stops scaling.
- Explain how IVF and HNSW find approximate neighbours, and read a recall-versus-cost table.
- Build a RAG pipeline (chunk, embed, index, retrieve, prompt, answer with citations) and
  evaluate its retrieval.

## How this lab fits the course

Lab 7 kept concurrent transactions correct on one server, and Lab 8 brought one server back
after a crash. Lab 8's disaster recovery plan already needed replicas, failover, and
in-doubt transactions; Lab 9 builds those pieces. Raft is how a replicated log decides who
may accept writes, two-phase commit is what `pg_prepared_xacts` was listing, and
partitioning decides which machine holds which row. Vector indexes continue Lab 4's index
structures: a B+ tree finds equal or ordered keys, an R-tree finds nearby points in two
dimensions, and HNSW finds nearby points in hundreds of dimensions.

After class, students complete the independent implementation practice.

## Part 1 - Leader election with Raft

A replicated database needs one node to order the writes; otherwise two replicas could
accept conflicting changes. Raft (Ongaro and Ousterhout, 2014) chooses that leader and
replicates its log. `raft.py` implements the election and log replication rules in a
deterministic simulation: one seeded random generator draws every timeout and message
delay, and time moves in integer ticks.

**Terms and roles.** Time is divided into terms numbered 1, 2, 3, and so on. Each term has at
most one leader. A node is a follower, a candidate, or a leader. Any message with a higher
term makes the receiver adopt that term and become a follower (`become_follower()`).

**Election.** A follower that hears nothing from a leader for its election timeout (drawn
from 150-300 ticks, `reset_election_timer()`) starts an election: it increments its term,
votes for itself, and sends `RequestVote` to everyone (`start_election()`). A node grants its
vote (`on_RequestVote()`) only if:

1. the request's term is its current term,
2. it has not voted for someone else in this term, and
3. the candidate's log is at least as up to date as its own: a higher last term, or the
   same last term and at least as many entries.

A candidate with votes from a majority (3 of 5) becomes leader (`maybe_win()`). Rule 3 means a
node that missed committed entries can never win, so committed data survives every change of
leader.

**Heartbeats and log replication.** The leader sends `AppendEntries` every 50 ticks
(`broadcast_append()`), with new entries if there are any. Each message carries the index
and term of the entry just before the new ones. A follower accepts only if it has that same
entry (`on_Append()`). If it does not, the leader backs up one entry and retries. Conflicting
follower entries are deleted and replaced. This keeps every log a prefix-copy of the
leader's.

**Commit.** An entry is committed when the leader has stored it on a majority and the entry is
from the leader's current term (`advance_commit()`). A new leader therefore appends a no-op
entry first: once that commits, every earlier entry is known to be committed. A node applies
committed entries to its key-value state in log order (`apply_committed()`).

**Reads.** A leader cut off from the majority may not know that it has been replaced. It
serves a linearizable read only while it holds a lease: a majority answered it within one
minimum election timeout (`has_lease()`). Any node can serve a non-linearizable local read,
which may be stale.

Not included: snapshots, membership changes, disk persistence, pre-vote, batching, and
client sessions. `Cluster.start()` keeps a node's term, vote, and log (Raft's persistent
state) and rebuilds the rest.

`python labs/lab09/raft.py` prints one run: D wins term 1, commits `x = 1`, stops, C wins
term 2, and D rejoins as a follower and receives the missing entries.

## Part 2 - Network partitions and the CAP trade-off

The CAP theorem says that during a network partition (P), a replicated system must choose
between consistency (C: every read sees the latest committed write) and availability (A:
every request to a working node gets an answer). When the network is healthy, both are
possible; the PACELC refinement adds that even then, systems trade latency against
consistency.

`cap_demo.py` runs the same partition, {A, B} | {C, D, E}, against two stores:

- **CP: Raft.** The old leader in the minority keeps believing it is leader for a while, and
  it even appends a client's write to its log. That write can never commit, because the
  minority cannot reach a majority. The majority elects a new leader in a higher term and
  continues. Linearizable reads on the old leader are refused. After the partition heals, the
  old leader sees the higher term, steps down, and its uncommitted entry is overwritten. No
  client was ever told that write succeeded.
- **AP: last-writer-wins.** Every replica accepts reads and writes locally and copies them to
  the replicas it can reach. Both sides keep answering, so replicas disagree during the
  partition. When it heals, each key keeps the version with the largest timestamp, and the
  other side's acknowledged write disappears without an error.

The `availability` scenario sends 200 random requests during the partition, 40% from the
minority side:

| System | Minority requests answered | Majority requests answered | Stale reads | Acknowledged writes lost |
|---|---|---|---|---|
| CP (Raft) | 0 / 83 | 117 / 117 | 0 | 0 |
| AP (LWW) | 83 / 83 | 117 / 117 | 43 | 5 |

Neither column is "better": a bank ledger needs the first row, and a shopping cart or a
"likes" counter may prefer the second. Real AP systems reduce the damage with vector clocks,
sibling versions, or CRDTs instead of plain last-writer-wins.

**Why randomized timeouts.** The `split-vote` scenario measures the first election over 200
seeds:

| Election timeout | Runs with no leader after 5,000 ticks | Mean elections | Mean ticks to a leader |
|---|---|---|---|
| exactly 150 | 200 / 200 | - | - |
| 150-160 | 0 / 200 | 14.6 | 602 |
| 150-300 | 0 / 200 | 1.3 | 197 |
| 150-600 | 0 / 200 | 1.1 | 247 |

With identical timeouts, every node becomes a candidate at the same moment, votes for itself,
and the vote splits forever. A wider range separates candidates but makes every failover
wait longer, which is why Raft recommends a range a few times the message delay.

## Part 3 - A distributed transaction coordinator (two-phase commit)

A transfer from alice (shard 1) to carol (shard 2) must change both shards or neither.
`two_phase_commit.py` implements a coordinator and two participants, each with a durable log
in the style of Lab 8.

1. **Prepare.** The coordinator sends `PREPARE` with each shard's changes. A participant checks
   its constraints and locks, forces a `PREPARED` record that contains the new values, and votes
   YES. Or it votes NO and forgets the transaction. A participant that does not answer counts
   as NO.
2. **Decide.** If every vote is YES, the coordinator forces `COMMIT` to its own log. That write
   is the commit point. It then sends the decision and writes `END` once every participant
   has acknowledged. Otherwise it tells the YES voters to abort.

With **presumed abort**, the coordinator does not need to log an abort: if it has no decision
record for a transaction, the answer is ABORT. Participants make `commit()` and `abort()`
idempotent, because a recovering coordinator may resend a decision.

| Scenario (`--scenario`) | What happens |
|---|---|
| `commit` | Both vote YES; 8 messages; both shards change |
| `vote-no` | alice cannot pay 500; nobody changes |
| `participant-down` | shard 2 does not answer the prepare; the transfer aborts |
| `coordinator-crash-before-decision` | both shards voted YES and hold locks; they cannot decide alone, so alice stays locked until the coordinator returns and presumes abort |
| `coordinator-crash-after-decision` | COMMIT is in the coordinator's log but only shard 1 heard it; the total is briefly 170 instead of 200; the restarted coordinator resends COMMIT |
| `participant-crash-after-yes` | shard 2 rebuilds its locks from its log after restarting and asks the coordinator for the outcome |

The fourth row is 2PC's known weakness: it is **blocking**. A YES voter has given up the right
to abort but does not know the outcome. Real systems replicate the coordinator's decision
with consensus (for example Paxos Commit, or Spanner running 2PC over Paxos groups) so that
it survives the coordinator's failure. Long business processes often use sagas instead:
a sequence of local transactions with compensating actions, which never block but are not
isolated.

PostgreSQL provides the participant side: `PREPARE TRANSACTION 'gid'` makes a transaction
durable but undecided, `pg_prepared_xacts` lists those transactions, and
`COMMIT PREPARED` / `ROLLBACK PREPARED` decides them, from any session.

## Part 4 - Data partitioning strategies

`partitioning.py` partitions 100,000 sequential customer ids over four shards:

| Measure | Range | Hash mod N | Consistent hashing (100 vnodes) |
|---|---|---|---|
| Balance of existing ids (largest / average) | 1.000 | 1.003 | 1.023 |
| Where the next 10,000 new ids go | all on s4 | spread evenly | spread evenly |
| Shards asked by `id BETWEEN 30000 AND 30999` | 1 | 4 | 4 |
| Keys that move when a 5th shard is added | 12.5% (split s4) | 80.0% | 19.7% |

- **Range** keeps related keys together, so range scans touch few shards. Inserts with
  increasing keys (time stamps, sequences) all hit the last shard: a write hot spot.
  Adding capacity means splitting one shard, and the new shard only relieves that one.
- **Hash mod N** spreads keys evenly but destroys key order, and changing N reassigns almost
  every key: with N to N+1, only about 1/(N+1) of keys stay put.
- **Consistent hashing** puts nodes and keys on the same hash ring. Each node owns the arc
  before its points, so adding a node takes keys only from its neighbours, about 1/(N+1) of
  the data. With one point per node the arcs are very uneven. Virtual nodes (many points per
  node) fix that: the mean skew over 20 rings falls from 1.99 (1 vnode) to 1.35 (10),
  1.11 (100), and 1.04 (1,000). The first replicas of a key are the next distinct nodes
  clockwise (`preference_list()`), as in Dynamo and Cassandra.

No placement can split a single hot key. If 20% of requests go to a few keys, those keys'
shards stay busier; caching, replication, or adding a random suffix to the key are the usual
remedies.

PostgreSQL's declarative partitioning splits one table into partitions on one server. The
planner skips partitions that the `WHERE` clause rules out (partition pruning). Systems such
as Citus put partitions on different servers, which is sharding. The demo shows that a
one-month range query reads one of four quarterly partitions, an equality on a hash key reads
one partition, and a range on a hash key reads all four.

## Part 5 - Vector search: k-NN and approximate nearest neighbours

An embedding model maps text, images, or users to vectors so that similar items get nearby
vectors. Searching then means: given a query vector, find the k stored vectors closest to
it.

**Metrics** (`vector_search.knn()`): cosine similarity compares directions only; the dot
product also rewards long vectors; L2 distance measures straight-line distance. On
normalized vectors all three give the same ranking. The demo shows them disagreeing on
unnormalized vectors.

**Exact k-NN** compares the query with every vector: O(n · d) per query. It is always
correct, and it is the ground truth for measuring the others. Space-partitioning trees
such as k-d trees and Lab 4's R-tree help in a few dimensions but not in hundreds: in high
dimensions distances concentrate. For random points, the nearest-to-farthest distance ratio
is 0.003 in 2-D but 0.88 in 1,000-D, so almost no subtree can be ruled out.

**Approximate nearest neighbour (ANN)** indexes give up a little recall for far less work.
Recall@k is the fraction of the true k nearest neighbours that the index returns.

- **IVF** (inverted file): k-means groups the vectors into `nlist` clusters. A query
  compares itself with every centroid, then scans only the `nprobe` closest clusters. More
  probes mean higher recall and more work.
- **HNSW** (hierarchical navigable small world; Malkov and Yashunin, 2018): every vector is a
  graph node linked to about M near neighbours. Each node also appears on higher layers with
  probability that falls exponentially, so upper layers are sparse "express lanes". A
  search starts at the top entry point, moves greedily toward the query on each layer, and on
  layer 0 runs a best-first search that keeps `ef` candidates (`_search_layer()`). When
  linking a new node, the selection heuristic (`_select_neighbors()`) skips a candidate that
  is closer to an already chosen neighbour than to the new node. This spreads links in
  different directions so that searches can cross between clusters. Larger M and
  `ef_construction` build a better graph more slowly; a larger `ef` at query time raises
  recall and cost.

`ann_benchmark.py` (5,000 clustered 64-d vectors, 100 queries, recall@10):

| Method | Recall | Distance computations / query |
|---|---|---|
| exact | 1.000 | 5,000 |
| IVF nprobe = 1 / 4 / 16 | 0.616 / 0.900 / 0.999 | 165 / 381 / 1,220 |
| HNSW M = 12, ef = 10 / 40 / 160 | 0.481 / 0.760 / 0.972 | 160 / 299 / 653 |

Compare the distance column first. The milliseconds depend on the implementation: exact
search (0.10 ms) and IVF (0.04-0.15 ms) are a few NumPy matrix products, while this HNSW is a
Python loop over a graph (1.5-9 ms), so it loses on time at this size even though it computes
far fewer distances. The distance count is what grows with n: exact search grows linearly,
while HNSW's search cost grows roughly with log n. This data set has 50 well-separated
clusters, which is ideal for IVF; HNSW needs a larger `ef` here because the points inside
one cluster behave like random 64-d noise. Production libraries (FAISS, hnswlib, pgvector)
implement the same algorithms in compiled code.

The `vectors` mode of the PostgreSQL demo stores the RAG embeddings in a `float8[]` column
and runs exact k-NN with a SQL cosine function. The plan is a sequential scan plus a sort, and
the top 5 matches Python's. The pgvector extension, which is not in the course image, adds a
`vector` type, distance operators, and `CREATE INDEX ... USING hnsw` or `ivfflat`.

## Part 6 - A basic Retrieval-Augmented Generation system

A language model answers from what it learned in training, which may be outdated, private
data it never saw, or invented. RAG retrieves relevant passages first and puts them in the
prompt, so the answer can be grounded in, and cited to, real sources.

`rag.py` answers questions from the course's lab guides:

1. **Chunk.** Each `labs/labNN/README.md` is split by headings, code blocks are removed, table
   rows become sentences, and long sections become overlapping windows of about 120 words.
   Small chunks retrieve precisely; overlap keeps a sentence from being cut away from its
   context.
2. **Embed.** `HashingEmbedder` hashes words and word pairs into 1,024 slots, weighted by
   TF-IDF. Words that never occur in the corpus are dropped, so an unrelated question embeds
   to the zero vector. It needs no model download and gives the same result on every machine.
   A neural embedding model would also match synonyms that share no words.
3. **Index and retrieve.** The chunk vectors go into the HNSW index from Part 5; a question
   retrieves its k closest chunks.
4. **Prompt.** `build_prompt()` shows exactly what a language model would receive: rules
   ("answer only from the context, cite passages, say when the notes do not cover it"), the
   numbered passages, and the question. `--show-prompt` prints it.
5. **Answer.** To stay offline and repeatable, the lab's generator is extractive: it returns the
   retrieved sentences most similar to the question, each with a citation. Every sentence
   comes from the notes, so the answer cannot state anything the context does not.
   Questions whose best match is below `min_score` get "the course notes do not cover this
   question".

`python labs/lab09/rag.py --eval` measures retrieval on twelve questions about Labs 2-8:
both exact search and HNSW put a chunk from the right lab in the top 4 for all 12. That is a
small, friendly test set: it checks the pipeline, not a production system. Real evaluations
use many more questions and also judge the answers' faithfulness to the retrieved context.

## Files

| File | Purpose |
|---|---|
| `raft.py` | Deterministic simplified Raft: election, heartbeats, log replication, majority commit, lease reads |
| `cap_demo.py` | Partition scenarios: CP Raft versus AP last-writer-wins, the availability table, split votes |
| `two_phase_commit.py` | Coordinator and participants with durable logs, presumed abort, six failure scenarios |
| `partitioning.py` | Range, hash, and consistent-hash partitioners and the balance / movement experiment |
| `vector_search.py` | Exact k-NN with three metrics, IVF, and HNSW from scratch |
| `ann_benchmark.py` | Recall and cost of exact search, IVF, and HNSW on one data set |
| `rag.py` | Chunking, hashed TF-IDF embeddings, HNSW retrieval, grounded prompt, extractive answers, evaluation |
| `test_lab09.py` | Offline checks for every module |
| `postgres_distributed_demo.py` | Declarative partitioning and pruning, `PREPARE TRANSACTION`, exact k-NN in SQL |
| `db/schema.sql` | Range, hash, and list partitioned tables, two "shard" tables, a vector table and cosine function |
| `db/seed.sql` | Repeatable fixture: 20,000 customers, 100,000 orders, six stores, four accounts |
| `db/reset.sql` | Optional destructive reset of only the `lab09` schema |
| `practice/` | After-class implementation assignment and public tests |

## Run the offline examples

These need only the course `.venv` (NumPy is already installed):

```powershell
.\.venv\Scripts\python.exe labs\lab09\raft.py
.\.venv\Scripts\python.exe labs\lab09\cap_demo.py --scenario all
.\.venv\Scripts\python.exe labs\lab09\two_phase_commit.py --scenario all
.\.venv\Scripts\python.exe labs\lab09\partitioning.py
.\.venv\Scripts\python.exe labs\lab09\vector_search.py
.\.venv\Scripts\python.exe labs\lab09\ann_benchmark.py
.\.venv\Scripts\python.exe labs\lab09\rag.py "Why must the log be flushed before a dirty page is written?"
.\.venv\Scripts\python.exe labs\lab09\rag.py --eval
.\.venv\Scripts\python.exe labs\lab09\test_lab09.py
```

`ann_benchmark.py` takes about a minute, mostly to build two HNSW graphs in Python;
`--n 2000` is faster. Ask `rag.py` your own questions, add `--show-prompt` to see the
grounded prompt, or `--exact` to compare retrieval without HNSW.

## Prepare the PostgreSQL fixture

Start the course service if needed, then load the schema and fixture from the repository
root:

```powershell
docker compose --env-file .env -f infra/compose.yaml start postgres
Get-Content .\labs\lab09\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
Get-Content .\labs\lab09\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

macOS or Linux:

```sh
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab09/db/schema.sql
docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab09/db/seed.sql
```

The seed may be rerun. `db/reset.sql` drops only the `lab09` schema.

## Run the PostgreSQL examples

```powershell
.\.venv\Scripts\python.exe labs\lab09\postgres_distributed_demo.py --mode partitioning
.\.venv\Scripts\python.exe labs\lab09\postgres_distributed_demo.py --mode twophase
.\.venv\Scripts\python.exe labs\lab09\postgres_distributed_demo.py --mode vectors
```

- **partitioning:** rows per partition, and the plan of five queries. Look for which
  partitions appear in each plan: one quarter for the one-month range, one hash partition for
  `id = 42`, all four for a range on the hash key.
- **twophase:** PostgreSQL disables `PREPARE TRANSACTION` by default
  (`max_prepared_transactions = 0`), and the demo says so. To see the full demo, an instructor
  enables it once and restarts the server:

  ```powershell
  docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "ALTER SYSTEM SET max_prepared_transactions = 10"
  docker compose --env-file .env -f infra/compose.yaml restart postgres
  ```

  Then both "shard" sessions prepare and disconnect, `pg_prepared_xacts` still lists their
  transactions, another update of alice times out on the lock they hold, and
  `COMMIT PREPARED` from a third session finishes them (alice 100 -> 70, carol 50 -> 80).
  `ALTER SYSTEM RESET max_prepared_transactions` and a restart restore the default. If a demo is
  interrupted, `--mode cleanup` rolls back the lab's leftover prepared transactions.
- **vectors:** loads the RAG chunks into `lab09.doc_chunks` and prints the SQL top 5, which
  matches Python's exact search.

## Home implementation practice

After class, complete [Practice 9](practice/README.md): a sharded, replicated vector store.
It places documents on a consistent-hash ring with replicas, answers k-NN queries by
scatter-gather across shards, keeps answering when nodes fail (and says when an answer may
be incomplete), and inserts batches atomically with two-phase commit. A short report measures
recall and rebalancing and analyses the store's CAP behaviour.

## Discussion and design limits

- Why must a Raft leader commit an entry from its own term before it can treat older entries
  as committed?
- During a partition, the old leader accepted a write into its log. Why was no client harmed?
  What would go wrong if a follower served linearizable reads?
- Which systems you use every day choose AP? What do they do about conflicting writes?
- Where in 2PC is the commit point? What does a participant hold while it is in doubt, and
  for how long?
- When would you choose range partitioning despite its hot spots?
- Your RAG system answered confidently from the wrong chunk. Which stage would you inspect
  first, and what measurement would show the problem?
