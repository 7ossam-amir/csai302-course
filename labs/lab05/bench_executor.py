"""Check results before reporting local timings; no assumed speedup."""
from time import perf_counter
import numpy as np
from executors import (Scan, Filter, Project, collect, VectorScan, VectorFilter,
                       VectorProject, collect_batches, scalar_hash_join, simd_hash_join)


def timed(label, function):
    start = perf_counter()
    result = function()
    print(f"{label:24s} {perf_counter() - start:.6f} s; {len(result)} results")
    return result


if __name__ == "__main__":
    rng = np.random.default_rng(302)
    amounts = rng.integers(0, 1000, size=100_000)
    ids = np.arange(len(amounts))
    rows = [{"id": int(i), "amount": int(a)} for i, a in zip(ids, amounts)]
    row_result = timed("Volcano", lambda: collect(Project(
        Filter(Scan(rows), lambda row: row["amount"] >= 800), ["id", "amount"])))
    vector_result = timed("Vectorized", lambda: collect_batches(VectorProject(
        VectorFilter(VectorScan({"id": ids, "amount": amounts}),
                     lambda batch: batch["amount"] >= 800), ["id", "amount"])))
    assert row_result == vector_result
    left, right = rng.integers(-1000, 1000, size=(2, 5000))
    scalar = timed("Scalar hash join", lambda: scalar_hash_join(left, right))
    vector = timed("SIMD-capable hash join", lambda: simd_hash_join(left, right))
    assert sorted(scalar) == sorted(vector)
    print("All results agree. NumPy runtime capabilities:")
    np.show_runtime()
