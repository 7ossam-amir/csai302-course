"""Concurrent B+ tree with latch crabbing and bottom-up bulk loading.

Every node has a reader/writer latch. Operations crab down the tree: latch the child,
then release the parent once it can no longer be affected.
"""
import bisect
import threading


class RWLatch:
    """Many readers or one writer."""

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False

    def r_lock(self):
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def r_unlock(self):
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def w_lock(self):
        with self._cond:
            while self._writer or self._readers:
                self._cond.wait()
            self._writer = True

    def w_unlock(self):
        with self._cond:
            self._writer = False
            self._cond.notify_all()


class Node:
    def __init__(self, leaf):
        self.leaf = leaf        # never changes, so it can be read without the latch
        self.keys = []
        self.values = []        # leaf only
        self.children = []      # internal only: len(children) == len(keys) + 1
        self.next = None        # leaf only: right sibling, for range scans
        self.latch = RWLatch()


class BPlusTree:
    def __init__(self, order=64):
        assert order >= 4
        self.order = order                      # max children of an internal node
        self.max_keys = order - 1
        self.root = Node(leaf=True)
        self._root_latch = threading.Lock()     # protects the root pointer
        self.pessimistic_inserts = 0            # inserts that had to split (approximate under threads)

    # ---- descent ----

    @staticmethod
    def _latch(node, write):
        if node.leaf and write:
            node.latch.w_lock()
        else:
            node.latch.r_lock()

    def _find_leaf(self, key, write):
        """Crab down with read latches. The leaf is write-latched if `write`, else read-latched."""
        self._root_latch.acquire()
        node = self.root
        self._latch(node, write)
        self._root_latch.release()
        while not node.leaf:
            child = node.children[bisect.bisect_right(node.keys, key)]
            self._latch(child, write)
            node.latch.r_unlock()
            node = child
        return node

    # ---- reads ----

    def search(self, key):
        leaf = self._find_leaf(key, write=False)
        i = bisect.bisect_left(leaf.keys, key)
        value = leaf.values[i] if i < len(leaf.keys) and leaf.keys[i] == key else None
        leaf.latch.r_unlock()
        return value

    def range_scan(self, lo, hi):
        """All (key, value) with lo <= key <= hi, walking the leaf chain left to right."""
        leaf = self._find_leaf(lo, write=False)
        out = []
        i = bisect.bisect_left(leaf.keys, lo)
        while True:
            while i < len(leaf.keys) and leaf.keys[i] <= hi:
                out.append((leaf.keys[i], leaf.values[i]))
                i += 1
            nxt = leaf.next
            if i < len(leaf.keys) or nxt is None:
                leaf.latch.r_unlock()
                return out
            nxt.latch.r_lock()      # latch the sibling before letting go of this leaf
            leaf.latch.r_unlock()
            leaf, i = nxt, 0

    # ---- writes ----

    def insert(self, key, value):
        """Insert or overwrite. Optimistic first: assume the leaf will not split."""
        leaf = self._find_leaf(key, write=True)
        i = bisect.bisect_left(leaf.keys, key)
        exists = i < len(leaf.keys) and leaf.keys[i] == key
        if exists:
            leaf.values[i] = value
        elif len(leaf.keys) < self.max_keys:
            leaf.keys.insert(i, key)
            leaf.values.insert(i, value)
        else:
            leaf.latch.w_unlock()
            self._insert_pessimistic(key, value)
            return
        leaf.latch.w_unlock()

    def _insert_pessimistic(self, key, value):
        """Write-latch the path; release ancestors as soon as a node is safe (has room)."""
        self.pessimistic_inserts += 1
        self._root_latch.acquire()
        root_held = True
        node = self.root
        node.latch.w_lock()
        held = []                               # write-latched ancestors that may still split
        while True:
            if len(node.keys) < self.max_keys:  # safe: a split below cannot go past this node
                for n in held:
                    n.latch.w_unlock()
                held = []
                if root_held:
                    self._root_latch.release()
                    root_held = False
            if node.leaf:
                break
            child = node.children[bisect.bisect_right(node.keys, key)]
            child.latch.w_lock()
            held.append(node)
            node = child

        path = held + [node]
        i = bisect.bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:  # another thread inserted it meanwhile
            node.values[i] = value
        else:
            node.keys.insert(i, key)
            node.values.insert(i, value)
            level = len(path) - 1
            while len(path[level].keys) > self.max_keys:
                sep, right = self._split(path[level])
                if level == 0:                  # path[0] is the root and the root latch is held
                    new_root = Node(leaf=False)
                    new_root.keys = [sep]
                    new_root.children = [path[0], right]
                    self.root = new_root
                    break
                parent = path[level - 1]
                j = bisect.bisect_right(parent.keys, sep)
                parent.keys.insert(j, sep)
                parent.children.insert(j + 1, right)
                level -= 1

        for n in path:
            n.latch.w_unlock()
        if root_held:
            self._root_latch.release()

    @staticmethod
    def _split(node):
        """Move the upper half of `node` to a new right sibling; return (separator, sibling)."""
        mid = len(node.keys) // 2
        right = Node(node.leaf)
        if node.leaf:
            right.keys, right.values = node.keys[mid:], node.values[mid:]
            del node.keys[mid:], node.values[mid:]
            right.next, node.next = node.next, right
            return right.keys[0], right         # leaf separator is copied up
        sep = node.keys[mid]                    # internal separator is pushed up
        right.keys, right.children = node.keys[mid + 1:], node.children[mid + 1:]
        del node.keys[mid:], node.children[mid + 1:]
        return sep, right

    def delete(self, key):
        """Remove the key from its leaf. Lazy: underfull leaves are not merged."""
        leaf = self._find_leaf(key, write=True)
        i = bisect.bisect_left(leaf.keys, key)
        found = i < len(leaf.keys) and leaf.keys[i] == key
        if found:
            del leaf.keys[i], leaf.values[i]
        leaf.latch.w_unlock()
        return found

    # ---- bulk loading ----

    def bulk_load(self, items, fill=0.9):
        """Build the tree bottom-up from (key, value) pairs sorted by unique key.

        Replaces the current content. Not meant to run concurrently with other operations.
        """
        items = list(items)
        per_leaf = max(1, int(self.max_keys * fill))
        level, prev = [], None                  # level = [(smallest key in subtree, node)]
        for start in range(0, len(items), per_leaf):
            chunk = items[start:start + per_leaf]
            leaf = Node(leaf=True)
            leaf.keys = [k for k, _ in chunk]
            leaf.values = [v for _, v in chunk]
            if prev:
                prev.next = leaf
            prev = leaf
            level.append((leaf.keys[0], leaf))
        if not level:
            level = [(None, Node(leaf=True))]

        fanout = max(3, int(self.order * fill))
        while len(level) > 1:
            groups = [level[s:s + fanout] for s in range(0, len(level), fanout)]
            if len(groups) > 1 and len(groups[-1]) == 1:    # no parent with a single child
                groups[-1].insert(0, groups[-2].pop())
            level = []
            for group in groups:
                node = Node(leaf=False)
                node.keys = [k for k, _ in group[1:]]
                node.children = [n for _, n in group]
                level.append((group[0][0], node))
        with self._root_latch:
            self.root = level[0][1]

    # ---- stats (single-threaded use) ----

    def height(self):
        h, node = 1, self.root
        while not node.leaf:
            h, node = h + 1, node.children[0]
        return h

    def leaf_count(self):
        node = self.root
        while not node.leaf:
            node = node.children[0]
        n = 0
        while node:
            n, node = n + 1, node.next
        return n
