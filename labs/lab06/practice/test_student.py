"""Public contract tests for Practice 6. The starter intentionally raises TODO errors."""

import math
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimizer import ColumnStats, CostParameters, Predicate, TableStats
from student import (
    combine_predicate_selectivities,
    estimate_candidate_costs,
    estimate_range_selectivity,
    recommend_plan,
)


PARAMS = CostParameters()


class RangeSelectivityTests(unittest.TestCase):
    def setUp(self):
        self.stats = ColumnStats(
            null_frac=0.10,
            n_distinct=10,
            most_common={10.0: 0.20, 90.0: 0.10},
            histogram_bounds=(0.0, 25.0, 50.0, 75.0, 100.0),
        )

    def test_histogram_interior_and_frequent_value(self):
        self.assertAlmostEqual(estimate_range_selectivity(self.stats, "<=", 20.0), 0.32)
        self.assertAlmostEqual(estimate_range_selectivity(self.stats, "<", 10.0), 0.06)

    def test_histogram_edges_and_complements(self):
        self.assertEqual(estimate_range_selectivity(self.stats, "<", 0.0), 0.0)
        self.assertEqual(estimate_range_selectivity(self.stats, ">", 100.0), 0.0)
        self.assertAlmostEqual(
            estimate_range_selectivity(self.stats, "<", 30.0)
            + estimate_range_selectivity(self.stats, ">=", 30.0),
            1.0 - self.stats.null_frac,
        )

    def test_range_contract_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            estimate_range_selectivity(None, "<", 20)
        with self.assertRaises(ValueError):
            estimate_range_selectivity(self.stats, "!=", 20)
        with self.assertRaises(ValueError):
            estimate_range_selectivity(self.stats, "<", math.inf)


def planning_fixture(rows=1000, pages=50, indexes=frozenset({"price", "status"})):
    return TableStats(
        rows=rows,
        pages=pages,
        columns={
            "price": ColumnStats(
                null_frac=0.0,
                n_distinct=100,
                most_common={10.0: 0.10, 90.0: 0.05},
                histogram_bounds=(0.0, 25.0, 50.0, 75.0, 100.0),
            ),
            "status": ColumnStats(0.0, 4, {"paid": 0.80, "cancelled": 0.01}),
            "customer_id": ColumnStats(0.0, 100, {1: 0.04}),
        },
        indexed_columns=indexes,
        table_name="orders",
    )


class PredicateCombinationTests(unittest.TestCase):
    def test_independence_is_used_only_across_different_columns(self):
        table = planning_fixture()
        combined = combine_predicate_selectivities(
            table,
            [Predicate("price", "<", 50.0), Predicate("status", "=", "paid")],
        )
        self.assertAlmostEqual(combined, 0.525 * 0.8)

    def test_same_column_conflicts_are_recognized(self):
        table = planning_fixture()
        self.assertEqual(
            combine_predicate_selectivities(
                table,
                [Predicate("status", "=", "paid"), Predicate("status", "=", "cancelled")],
            ),
            0.0,
        )
        self.assertEqual(
            combine_predicate_selectivities(
                table,
                [Predicate("price", ">", 80.0), Predicate("price", "<", 20.0)],
            ),
            0.0,
        )

    def test_repeated_equality_is_not_squared(self):
        table = planning_fixture()
        self.assertEqual(
            combine_predicate_selectivities(
                table,
                [Predicate("status", "=", "paid"), Predicate("status", "=", "paid")],
            ),
            0.80,
        )

    def test_empty_predicates_and_empty_table(self):
        table = planning_fixture(rows=0, pages=0)
        self.assertEqual(combine_predicate_selectivities(table, []), 1.0)
        plan = recommend_plan(table, [Predicate("status", "=", "paid")], PARAMS)
        self.assertEqual((plan.kind, plan.estimated_rows, plan.estimated_cost), ("SeqScan", 0, 0.0))

    def test_null_equality_makes_its_column_group_empty(self):
        table = planning_fixture()
        self.assertEqual(
            combine_predicate_selectivities(
                table, [Predicate("price", "=", None), Predicate("price", ">", 30.0)]
            ),
            0.0,
        )

    def test_missing_statistics_and_unknown_columns_are_errors(self):
        table = TableStats(10, 1, {"x": None})
        with self.assertRaises(ValueError):
            combine_predicate_selectivities(table, [Predicate("x", "<", 3)])
        with self.assertRaises(ValueError):
            combine_predicate_selectivities(table, [Predicate("absent", "=", 3)])


class CandidatePlanTests(unittest.TestCase):
    def test_candidate_cost_breakdown_matches_the_contract(self):
        plans = estimate_candidate_costs(
            planning_fixture(), [Predicate("status", "=", "cancelled")], PARAMS
        )
        seq, index = plans
        self.assertEqual(seq.estimated_rows, 10)
        self.assertEqual(seq.estimated_cost, 60.0)
        self.assertEqual(index.index_column, "status")
        self.assertAlmostEqual(index.estimated_cost, 18.12)
        self.assertAlmostEqual(index.breakdown["heap_io_cost"], 15.0)

    def test_only_available_indexes_on_referenced_columns_are_candidates(self):
        table = planning_fixture(indexes=frozenset({"price", "customer_id"}))
        plans = estimate_candidate_costs(
            table,
            [Predicate("status", "=", "cancelled"), Predicate("price", "<", 20)],
            PARAMS,
        )
        self.assertEqual([plan.kind for plan in plans], ["SeqScan", "IndexScan"])
        self.assertEqual(plans[1].index_column, "price")

    def test_no_index_keeps_sequential_fallback(self):
        plans = estimate_candidate_costs(
            planning_fixture(indexes=frozenset()),
            [Predicate("status", "=", "cancelled")],
            PARAMS,
        )
        self.assertEqual([(plan.kind, plan.index_column) for plan in plans], [("SeqScan", None)])

    def test_selection_is_deterministic_and_has_rationale(self):
        table = planning_fixture()
        predicates = [Predicate("status", "=", "cancelled")]
        first = recommend_plan(table, predicates, PARAMS)
        second = recommend_plan(table, predicates, PARAMS)
        self.assertEqual(first, second)
        self.assertTrue(first.rationale)
        self.assertTrue(math.isfinite(first.estimated_cost))

    def test_exact_tie_prefers_sequential_scan(self):
        table = TableStats(
            10, 10, {"status": ColumnStats(0, 1, {"all": 1})}, frozenset({"status"})
        )
        params = CostParameters(
            seq_page_cost=0.15, random_page_cost=0.04, cpu_tuple_cost=0.01,
            index_page_cost=1.0, index_tuple_cost=0.01, index_depth=1.0,
        )
        plan = recommend_plan(table, [Predicate("status", "=", "all")], params)
        self.assertEqual(plan.kind, "SeqScan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
