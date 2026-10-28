# Lab 5 Practice — A Small School

Repeat the parts of the lab on a different topic. Instead of customers and orders, you build a small **school**: students and their course grades. The database tables are `practice05_students` and `practice05_enrollments`, so the `lab05_*` tables are not affected.

Each part below names the lab file to copy the idea from. Read that file first.

## Before you start

- Run the lab once: `orm_demo.py`, `test_lab05.py` and `bench_executor.py` all work.
- The checks use SQLite in memory, so no server is needed. PostgreSQL is used only for the optional `--postgres` run.

## Part 1 — ORM, bound queries and roles (`school.py`)

Copy the idea from `orm_demo.py`. `Student`, `PERMISSIONS` and the seed data are given.

| What | What it does |
|---|---|
| `Enrollment` | add the columns `student_id` (foreign key to `practice05_students.id`), `course` (at most 20 characters) and `grade` (integer) |
| `authorize(action)` | raises `PermissionError` unless the role may do the action; an unknown role may do nothing |
| `find_student(name)` | `read`: the students with exactly this name, using `select(Student).where(...)` |
| `top_grades(minimum)` | `report`: `[(name, course, grade), ...]` with `grade >= minimum`, ordered by enrollment id; raw SQL with `text()` and `:minimum` |
| `add_enrollment(student_id, course, grade)` | `write`: rejects a grade outside 0..100 with `ValueError`, adds the row, flushes (no commit) and returns the new id |
| `seed(engine)` | creates both tables and inserts `STUDENTS` and `ENROLLMENTS` only if there is no student yet |

Then run, from the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab05\practice\school.py
```

The injection input must return `[]`, and the `student` role must be refused the report.

Optional: start the course database and run it on PostgreSQL twice:

```powershell
.\.venv\Scripts\python.exe labs\lab05\practice\school.py --postgres
```

## Part 2 — Volcano iterator (`operators.py`)

Copy the idea from `Filter` and `Project` in `executors.py`.

1. Complete `Filter.next()` and `Project.next()`. Each call returns **one** row, or `None` at the end.
2. Complete `Limit` (SQL `LIMIT n`). After returning `n` rows it must return `None` **without calling the child again**. Reopening it starts the count again.

## Part 3 — Vectorized executor (`operators.py`)

Copy the idea from `VectorFilter` and `VectorProject` in `executors.py`.

1. `VectorFilter.next_batch()`: one Boolean mask per batch; raise `ValueError` if the predicate does not give one Boolean per row; never return an empty batch.
2. `VectorProject.next_batch()`: keep only the requested columns.

## Part 4 — Hash join (`operators.py`)

Copy the idea from `simd_hash_join` in `executors.py`. Complete `hash_join(left, right, bucket_count)`:

- **Build:** put every left position in bucket `key % bucket_count`, and keep each bucket's keys in one NumPy array.
- **Probe:** for every right key, compare it with the whole bucket at once (`keys == key`) and return every matching `(left_index, right_index)`.

Different keys can share a bucket (for example `-1`, `15` and `31` with 16 buckets), and duplicate keys must give every pair.

Then compare the implementations:

```powershell
.\.venv\Scripts\python.exe labs\lab05\practice\compare.py
```

It checks that the results agree before it prints any timing.

## Check your work

```powershell
.\.venv\Scripts\python.exe labs\lab05\practice\test_student.py
```

The starter functions raise `NotImplementedError` until completed.

## What to Submit

- `school.py` and `operators.py`, completed.
- `results.md` with:
  - the output of `school.py` (and of the two `--postgres` runs, if you did them),
  - the output of `compare.py`,
  - the output of `test_student.py`,
  - short answers:
    1. Why does `"' OR 1=1 --"` return no students?
    2. Why can `:minimum` not be used for a column name, for example `ORDER BY :column`? What would you do instead?
    3. Why does `Limit` read only 3 rows from the scan, while `Filter` may read many rows for one `next()`?
    4. Why must `hash_join` compare `keys == key` instead of returning the whole bucket?
    5. In your `compare.py` output, which join was faster, and why?
    6. (If you ran `--postgres` twice) The second run printed a different new enrollment id, although the first one was rolled back. Why?

Do not modify the provided checks or the original lab files.
