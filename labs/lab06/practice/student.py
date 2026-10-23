"""Starter API for Practice 6. Implement the four documented functions below."""

from pathlib import Path
import sys

# Make the sibling teaching module importable when this starter is run directly
# from the repository-root command shown in the practice README.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimizer import ColumnStats, CostParameters, Plan, Predicate, TableStats


def estimate_range_selectivity(column_stats: ColumnStats | None,
                               operator: str,
                               value: object) -> float:
    """Estimate a numeric range predicate under the assignment histogram contract."""
    raise NotImplementedError("Implement histogram-based range selectivity")


def combine_predicate_selectivities(table_stats: TableStats,
                                    predicates: list[Predicate]) -> float:
    """Combine same-column constraints, then apply independence across columns."""
    raise NotImplementedError("Implement grouped predicate selectivity")


def estimate_candidate_costs(table_stats: TableStats,
                             predicates: list[Predicate],
                             cost_params: CostParameters) -> list[Plan]:
    """Build a sequential-scan fallback and only legal predicate-index paths."""
    raise NotImplementedError("Implement candidate generation and cost breakdowns")


def recommend_plan(table_stats: TableStats,
                   predicates: list[Predicate],
                   cost_params: CostParameters) -> Plan:
    """Return the cheapest candidate using the documented deterministic tie-break."""
    raise NotImplementedError("Implement deterministic plan selection")
