"""Starter API for Practice 9. Complete the methods without changing their signatures."""

import numpy as np  # noqa: F401  (you will need it)


class Unavailable(Exception):
    """Not enough live replicas to accept a write, or none to serve a read."""


class TransactionAborted(Exception):
    """A batch was rolled back; none of its documents were written."""


class ShardedVectorStore:
    """Consistent-hash placement, replicas with a write quorum, scatter-gather k-NN, 2PC batches."""

    def __init__(self, nodes, dim: int, *, replication: int = 3, write_quorum: int = 2,
                 vnodes: int = 64, capacity: int | None = None):
        raise NotImplementedError("Validate the parameters and build the ring and the nodes")

    # ---------------------------------------------------- membership and failures
    def placement(self, doc_id: str) -> list[str]:
        raise NotImplementedError("Walk the ring clockwise and collect distinct nodes")

    def add_node(self, name: str) -> int:
        raise NotImplementedError("Add the node to the ring and rebalance")

    def remove_node(self, name: str) -> int:
        raise NotImplementedError("Hand over the node's copies, remove it, and rebalance")

    def fail(self, name: str) -> None:
        raise NotImplementedError("Mark the node down; keep its data")

    def recover(self, name: str) -> int:
        raise NotImplementedError("Mark the node up and repair stale or missing copies")

    def live_nodes(self) -> list[str]:
        raise NotImplementedError("Return the sorted names of nodes that are up")

    # ------------------------------------------------------------------- data
    def upsert(self, doc_id: str, vector, text: str = "") -> list[str]:
        raise NotImplementedError("A one-item atomic batch")

    def upsert_many(self, items) -> dict[str, list[str]]:
        raise NotImplementedError("Quorum check, then two-phase commit across the involved nodes")

    def get(self, doc_id: str):
        raise NotImplementedError("Newest text on a live placement node")

    def search(self, query, k: int) -> dict:
        raise NotImplementedError("Scatter to live nodes, gather and merge their local top-k")

    def copies(self) -> dict[str, list[str]]:
        raise NotImplementedError("Return {node: sorted document ids} for every node")
