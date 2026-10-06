"""R-tree (Guttman, quadratic split) for 2-D geospatial data.

A rectangle is a tuple (xmin, ymin, xmax, ymax); for geo data x = longitude, y = latitude.
A point is a rectangle with zero area. Distances are plain Euclidean distances in degrees.
"""
import heapq
from itertools import combinations, count


def area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def enlargement(r, added):
    """How much r's area must grow to also cover `added`."""
    return area(union(r, added)) - area(r)


def min_dist2(r, x, y):
    """Squared distance from point (x, y) to the nearest point of rectangle r."""
    dx = max(r[0] - x, 0, x - r[2])
    dy = max(r[1] - y, 0, y - r[3])
    return dx * dx + dy * dy


class Node:
    def __init__(self, leaf):
        self.leaf = leaf
        self.entries = []   # (rect, object) in a leaf, (bounding rect of child, child Node) otherwise

    def mbr(self):
        r = self.entries[0][0]
        for rect, _ in self.entries[1:]:
            r = union(r, rect)
        return r


class RTree:
    def __init__(self, max_entries=16):
        self.M = max_entries
        self.m = max(2, max_entries * 4 // 10)  # min entries per node after a split
        self.root = Node(leaf=True)
        self.size = 0
        self.nodes_visited = 0

    # ---- insert ----

    def insert(self, rect, obj):
        split = self._insert(self.root, rect, obj)
        if split:                               # root split: the tree grows one level
            old = self.root
            self.root = Node(leaf=False)
            self.root.entries = [(old.mbr(), old), (split.mbr(), split)]
        self.size += 1

    def insert_point(self, x, y, obj):
        self.insert((x, y, x, y), obj)

    def _insert(self, node, rect, obj):
        """Insert below `node`; return the new sibling if `node` had to split."""
        if node.leaf:
            node.entries.append((rect, obj))
        else:
            # choose the subtree that needs the least enlargement (ties: the smaller one)
            i = min(range(len(node.entries)),
                    key=lambda j: (enlargement(node.entries[j][0], rect), area(node.entries[j][0])))
            child = node.entries[i][1]
            split = self._insert(child, rect, obj)
            node.entries[i] = (child.mbr(), child)
            if split:
                node.entries.append((split.mbr(), split))
        if len(node.entries) > self.M:
            return self._split(node)
        return None

    def _split(self, node):
        """Quadratic split: keep group 1 in `node`, return a new node with group 2."""
        entries = node.entries
        # seeds: the pair that would waste the most area if kept in the same node
        a, b = max(combinations(range(len(entries)), 2),
                   key=lambda p: area(union(entries[p[0]][0], entries[p[1]][0]))
                   - area(entries[p[0]][0]) - area(entries[p[1]][0]))
        g1, g2 = [entries[a]], [entries[b]]
        r1, r2 = entries[a][0], entries[b][0]
        rest = [e for i, e in enumerate(entries) if i not in (a, b)]
        while rest:
            if len(g1) + len(rest) == self.m:   # a group needs everything left to reach the minimum
                g1 += rest
                break
            if len(g2) + len(rest) == self.m:
                g2 += rest
                break
            # next: the entry with the strongest preference for one of the groups
            i = max(range(len(rest)),
                    key=lambda j: abs(enlargement(r1, rest[j][0]) - enlargement(r2, rest[j][0])))
            e = rest.pop(i)
            d1, d2 = enlargement(r1, e[0]), enlargement(r2, e[0])
            if (d1, area(r1), len(g1)) <= (d2, area(r2), len(g2)):
                g1.append(e)
                r1 = union(r1, e[0])
            else:
                g2.append(e)
                r2 = union(r2, e[0])
        node.entries = g1
        sibling = Node(node.leaf)
        sibling.entries = g2
        return sibling

    # ---- queries ----

    def search(self, rect):
        """Window query: every object whose rectangle intersects `rect`."""
        out, stack = [], [self.root]
        while stack:
            node = stack.pop()
            self.nodes_visited += 1
            for r, item in node.entries:
                if intersects(r, rect):
                    if node.leaf:
                        out.append(item)
                    else:
                        stack.append(item)
        return out

    def nearest(self, x, y, k=1):
        """k nearest objects to (x, y) as (distance, object), closest first (best-first search)."""
        tie = count()
        heap = [(0.0, next(tie), self.root, False)]
        out = []
        while heap and len(out) < k:
            d2, _, item, is_obj = heapq.heappop(heap)
            if is_obj:
                out.append((d2 ** 0.5, item))
                continue
            self.nodes_visited += 1
            for r, child in item.entries:
                heapq.heappush(heap, (min_dist2(r, x, y), next(tie), child, item.leaf))
        return out

    def height(self):
        h, node = 1, self.root
        while not node.leaf:
            h, node = h + 1, node.entries[0][1]
        return h
