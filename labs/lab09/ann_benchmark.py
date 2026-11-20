"""Recall versus cost for exact k-NN, IVF, and HNSW on the same data.

Each row reports recall@10 against exact search, distance computations per query (the cost
that does not depend on the machine or the language), and wall-clock milliseconds per query.
Exact search and IVF are a few NumPy matrix products; HNSW here is a Python loop over a graph,
so it is slower per distance and can lose on time at this small size while winning on
distances. The distance column is what grows with n.

    python labs/lab09/ann_benchmark.py
    python labs/lab09/ann_benchmark.py --n 10000 --dim 64
"""

import argparse
import time

import numpy as np

from vector_search import HNSWIndex, IVFIndex, exact_knn, make_dataset, recall_at_k


def evaluate(name, search, queries, truth, counter=None):
    start = time.perf_counter()
    found = [search(q) for q in queries]
    ms = 1000 * (time.perf_counter() - start) / len(queries)
    recall = float(np.mean([recall_at_k(f, t) for f, t in zip(found, truth)]))
    distances = counter() / len(queries) if counter else None
    return name, recall, distances, ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--dim", type=int, default=64)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    data = make_dataset(args.n, args.dim, seed=1)
    queries = make_dataset(args.queries, args.dim, seed=2)
    truth = [exact_knn(data, q, args.k) for q in queries]
    rows = [evaluate("exact (brute force)", lambda q: exact_knn(data, q, args.k), queries, truth)]
    rows[0] = (rows[0][0], rows[0][1], float(args.n), rows[0][3])

    t0 = time.perf_counter()
    ivf = IVFIndex(nlist=int(np.sqrt(args.n))).build(data)
    ivf_build = time.perf_counter() - t0
    for nprobe in (1, 2, 4, 8, 16):
        ivf.distance_count = 0
        rows.append(evaluate(f"IVF nprobe={nprobe}", lambda q: ivf.search(q, args.k, nprobe), queries, truth,
                             lambda: ivf.distance_count))

    builds = {}
    for M in (4, 12):
        t0 = time.perf_counter()
        index = HNSWIndex(args.dim, M=M, ef_construction=80, seed=0).build(data)
        builds[M] = (time.perf_counter() - t0, index.layer_sizes())
        efs = (10, 20, 40, 80, 160) if M == 12 else (40,)
        for ef in efs:
            index.distance_count = 0
            rows.append(evaluate(f"HNSW M={M} ef={ef}", lambda q: index.search(q, args.k, ef), queries, truth,
                                 lambda: index.distance_count))

    print(f"{args.n:,} vectors, {args.dim} dimensions, {args.queries} queries, recall@{args.k}")
    print(f"{'method':<22}{'recall':>8}{'distances/query':>18}{'ms/query':>10}")
    for name, recall, distances, ms in rows:
        print(f"{name:<22}{recall:>8.3f}{distances:>18,.0f}{ms:>10.2f}")
    print(f"\nBuild: IVF ({ivf.nlist} lists, k-means) {ivf_build:.1f} s; "
          + "; ".join(f"HNSW M={M} {secs:.1f} s, layers {sizes}" for M, (secs, sizes) in builds.items()))
    print("Exact search reads every vector; ANN trades a little recall for far fewer distances.")


if __name__ == "__main__":
    main()
