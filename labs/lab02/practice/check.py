"""Checks your practice tasks.

Run: python check.py        (all tasks)
     python check.py 3      (only task 3)
"""
import contextlib
import io
import os
import sys

import common
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from crypto_disk import SLOT, EncryptedDiskManager
from disk_manager import PAGE_SIZE
from replacers import LRUReplacer, TwoQReplacer
from row_store import RowStore

results = {"PASS": 0, "FAIL": 0}


def check(label, got, expected):
    ok = got == expected
    results["PASS" if ok else "FAIL"] += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got {got!r}, expected {expected!r}"))


def close(got, expected):
    """Hit ratios are compared as percentages with one decimal, like the printed tables."""
    return round(got * 100, 1), expected


def touch(replacer, fids):
    for fid in fids:
        replacer.record_access(fid)
        replacer.set_evictable(fid, True)


def task1():
    from task1_replacers import FIFOReplacer, LFUReplacer

    r = FIFOReplacer(3)
    touch(r, [0, 1, 2, 0])  # frame 0 arrived first; using it again must not save it
    check("FIFO evicts the first arrival even if it was used again", r.evict(), 0)
    r.set_evictable(1, False)
    check("FIFO skips a pinned frame", r.evict(), 2)
    check("FIFO returns None when everything left is pinned", r.evict(), None)
    r.set_evictable(1, True)
    touch(r, [0])  # frame 0 comes back: it is now the newest arrival
    check("FIFO treats an evicted frame as a new arrival", r.evict(), 1)
    bpm = common.run_trace(FIFOReplacer, 3, [0, 1, 2, 0, 3, 0, 4, 1, 0])
    check("FIFO in the buffer pool (hits, misses)", (bpm.hits, bpm.misses), (2, 7))

    r = LFUReplacer(3)
    touch(r, [0, 0, 0, 1, 1, 2])
    check("LFU evicts the frame used the fewest times", r.evict(), 2)
    touch(r, [2])  # the counter of frame 2 starts again from zero
    check("LFU forgets the counter of an evicted frame", r.evict(), 2)
    r = LFUReplacer(3)
    touch(r, [0, 1, 0, 1])
    check("LFU tie: the oldest last use is evicted", r.evict(), 0)
    r.set_evictable(1, False)
    check("LFU returns None when everything left is pinned", r.evict(), None)
    bpm = common.run_trace(LFUReplacer, 3, [0, 1, 2, 0, 3, 0, 4, 1, 0])
    check("LFU in the buffer pool (hits, misses)", (bpm.hits, bpm.misses), (3, 6))


def task2():
    import task2_bench
    from task1_replacers import FIFOReplacer, LFUReplacer

    traces = task2_bench.make_traces()
    check("LRU, 64 frames, 80-20", *close(task2_bench.hit_ratio(LRUReplacer, 64, traces["80-20"]), 20.5))
    check("2Q, 64 frames, hot+scan", *close(task2_bench.hit_ratio(TwoQReplacer, 64, traces["hot+scan"]), 66.6))
    check("FIFO, 256 frames, 80-20", *close(task2_bench.hit_ratio(FIFOReplacer, 256, traces["80-20"]), 60.7))
    check("FIFO, 64 frames, hot+scan", *close(task2_bench.hit_ratio(FIFOReplacer, 64, traces["hot+scan"]), 53.8))
    check("LFU, 64 frames, 80-20", *close(task2_bench.hit_ratio(LFUReplacer, 64, traces["80-20"]), 25.4))
    check("LFU, 16 frames, hot+scan", *close(task2_bench.hit_ratio(LFUReplacer, 16, traces["hot+scan"]), 53.1))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        task2_bench.main()
    text = out.getvalue()
    check("main() prints a table for each workload",
          all(word in text for word in ("uniform", "80-20", "hot+scan", "FIFO", "LFU")), True)


def task3():
    import task3_storage as t

    rows, cols = common.build_stores()
    try:
        n, reads = common.page_reads(rows, lambda: t.count_honors_row(rows, 3.5))
        check("row store: students with gpa >= 3.5", n, 5023)
        check("row store: pages read", reads, 137)
        n, reads = common.page_reads(cols, lambda: t.count_honors_column(cols, 3.5))
        check("column store: students with gpa >= 3.5", n, 5023)
        check("column store: pages read (only the gpa column)", reads, 20)
        names, reads = common.page_reads(cols, lambda: t.honor_names_column(cols, 3.5))
        names = list(names)
        check("honor names: how many", len(names), 5023)
        check("honor names: the first three", names[:3], ["student13", "student17", "student20"])
        check("honor names: pages read (name + gpa columns, not id)", reads, 119)

        back = RowStore(common.cold_pool(common.fresh_disk("p_back.db")))
        try:
            t.convert_column_to_row(cols, back)
            back.bpm.flush_all()
            check("column -> row: number of rows", back.num_rows, rows.num_rows)
            check("column -> row: number of pages", back.num_pages, rows.num_pages)
            check("column -> row: same rows as the original row store", list(back.scan()) == list(rows.scan()), True)
        finally:
            common.close_stores(back)
    finally:
        common.close_stores(rows, cols)


def task4():
    import task4_crypto as t

    path = common.db_path("p_secret.db")
    old_key, new_key = AESGCM.generate_key(bit_length=256), AESGCM.generate_key(bit_length=256)
    pages = [f"page {i} secret".encode().ljust(PAGE_SIZE, b"\0") for i in range(8)]

    def new_file():
        if os.path.exists(path):
            os.remove(path)
        disk = EncryptedDiskManager(path, old_key)
        for i, data in enumerate(pages):
            disk.write_page(i, data)
        disk.f.flush()
        return disk

    disk = new_file()
    check("a clean file has no corrupted pages", t.find_corrupted_pages(disk, 8), [])
    for page_id in (2, 5):  # flip one byte inside the stored page
        disk.f.seek(page_id * SLOT + 100)
        byte = disk.f.read(1)
        disk.f.seek(page_id * SLOT + 100)
        disk.f.write(bytes([byte[0] ^ 1]))
    disk.f.flush()
    check("the two damaged pages are found", t.find_corrupted_pages(disk, 8), [2, 5])
    disk.close()

    new_file().close()
    t.rotate_key(path, old_key, new_key, 8)
    disk = EncryptedDiskManager(path, new_key)
    check("after rotation the new key reads the same data", [disk.read_page(i) for i in range(8)], pages)
    disk.close()
    disk = EncryptedDiskManager(path, old_key)
    try:
        disk.read_page(0)
        check("after rotation the old key is rejected", "page was readable", "InvalidTag")
    except InvalidTag:
        check("after rotation the old key is rejected", "InvalidTag", "InvalidTag")
    disk.close()
    try:
        os.remove(path)
        check("rotate_key closed its files", True, True)
    except PermissionError:
        check("rotate_key closed its files", "file still open", True)


TASKS = {"1": task1, "2": task2, "3": task3, "4": task4}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(TASKS)
    for number in wanted:
        print(f"\nTask {number}")
        try:
            TASKS[number]()
        except NotImplementedError as todo:
            print(f"  TODO  not implemented yet: {todo}")
        except Exception as error:  # a crash in one task must not hide the others
            results["FAIL"] += 1
            print(f"  FAIL  stopped with {type(error).__name__}: {error}")
    print(f"\n{results['PASS']} passed, {results['FAIL']} failed")
