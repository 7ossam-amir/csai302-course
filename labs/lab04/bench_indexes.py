"""Insert-heavy vs read-heavy workloads on the B+ tree, LSM tree and R-tree.

Run: python bench_indexes.py  -> prints tables and saves index_bench.png
"""
import gc
import random
import shutil
import threading
import time

import matplotlib.pyplot as plt

from bplus_tree import BPlusTree
from lsm_tree import LSMTree
from rtree import RTree, intersects

N = 100_000             # keys loaded before each workload
OPS = 100_000           # operations per workload
KEY_SPACE = 10 * N
WORKLOADS = {"insert-heavy (90% insert)": 0.9, "balanced (50% insert)": 0.5,
             "read-heavy (10% insert)": 0.1}
LSM_DIR = "bench_lsm"
REPS = 3                # each timing is repeated on a fresh structure; the best run is reported

GEO_N = 20_000          # points loaded before each R-tree workload
GEO_OPS = 2_000
WINDOW = 0.2            # window query side, in degrees


def timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


def value(k):
    return b"value-%d" % k


def make_trace(loaded, insert_fraction):
    """[(is_insert, key)]: inserts use new random keys, reads look up keys that were loaded."""
    return [(True, random.randrange(KEY_SPACE)) if random.random() < insert_fraction
            else (False, random.choice(loaded)) for _ in range(OPS)]


# ---- 1. B+ tree: how to build it ----

def bench_build(keys):
    print(f"\n=== B+ tree build, {N:,} keys, order 64 ===")
    print(f"{'method':<28} {'time (s)':>9} {'height':>7} {'leaves':>7} {'leaf fill':>10}")
    sorted_items = [(k, value(k)) for k in sorted(keys)]
    shuffled = [(k, value(k)) for k in keys]

    def insert_all(tree, items):
        for k, v in items:
            tree.insert(k, v)

    for name, build in [("insert, random order", lambda t: insert_all(t, shuffled)),
                        ("insert, sorted order", lambda t: insert_all(t, sorted_items)),
                        ("bulk load (fill 0.9)", lambda t: t.bulk_load(sorted_items)),
                        ("bulk load (fill 1.0)", lambda t: t.bulk_load(sorted_items, fill=1.0))]:
        tree = BPlusTree(order=64)
        secs = timed(lambda: build(tree))
        fill = N / (tree.leaf_count() * tree.max_keys)
        print(f"{name:<28} {secs:9.3f} {tree.height():7} {tree.leaf_count():7} {fill:10.0%}")


# ---- 2. B+ tree vs LSM tree ----

def loaded_bplus(keys):
    tree = BPlusTree(order=64)
    tree.bulk_load([(k, value(k)) for k in sorted(keys)])
    return tree


def run_trace(put, get, trace):
    for is_insert, k in trace:
        if is_insert:
            put(k, value(k))
        else:
            get(k)


def bench_kv(keys):
    results = {}
    print(f"\n=== B+ tree vs LSM tree, {N:,} keys loaded, {OPS:,} ops (ops/sec) ===")
    print(f"{'workload':<28} {'B+ tree':>10} {'LSM tree':>10}   LSM details")
    for wname, frac in WORKLOADS.items():
        trace = make_trace(keys, frac)      # the same trace for both structures

        bpt = lsm_rate = 0
        for _ in range(REPS):
            tree = loaded_bplus(keys)
            bpt = max(bpt, OPS / timed(lambda: run_trace(tree.insert, tree.search, trace)))

            shutil.rmtree(LSM_DIR, ignore_errors=True)
            lsm = LSMTree(LSM_DIR, memtable_limit=4096, fanout=4)
            for k in keys:
                lsm.put(k, value(k))
            lsm_rate = max(lsm_rate, OPS / timed(lambda: run_trace(lsm.put, lsm.get, trace)))
            puts = N + sum(1 for is_insert, _ in trace if is_insert)
            details = (f"{lsm.table_count()} tables / {len(lsm.levels)} levels, "
                       f"write amp {lsm.disk_bytes / lsm.user_bytes:.1f}x, "
                       f"{lsm.disk_bytes / puts:.0f} bytes written per insert")
            lsm.close()
            shutil.rmtree(LSM_DIR)

        results[wname] = (bpt, lsm_rate)
        print(f"{wname:<28} {bpt:10,.0f} {lsm_rate:10,.0f}   {details}")
    return results


# ---- 3. B+ tree with several threads ----

def bench_threads(keys):
    print(f"\n=== B+ tree, {OPS:,} ops split over T threads (ops/sec) ===")
    print(f"{'threads':<8} " + " ".join(f"{w.split(' (')[0]:>13}" for w in WORKLOADS))
    for threads in (1, 2, 4, 8):
        row = []
        for frac in WORKLOADS.values():
            trace = make_trace(keys, frac)
            best = 0
            for _ in range(REPS):
                tree = loaded_bplus(keys)
                workers = [threading.Thread(target=run_trace,
                                            args=(tree.insert, tree.search, trace[i::threads]))
                           for i in range(threads)]

                def go():
                    for w in workers:
                        w.start()
                    for w in workers:
                        w.join()

                best = max(best, OPS / timed(go))
            row.append(best)
        print(f"{threads:<8} " + " ".join(f"{r:13,.0f}" for r in row))


# ---- 4. R-tree vs a plain list ----

def random_point():
    return random.uniform(25, 35), random.uniform(22, 32)   # lon, lat: roughly Egypt


def bench_geo():
    results = {}
    print(f"\n=== R-tree vs linear scan, {GEO_N:,} points loaded, {GEO_OPS:,} ops (ops/sec) ===")
    print(f"{'workload':<28} {'R-tree':>10} {'linear':>10}   nodes visited per query")
    for wname, frac in WORKLOADS.items():
        points = [random_point() for _ in range(GEO_N)]
        trace = [(random.random() < frac, random_point()) for _ in range(GEO_OPS)]

        rt = RTree(max_entries=16)
        for i, (x, y) in enumerate(points):
            rt.insert_point(x, y, i)
        rt.nodes_visited = 0

        def run_rtree():
            for is_insert, (x, y) in trace:
                if is_insert:
                    rt.insert_point(x, y, None)
                else:
                    rt.search((x, y, x + WINDOW, y + WINDOW))

        flat = [(x, y, x, y) for x, y in points]

        def run_linear():
            for is_insert, (x, y) in trace:
                if is_insert:
                    flat.append((x, y, x, y))
                else:
                    w = (x, y, x + WINDOW, y + WINDOW)
                    [p for p in flat if intersects(p, w)]

        rt_rate = GEO_OPS / timed(run_rtree)
        lin_rate = GEO_OPS / timed(run_linear)
        queries = sum(1 for is_insert, _ in trace if not is_insert)
        results[wname] = (rt_rate, lin_rate)
        print(f"{wname:<28} {rt_rate:10,.0f} {lin_rate:10,.0f}   "
              f"{rt.nodes_visited / max(1, queries):.1f} (height {rt.height()})")
    return results


def plot(kv, geo):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    labels = [w.split(" (")[0] for w in WORKLOADS]
    for ax, results, names, title in [(axes[0], kv, ("B+ tree", "LSM tree"), "key-value workloads"),
                                      (axes[1], geo, ("R-tree", "linear scan"), "geospatial workloads")]:
        for i, name in enumerate(names):
            ax.bar([x + (i - 0.5) * 0.38 for x in range(len(labels))],
                   [results[w][i] for w in WORKLOADS], width=0.38, label=name)
        ax.set_xticks(range(len(labels)), labels)
        ax.set_ylabel("ops / sec")
        ax.set_yscale("log")
        ax.set_title(title)
        ax.legend()
    plt.tight_layout()
    plt.savefig("index_bench.png")
    print("\nsaved index_bench.png")


def main():
    random.seed(42)
    gc.disable()        # collector pauses otherwise add a lot of noise to the timings
    keys = random.sample(range(KEY_SPACE), N)
    bench_build(keys)
    kv = bench_kv(keys)
    bench_threads(keys)
    geo = bench_geo()
    plot(kv, geo)


if __name__ == "__main__":
    main()
