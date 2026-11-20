"""Data partitioning (sharding) strategies and what each one costs.

* Range partitioning: each shard owns a contiguous key range. Range scans touch few shards;
  sequential keys (time stamps, auto-increment ids) all land on the last shard.
* Hash partitioning (hash mod N): even spread, but every range scan touches every shard,
  and changing N moves almost every key.
* Consistent hashing with virtual nodes: keys and nodes share one hash ring; a key belongs to
  the next node clockwise. Adding a node moves only about 1/(N+1) of the keys.

    python labs/lab09/partitioning.py
"""

from __future__ import annotations

import bisect
import hashlib
import random
from collections import Counter


def stable_hash(text: str) -> int:
    """A 64-bit hash that is the same on every machine and every run (Python's hash() is not)."""
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


class RangePartitioner:
    """Shard i owns keys in [boundaries[i-1], boundaries[i]); keys are integers."""

    def __init__(self, boundaries: list[int], names: list[str]) -> None:
        if len(names) != len(boundaries) + 1 or boundaries != sorted(boundaries):
            raise ValueError("need one more name than boundaries, and sorted boundaries")
        self.boundaries, self.names = list(boundaries), list(names)

    def shard_for(self, key: int) -> str:
        return self.names[bisect.bisect_right(self.boundaries, key)]

    def shards_for_range(self, low: int, high: int) -> list[str]:
        first = bisect.bisect_right(self.boundaries, low)
        last = bisect.bisect_right(self.boundaries, high)
        return self.names[first:last + 1]

    def split(self, name: str, at: int, new_name: str) -> "RangePartitioner":
        """Split one shard at a key; only that shard's upper part moves."""
        i = self.names.index(name)
        return RangePartitioner(self.boundaries[:i] + [at] + self.boundaries[i:],
                                self.names[:i + 1] + [new_name] + self.names[i + 1:])


class HashPartitioner:
    def __init__(self, names: list[str]) -> None:
        self.names = list(names)

    def shard_for(self, key) -> str:
        return self.names[stable_hash(str(key)) % len(self.names)]

    def shards_for_range(self, low: int, high: int) -> list[str]:
        return list(self.names)  # hashing destroys key order: every shard may hold part of the range


class ConsistentHashRing:
    """Each node owns `vnodes` points on a 64-bit ring; a key goes to the first point at or after it."""

    def __init__(self, names: list[str], vnodes: int = 100) -> None:
        self.vnodes = vnodes
        self.points: list[int] = []
        self.owner: dict[int, str] = {}
        for name in names:
            self.add(name)

    def add(self, name: str) -> None:
        for i in range(self.vnodes):
            point = stable_hash(f"{name}#{i}")
            self.owner[point] = name
            bisect.insort(self.points, point)

    def remove(self, name: str) -> None:
        self.points = [p for p in self.points if self.owner[p] != name]
        self.owner = {p: n for p, n in self.owner.items() if n != name}

    @property
    def names(self) -> list[str]:
        return sorted(set(self.owner.values()))

    def shard_for(self, key) -> str:
        i = bisect.bisect_left(self.points, stable_hash(str(key))) % len(self.points)
        return self.owner[self.points[i]]

    def preference_list(self, key, n: int) -> list[str]:
        """The first n distinct nodes clockwise from the key: where its n replicas live."""
        if n > len(self.names):
            raise ValueError("not enough nodes for that many replicas")
        i = bisect.bisect_left(self.points, stable_hash(str(key)))
        chosen = []
        while len(chosen) < n:
            node = self.owner[self.points[i % len(self.points)]]
            if node not in chosen:
                chosen.append(node)
            i += 1
        return chosen

    def shards_for_range(self, low: int, high: int) -> list[str]:
        return self.names


# ------------------------------------------------------------------ measures
def load(keys, partitioner) -> Counter:
    return Counter(partitioner.shard_for(k) for k in keys)


def skew(counts: Counter, names) -> float:
    """Largest shard divided by the average shard (1.00 = perfectly even)."""
    values = [counts.get(n, 0) for n in names]
    return max(values) / (sum(values) / len(values))


def moved_fraction(keys, before, after) -> float:
    return sum(before.shard_for(k) != after.shard_for(k) for k in keys) / len(keys)


def main() -> None:
    rng = random.Random(9)
    keys = list(range(100_000))  # e.g. customer ids 0 .. 99,999
    four = ["s1", "s2", "s3", "s4"]
    five = four + ["s5"]
    ranges = RangePartitioner([25_000, 50_000, 75_000], four)
    hashed = HashPartitioner(four)
    ring = ConsistentHashRing(four, vnodes=100)

    print("1. Balance of 100,000 sequential ids on 4 shards (skew = largest / average)")
    for name, p in (("range", ranges), ("hash mod 4", hashed), ("consistent hash", ring)):
        counts = load(keys, p)
        print(f"   {name:<16} skew {skew(counts, four):.3f}  {dict(sorted(counts.items()))}")

    print("\n2. Hot spot: the next 10,000 new ids (100,000 .. 109,999) are all inserted now")
    new_keys = range(100_000, 110_000)
    for name, p in (("range", ranges), ("hash mod 4", hashed), ("consistent hash", ring)):
        counts = load(new_keys, p)
        print(f"   {name:<16} {dict(sorted(counts.items()))}")

    print("\n3. Range query 'id BETWEEN 30,000 AND 30,999': shards that must be asked")
    for name, p in (("range", ranges), ("hash mod 4", hashed), ("consistent hash", ring)):
        touched = sorted({p.shard_for(k) for k in range(30_000, 31_000)})
        print(f"   {name:<16} {p.shards_for_range(30_000, 30_999)}  (rows really on {touched})")

    print("\n4. Adding a fifth shard: fraction of keys that must move")
    split = ranges.split("s4", 87_500, "s5")
    ring5 = ConsistentHashRing(four, vnodes=100)
    ring5.add("s5")
    rows = [("range (split s4)", ranges, split), ("hash mod 4 -> mod 5", hashed, HashPartitioner(five)),
            ("consistent hash", ring, ring5)]
    for name, before, after in rows:
        print(f"   {name:<22} {moved_fraction(keys, before, after):6.1%}   (ideal for a new 5th shard: 20.0%)")

    print("\n5. Virtual nodes and balance (consistent hashing, 4 nodes, 20 different rings each)")
    sample = keys[::10]
    for v in (1, 10, 100, 1000):
        skews = []
        for trial in range(20):
            names = [f"n{trial}-{i}" for i in range(4)]
            skews.append(skew(load(sample, ConsistentHashRing(names, vnodes=v)), names))
        print(f"   {v:>4} vnodes per node  mean skew {sum(skews) / len(skews):.3f}   worst {max(skews):.3f}")

    print("\n6. Skewed access: 20% of requests go to 10 'celebrity' keys")
    hot = [rng.randrange(10) for _ in range(20_000)] + [rng.randrange(100_000) for _ in range(80_000)]
    counts = load(hot, ring)
    print(f"   consistent hash request skew {skew(counts, four):.3f}  {dict(sorted(counts.items()))}")
    print("   Even a perfect key spread cannot split one hot key: it needs replication or key salting.")

    print("\n7. Replicas: preference list (3 distinct nodes clockwise) for a few keys")
    for key in ("alice", "bob", 42):
        print(f"   {key!r:<8} -> {ring5.preference_list(key, 3)}")


if __name__ == "__main__":
    main()
