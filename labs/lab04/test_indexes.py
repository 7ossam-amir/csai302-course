"""Sanity checks for the B+ tree, LSM tree and R-tree. Run: python test_indexes.py"""
import random
import shutil
import threading

from bplus_tree import BPlusTree
from lsm_tree import LSMTree
from rtree import RTree, intersects

INF = float("inf")
random.seed(7)


def check_bplus(tree):
    """Structural invariants: sorted keys, node sizes, separators, all leaves at the same depth."""
    depths = set()

    def walk(node, lo, hi, depth):
        assert node.keys == sorted(node.keys)
        assert len(node.keys) <= tree.max_keys
        assert all(lo <= k < hi for k in node.keys), (lo, hi, node.keys)
        if node.leaf:
            depths.add(depth)
            return
        assert len(node.children) == len(node.keys) + 1
        bounds = [lo] + node.keys + [hi]
        for i, child in enumerate(node.children):
            walk(child, bounds[i], bounds[i + 1], depth + 1)

    walk(tree.root, -INF, INF, 1)
    assert len(depths) == 1, depths


# ---- B+ tree: inserts, overwrite, search, range scan, delete ----
tree, model = BPlusTree(order=4), {}
for _ in range(5000):
    k = random.randrange(3000)
    tree.insert(k, k * 10)
    model[k] = k * 10
tree.insert(5, "new")
model[5] = "new"
check_bplus(tree)
assert all(tree.search(k) == v for k, v in model.items())
assert tree.search(-1) is None and tree.search(99999) is None
assert tree.range_scan(-INF, INF) == sorted(model.items())
assert tree.range_scan(100, 200) == sorted((k, v) for k, v in model.items() if 100 <= k <= 200)
for k in list(model)[::3]:
    assert tree.delete(k)
    del model[k]
assert not tree.delete(-1)
assert tree.range_scan(-INF, INF) == sorted(model.items())
print(f"B+ tree insert/search/scan/delete ok (height {tree.height()})")

# ---- B+ tree: bulk load, then normal inserts on top ----
for n in (0, 1, 7, 1000, 12345):
    items = [(k, str(k)) for k in range(0, 2 * n, 2)]
    bulk = BPlusTree(order=8)
    bulk.bulk_load(items)
    check_bplus(bulk)
    assert bulk.range_scan(-INF, INF) == items
for k in range(1, 2000, 2):
    bulk.insert(k, str(k))
check_bplus(bulk)
assert bulk.search(1001) == "1001" and bulk.search(1000) == "1000"
assert len(bulk.range_scan(-INF, INF)) == 12345 + 1000
print("B+ tree bulk load ok")

# ---- B+ tree: concurrent writers + readers ----
tree = BPlusTree(order=8)
THREADS, PER = 8, 3000
errors = []


def writer(tid):
    keys = list(range(tid, THREADS * PER, THREADS))     # disjoint keys per thread
    random.Random(tid).shuffle(keys)
    for k in keys:
        tree.insert(k, k)


def reader():
    rnd = random.Random()
    try:
        for _ in range(3000):
            k = rnd.randrange(THREADS * PER)
            assert tree.search(k) in (None, k)
            scan = tree.range_scan(k, k + 50)
            assert scan == sorted(scan) and all(a == b for a, b in scan)
    except Exception as e:      # an assertion in a thread would otherwise be lost
        errors.append(e)


threads = [threading.Thread(target=writer, args=(t,)) for t in range(THREADS)]
threads += [threading.Thread(target=reader) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert not errors, errors
check_bplus(tree)
assert tree.range_scan(-INF, INF) == [(k, k) for k in range(THREADS * PER)]
print(f"B+ tree concurrency ok ({THREADS} writers + 4 readers, no lost inserts)")

# ---- LSM tree: put / overwrite / delete across flushes and compactions ----
shutil.rmtree("test_lsm", ignore_errors=True)
lsm, model = LSMTree("test_lsm", memtable_limit=64, fanout=3), {}
for i in range(20000):
    k = random.randrange(4000)
    if random.random() < 0.2:
        lsm.delete(k)
        model.pop(k, None)
    else:
        v = b"v%d" % i
        lsm.put(k, v)
        model[k] = v
assert lsm.compactions > 0 and len(lsm.levels) > 2
assert all(lsm.get(k) == model.get(k) for k in range(4000))
assert lsm.scan(0, 4000) == sorted(model.items())
assert lsm.scan(1000, 1100) == sorted((k, v) for k, v in model.items() if 1000 <= k <= 1100)
lsm.flush()
assert all(lsm.get(k) == model.get(k) for k in range(4000))
print(f"LSM tree ok ({lsm.flushes} flushes, {lsm.compactions} compactions, "
      f"{lsm.table_count()} tables in {len(lsm.levels)} levels)")
lsm.close()
shutil.rmtree("test_lsm")

# ---- R-tree: window queries and nearest neighbours vs brute force ----
rt, points = RTree(max_entries=8), []
for i in range(3000):
    x, y = random.uniform(25, 35), random.uniform(22, 32)
    rt.insert_point(x, y, i)
    points.append((x, y))
for _ in range(200):
    x, y = random.uniform(25, 35), random.uniform(22, 32)
    w = (x, y, x + random.uniform(0, 2), y + random.uniform(0, 2))
    expected = [i for i, (px, py) in enumerate(points) if intersects((px, py, px, py), w)]
    assert sorted(rt.search(w)) == expected
    by_dist = sorted(range(len(points)), key=lambda i: (points[i][0] - x) ** 2 + (points[i][1] - y) ** 2)
    assert [i for _, i in rt.nearest(x, y, k=5)] == by_dist[:5]
rt.insert((26, 23, 28, 25), "region")       # rectangles work too, not only points
assert "region" in rt.search((27, 24, 27.1, 24.1))
print(f"R-tree window + kNN ok (height {rt.height()})")

print("\nall tests passed")
