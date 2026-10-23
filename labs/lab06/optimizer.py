"""A deterministic teaching model for equality selectivity and access paths."""

from dataclasses import dataclass, field
from math import fsum, isfinite, prod
from numbers import Real
from typing import Hashable, Mapping


DEFAULT_EQUALITY_SELECTIVITY = 0.10


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _validate_column_stats(stats: "ColumnStats | None") -> None:
    if stats is None:
        return
    null_frac = _finite(stats.null_frac, "null_frac")
    n_distinct = _finite(stats.n_distinct, "n_distinct")
    if not 0 <= null_frac <= 1 or n_distinct < 0:
        raise ValueError("null_frac must be in [0, 1] and n_distinct non-negative")
    if len(stats.most_common) > n_distinct:
        raise ValueError("n_distinct cannot be smaller than the MCV count")

    frequencies = []
    for value, frequency in stats.most_common.items():
        if value is None:
            raise ValueError("MCV values cannot be NULL; represent nulls with null_frac")
        frequency = _finite(frequency, "MCV frequency")
        if not 0 <= frequency <= 1:
            raise ValueError("MCV frequencies must be in [0, 1]")
        frequencies.append(frequency)
    if sum(frequencies) > 1 - null_frac:
        raise ValueError("MCV frequencies exceed the non-null row fraction")
    bounds = [_finite(value, "histogram bound") for value in stats.histogram_bounds]
    if any(left >= right for left, right in zip(bounds, bounds[1:])):
        raise ValueError("histogram bounds must be strictly increasing")


def _validate_table_stats(table: "TableStats") -> None:
    if (isinstance(table.rows, bool) or not isinstance(table.rows, int) or table.rows < 0
            or isinstance(table.pages, bool) or not isinstance(table.pages, int) or table.pages < 0):
        raise ValueError("rows and pages must be non-negative integers")
    if table.rows and not table.pages:
        raise ValueError("a non-empty table must have at least one page")
    for name, stats in table.columns.items():
        if not isinstance(name, str) or not name:
            raise ValueError("column names must be non-empty strings")
        if stats is not None and not isinstance(stats, ColumnStats):
            raise ValueError(f"statistics for {name} must be ColumnStats or None")
        _validate_column_stats(stats)
    unknown = set(table.indexed_columns) - set(table.columns)
    if unknown:
        raise ValueError(f"indexes refer to unknown columns: {sorted(unknown)}")


def _validate_cost_parameters(params: "CostParameters") -> None:
    names = ("seq_page_cost", "random_page_cost", "cpu_tuple_cost",
             "index_page_cost", "index_tuple_cost", "index_depth")
    if any(_finite(getattr(params, name), name) <= 0 for name in names):
        raise ValueError("all cost coefficients, including index_depth, must be positive")


def _product(label: str, *values: float | int) -> float:
    try:
        result = prod(float(value) for value in values)
    except OverflowError as exc:
        raise ValueError(f"{label} exceeds the finite cost range") from exc
    if not isfinite(result) or result < 0:
        raise ValueError(f"{label} exceeds the finite cost range")
    return result


def _sum_cost(label: str, *values: float) -> float:
    try:
        result = fsum(values)
    except OverflowError as exc:
        raise ValueError(f"{label} exceeds the finite cost range") from exc
    if not isfinite(result):
        raise ValueError(f"{label} exceeds the finite cost range")
    return result


@dataclass(frozen=True)
class ColumnStats:
    """MCV frequencies are fractions of all rows; histogram is optional for practice."""

    null_frac: float
    n_distinct: float
    most_common: Mapping[Hashable, float] = field(default_factory=dict)
    histogram_bounds: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _validate_column_stats(self)


@dataclass(frozen=True)
class TableStats:
    """Table cardinality, page count, column statistics and known indexes."""

    rows: int
    pages: int
    columns: Mapping[str, ColumnStats | None]
    indexed_columns: frozenset[str] = frozenset()
    table_name: str = "table"

    def __post_init__(self) -> None:
        if not isinstance(self.indexed_columns, frozenset):
            object.__setattr__(self, "indexed_columns", frozenset(self.indexed_columns))
        _validate_table_stats(self)


@dataclass(frozen=True)
class Predicate:
    """Reference predicates support equality only."""

    column: str
    op: str
    value: object


@dataclass(frozen=True)
class CostParameters:
    """Positive relative cost coefficients; these units are not milliseconds."""

    seq_page_cost: float = 1.0
    random_page_cost: float = 1.5
    cpu_tuple_cost: float = 0.01
    index_page_cost: float = 1.0
    index_tuple_cost: float = 0.002
    index_depth: float = 3.0

    def __post_init__(self) -> None:
        _validate_cost_parameters(self)


@dataclass(frozen=True)
class Plan:
    """Chosen path, estimated output, numeric cost breakdown and rationale."""

    kind: str
    estimated_rows: int
    estimated_cost: float
    index_column: str | None = None
    breakdown: Mapping[str, float] = field(default_factory=dict)
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"SeqScan", "IndexScan"}:
            raise ValueError("kind must be 'SeqScan' or 'IndexScan'")
        if isinstance(self.estimated_rows, bool) or not isinstance(self.estimated_rows, int):
            raise ValueError("estimated_rows must be an integer")
        if self.estimated_rows < 0 or _finite(self.estimated_cost, "estimated_cost") < 0:
            raise ValueError("estimated rows and cost must be non-negative")
        if (self.kind == "SeqScan") != (self.index_column is None):
            raise ValueError("only IndexScan plans have an index_column")
        if any(_finite(value, f"breakdown[{key}]") < 0 for key, value in self.breakdown.items()):
            raise ValueError("breakdown values must be finite and non-negative")


def estimate_equality_selectivity(column_stats: ColumnStats | None, value: object) -> float:
    """Use an MCV, residual uniformity, or 10% fallback when stats are missing."""

    _validate_column_stats(column_stats)
    if value is None:  # SQL `column = NULL` is UNKNOWN and matches no rows.
        return 0.0
    if column_stats is None:
        return DEFAULT_EQUALITY_SELECTIVITY
    try:
        if value in column_stats.most_common:
            return float(column_stats.most_common[value])
    except TypeError as exc:
        raise ValueError("predicate values must be hashable scalars") from exc

    residual = max(0.0, 1.0 - column_stats.null_frac - sum(column_stats.most_common.values()))
    remaining = column_stats.n_distinct - len(column_stats.most_common)
    return min(1.0, residual / remaining) if remaining > 0 else 0.0


def _validate_predicate(table_stats: TableStats, predicate: Predicate) -> ColumnStats | None:
    _validate_table_stats(table_stats)
    if not isinstance(predicate, Predicate):
        raise ValueError("predicate must be a Predicate")
    if predicate.op != "=":
        raise ValueError("the reference optimizer supports only '=' predicates")
    if predicate.column not in table_stats.columns:
        raise ValueError(f"unknown column: {predicate.column}")
    return table_stats.columns[predicate.column]


def _round_rows(rows: int, selectivity: float) -> int:
    """Round to the nearest whole row; exact halves round up."""

    numerator, denominator = selectivity.as_integer_ratio()
    return (2 * rows * numerator + denominator) // (2 * denominator)


def estimate_rows(table_stats: TableStats, predicate: Predicate) -> int:
    """Estimate cardinality with the published half-up rounding rule."""

    stats = _validate_predicate(table_stats, predicate)
    selectivity = estimate_equality_selectivity(stats, predicate.value)
    return min(table_stats.rows, _round_rows(table_stats.rows, selectivity))


def _seq_scan_breakdown(table_stats: TableStats, predicate: Predicate,
                        cost_parameters: CostParameters) -> dict[str, float]:
    _validate_predicate(table_stats, predicate)
    pages = _product("sequential page cost", table_stats.pages, cost_parameters.seq_page_cost)
    cpu = _product("sequential CPU cost", table_stats.rows, cost_parameters.cpu_tuple_cost)
    return {"pages_read": float(table_stats.pages), "page_cost": pages,
            "rows_processed": float(table_stats.rows), "cpu_cost": cpu,
            "total_cost": _sum_cost("sequential scan cost", pages, cpu)}


def estimate_seq_scan_cost(table_stats: TableStats, predicate: Predicate,
                           cost_parameters: CostParameters) -> float:
    """Charge all table pages and CPU work for all table rows."""

    return _seq_scan_breakdown(table_stats, predicate, cost_parameters)["total_cost"]


def _index_scan_breakdown(table_stats: TableStats, predicate: Predicate,
                          cost_parameters: CostParameters) -> dict[str, float]:
    _validate_predicate(table_stats, predicate)
    if predicate.column not in table_stats.indexed_columns:
        raise ValueError(f"no available index on {predicate.column}")
    rows = estimate_rows(table_stats, predicate)
    traversal = _product("index traversal cost", cost_parameters.index_depth,
                         cost_parameters.index_page_cost)
    leaf = _product("index leaf work", rows, cost_parameters.index_tuple_cost)
    heap_pages = min(table_stats.pages, rows)  # At most one heap page per matching row.
    heap = _product("heap I/O cost", heap_pages, cost_parameters.random_page_cost)
    cpu = _product("index CPU cost", rows, cost_parameters.cpu_tuple_cost)
    total = _sum_cost("index scan cost", traversal, leaf, heap, cpu)
    return {"index_depth": cost_parameters.index_depth, "index_traversal_cost": traversal,
            "estimated_index_leaf_entries": float(rows), "index_leaf_work": leaf,
            "estimated_heap_pages": float(heap_pages), "heap_io_cost": heap,
            "candidate_rows": float(rows), "cpu_cost": cpu, "total_cost": total}


def estimate_index_scan_cost(table_stats: TableStats, predicate: Predicate,
                             cost_parameters: CostParameters) -> float:
    """Cost an index scan or raise ValueError when its index does not exist."""

    return _index_scan_breakdown(table_stats, predicate, cost_parameters)["total_cost"]


def choose_plan(table_stats: TableStats, predicate: Predicate,
                cost_parameters: CostParameters) -> Plan:
    """Choose the cheapest legal candidate; SeqScan wins exact ties."""

    rows = estimate_rows(table_stats, predicate)
    seq = _seq_scan_breakdown(table_stats, predicate, cost_parameters)
    candidates = [Plan("SeqScan", rows, seq["total_cost"], breakdown=seq,
                       rationale="Full scan is always a legal fallback.")]
    if predicate.column in table_stats.indexed_columns:
        index = _index_scan_breakdown(table_stats, predicate, cost_parameters)
        candidates.append(Plan("IndexScan", rows, index["total_cost"],
                               index_column=predicate.column, breakdown=index,
                               rationale=f"Uses the available index on {predicate.column}."))
    return min(candidates, key=lambda p: (p.estimated_cost,
                                          0 if p.kind == "SeqScan" else 1,
                                          p.index_column or ""))
