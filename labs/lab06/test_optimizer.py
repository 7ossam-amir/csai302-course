"""Offline correctness checks for the educational equality optimizer."""

import math
import unittest

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


def fixture(indexed=True, stats=None, rows=10_000, pages=200):
    return TableStats(
        rows=rows,
        pages=pages,
        columns={"status": stats or ColumnStats(0.05, 12, {"hot": 0.60, "warm": 0.20})},
        indexed_columns=frozenset({"status"}) if indexed else frozenset(),
    )


class EqualitySelectivityTests(unittest.TestCase):
    def test_common_mcv_uses_whole_table_frequency(self):
        stats = ColumnStats(0.05, 12, {"hot": 0.60, "warm": 0.20})
        self.assertEqual(estimate_equality_selectivity(stats, "hot"), 0.60)

    def test_unseen_value_uses_remaining_mass_and_distinct_values(self):
        stats = ColumnStats(0.05, 12, {"hot": 0.60, "warm": 0.20})
        self.assertAlmostEqual(estimate_equality_selectivity(stats, "rare"), 0.015)
        self.assertEqual(estimate_rows(fixture(stats=stats), Predicate("status", "=", "rare")), 150)

    def test_no_residual_distinct_values_estimates_zero(self):
        stats = ColumnStats(0.0, 2, {"a": 0.5, "b": 0.5})
        self.assertEqual(estimate_equality_selectivity(stats, "other"), 0.0)

    def test_missing_stats_use_published_fallback(self):
        table = TableStats(100, 10, {"status": None})
        self.assertEqual(estimate_rows(table, Predicate("status", "=", "unknown")), 10)

    def test_null_equality_has_zero_matches(self):
        self.assertEqual(estimate_equality_selectivity(ColumnStats(0.1, 4), None), 0.0)


class ValidationTests(unittest.TestCase):
    def test_rejects_contradictory_mcv_mass(self):
        with self.assertRaisesRegex(ValueError, "MCV frequencies"):
            ColumnStats(0.2, 2, {"a": 0.9})
        with self.assertRaisesRegex(ValueError, "cannot be NULL"):
            ColumnStats(0.2, 2, {None: 0.2})

    def test_rejects_invalid_costs(self):
        with self.assertRaises(ValueError):
            CostParameters(random_page_cost=math.inf)

    def test_cost_overflow_is_rejected_not_returned_as_infinity(self):
        table = TableStats(10**400, 10**400, {"status": ColumnStats(0, 1, {"x": 1})})
        with self.assertRaisesRegex(ValueError, "finite cost range"):
            estimate_seq_scan_cost(table, Predicate("status", "=", "x"), CostParameters())

    def test_rejects_unknown_column_and_unsupported_operator(self):
        table = fixture()
        with self.assertRaisesRegex(ValueError, "unknown column"):
            estimate_rows(table, Predicate("missing", "=", "hot"))
        with self.assertRaisesRegex(ValueError, "only '='"):
            estimate_rows(table, Predicate("status", ">", "hot"))


class CostAndPlanTests(unittest.TestCase):
    def test_no_index_means_only_seqscan_is_considered(self):
        table = fixture(indexed=False)
        predicate = Predicate("status", "=", "rare")
        plan = choose_plan(table, predicate, CostParameters())
        self.assertEqual(plan.kind, "SeqScan")
        with self.assertRaisesRegex(ValueError, "no available index"):
            estimate_index_scan_cost(table, predicate, CostParameters())

    def test_rare_value_can_choose_index_and_hot_value_seqscan(self):
        table = fixture()
        params = CostParameters()
        self.assertEqual(choose_plan(table, Predicate("status", "=", "rare"), params).kind, "IndexScan")
        self.assertEqual(choose_plan(table, Predicate("status", "=", "hot"), params).kind, "SeqScan")

    def test_empty_table_has_finite_zero_costs_and_rows(self):
        table = fixture(rows=0, pages=0)
        predicate = Predicate("status", "=", "hot")
        plan = choose_plan(table, predicate, CostParameters())
        self.assertEqual(plan.estimated_rows, 0)
        self.assertEqual(estimate_seq_scan_cost(table, predicate, CostParameters()), 0.0)
        self.assertTrue(math.isfinite(plan.estimated_cost))

    def test_seqscan_wins_exact_cost_tie(self):
        table = TableStats(
            10, 10,
            {"status": ColumnStats(0, 1, {"all": 1})},
            frozenset({"status"}),
        )
        params = CostParameters(
            seq_page_cost=0.15,
            random_page_cost=0.04,
            cpu_tuple_cost=0.01,
            index_page_cost=1.0,
            index_tuple_cost=0.01,
            index_depth=1.0,
        )
        self.assertEqual(estimate_seq_scan_cost(table, Predicate("status", "=", "all"), params),
                         estimate_index_scan_cost(table, Predicate("status", "=", "all"), params))
        self.assertEqual(choose_plan(table, Predicate("status", "=", "all"), params).kind, "SeqScan")

    def test_decision_and_breakdown_are_deterministic_and_explainable(self):
        table = fixture()
        predicate = Predicate("status", "=", "rare")
        first = choose_plan(table, predicate, CostParameters())
        second = choose_plan(table, predicate, CostParameters())
        self.assertEqual(first, second)
        self.assertIn("index_traversal_cost", first.breakdown)
        self.assertEqual(first.estimated_cost, first.breakdown["total_cost"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
