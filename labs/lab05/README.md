# Lab 5 — ORM, Secure Queries, and Query Execution

Completed reference implementation using SQLAlchemy 2.x, NumPy and the existing course Python environment. SQLite runs the ORM exercise without a server; `--postgres` uses the shared course PostgreSQL database and `.env`. Only `lab05_customers` and `lab05_orders` are created; existing lab tables are untouched. Seed data is inserted only when the customers table is empty.

## Run from the repository root (PowerShell)

```powershell
.\.venv\Scripts\python.exe -m pip install -r labs\lab05\requirements.txt
.\.venv\Scripts\python.exe labs\lab05\orm_demo.py
.\.venv\Scripts\python.exe labs\lab05\test_lab05.py
.\.venv\Scripts\python.exe labs\lab05\bench_executor.py
```

Optional PostgreSQL run, after starting the course database:

```powershell
.\.venv\Scripts\python.exe labs\lab05\orm_demo.py --postgres
```

## Requirements mapped to implementation

| Requirement | Implementation |
|---|---|
| ORM integration | `orm_demo.py`: Customer and Order mapped classes, Session, select, transactions |
| Parameterized execution | ORM comparison and `text(... :minimum)` with a separate parameter dictionary |
| Role-based query access | QueryService checks read/report/write permissions before database execution |
| Volcano iterator model | `executors.py`: Scan → Filter → Project, open/next/close, one row per call |
| Simple vectorized executor | VectorScan → VectorFilter → VectorProject, column arrays and Boolean masks per batch |
| SIMD optimized hash join | `simd_hash_join.cpp`: explicit SSE2 four-lane int32 comparison; Python also includes a NumPy version |

## What to explain in the lab

SQLAlchemy maps Python classes to tables. A Session tracks objects and manages a transaction. The ORM query `Customer.name == name` binds the value; it does not paste it into SQL. The raw report uses `:minimum` with a parameter dictionary. The injection string is treated as data and returns no customers. Parameters bind values, not table or column identifiers: dynamic identifiers require an explicit allowlist.

The viewer can look up customers, the analyst can also run reports, and the admin can write orders. Unknown roles are denied. This is application-level authorization: the service's role must be supplied by trusted authentication. The demo does not implement login or PostgreSQL database roles, and code with direct access to the Session can bypass the service. A deployed system must protect that boundary and use least-privilege database credentials.

Volcano is a pull model: Project asks Filter for a row; Filter keeps asking Scan until a predicate matches or the input ends. `None` signals exhaustion. `collect` closes the tree even if evaluation fails; reopening restarts the scan. The vector executor pulls a batch of columns, computes one Boolean mask for all rows, then projects columns. Empty filtered batches are skipped; the last batch may be partial.

The join builds hash buckets from the left relation, then probes with each right key. It compares the key against an entire bucket using `keys == key`. Hash collisions are resolved by checking equality. Every matching index is returned, so duplicate keys preserve SQL inner-join multiplicity. Keys are one-dimensional, signed int64 values; NULL and string join semantics are outside this exercise.

NumPy's native equality kernels can use SIMD CPU dispatch. The Python implementation vectorizes bucket comparison; hashing, probing and result construction still involve Python. SIMD use depends on the installed build and CPU. `np.show_runtime()` reports available capabilities, not proof that every equality call used a particular instruction.

The C++ implementation explicitly uses SSE2 intrinsics: broadcast the probe key, load four bucket keys, compare all four lanes, extract the match mask, and emit matching pairs. A scalar tail handles remaining keys without reading outside the array. It uses signed int32 keys and requires an x86-64 compiler/CPU with SSE2. Compile and run with an existing GCC/MinGW installation:

```powershell
g++ -O2 -std=c++17 -msse2 labs\lab05\simd_hash_join.cpp -o labs\lab05\simd_hash_join.exe
.\labs\lab05\simd_hash_join.exe
```

Or in a Visual Studio x64 Developer PowerShell:

```powershell
cl /O2 /EHsc /std:c++17 labs\lab05\simd_hash_join.cpp /Fe:labs\lab05\simd_hash_join.exe
.\labs\lab05\simd_hash_join.exe
```

Its executable verifies results against a nested-loop join across empty inputs, duplicates, negative keys, forced collisions, scalar tails and 100 random datasets. Compilation requires a C++ toolchain separately from the Python environment.

## Verification and interpretation

`test_lab05.py` compares joins with an independent nested-loop oracle, including duplicates, negative keys, forced collisions and empty inputs. It checks batch boundaries, reopening, malformed input, injection attempts, denied roles and transaction rollback. These database tests run on SQLite; PostgreSQL compatibility requires the optional server run.

`bench_executor.py` verifies equal results before printing timings. Conversion to row/column input happens before timing; output materialization is included. One local timing per implementation is illustrative, not a rigorous benchmark. The NumPy join can be slower than Python dictionary lookup because of per-probe array overhead. Record actual timings rather than claiming a guaranteed speedup.

## شرح سريع بالعربي

ابدئي بتشغيل `orm_demo.py`: هتشوفي البحث بالـORM، تجربة SQL injection، تقرير بمعامل مربوط، ورفض التقرير لدور viewer. بعدها شغّلي الاختبارات ثم المقارنة الزمنية.

في Volcano كل operator بيرجع صف واحد لما الأب يطلبه. في التنفيذ vectorized بنعالج مجموعة صفوف كأعمدة NumPy باستخدام mask. في hash join بنقسم مفاتيح الجدول الأول إلى buckets، وبعدها نقارن مفتاح الجدول الثاني بمفاتيح الـbucket دفعة واحدة. قارني النتائج أولًا، وبعدها ناقشي الزمن والقيود المذكورة فوق.
