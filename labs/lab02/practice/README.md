# Practice 2 — Extend the storage engine

Apply what you did in the live lab to new problems. You will add two replacement policies,
benchmark them, write queries on the row store and the column store, and work with encrypted
pages. You **use** the lab code one folder up (`buffer_pool.py`, `replacers.py`, `row_store.py`,
`column_store.py`, `crypto_disk.py`); do not change it. Write your code only where a file says
`TODO`.

| File | What you do |
| --- | --- |
| `task1_replacers.py` | Implement the `FIFOReplacer` and `LFUReplacer` classes |
| `task2_bench.py` | Measure the hit ratio of FIFO and LFU against LRU and 2Q |
| `task3_storage.py` | Queries on both stores, and convert column store → row store |
| `task4_crypto.py` | Find damaged encrypted pages, and change the encryption key |
| `check.py` | Tests your work (do not edit) |
| `common.py` | Helpers used by the tasks and the checker (do not edit) |

## Setup

From the repository root, with the course environment active (Windows PowerShell):

    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    cd labs\lab02\practice

Check your work at any time. Tasks you have not started are reported as `TODO`:

    python check.py
    python check.py 1

The `*.db` files that appear in this folder are temporary page files; you can delete them.

## Task 1 — Two more replacement policies

File: `task1_replacers.py`

The lab compared LRU, Clock, LRU-K and 2Q. Add two classic policies with the **same three
methods** (`record_access`, `set_evictable`, `evict`), so the buffer pool can use them unchanged:

- **FIFO** — evict the frame that *entered* the buffer pool first. Using a frame again does not
  move it. Once evicted, a frame is forgotten; its next access is a new arrival.
- **LFU** — evict the frame that was used the *fewest times*. On a tie, evict the one whose last
  use is the oldest. Once evicted, its counter is forgotten.

In both, a frame that is not evictable (pinned) is never chosen, and `evict()` returns `None`
when there is nothing to evict.

    python check.py 1

Expected: ten `PASS` lines.

Hints: read `LRUReplacer` in `../replacers.py` first — FIFO is LRU with one line less. A new
frame starts as *not* evictable; the buffer pool calls `set_evictable(fid, True)` when the page is
unpinned.

Work this example by hand before you code (3 frames, pages requested in this order):

    0 1 2 0 3 0 4 1 0

How many hits does FIFO get? LFU? LRU? `check.py` uses the same trace.

## Task 2 — Benchmark the new policies

File: `task2_bench.py`

Complete `hit_ratio(policy_cls, size, trace)` and `main()`. Use the same workloads as the lab
(`make_traces()` is given: 1000 pages, 20,000 requests, `uniform`, `80-20`, `hot+scan`), buffer
sizes 16, 64 and 256 frames, and the policies LRU, FIFO, LFU and 2Q.

    python task2_bench.py
    python check.py 2

Expected: three tables. Two of the rows you should get:

| | LRU | FIFO | LFU | 2Q |
| --- | --- | --- | --- | --- |
| 80-20, 256 frames | 69.4% | 60.7% | 80.4% | 80.4% |
| hot+scan, 64 frames | 58.1% | 53.8% | 66.6% | 66.6% |

Answer in your own words:

1. Why are all four policies equal on the `uniform` workload?
2. FIFO is never better than LRU here. What information does LRU use that FIFO ignores?
3. LFU is as good as 2Q on `hot+scan`. Why do the scan pages not push out the hot pages?
4. LFU has a known weakness that these workloads do not show: a page that was very popular an
   hour ago and is never used again. What happens to it, and how do LRU-K and 2Q avoid that?

## Task 3 — Queries on the row store and the column store

File: `task3_storage.py`

The table is the lab's students table `(id, name, gpa)`; the checker loads 20,000 students into a
row store and a column store. Write:

- `count_honors_row(rows, min_gpa)` — how many students have `gpa >= min_gpa`, using `rows.scan()`.
- `count_honors_column(cols, min_gpa)` — the same answer from the column store, reading **only**
  the column the query needs.
- `honor_names_column(cols, min_gpa)` — the names of those students, in table order, reading only
  the **two** columns the query needs.
- `convert_column_to_row(cols, rows)` — the reverse of the lab's `convert_row_to_column`.

      python check.py 3

Expected: 5023 students with `gpa >= 3.5`. The row store reads **137** pages to count them, the
column store **20**. The names query reads **119** pages.

Hints: `cols.scan_column("gpa")` yields the values of one column in table order, so values at
the same position in two columns belong to the same row (`zip`). `scan_column("name")` yields
raw `bytes` padded with zero bytes; see how `ColumnStore.get_row` turns them into text.

Answer in your own words:

1. Where do 137, 20 and 119 come from? (How many rows or values fit in one 4 KB page?)
2. The names query reads 119 pages although only a quarter of the students qualify. Why? How
   could a column store read fewer `name` pages for a very selective filter such as `gpa >= 3.99`?
3. Which store would you choose for "show the full record of student 4821", and why?

## Task 4 — Encrypted pages: integrity scan and key rotation

File: `task4_crypto.py`

`EncryptedDiskManager` (`../crypto_disk.py`) encrypts every page with AES-256-GCM. Reading a page
that was changed on disk, or reading with the wrong key, raises `InvalidTag`.

- `find_corrupted_pages(disk, num_pages)` — return the ids of the pages that fail the integrity
  check (real databases run this kind of scan regularly).
- `rotate_key(path, old_key, new_key, num_pages)` — re-encrypt the file with a new key. Afterwards
  the new key reads the same data and the old key is rejected.

      python check.py 4

Expected: five `PASS` lines.

Hints: catch `InvalidTag`, not every exception. In `rotate_key`, read all pages with a disk
manager that has the old key, close it, then write them with one that has the new key. Close
every disk manager you open — on Windows a file that is still open cannot be deleted.

Answer in your own words:

1. Why does `write_page` create a new random nonce on every write, even for the same page?
2. `rotate_key` holds all decrypted pages in memory. Why is that a problem for a 500 GB database,
   and what would you do instead?
3. The page id is passed to AES-GCM as *associated data*. Which attack does that stop?
4. This is encryption **at rest**. What does it not protect? (Think about Lab 3.)

## What to hand in

The four `task*.py` files, the output of `python check.py`, the output of
`python task2_bench.py`, and your written answers.
