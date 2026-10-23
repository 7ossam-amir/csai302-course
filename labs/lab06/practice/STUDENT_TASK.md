# Practice 6 — Selectivity-aware access-path advisor

## Scenario

An e-commerce service filters orders by status, price, customer, and combinations of
those fields. Status frequencies are skewed, numeric price values have a histogram,
and statistics can be absent or stale. Extend the lab's plan advisor so it can reason
about numeric ranges and several predicates while preserving a sequential-scan
fallback. The advisor chooses a path; it does not execute a query or change its result.

Plan for approximately 4–7 hours. Work independently after class. You may use the
Python standard library, but do not import or call `estimate_equality_selectivity`,
`estimate_rows`, either cost function, or `choose_plan` from the reference optimizer
as part of your solution. You may import and construct its data classes.

## Files and public API

Implement these functions in `student.py`:

```python
estimate_range_selectivity(column_stats, operator, value) -> float
combine_predicate_selectivities(table_stats, predicates) -> float
estimate_candidate_costs(table_stats, predicates, cost_params) -> list[Plan]
recommend_plan(table_stats, predicates, cost_params) -> Plan
```

Use `ColumnStats`, `TableStats`, `Predicate`, `CostParameters`, and `Plan` from
`../optimizer.py`. `ColumnStats.histogram_bounds` is an optional tuple that supports
this extension; the reference equality estimator ignores it. A column present in
`TableStats.columns` with value `None` means statistics were not collected. A column
name absent from that mapping is unknown and is an input error.

Only these operators are supported: `=`, `<`, `<=`, `>`, `>=`. Raise `ValueError`
with a useful message for an unsupported operator, malformed statistics, nonnumeric
range boundary, or range predicate without a usable histogram. Do not invent an
estimate when statistics cannot support the requested operation. A predicate with
`op == "="` and `value is None` represents SQL `column = NULL` and has selectivity
zero; `IS NULL` is outside this API.

## Statistics and exact formulas

All frequencies are fractions of **all table rows**. `null_frac` is the null fraction;
null rows do not satisfy any supported predicate. `most_common` maps a value to its
whole-table frequency. Its total may not exceed `1 - null_frac`. The remaining
non-null, non-MCV mass is:

```text
residual_mass = 1 - null_frac - sum(most_common frequencies)
residual_distinct = n_distinct - number of MCV values
```

For equality, use the exact MCV frequency when the value is listed. Otherwise use
`residual_mass / residual_distinct`, or zero when `residual_distinct <= 0`. This
equality rule applies when combining predicates too. MCV equality remains exact even
when the same value is also a histogram boundary.

For ranges, `histogram_bounds` must contain at least two finite, strictly increasing
numeric values. It describes an equal-population histogram of the **non-null,
non-MCV** residual values, from the first bound (minimum) through the last bound
(maximum). If there are `B = len(histogram_bounds) - 1` bins, each bin contains `1/B`
of the residual mass. Within a bin, assume values are distributed uniformly between
its two bounds. For a boundary `x`, calculate residual CDF `F(x)` as follows:

- `F(x) = 0` when `x <= first_bound`.
- `F(x) = 1` when `x >= last_bound`.
- Otherwise find the bin `[low, high]` containing `x`, where bin `j` is zero-based,
  and calculate `F(x) = (j + (x - low) / (high - low)) / B`.
- For the residual component, `<` and `<=` use `F(x)`; `>` and `>=` use `1 - F(x)`.
  The residual model is continuous, so a non-MCV value at a boundary has no point
  mass. Frequent values are handled separately below.

For the MCV component, sum the exact frequencies of MCV values satisfying the
operator, using ordinary numeric comparisons (`<`, `<=`, `>`, `>=`). Add
`residual_mass * residual_fraction` to that sum. The final selectivity must be finite
and clamped to `[0, 1]`. Thus an MCV exactly on a boundary is included for `<=` and
`>=`, and excluded for `<` and `>` as SQL semantics require.

## Combining multiple predicates

Group predicates by column. Do not multiply predicates on the same column as if they
were independent:

- Repeated equalities to the same value count once. Different equality values on one
  column are contradictory and yield zero.
- If an equality and one or more ranges use the same column, check whether the equality
  value satisfies every range. If not, the group is contradictory and yields zero;
  otherwise use the equality selectivity once. An equality to `None` makes the group
  selectivity zero under SQL `= NULL` semantics; do not compare `None` with a range.
- For ranges alone, intersect them by choosing the strongest lower and upper bound.
  At an equal lower boundary, `>` is stronger than `>=`; at an equal upper boundary,
  `<` is stronger than `<=`. A lower bound above the upper bound is contradictory.
  Equal bounds are contradictory if either side is strict. If both are inclusive,
  treat the intersection as equality at that value, using the equality rule above.
  Otherwise compute interval selectivity as upper cumulative mass minus lower
  cumulative mass: for upper `<= u`, subtract the selectivity of `< lower` when the
  lower bound is inclusive, or `<= lower` when it is strict. For upper `< u`, use
  `< u` instead. Clamp the result at zero.
- Selectivities of different columns may be multiplied using the documented
  independence approximation. The empty predicate list has selectivity 1.

Range comparisons require numeric values. Mixed or incomparable values on the same
column must raise `ValueError`, not silently coerce. Non-finite numbers are invalid.

## Cardinality and plan contracts

Estimate output rows as `floor(table_stats.rows * selectivity + 0.5)` (nearest row,
half up), clamped to the inclusive range `0..table_stats.rows`. An empty table always
has zero estimated rows and a zero-cost sequential scan.

`estimate_candidate_costs` returns `Plan` objects in deterministic order: one
`SeqScan` first, then one `IndexScan` for each lexicographically sorted indexed
column that appears in the predicates. Never invent an index. The sequential scan is
always available. For a zero-predicate query, only `SeqScan` is a candidate.

Use the provided positive coefficients and publish the formulas in your code:

```text
SeqScan = pages * seq_page_cost
        + rows * cpu_tuple_cost * number_of_predicates

IndexScan(c) = index_depth * index_page_cost
             + estimated_rows * index_tuple_cost
             + min(pages, estimated_rows) * random_page_cost
             + estimated_rows * cpu_tuple_cost * number_of_predicates
```

The heap-page term assumes, conservatively, that each qualifying row may touch a
different page, capped by the table page count. A zero-row index candidate still pays
the traversal cost. All plan costs and breakdown values must be finite and
non-negative. `Plan.breakdown` must name the numeric cost components. Populate
`Plan.rationale` with a concise explanation of the estimated selectivity/cardinality,
which candidates were legal, and why the winner was selected.

`recommend_plan` returns the minimum-cost candidate. Exact ties resolve in this order:
`SeqScan` first, then `IndexScan` by index column name. Plans must preserve query
semantics; this model only chooses a path and never evaluates or rewrites results.

## Required tests and engineering note

Run the public tests:

```powershell
.\.venv\Scripts\python.exe labs\lab06\practice\test_student.py
```

They cover common and rare MCVs, histogram interiors and boundaries, null and empty
inputs, predicates on multiple columns, same-column contradictions, legal indexes,
the no-index fallback, invalid or missing statistics, and deterministic choices.
Write 2–3 additional tests of your own, including at least one edge case the public
tests do not cover. Do not alter the public tests.

Submit:

- Your `student.py` implementation.
- Output from the passing public test command and your own tests.
- Your 2–3 additional tests.
- A short `results.md` with a table of at least four test scenarios, the outcome you
  observed, and your explanation of why it occurred.
- One example of inaccurate or stale statistics that misleads the advisor, and one
  observable way an operator could diagnose the problem.

## Marking guide

| Component | Weight |
|---|---:|
| Home implementation and API behavior | 45% |
| In-lab code-tracing/documentation task | 35% |
| Student-created edge-case tests | 15% |
| Results table and engineering rationale | 5% |

The instructor may adjust the course-level weighting later. No due date or submission
system is specified here.
