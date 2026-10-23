# Lab 6 — Query Optimization & Cost-Based Planning

**Duration:** 2 hours in class, followed by an independent 4–7 hour home practice.

The Week 6 syllabus asks students to collect table statistics and histograms, build a
simple cost model, and compare estimated with actual costs using `EXPLAIN ANALYZE`.
This lab connects those ideas to the access paths a query executor can use.

## Learning outcomes

By the end of the lab, you should be able to:

- Explain why a database optimizer chooses among physical plans and why equivalent
  plans must return the same rows.
- Estimate equality selectivity from null fractions, distinct counts, and most-common
  values (MCVs), then turn selectivity into estimated cardinality.
- Compare sequential and index scan costs while respecting which indexes exist.
- Read PostgreSQL statistics and explain the difference between estimated rows,
  actual rows, buffer activity, planner cost units, and elapsed milliseconds.
- Trace a small optimizer through branches and data structures, then extend the idea
  independently to ranges and multiple predicates.

## How this follows Lab 5

Lab 5 builds query operators such as Volcano iterators, vectorized scans, and joins.
This lab adds the planning decision that comes before those operators run: which
physical access path should produce the rows? Changing from a sequential scan to an
index scan must not change the query result. The optimizer estimates work and selects
a plan; the execution engine still applies the query's predicates and returns the
same qualifying rows.

## Files

| File | Purpose |
|---|---|
| `optimizer.py` | Small, runnable equality-selectivity estimator and cost-based planner |
| `bench_optimizer.py` | Four deterministic cost-comparison scenarios, including stale statistics |
| `test_optimizer.py` | Offline correctness and edge-case checks for the reference implementation |
| `explain_postgres.py` | Read-only JSON `EXPLAIN ANALYZE` plans from the shared course database |
| `db/schema.sql` | Lab-scoped customers and orders tables; only primary-key indexes initially |
| `db/seed.sql` | Repeatable 120,000-order skewed dataset and `ANALYZE` |
| `db/queries.sql` | Read-only row counts, `pg_stats`, and before/after plan queries |
| `db/indexes.sql` | Explicit second step: status and customer indexes on Lab 6 tables only |
| `db/reset.sql` | Optional, destructive drop of only the `lab06` schema |
| `code_trace_task.docx` | Supervised, individual in-lab tracing and documentation submission |
| `practice/` | Home assignment, starter functions, and public tests |

## Core idea: estimates guide a choice

A **logical plan** describes what a query means (for example, filter orders where
`status = 'cancelled'`). A **physical plan** describes how to get those rows. A
sequential scan visits table pages in order and checks every row. An index scan first
traverses an index and then visits matching heap rows. A selective predicate may make
an index attractive; when many rows qualify, reading the whole table can be cheaper.

The model uses relative **cost units**, not milliseconds. Page I/O usually dominates
the simplified comparison; CPU cost accounts for processing rows. PostgreSQL's
`EXPLAIN` costs are also planner units rather than elapsed time, but PostgreSQL uses a
larger model and machine-specific settings.

Statistics help estimate how much work a predicate leaves:

- `null_frac` is the fraction of rows whose column is null. Null rows do not match
  ordinary equality predicates.
- `n_distinct` estimates the number of distinct non-null values.
- MCVs (most-common values) record frequent values and their frequencies over all
  rows. They capture skew such as a status that appears in most orders.
- Histograms summarize the distribution of values that are not in the MCV list.
  The home task uses explicit equal-population histogram boundaries for numeric
  ranges.
- **Selectivity** is the fraction of rows expected to qualify. **Cardinality** is the
  estimated number of qualifying rows: `table rows × selectivity`.

Skew can make a uniform `1 / n_distinct` estimate inaccurate. Stale statistics can
describe last week's data rather than today's. Correlated columns can also break an
independence assumption. Statistics are estimates, not a promise of exact counts.

### Two manual equality examples

Use this fixture: 10,000 rows, 200 pages, `null_frac = 0.05`, `n_distinct = 12`, and
MCVs `hot = 0.60`, `warm = 0.20`. The remaining non-null, non-MCV mass is
`1 - 0.05 - 0.60 - 0.20 = 0.15`; it is spread over `12 - 2 = 10` other values.

| Predicate | Selectivity | Estimated rows | What the model concludes |
|---|---:|---:|---|
| `status = 'hot'` | 0.60 (known MCV) | 6,000 | A frequent value may make an index scan too expensive |
| `status = 'rare'` (not in MCV list) | 0.015 (`0.15 / 10`) | 150 | A rare value may justify an available index |

The decision flow is:

```text
statistics -> selectivity -> estimated rows -> legal candidate plans -> costs -> choice
```

For the Python fixture, the sequential scan costs `200 × 1.0 + 10,000 × 0.01 = 300`
units. With the published default parameters and a status index, the estimated rare
index scan costs `3 + 150 × 0.002 + 150 × 1.5 + 150 × 0.01 = 229.8` units. The hot
index scan costs `3 + 6,000 × 0.002 + 200 × 1.5 + 6,000 × 0.01 = 375` units; the
sequential scan is cheaper. These are results of the teaching formula, not
PostgreSQL's formula.

## Python walkthrough

Open `optimizer.py` and follow the actual functions below. The functions are pure:
they return estimates or plans and do not print, access the database, or change query
results.

- `ColumnStats`, `TableStats`, `Predicate`, `CostParameters`, and `Plan` (lines 94–165)
  define the
  records that move through the planner. `@dataclass(frozen=True)` keeps each record
  stable after it is created.
- `estimate_equality_selectivity()` (line 170) first checks the MCV dictionary. Its remaining
  branch subtracts null and MCV mass, then divides by remaining distinct values.
  `max(0, ...)` protects residual mass from a tiny negative value; the reference
  validates contradictory MCV totals before reaching that calculation.
- `estimate_rows()` (line 207) multiplies selectivity by table rows and rounds to the nearest
  whole row, with halves rounded up.
- `_seq_scan_breakdown()` (line 215) and `_index_scan_breakdown()` (line 232) separate the cost components.
  The index function validates that the predicate column actually has an index.
- `choose_plan()` (line 258) builds the sequential-scan fallback, adds an index scan only when
  the matching index exists, and uses `min()` with an explicit tie-break key.

The internal validators check finite values, ranges, unknown columns, and legal
operators. Follow calls from `choose_plan()` into the cost helpers, then into
`estimate_rows()` and `estimate_equality_selectivity()`. The in-lab task asks you to
trace other branches in the working file without implementing any code.

Run the deterministic cost experiment from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab06\bench_optimizer.py
```

It prints rare, hot, no-index, and stale-statistics scenarios. The displayed values
are cost estimates; the script does not time a simulated query.

With the checked-in default coefficients, the Python model produces these stable
comparisons:

| Scenario | Selectivity | Estimated rows | SeqScan cost | IndexScan cost | Chosen |
|---|---:|---:|---:|---:|---|
| Rare equality, index available | 0.015 | 150 | 300.000 | 229.800 | IndexScan |
| Hot equality, index available | 0.600 | 6,000 | 300.000 | 375.000 | SeqScan |
| Rare equality, no index | 0.015 | 150 | 300.000 | Not legal | SeqScan |
| Rare equality, stale stats say 40% | 0.400 | 4,000 | 300.000 | 351.000 | SeqScan |

The stale-statistics row is a sensitivity demonstration: the same query can lead to a
different estimate and plan when the statistics change. It is not a benchmark of
PostgreSQL or a claim about actual data.

## PostgreSQL experiment

The database steps use the course's existing `csai302` PostgreSQL service, shared
`.env`, and `.venv`. Do not create a separate database or Compose service. If the
service has never been created on this machine, run the one-time `up` command from the
root README first. Otherwise, from the repository root start and inspect it:

```powershell
docker compose --env-file .env -f infra/compose.yaml start postgres
docker compose --env-file .env -f infra/compose.yaml ps
```

Create the Lab 6 schema and seed its deterministic 120,000 orders. The script can be
rerun without adding duplicates:

```powershell
Get-Content .\labs\lab06\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
Get-Content .\labs\lab06\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

Run the read-only row-count, `pg_stats`, and `EXPLAIN (ANALYZE, BUFFERS)` queries
before adding the optional indexes:

```powershell
Get-Content .\labs\lab06\db\queries.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

Before creating an index, make a hypothesis: an index on `status` may help the rare
`cancelled` filter while the common `paid` filter may still favor a sequential scan.
The Python fixture can compare a hypothetical candidate by listing `status` as
indexed; PostgreSQL itself cannot consider an index that does not exist. This
reasoning step needs no HypoPG extension.

Then add the two Lab 6 indexes and run the same queries again:

```powershell
Get-Content .\labs\lab06\db\indexes.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
Get-Content .\labs\lab06\db\queries.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
```

Compare the `status = 'cancelled'` and `status = 'paid'` plans, then the unusually
active customer query. Look for Seq Scan, Index Scan, or Bitmap Heap Scan; estimated
and actual rows; actual rows per loop; shared buffer hits and reads; and timing.
`EXPLAIN ANALYZE` executes the `SELECT`, but these statements are read-only. The
summary counts at the end let you confirm that the same filters return the same
number of rows before and after the indexes.

`pg_stats` exposes sampled `null_frac`, `n_distinct`, MCVs, and histogram bounds.
Run `ANALYZE lab06.orders;` after changing data so PostgreSQL refreshes its estimates.
An index does not have to win: a common value, a small table, or random heap visits
can make a sequential scan cheaper. Buffer cache state, hardware, PostgreSQL settings,
and data distribution affect observed timing and plans. No particular PostgreSQL plan
or speedup is required.

To inspect the same three read-only queries from Python, run:

```powershell
.\.venv\Scripts\python.exe labs\lab06\explain_postgres.py
```

The script loads the repository `.env`, uses a static query allowlist, and prints the
JSON plan tree's operation, relation/index name, estimated rows, actual rows per loop,
loops, costs, timings, and buffer figures. If PostgreSQL or the Lab 6 schema is
unavailable, it reports that clearly; the Python examples and tests remain offline.

### Interpreting the observations

The Python benchmark has reproducible outputs because its input statistics and cost
coefficients are fixed. PostgreSQL observations are machine- and version-dependent.
Typical possibilities (illustrative only) are that a rare `cancelled` value uses the
new status index after `ANALYZE`, while common `paid` rows still use a sequential scan;
the customer predicate may use an index or bitmap path. Use your own plan and buffer
counts as the result. `EXPLAIN` cost values are planner units; actual time is reported
separately in milliseconds.

## In-class task — supervised code trace (65 minutes)

Download/open [`code_trace_task.docx`](code_trace_task.docx) during the supervised lab.
This is an individual code-reading, manual-tracing, and documentation submission; it
requires no implementation. Predict the trace before running code. The worksheet says
when you may run the program to check a prediction. Generative AI and code assistants
are not allowed during this supervised activity. Submit your own completed Word file
as `CSAI302_Lab06_CodeTrace_<StudentID>.docx`.

The in-lab worksheet is marked out of 100 points across architecture/function mapping,
manual traces, code reasoning, edge cases, a controlled cost change, and engineering
judgment. No answer sheet is included in this repository.

## Home practice

After class, complete [`practice/STUDENT_TASK.md`](practice/STUDENT_TASK.md). It extends
the model to numeric histogram ranges, multiple predicates, contradictions, and
transparent candidate costs. From the repository root, run the public tests with:

```powershell
.\.venv\Scripts\python.exe labs\lab06\practice\test_student.py
```

They are expected to fail with `NotImplementedError` until you implement the starter.
Submit your `student.py`, test output, your own tests, and your own `results.md` as
listed in the assignment. No due date or submission system is specified here.

## Two-hour class sequence

| Time | Activity |
|---:|---|
| 20 min | Instructor theory: why optimizers exist, statistics, cost trade-offs, and estimate limits |
| 25 min | Instructor code foundations: selected `optimizer.py` functions, records, branches, and debugging |
| 65 min | Supervised individual code reading, prediction, tracing, and Word documentation; no new code |
| 10 min | Technical debrief: skew, stale statistics, index maintenance, and plan failures |

## Discussion prompts

- A status distribution shifts after a promotion, but statistics are old. What output
  from `EXPLAIN ANALYZE` would reveal a cardinality estimate problem, and when would
  you run `ANALYZE`?
- A status index helps a rare filter but adds work to every order insert and update.
  Which reads and writes should an operator measure before keeping it?
- Two columns are correlated (for example, cancelled orders are mostly old orders).
  Why might multiplying independent selectivities under-estimate or over-estimate
  the result size?
- A plan has the expected row count but many shared buffer reads. What storage or
  cache effects could still make the query slow?

## Simplifications and limits

The reference program handles equality predicates only, with MCV frequencies and a
uniform distribution of the remaining distinct values. Missing column statistics use
a documented 10% equality fallback; malformed or contradictory statistics raise
`ValueError`. The index model uses an upper-bound approximation of one heap page per
matching row, capped at the table page count. The home assignment defines an
equal-population histogram approximation for numeric ranges and assumes independence
between different columns.

These costs are teaching units, not PostgreSQL's actual cost formula. They omit joins,
parallelism, cache state, visibility maps, correlation, index maintenance, and many
other planner details. The advisor chooses an access path; it does not parse SQL or
execute the query. An estimate can be wrong, and a chosen plan must still preserve
query semantics.
