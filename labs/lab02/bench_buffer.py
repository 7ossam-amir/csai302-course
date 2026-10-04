"""Hit ratio of LRU / Clock / LRU-2 / 2Q across buffer sizes and workloads.

Run: python bench_buffer.py  -> prints tables and saves buffer_hit_ratio.png
"""
import os
import random

import matplotlib.pyplot as plt

from buffer_pool import BufferPoolManager
from disk_manager import DiskManager
from replacers import ClockReplacer, LRUKReplacer, LRUReplacer, TwoQReplacer

NUM_PAGES = 1000
N = 20000
DB = "bench.db"


def uniform():
    return [random.randrange(NUM_PAGES) for _ in range(N)]


def eighty_twenty():
    """80% of requests go to 20% of the pages."""
    hot = NUM_PAGES // 5
    return [random.randrange(hot) if random.random() < 0.8
            else random.randrange(hot, NUM_PAGES) for _ in range(N)]


def hot_plus_scan():
    """A small hot set (pages 0..19) interleaved with sequential scans read only once."""
    out, start = [], 20
    while len(out) < N:
        out += [random.randrange(20) for _ in range(100)]
        out += list(range(start, start + 50))
        start = 20 if start + 100 > NUM_PAGES else start + 50
    return out[:N]


POLICIES = {"LRU": LRUReplacer, "Clock": ClockReplacer,
            "LRU-2": LRUKReplacer, "2Q": TwoQReplacer}
SIZES = [8, 16, 32, 64, 128, 256]
WORKLOADS = {"uniform": uniform, "80-20": eighty_twenty, "hot+scan": hot_plus_scan}


def run(policy_cls, size, trace):
    disk = DiskManager(DB)
    bpm = BufferPoolManager(size, disk, policy_cls(size))
    for p in trace:
        bpm.fetch_page(p)
        bpm.unpin_page(p)
    disk.close()
    return bpm.hit_ratio()


def main():
    random.seed(42)
    results = {}
    for wname, gen in WORKLOADS.items():
        trace = gen()  # the same trace for every policy, so the comparison is fair
        print(f"\n=== {wname} ===")
        print("size  " + "  ".join(f"{p:>7}" for p in POLICIES))
        for size in SIZES:
            row = [run(cls, size, trace) for cls in POLICIES.values()]
            results[(wname, size)] = row
            print(f"{size:<5} " + "  ".join(f"{r:7.1%}" for r in row))

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, wname in zip(axes, WORKLOADS):
        for i, pname in enumerate(POLICIES):
            ax.plot(SIZES, [results[(wname, s)][i] for s in SIZES], marker="o", label=pname)
        ax.set_title(wname)
        ax.set_xlabel("buffer size (frames)")
        ax.set_ylabel("hit ratio")
        ax.set_xscale("log", base=2)
    axes[0].legend()
    plt.tight_layout()
    plt.savefig("buffer_hit_ratio.png")
    os.remove(DB)
    print("\nsaved buffer_hit_ratio.png")


if __name__ == "__main__":
    main()
