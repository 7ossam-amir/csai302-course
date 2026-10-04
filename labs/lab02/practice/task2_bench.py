"""Task 2 - benchmark your FIFO and LFU against LRU and 2Q.

Run:   python task2_bench.py      (prints one table per workload)
Check: python check.py 2
"""
import random

import common  # noqa: F401  (makes the lab code importable)
from bench_buffer import eighty_twenty, hot_plus_scan, uniform
from replacers import LRUReplacer, TwoQReplacer
from task1_replacers import FIFOReplacer, LFUReplacer

POLICIES = {"LRU": LRUReplacer, "FIFO": FIFOReplacer, "LFU": LFUReplacer, "2Q": TwoQReplacer}
SIZES = [16, 64, 256]


def make_traces():
    """The same three workloads as the lab: 1000 pages, 20,000 requests each."""
    random.seed(42)
    return {"uniform": uniform(), "80-20": eighty_twenty(), "hot+scan": hot_plus_scan()}


def hit_ratio(policy_cls, size, trace):
    """Hit ratio (0.0 - 1.0) of one policy with `size` frames on one trace."""
    # TODO: create a disk (common.fresh_disk), a BufferPoolManager with policy_cls(size),
    # then fetch and unpin every page of the trace. Close the disk and return the hit ratio.
    raise NotImplementedError("Task 2: hit_ratio")


def main():
    # TODO: for every workload print a table like the lab's bench_buffer.py:
    #
    # === 80-20 ===
    # size      LRU     FIFO      LFU       2Q
    # 16       5.2%     ...
    #
    # Use the SAME trace for all policies of a workload.
    raise NotImplementedError("Task 2: main")


if __name__ == "__main__":
    main()
