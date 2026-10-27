"""Check results first, then print one local timing per implementation (no assumed speedup)."""
from collections import defaultdict
from time import perf_counter

import numpy as np

from operators import (Scan, Filter, Project, collect, VectorScan, VectorFilter,
                       VectorProject, collect_batches, hash_join)


def timed(label, function):
    start = perf_counter()
    result = function()
    print(f"{label:24s} {perf_counter() - start:.6f} s; {len(result)} results")
    return result


def dict_join(left, right):
    table = defaultdict(list)
    for i, key in enumerate(left):
        table[int(key)].append(i)
    return [(i, j) for j, key in enumerate(right) for i in table.get(int(key), ())]


if __name__ == "__main__":
    rng = np.random.default_rng(302)
    grades = rng.integers(0, 101, size=100_000)
    ids = np.arange(len(grades))
    rows = [{"id": int(i), "grade": int(g)} for i, g in zip(ids, grades)]
    volcano = timed("Volcano", lambda: collect(Project(
        Filter(Scan(rows), lambda r: r["grade"] >= 90), ["id", "grade"])))
    vector = timed("Vectorized", lambda: collect_batches(VectorProject(
        VectorFilter(VectorScan({"id": ids, "grade": grades}),
                     lambda b: b["grade"] >= 90), ["id", "grade"])))
    assert volcano == vector
    students = np.arange(2000)
    enrollments = rng.integers(0, 2000, size=5000)
    plain = timed("Dictionary hash join", lambda: dict_join(students, enrollments))
    bucketed = timed("NumPy bucket hash join", lambda: hash_join(students, enrollments, 256))
    assert sorted(plain) == sorted(bucketed)
    print("All results agree.")
