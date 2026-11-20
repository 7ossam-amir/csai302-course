"""Core components of three NoSQL data models (the fourth, documents, is in docdb.py).

* Key-value: a Bitcask-style store (the design of Riak's default backend). Every write is
  appended to a log; an in-memory "keydir" maps each key to the offset of its latest value.
  Reads are one lookup, writes are one append, and compaction rewrites only the live values.
* Wide-column: a Cassandra-style table. Rows are grouped by a partition key and kept sorted
  inside the partition by clustering keys. Fast queries name the partition and a clustering
  range; anything else needs a full scan ("ALLOW FILTERING").
* Graph: a property graph with adjacency lists. A traversal follows edges from a node
  without joins, so cost depends on the neighbourhood, not on the size of the graph.

    python labs/lab10/nosql_models.py
"""

from __future__ import annotations

import bisect
from collections import deque


class QueryError(Exception):
    pass


# --------------------------------------------------------------- key-value
class BitcaskKV:
    """Append-only log + in-memory keydir. Values may carry a time-to-live."""

    TOMBSTONE = object()

    def __init__(self) -> None:
        self.log: list[tuple[str, object, float | None]] = []  # (key, value or TOMBSTONE, expires_at)
        self.keydir: dict[str, int] = {}  # key -> offset of its latest record (volatile)
        self.now = 0.0  # a logical clock, so TTL behaviour is deterministic

    def put(self, key: str, value, ttl: float | None = None) -> int:
        if not isinstance(key, str) or not key:
            raise ValueError("keys must be non-empty strings")
        self.log.append((key, value, None if ttl is None else self.now + ttl))
        self.keydir[key] = len(self.log) - 1
        return self.keydir[key]

    def get(self, key: str, default=None):
        offset = self.keydir.get(key)
        if offset is None:
            return default
        _, value, expires = self.log[offset]
        if value is self.TOMBSTONE or (expires is not None and self.now >= expires):
            return default
        return value

    def delete(self, key: str) -> None:
        self.log.append((key, self.TOMBSTONE, None))
        self.keydir[key] = len(self.log) - 1

    def incr(self, key: str, by: int = 1) -> int:
        value = self.get(key, 0) + by
        self.put(key, value)
        return value

    def rebuild_keydir(self) -> int:
        """After a restart the keydir is gone: scan the log once, later records win."""
        self.keydir = {}
        for offset, (key, _, _) in enumerate(self.log):
            self.keydir[key] = offset
        return len(self.log)

    def compact(self) -> tuple[int, int]:
        """Rewrite only live, unexpired latest values. Returns (records before, records after)."""
        before = len(self.log)
        live = [(k, self.log[o]) for k, o in self.keydir.items()
                if self.log[o][1] is not self.TOMBSTONE and (self.log[o][2] is None or self.now < self.log[o][2])]
        self.log = [record for _, record in live]
        self.keydir = {k: i for i, (k, _) in enumerate(live)}
        return before, len(self.log)


# ------------------------------------------------------------- wide column
class WideColumnTable:
    """Rows live in partitions (by partition key) sorted by clustering key inside each partition."""

    def __init__(self, partition_key: str, clustering_keys: list[str]) -> None:
        self.partition_key = partition_key
        self.clustering_keys = list(clustering_keys)
        self.partitions: dict[object, list[tuple[tuple, dict]]] = {}
        self.rows_read = 0

    def _cluster(self, row: dict) -> tuple:
        return tuple(row[c] for c in self.clustering_keys)

    def insert(self, row: dict) -> None:
        """Insert or overwrite (Cassandra writes are upserts)."""
        if self.partition_key not in row or any(c not in row for c in self.clustering_keys):
            raise QueryError("every row needs its partition key and all clustering keys")
        rows = self.partitions.setdefault(row[self.partition_key], [])
        key = self._cluster(row)
        i = bisect.bisect_left(rows, key, key=lambda item: item[0])
        if i < len(rows) and rows[i][0] == key:
            rows[i] = (key, {**rows[i][1], **row})
        else:
            rows.insert(i, (key, dict(row)))

    def select(self, partition, *, start: tuple | None = None, end: tuple | None = None,
               limit: int | None = None, descending: bool = False) -> list[dict]:
        """One partition, an optional clustering range [start, end], newest-first if descending."""
        rows = self.partitions.get(partition, [])
        lo = 0 if start is None else bisect.bisect_left(rows, start, key=lambda item: item[0][:len(start)])
        hi = len(rows) if end is None else bisect.bisect_right(rows, end, key=lambda item: item[0][:len(end)])
        chosen = rows[lo:hi][::-1] if descending else rows[lo:hi]
        chosen = chosen[:limit] if limit is not None else chosen
        self.rows_read += len(chosen)
        return [dict(r) for _, r in chosen]

    def select_where(self, predicate, *, allow_filtering: bool = False) -> list[dict]:
        """A query without the partition key must read every partition."""
        if not allow_filtering:
            raise QueryError("query does not restrict the partition key; it would scan the whole "
                             "table (Cassandra requires ALLOW FILTERING)")
        result = []
        for rows in self.partitions.values():
            self.rows_read += len(rows)
            result += [dict(r) for _, r in rows if predicate(r)]
        return result


# ------------------------------------------------------------------- graph
class PropertyGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, tuple[str, dict]] = {}
        self.out: dict[str, list[tuple[str, str, dict]]] = {}
        self.inn: dict[str, list[tuple[str, str, dict]]] = {}
        self.edges_followed = 0

    def add_node(self, node_id: str, label: str, **props) -> None:
        self.nodes[node_id] = (label, props)
        self.out.setdefault(node_id, [])
        self.inn.setdefault(node_id, [])

    def add_edge(self, src: str, edge_type: str, dst: str, **props) -> None:
        if src not in self.nodes or dst not in self.nodes:
            raise KeyError("both endpoints must exist")
        self.out[src].append((edge_type, dst, props))
        self.inn[dst].append((edge_type, src, props))

    def neighbors(self, node_id: str, edge_type: str | None = None, direction: str = "out") -> list[str]:
        edges = self.out[node_id] if direction == "out" else self.inn[node_id]
        self.edges_followed += len(edges)
        return [other for t, other, _ in edges if edge_type is None or t == edge_type]

    def shortest_path(self, src: str, dst: str, edge_type: str | None = None) -> list[str] | None:
        """Breadth-first search: fewest hops."""
        previous = {src: None}
        queue = deque([src])
        while queue:
            node = queue.popleft()
            if node == dst:
                path = []
                while node is not None:
                    path.append(node)
                    node = previous[node]
                return path[::-1]
            for nxt in self.neighbors(node, edge_type):
                if nxt not in previous:
                    previous[nxt] = node
                    queue.append(nxt)
        return None

    def friends_of_friends(self, person: str) -> list[str]:
        direct = set(self.neighbors(person, "FOLLOWS"))
        suggestions = set()
        for friend in direct:
            suggestions.update(self.neighbors(friend, "FOLLOWS"))
        return sorted(suggestions - direct - {person})

    def match(self, src_label: str, edge_type: str, dst_label: str, where=None) -> list[tuple[str, str]]:
        """A tiny pattern match: (a:src_label)-[:edge_type]->(b:dst_label) WHERE where(a, b)."""
        result = []
        for a, (label, props) in self.nodes.items():
            if label != src_label:
                continue
            for b in self.neighbors(a, edge_type):
                if self.nodes[b][0] == dst_label and (where is None or where(props, self.nodes[b][1])):
                    result.append((a, b))
        return result


# -------------------------------------------------------------------- demo
def main() -> None:
    print("1. Key-value (Bitcask): sessions with a time-to-live")
    kv = BitcaskKV()
    kv.put("session:42", {"user": "sara"}, ttl=30)
    kv.put("cart:42", ["book"])
    kv.put("cart:42", ["book", "pen"])
    kv.incr("visits")
    kv.incr("visits")
    kv.delete("cart:42")
    print(f"   log records {len(kv.log)}, keydir {kv.keydir}")
    kv.now = 31
    print(f"   at t=31: session {kv.get('session:42')}, cart {kv.get('cart:42')}, visits {kv.get('visits')}")
    print(f"   restart: keydir rebuilt by scanning {kv.rebuild_keydir()} records; compaction keeps "
          f"{kv.compact()[1]} of 6 records")
    print("   Strength: O(1) get/put by key. Weakness: no query by value ('all carts with a pen').")

    print("\n2. Wide-column: messages partitioned by chat, clustered by time")
    messages = WideColumnTable("chat_id", ["ts"])
    for ts in range(1, 1001):
        messages.insert({"chat_id": f"chat{ts % 10}", "ts": ts, "sender": f"u{ts % 7}", "text": f"m{ts}"})
    latest = messages.select("chat3", descending=True, limit=3)
    print(f"   latest 3 in chat3: {[m['ts'] for m in latest]}  (rows read {messages.rows_read})")
    window = messages.select("chat3", start=(500,), end=(560,))
    print(f"   chat3 between ts 500 and 560: {len(window)} rows")
    try:
        messages.select_where(lambda r: r["sender"] == "u3")
    except QueryError as problem:
        print(f"   by sender without the partition key -> QueryError: {problem}")
    messages.rows_read = 0
    found = messages.select_where(lambda r: r["sender"] == "u3", allow_filtering=True)
    print(f"   with ALLOW FILTERING: {len(found)} rows found, {messages.rows_read} rows read")
    print("   Design rule: one table per query. A 'messages_by_sender' table would duplicate the data.")

    print("\n3. Graph: who follows whom")
    g = PropertyGraph()
    for name, city in (("sara", "Cairo"), ("omar", "Giza"), ("laila", "Cairo"), ("ali", "Alex"), ("mona", "Cairo")):
        g.add_node(name, "Person", city=city)
    for a, b in (("sara", "omar"), ("omar", "laila"), ("laila", "ali"), ("sara", "mona"), ("mona", "laila")):
        g.add_edge(a, "FOLLOWS", b)
    g.add_node("db", "Course", title="Advanced Databases")
    g.add_edge("laila", "TAKES", "db")
    print(f"   shortest path sara -> ali: {g.shortest_path('sara', 'ali', 'FOLLOWS')}")
    print(f"   suggestions for sara (friends of friends): {g.friends_of_friends('sara')}")
    same_city = g.match("Person", "FOLLOWS", "Person", where=lambda a, b: a["city"] == b["city"])
    print(f"   (a:Person)-[:FOLLOWS]->(b:Person) WHERE a.city = b.city: {same_city}")
    print(f"   edges followed in total: {g.edges_followed}. In SQL each extra hop is one more self-join.")


if __name__ == "__main__":
    main()
