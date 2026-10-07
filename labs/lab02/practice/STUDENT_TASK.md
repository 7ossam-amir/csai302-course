# Lab 2 Practice

## Overview

Apply the concepts covered in Lab 2: buffer pools, replacement policies, and row-oriented versus column-oriented storage.

## Task 1: Complete the Buffer Pool Manager 

Complete these methods in `StudentBufferPool`. Initialization is provided.

### 1. `fetch_page(page_id)`

Return the page contents as a mutable `bytearray`.

1. Look up the page in `page_table`.
2. On a hit, increment `hits` and use the existing frame without reading from disk.
3. On a miss, increment `misses`, obtain a frame using `_get_free_frame()`, and read the page using `disk.read_page(page_id)`.
4. Store the loaded page as a `bytearray` and update `frames`, `frame_page`, and `page_table`.
5. Increment the frame's `pin_count` for every successful fetch, whether a hit or a miss.
6. Call `replacer.record_access(fid)` and `replacer.set_evictable(fid, False)`.
7. Return the actual bytearray stored in the frame, rather than a copy.

### 2. `_get_free_frame()`

1. If `free_frames` is not empty, remove and return a free frame ID.
2. Otherwise, request a victim using `replacer.evict()`.
3. If the result is `None`, raise `RuntimeError` because all frames are pinned.
4. If the victim page is dirty, write it to disk using its old page ID, not its frame ID.
5. Remove the old page from `page_table`. Reset the frame's dirty flag and pin count before reuse.
6. Return the selected frame ID.

### 3. `unpin_page(page_id, is_dirty=False)`

1. Raise `KeyError` if the page is not resident.
2. Raise `ValueError` if its pin count is already zero, without changing the count.
3. If `is_dirty=True`, mark the page as dirty.
4. If `is_dirty=False`, preserve its existing dirty flag.
5. Decrement its pin count by one.
6. Make the frame evictable only when its pin count reaches zero.

### 4. `flush_all()`

1. Visit all resident pages and write only dirty pages to disk.
2. Clear each dirty flag after a successful write.
3. Do not evict pages or change pin counts.
4. Calling the method again without further modifications must not cause additional writes.

Do not modify `DiskManager` or the replacer interface. Disk failures and concurrency are outside the scope of this lab practice.

### Required trace experiment

Use three frames and the existing `LRUReplacer`. Execute the following requests, unpinning each page after every fetch:

```text
0, 1, 2, 0, 3, 1
```

In `answers.md`, provide a table showing the hit or miss, resident pages, and evicted page after each request. Report the total hits, total misses, and hit ratio obtained from your implementation.

## Task 2: Implement FIFO Replacement

Complete `FIFOReplacer` in `student.py`.

| Method | Required behavior |
|---|---|
| `__init__(num_frames)` | Initialize structures for admission order and eviction eligibility. |
| `record_access(fid)` | Append a new frame to the queue as non-evictable. Accessing an existing frame must not change its order. |
| `set_evictable(fid, ok)` | Update eligibility without changing admission order. Unknown frame IDs may be ignored. |
| `evict()` | Remove and return the oldest eligible frame. Skip pinned frames without removing or reordering them. Return `None` if no victim exists. |

If an evicted frame ID is reused, treat it as a new admission at the end of the queue.

Run the Task 1 trace using FIFO with `StudentBufferPool`. Report your trace table, total hits, total misses, and hit ratio in `answers.md`. Compare your measured FIFO and LRU results and explain your observations. Discuss whether this single trace is sufficient to judge performance across workloads.

## Task 3: Query Row and Column Storage 

Implement the following query using both storage layouts:

```sql
SELECT AVG(gpa)
FROM students
WHERE gpa >= minimum;
```

### 1. `average_gpa_row(store, minimum)`

- Read rows through `store.scan()`; each row contains `(id, name, gpa)`.
- Accumulate the sum and count of GPA values satisfying `gpa >= minimum`.
- Return the average, or `None` if no values qualify.

### 2. `average_gpa_column(store, minimum)`

- Read only GPA using `store.scan_column('gpa')`.
- Apply the same condition and return the same result.
- Do not use `get_row()` or read the ID and name columns.

Both functions must use constant additional space: maintain a sum and count instead of collecting values in a list.

### Required storage experiment

Create `experiment.py` beside `student.py`:

1. Create a `RowStore` and a `ColumnStore`, each with its own disk file and an eight-frame buffer pool using LRU.
2. Insert 1,500 students into each store. For `i` from 0 through 1499, use:

   ```python
   (i, f'S{i}', float(i % 5))
   ```

3. Call `flush_all()` on both buffer pools.
4. Create a new buffer pool for each store using its existing disk manager, and assign it to `store.bpm`. Keep the original store objects to preserve their in-memory metadata.
5. Record `disk.reads` immediately before and after each query and calculate the difference.
6. Run both average functions with `minimum=3`.
7. Print the average and page-read count for each store.
8. Use a temporary directory and close both disk managers before cleaning it up.

Create a results table in `answers.md` containing the storage layout, computed average, and measured query page reads for each store. Include the output of your experiment and explain your observations. Count query reads only, excluding insertion reads. A new buffer pool provides a cold database buffer; the operating system may still cache the file.

## Task 4: Explain and Test 

Include your trace table and experiment results in `answers.md`, and answer:

1. What is the difference between `page_id` and `frame_id`? Why must the old mapping be removed during eviction?
2. If a page is fetched twice and unpinned once, can it be evicted? Why?
3. Why must `is_dirty=False` preserve an existing dirty flag?
4. Compare the FIFO and LRU results you obtained. Compare the page-read counts measured for the two storage layouts. Explain both comparisons using the algorithms and page layouts.

Create `test_extra.py` containing an original edge-case test not already covered by the provided tests. Explain which bug it detects. You may use Python's built-in `unittest`.

## Bonus: Encrypted Pages — optional 

Create `bonus_crypto.py`:

1. Use the existing `EncryptedDiskManager` with `StudentBufferPool` and a randomly generated AES-256 key.
2. Modify a page, unpin it as dirty, and flush it.
3. Close the file, reopen it with a new disk manager using the same key, and verify data recovery.
4. After closing all file handles, flip one bit within the ciphertext of a written page.
5. Reopen the file and verify that reading the page raises `cryptography.exceptions.InvalidTag`.
6. Explain why buffered pages remain plaintext and why moving ciphertext to a different page ID is detected.

Use a temporary directory. Do not implement AES yourself or submit the key. The bonus is assessed separately from the public tests.

## Running the Tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py
```

To run a single group:

```powershell
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py BufferTests
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py FIFOTests
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py QueryTests
```

Failures are expected before implementation. All nine public tests should pass when you finish. Do not modify the provided tests or original lab modules to make them pass. Passing tests does not replace code review and explanation.

## Submission Checklist

- `student.py`: your completed implementation.
- `experiment.py`: the storage comparison experiment.
- `test_extra.py`: your additional test.
- `answers.md`: the trace table, results, and explanations.
- A screenshot or text file showing test results.
- `bonus_crypto.py`, if completed.

Do not submit `.venv`, `.db` files, or encryption keys. Be prepared to explain your code and trace the buffer state during discussion.

