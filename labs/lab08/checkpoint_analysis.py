"""Measure how checkpoint frequency changes restart work in the Lab 8 ARIES model.

The same seeded workload runs once per checkpoint policy. A long-running batch
transaction starts half-way through and never finishes, the last transaction is
still running, and then the system crashes and recovers. The table compares
normal-operation overhead with restart work, and every run is checked against an
independent record of the committed work.

    python labs/lab08/checkpoint_analysis.py
    python labs/lab08/checkpoint_analysis.py --transactions 200 --flush-every 0
"""

import argparse
import random

from aries import CKPT_BEGIN, CKPT_END, MiniARIES

PAGES = [f"P{i}" for i in range(10)]
BATCH_PAGE = "BATCH"  # only the long-running transaction writes this page


def run_workload(
    checkpoint_every: int | None,
    *,
    flush_dirty: bool = False,
    transactions: int = 58,
    flush_every: int = 4,
    seed: int = 302,
) -> dict:
    """Run one checkpoint policy, crash, recover, and return the measurements."""
    rng = random.Random(seed)
    db = MiniARIES({**{page: 0 for page in PAGES}, BATCH_PAGE: 0})
    committed = {**{page: 0 for page in PAGES}, BATCH_PAGE: 0}  # oracle
    writes = 0

    for number in range(1, transactions + 1):
        if number == transactions // 2:
            batch = db.begin("batch-job")
            db.write(batch, BATCH_PAGE, 1)  # never commits: a long-running loser
        tx = db.begin(f"user{number % 5}")
        staged = {}
        for page in rng.sample(PAGES, 3):
            staged[page] = db.read(tx, page) + rng.randint(1, 9)
            db.write(tx, page, staged[page])
            writes += 1
            if flush_every and writes % flush_every == 0:
                dirty = db.dirty_page_table
                if dirty:  # background writer: clean the page with the oldest recLSN
                    db.flush_page(min(dirty, key=dirty.get))
        if number == transactions:
            pass  # still running at the crash; its records may not even be stable
        elif number % 7 == 0:
            db.abort(tx)
        else:
            db.commit(tx)
            committed.update(staged)
        if checkpoint_every and number % checkpoint_every == 0:
            db.checkpoint(flush_dirty=flush_dirty)

    normal = {
        "log_records": db.log.last_lsn,
        "ckpt_records": sum(r.kind in (CKPT_BEGIN, CKPT_END) for r in db.log.records),
        "page_writes": db.page_writes,
        "log_forces": db.log.forces,
        "truncate_before": db.truncation_point(),
    }
    db.crash()
    report = db.recover()
    return {
        **normal,
        "analysis_scanned": report.analysis_scanned,
        "redo_start": report.redo_start,
        "redo_examined": report.redo_examined,
        "redo_applied": len(report.redo_applied),
        "clrs": len(report.clrs_written),
        "correct": db.current_values() == dict(sorted(committed.items())),
    }


POLICIES = [(None, False), (30, False), (10, False), (5, False), (10, True), (5, True)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transactions", type=int, default=58)
    parser.add_argument("--flush-every", type=int, default=4,
                        help="background writer cleans one page every N writes (0 = never)")
    args = parser.parse_args()

    header = (f"{'policy':<19}{'log':>5}{'ckpt':>6}{'pgW':>5}{'force':>7}{'trunc':>7}"
              f"{'scan':>6}{'redo@':>7}{'redoX':>7}{'redoA':>7}{'CLR':>5}{'ok':>4}")
    print(header)
    print("-" * len(header))
    for every, sharp in POLICIES:
        r = run_workload(every, flush_dirty=sharp,
                         transactions=args.transactions, flush_every=args.flush_every)
        name = "no checkpoint" if every is None else f"every {every} tx" + (" +flush" if sharp else "")
        print(f"{name:<19}{r['log_records']:>5}{r['ckpt_records']:>6}{r['page_writes']:>5}"
              f"{r['log_forces']:>7}{r['truncate_before']:>7}{r['analysis_scanned']:>6}"
              f"{str(r['redo_start']):>7}{r['redo_examined']:>7}{r['redo_applied']:>7}"
              f"{r['clrs']:>5}{'yes' if r['correct'] else 'NO':>4}")
    print("""
log    log records written before the crash     scan   records read by analysis
ckpt   checkpoint records among them            redo@  redo start LSN = min(recLSN)
pgW    data-page writes                         redoX  redo records examined
force  log flushes (commits, WAL rule, ckpts)   redoA  redo records actually applied
trunc  oldest LSN recovery still needs          CLR    compensation records from undo
ok     recovered state equals committed work only""")


if __name__ == "__main__":
    main()
