# Lab 5 Practice

An intermediate activity designed for about 60 minutes. Read [STUDENT_TASK.md](STUDENT_TASK.md) for the full instructions.

Students repeat the parts of the lab on a different topic, a small school: an ORM model, bound queries and role checks for students and their grades, the Volcano operators plus a new `Limit`, the vectorized operators, and a bucketed hash join. The tables are `practice05_students` and `practice05_enrollments`, so the `lab05_*` data is not affected.

## Files

- `school.py`: the `Enrollment` model, `SchoolService` and `seed` to complete, with a ready demo.
- `operators.py`: guided stubs for `Filter`, `Project`, `Limit`, `VectorFilter`, `VectorProject` and `hash_join`.
- `compare.py`: checks that the implementations agree, then prints local timings.
- `test_student.py`: checks for the model, injection, roles, rollback, operators and join.
- `STUDENT_TASK.md`: requirements and submission instructions.

## Run

No server is needed; the checks use SQLite in memory.

```powershell
.\.venv\Scripts\python.exe labs\lab05\practice\test_student.py
```
