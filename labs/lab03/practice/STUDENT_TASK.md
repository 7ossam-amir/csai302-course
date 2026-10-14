# Lab 3 Practice

Difficulty: intermediate. Suggested time: 45–60 minutes.

In the lab, `upload.py` stored each file in two places: the **bytes** in the object store, and a **row** in `lab03.documents` that points to them (`bucket` + `object_key`). In this practice you write four small functions that work with both places, then a short script that uses them.

Everything you need is already in the lab: `connect_db()`, `s3_client()` and `BUCKET` come from `large_objects/common.py`, and `upload.py` / `download.py` show the same kind of calls. Each function in `student.py` has hints that name the exact calls to use.

## Before you start

1. `node1` and `objectstore` are running (only one of `node1` / `node2` may run at a time).
2. You ran `python labs/lab03/large_objects/setup.py` once.
3. You uploaded at least one file with `upload.py`.

## Task 1 — Is my connection encrypted? (`tls_info`)

Run one query on `pg_stat_ssl` and return its three values in a dictionary:

```python
{'ssl': True, 'version': 'TLSv1.3', 'cipher': 'TLS_AES_256_GCM_SHA384'}
```

## Task 2 — Which files does a student have? (`list_student_objects`)

Ask the object store for all keys that start with `students/<student_id>/` and return `(key, size)` pairs sorted by key. If the student has no files, return `[]`.

```python
list_student_objects(s3, "lab03", 5)
# [('students/5/aa11-notes.txt', 120), ('students/5/bb22-lab.pdf', 9000)]
```

## Task 3 — Delete a document from both places (`delete_document`)

1. Find the row's `bucket` and `object_key`. No row → return `False`.
2. Delete the row and `commit()`.
3. Delete the object, then return `True`.

Delete the row **first**. If the program stops between steps 2 and 3, only an unused object is left. With the opposite order, a row would point to a file that no longer exists.

## Task 4 — Find what does not match (`find_inconsistencies`)

The two places can disagree, for example after a crash or a manual delete. Collect the keys from each place as a set and compare them:

| Problem | Meaning | How to compute |
|---|---|---|
| `missing_objects` | a row exists, the file does not | keys in PostgreSQL − keys in the object store |
| `orphan_objects` | a file exists, no row points to it | keys in the object store − keys in PostgreSQL |

```python
find_inconsistencies(conn, s3, "lab03", "students/5/")
# {'missing_objects': [], 'orphan_objects': ['students/5/extra.txt']}
```

This function only reports. It does not delete or fix anything.

## Experiment

Create `experiment.py` beside `student.py`. Start it with:

```python
from student import BUCKET, connect_db, s3_client, tls_info, list_student_objects, \
    delete_document, find_inconsistencies
from upload import upload
```

Choose a student id that exists in `lab03.students`, then:

1. Print `tls_info` for a connection from `connect_db()`.
2. Upload two small files of your own for that student with `upload(student_id, path)`, and print `list_student_objects`.
3. Delete one of the two objects directly with `s3.delete_object(...)`. Print `find_inconsistencies` for the student's prefix: it should report that key as missing. Fix it with `delete_document` (use the document id that `upload` returned), and print `find_inconsistencies` again: both lists should be empty.

## What to Submit

- `student.py`: the four completed functions.
- `experiment.py`: the three steps above.
- `results.md`: the output of `test_student.py` and of `experiment.py`, and short answers:
  1. In Task 2, why does the prefix end with `/`? What would go wrong for student 1 without it?
  2. In Task 3, if the program stops after deleting the row but before deleting the object, what is left behind? Which list of Task 4 would show it?

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab03\practice\test_student.py
.\.venv\Scripts\python.exe labs\lab03\practice\experiment.py
```

The starter raises `NotImplementedError` until completed. The checks create and remove their own test students (ids 9001 and 90010) and never touch your rows or files. Do not modify the provided checks or the original lab modules. Do not submit certificates, keys, downloaded files or your virtual environment.
