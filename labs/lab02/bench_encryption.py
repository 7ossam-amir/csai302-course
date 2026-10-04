"""Plain vs encrypted storage under the same workload, for several buffer sizes.

Run: python bench_encryption.py
"""
import os
import random
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from buffer_pool import BufferPoolManager
from crypto_disk import EncryptedDiskManager
from disk_manager import PAGE_SIZE, DiskManager
from replacers import LRUReplacer

NUM_PAGES = 1000
N = 20000
KEY = AESGCM.generate_key(bit_length=256)


def make_disk(kind):
    path = f"{kind}.db"
    if os.path.exists(path):
        os.remove(path)
    disk = DiskManager(path) if kind == "plain" else EncryptedDiskManager(path, KEY)
    for p in range(NUM_PAGES):
        disk.write_page(p, os.urandom(PAGE_SIZE))
    return disk, path


def main():
    random.seed(1)
    hot = NUM_PAGES // 5
    trace = [(random.randrange(hot) if random.random() < 0.8 else random.randrange(hot, NUM_PAGES),
              random.random() < 0.3)  # 30% of requests modify the page
             for _ in range(N)]

    print(f"{'size':<6}{'hit%':>7}{'plain(s)':>10}{'enc(s)':>10}{'overhead':>10}")
    for size in [8, 32, 128, 512]:
        times = {}
        for kind in ("plain", "enc"):
            disk, path = make_disk(kind)
            bpm = BufferPoolManager(size, disk, LRUReplacer(size))
            t = time.perf_counter()
            for p, is_write in trace:
                page = bpm.fetch_page(p)
                if is_write:
                    page[0] = (page[0] + 1) % 256
                bpm.unpin_page(p, is_dirty=is_write)
            bpm.flush_all()
            times[kind] = time.perf_counter() - t
            disk.close()
            os.remove(path)
        overhead = times["enc"] / times["plain"] - 1
        print(f"{size:<6}{bpm.hit_ratio():>7.1%}{times['plain']:>10.3f}"
              f"{times['enc']:>10.3f}{overhead:>10.0%}")


if __name__ == "__main__":
    main()
