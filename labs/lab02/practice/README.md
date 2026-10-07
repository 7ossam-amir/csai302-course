# Lab 2 Practice — Build and Use a Mini Buffer Pool

Read [STUDENT_TASK.md](STUDENT_TASK.md) for the complete lab practice instructions, implementation requirements, experiments to perform, submission checklist, and marking rubric.

## Provided Files

- `STUDENT_TASK.md`: lab practice instructions in English.
- `student.py`: starter code with TODOs.
- `test_student.py`: nine public acceptance tests.

Use the existing Lab 2 support modules: DiskManager, LRUReplacer, RowStore, ColumnStore, and EncryptedDiskManager for the optional bonus.

## Practice Overview

| Task | Marks | Suggested time |
|---|---:|---:|
| Complete the buffer pool operations | 45 | 50 minutes |
| Implement FIFO and compare it with LRU | 20 | 20 minutes |
| Query both layouts and measure page reads | 25 | 30 minutes |
| Explain results and add an edge-case test | 10 | 20 minutes |
| Optional encryption and tamper detection | +10 | Optional |

Work individually. PostgreSQL and additional packages are not required for the core tasks.

## Running the Tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe labs\lab02\practice\test_student.py
```

The starter intentionally raises NotImplementedError. Tests will fail until the required implementation is complete.

## Instructor Note

Distribute this directory with the required Lab 2 support modules. Use STUDENT_TASK.md as the authoritative specification. Assess implementation correctness, explanations, state tracing, and the additional edge-case test. Review the optional encryption task separately from the public tests.
