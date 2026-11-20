"""Vector search for Lab 9: exact k-NN and two approximate (ANN) indexes, IVF and HNSW.

All indexes store L2-normalized float32 vectors and rank by cosine similarity, so the
distance is 1 - dot(a, b). Every index counts its distance computations: that count is the
hardware-independent cost of a query, and the one to compare across methods (the Python
loops in HNSW and IVF are much slower per distance than NumPy's brute-force matrix product).

* exact_knn: compare the query with every vector. Always correct; cost grows with n.
* IVFIndex: k-means splits the data into `nlist` clusters; a query scans only the `nprobe`
  clusters whose centroids are closest (the inverted-file index used by FAISS and pgvector).
* HNSWIndex: Hierarchical Navigable Small World graphs (Malkov and Yashunin, 2018). Every
  vector is a node linked to about M neighbours; upper layers hold exponentially fewer nodes
  and act like express lanes. A query walks greedily down the layers, then runs a best-first
  search with a candidate list of size `ef` on layer 0.

    python labs/lab09/vector_search.py          # k-NN fundamentals and a small HNSW demo
"""

from __future__ import annotations

import heapq
import math
import random

import numpy as np


def normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("cannot normalize a zero vector")
    return x / norms


def make_dataset(n: int, dim: int, clusters: int = 50, spread: float = 0.35, seed: int = 0) -> np.ndarray:
    """Clustered, normalized vectors: a rough stand-in for text or image embeddings."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(clusters, dim))
    labels = rng.integers(0, clusters, size=n)
    return normalize(centers[labels] + spread * rng.normal(size=(n, dim)))


def knn(data: np.ndarray, query: np.ndarray, k: int, metric: str = "cosine") -> tuple[np.ndarray, np.ndarray]:
    """Exact k nearest neighbours of one query. Returns (ids, scores), best first.

    cosine: larger is closer; dot: larger is closer (favours long vectors); l2: smaller is closer.
    """
    data = np.asarray(data, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    if metric == "cosine":
        scores = normalize(data) @ normalize(query)
    elif metric == "dot":
        scores = data @ query
    elif metric == "l2":
        scores = -np.linalg.norm(data - query, axis=1)  # negate so that larger is closer
    else:
        raise ValueError(f"unknown metric {metric!r}")
    k = min(k, len(data))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top], kind="stable")]
    shown = -scores[top] if metric == "l2" else scores[top]
    return top, shown


def exact_knn(data: np.ndarray, query: np.ndarray, k: int) -> np.ndarray:
    """Cosine k-NN on already-normalized data: the ground truth for recall."""
    scores = data @ normalize(query)
    k = min(k, len(data))
    top = np.argpartition(-scores, k - 1)[:k]
    return top[np.argsort(-scores[top], kind="stable")]


def recall_at_k(found, truth) -> float:
    return len(set(map(int, found)) & set(map(int, truth))) / len(truth)


# ----------------------------------------------------------------------- IVF
class IVFIndex:
    def __init__(self, nlist: int = 64, iterations: int = 10, seed: int = 0) -> None:
        self.nlist, self.iterations, self.seed = nlist, iterations, seed
        self.distance_count = 0

    def build(self, data: np.ndarray) -> "IVFIndex":
        self.data = normalize(data)
        rng = np.random.default_rng(self.seed)
        centroids = self.data[rng.choice(len(self.data), self.nlist, replace=False)]
        for _ in range(self.iterations):  # spherical k-means
            assign = np.argmax(self.data @ centroids.T, axis=1)
            for c in range(self.nlist):
                members = self.data[assign == c]
                if len(members):
                    centroids[c] = normalize(members.sum(axis=0))
        self.centroids = centroids
        assign = np.argmax(self.data @ centroids.T, axis=1)
        self.lists = [np.flatnonzero(assign == c) for c in range(self.nlist)]
        return self

    def search(self, query: np.ndarray, k: int, nprobe: int = 4) -> np.ndarray:
        q = normalize(query)
        nearest = np.argsort(-(self.centroids @ q))[:nprobe]
        candidates = np.concatenate([self.lists[c] for c in nearest])
        self.distance_count += self.nlist + len(candidates)
        if len(candidates) == 0:
            return candidates
        scores = self.data[candidates] @ q
        order = np.argsort(-scores, kind="stable")[:k]
        return candidates[order]


# ---------------------------------------------------------------------- HNSW
class HNSWIndex:
    def __init__(self, dim: int, M: int = 12, ef_construction: int = 80, seed: int = 0) -> None:
        if M < 2:
            raise ValueError("M must be at least 2")
        self.dim, self.M, self.M0 = dim, M, 2 * M  # layer 0 allows twice as many links
        self.ef_construction = ef_construction
        self.level_mult = 1 / math.log(M)
        self.rng = random.Random(seed)
        self.data = np.empty((0, dim), dtype=np.float32)
        self.count = 0
        self.levels: list[int] = []
        self.graph: list[dict[int, list[int]]] = []  # graph[layer][node] -> neighbour ids
        self.entry: int | None = None
        self.distance_count = 0

    def __len__(self) -> int:
        return self.count

    def _distances(self, query: np.ndarray, ids) -> np.ndarray:
        self.distance_count += len(ids)
        return 1.0 - self.data[ids] @ query

    def _search_layer(self, query, entry_points, ef, layer) -> list[tuple[float, int]]:
        """Best-first search on one layer. Returns up to ef (distance, id) pairs, closest first."""
        visited = set(entry_points)
        dists = self._distances(query, list(entry_points))
        candidates = list(zip(dists.tolist(), entry_points))  # min-heap: closest candidate first
        heapq.heapify(candidates)
        results = [(-d, i) for d, i in candidates]  # max-heap by distance: worst result first
        heapq.heapify(results)
        while len(results) > ef:
            heapq.heappop(results)
        while candidates:
            dist, node = heapq.heappop(candidates)
            if dist > -results[0][0]:
                break  # the closest unexplored candidate is worse than our worst result
            fresh = [n for n in self.graph[layer].get(node, ()) if n not in visited]
            if not fresh:
                continue
            visited.update(fresh)
            for d, n in zip(self._distances(query, fresh).tolist(), fresh):
                if len(results) < ef or d < -results[0][0]:
                    heapq.heappush(candidates, (d, n))
                    heapq.heappush(results, (-d, n))
                    if len(results) > ef:
                        heapq.heappop(results)
        return sorted((-d, i) for d, i in results)

    def _select_neighbors(self, base: np.ndarray, candidates: list[tuple[float, int]], m: int) -> list[int]:
        """HNSW's heuristic: keep a candidate only if it is closer to the base than to every
        neighbour already kept. This spreads links in different directions, which keeps the graph
        navigable between clusters. Unused slots are then filled with the closest skipped ones."""
        if len(candidates) <= m:
            return [cid for _, cid in candidates]
        ids = [cid for _, cid in candidates]
        sim = (self.data[ids] @ self.data[ids].T).tolist()  # one matrix product instead of many
        self.distance_count += len(ids) * len(ids)
        kept, skipped = [], []
        for i, (dist, cid) in enumerate(candidates):
            if len(kept) >= m:
                break
            # skip c if some kept neighbour k is closer to c than the base is: 1 - sim(c, k) < dist
            if any(sim[i][j] > 1.0 - dist for j in kept):
                skipped.append(i)
            else:
                kept.append(i)
        for i in skipped:
            if len(kept) >= m:
                break
            kept.append(i)
        return [ids[i] for i in kept]

    def add(self, vector) -> int:
        node = self.count
        if self.count == len(self.data):  # grow storage geometrically
            grown = np.empty((max(16, 2 * len(self.data)), self.dim), dtype=np.float32)
            grown[: self.count] = self.data[: self.count]
            self.data = grown
        self.data[node] = normalize(vector)
        self.count += 1
        level = int(-math.log(1.0 - self.rng.random()) * self.level_mult)
        self.levels.append(level)
        while len(self.graph) <= level:
            self.graph.append({})
        for layer in range(level + 1):
            self.graph[layer][node] = []
        if self.entry is None:
            self.entry = node
            return node

        query = self.data[node]
        top = self.levels[self.entry]
        entry_points = [self.entry]
        for layer in range(top, level, -1):  # greedy descent through layers above the new node
            entry_points = [self._search_layer(query, entry_points, 1, layer)[0][1]]
        for layer in range(min(level, top), -1, -1):
            found = self._search_layer(query, entry_points, self.ef_construction, layer)
            limit = self.M0 if layer == 0 else self.M
            neighbours = self._select_neighbors(query, found, self.M)
            self.graph[layer][node] = neighbours
            for n in neighbours:
                links = self.graph[layer][n]
                links.append(node)
                if len(links) > limit:  # shrink an over-full neighbour list with the same heuristic
                    d = self._distances(self.data[n], links)
                    order = sorted(zip(d.tolist(), links))
                    self.graph[layer][n] = self._select_neighbors(self.data[n], order, limit)
            entry_points = [i for _, i in found]
        if level > top:
            self.entry = node
        return node

    def build(self, data: np.ndarray) -> "HNSWIndex":
        for vector in data:
            self.add(vector)
        return self

    def search(self, query, k: int, ef: int = 50) -> np.ndarray:
        if self.entry is None:
            return np.array([], dtype=np.int64)
        q = normalize(query)
        entry_points = [self.entry]
        for layer in range(self.levels[self.entry], 0, -1):
            entry_points = [self._search_layer(q, entry_points, 1, layer)[0][1]]
        found = self._search_layer(q, entry_points, max(ef, k), 0)
        return np.array([i for _, i in found[:k]], dtype=np.int64)

    def layer_sizes(self) -> list[int]:
        return [len(layer) for layer in self.graph]


# ---------------------------------------------------------------------- demo
def main() -> None:
    print("1. The metric decides who is 'near' (unnormalized vectors)")
    docs = np.array([[1.0, 0.1], [10.0, 9.0], [0.2, 1.0], [3.0, 0.0]], dtype=np.float32)
    query = np.array([1.0, 0.0], dtype=np.float32)
    for metric in ("cosine", "dot", "l2"):
        ids, scores = knn(docs, query, 2, metric)
        print(f"   {metric:<6} top-2 ids {ids.tolist()}  scores {[round(float(s), 3) for s in scores]}")
    print("   dot product rewards the long vector 1; cosine ignores length; L2 mixes both.")

    print("\n2. Distance concentration: nearest / farthest distance ratio for random points")
    rng = np.random.default_rng(1)
    for dim in (2, 10, 100, 1000):
        points = rng.random((2000, dim))
        d = np.linalg.norm(points[1:] - points[0], axis=1)
        print(f"   dim {dim:>4}: nearest/farthest = {d.min() / d.max():.3f}")
    print("   In high dimensions every point is almost equally far: why plain trees (k-d) stop helping.")

    print("\n3. HNSW on 2,000 clustered 32-d vectors")
    data = make_dataset(2000, 32, seed=3)
    queries = make_dataset(50, 32, seed=4)
    index = HNSWIndex(32, M=12, ef_construction=80).build(data)
    print(f"   layer sizes (layer 0 first): {index.layer_sizes()}  entry point {index.entry}")
    for ef in (10, 50):
        index.distance_count = 0
        recall = np.mean([recall_at_k(index.search(q, 10, ef), exact_knn(data, q, 10)) for q in queries])
        print(f"   ef={ef:<3} recall@10 {recall:.3f}, {index.distance_count / len(queries):.0f} distances "
              f"per query (exact search: {len(data)})")


if __name__ == "__main__":
    main()
