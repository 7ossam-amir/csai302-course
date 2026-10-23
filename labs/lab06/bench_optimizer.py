"""Print deterministic cost comparisons; this does not time simulated queries."""

from dataclasses import replace

from optimizer import (
    ColumnStats,
    CostParameters,
    Predicate,
    TableStats,
    choose_plan,
    estimate_equality_selectivity,
    estimate_index_scan_cost,
    estimate_rows,
    estimate_seq_scan_cost,
)


PARAMS = CostParameters()


def base_table(indexed=True, frequency=None):
    common = {"hot": 0.60, "warm": 0.20}
    if frequency is not None:
        common["rare"] = frequency
        common["hot"] -= frequency
    return TableStats(
        rows=10_000,
        pages=200,
        columns={
            "status": ColumnStats(null_frac=0.05, n_distinct=12, most_common=common),
        },
        indexed_columns=frozenset({"status"}) if indexed else frozenset(),
        table_name="orders",
    )


def show_case(name, table, predicate):
    sel = estimate_equality_selectivity(table.columns[predicate.column], predicate.value)
    seq = estimate_seq_scan_cost(table, predicate, PARAMS)
    rows = estimate_rows(table, predicate)
    index = None
    if predicate.column in table.indexed_columns:
        index = estimate_index_scan_cost(table, predicate, PARAMS)
    plan = choose_plan(table, predicate, PARAMS)
    print(f"\n{name}")
    print(f"  selectivity: {sel:.4f}  estimated rows: {rows:,}")
    print(f"  SeqScan cost: {seq:.3f}")
    print(f"  IndexScan cost: {index:.3f}" if index is not None else "  IndexScan cost: not a legal candidate")
    print(f"  chosen plan: {plan.kind}" + (f" on {plan.index_column}" if plan.index_column else ""))


def main():
    rare = Predicate("status", "=", "rare")
    hot = Predicate("status", "=", "hot")
    show_case("1. Rare equality (unseen value, indexed)", base_table(), rare)
    show_case("2. Hot equality (indexed but nonselective)", base_table(), hot)
    show_case("3. Rare equality (no status index exists)", base_table(indexed=False), rare)

    accurate = base_table()
    stale = base_table(frequency=0.40)
    print("\n4. Stale/skewed statistics sensitivity (same query and table size)")
    show_case("  Current estimate", accurate, rare)
    show_case("  Stale estimate says 'rare' occurs in 40% of rows", stale, rare)
    print("\nCosts are deterministic model units, not elapsed query time or PostgreSQL predictions.")


if __name__ == "__main__":
    main()
