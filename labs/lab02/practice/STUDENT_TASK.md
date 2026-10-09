# Lab 2 Practice

Apply the existing Lab 2 code by completing four short functions in `student.py`. Use `LRUReplacer`, `ClockReplacer`, `BufferPoolManager`, and `DiskManager` as provided. You do not need to implement a new replacement policy or rewrite the buffer pool.

## Task 1 — Compare LRU and Clock

Complete `run_trace(disk, replacer_cls, pool_size, trace)`:

1. The buffer pool is already constructed in the starter.
2. Loop over the page IDs in `trace`.
3. Call `fetch_page(page_id)`, then `unpin_page(page_id)` after each request.
4. Return a dictionary with keys `hits`, `misses`, and `hit_ratio`, using the pool's counters and `hit_ratio()` method.
5. Do not close the disk inside this function; the experiment script owns it.

Create `experiment.py` beside `student.py`. Import `student` first so its provided path setup makes the lab modules available. Use a temporary directory and run these traces with three frames:

```python
short_trace = [0, 1, 2, 0, 3, 1]
hot_and_scan = [0, 1, 0, 1, 10, 11, 12, 0, 1]
```

Run each trace once with `LRUReplacer` and once with `ClockReplacer`. Create a fresh disk manager and buffer pool for every policy/trace combination. Print the policy, trace name, hits, misses, and hit ratio. Close each disk manager before cleaning up the temporary directory.

The two policies may produce identical statistics for some traces. Report what you observe rather than assuming one must perform better.

## Task 2 — Save a Modified Page

Complete `save_message(pool, page_id, message)`. The message is supplied as bytes and fits within one page.

1. Fetch the requested page.
2. Copy the message into the beginning of the page without changing the page's total size.
3. Unpin the page with `is_dirty=True`.
4. Call `flush_all()` to write the modification to disk.

Extend `experiment.py` to demonstrate persistence:

1. Create a buffer pool with either LRU or Clock and a fresh temporary disk file.
2. Call `save_message` with page ID 0 and a short bytes message of your choice.
3. Close the disk manager.
4. Reopen the same file with a new disk manager and buffer pool.
5. Read the page and compare its prefix with your original message.
6. Unpin the page, close the disk, and print your verification result.

## Task 3 — Calculate Average GPA

Complete:

- `average_gpa_row(store, minimum)`: read tuples `(id, name, gpa)` from `store.scan()`.
- `average_gpa_column(store, minimum)`: read only GPA values from `store.scan_column('gpa')`.

In both functions, accumulate a sum and count for values satisfying `gpa >= minimum`. Return the average, or `None` when no values qualify. Do not collect all values into a list or reconstruct full rows in the column version.

Use the supplied checks to exercise these functions. Building a storage benchmark is not required.

## What to Submit

- `student.py`: the four completed functions.
- `experiment.py`: the LRU/Clock comparison and page-persistence demonstration.
- `results.md`: your measured statistics, persistence verification, test output, and brief answers to these questions:
  1. How does LRU choose a victim, and how does Clock use its reference bits?
  2. Can a pinned frame be evicted?
  3. Why must a modified page be marked dirty?
  4. Which columns does each average function read?

Calculate and submit your own results. No reference output is supplied.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py
.\.venv\Scripts\python.exe labs\lab02\practice\experiment.py
```

Create `experiment.py` before running its command. The starter raises `NotImplementedError` until completed. Do not modify the provided checks or original lab modules. Do not submit disk files or your virtual environment.
