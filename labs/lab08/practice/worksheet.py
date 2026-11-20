"""Lab 8 Worksheet, Part D: three short recovery functions.

Each one is small. Read the docstring, then write the body in place of the TODO.
Records are the `LogRecord` objects of `labs/lab08/aries.py` (for example `db.log.records`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # labs/lab08, for aries.py
from aries import ABORT, BEGIN, CLR, COMMIT, END, UPDATE  # noqa: E402,F401  (use these names)


def redo_decision(record, dpt, disk_page_lsn):
    """Decide what ARIES redo does with one UPDATE or CLR.

    dpt is the dirty page table built by analysis ({page_id: rec_lsn}); disk_page_lsn is the
    pageLSN of record.page_id on disk. Test in this order and return the first that holds:
        "not in DPT"      the page is not in dpt
        "LSN < recLSN"    record.lsn < dpt[page]
        "pageLSN >= LSN"  disk_page_lsn >= record.lsn
        "apply"           otherwise
    Any record that is not an UPDATE or a CLR raises ValueError.
    """
    # TODO
    raise NotImplementedError


def undo_chain(records, tx_id):
    """Return the LSNs of tx_id's UPDATE records that undo still has to compensate, newest first.

    Start at the transaction's last record in `records` and walk backwards:
        UPDATE -> it needs undoing; continue at its prev_lsn
        CLR    -> its update is already undone; continue at its undo_next_lsn
        ABORT or END -> continue at its prev_lsn
        BEGIN  -> stop
    A transaction with no records, or with a COMMIT record, raises ValueError
    (committed work is never undone). `records` may be any slice of the log, so look
    records up by their .lsn, not by their position in the list.
    """
    # TODO
    raise NotImplementedError


def failover_loss(commits, standby_lsn):
    """What a standby promotion loses.

    commits: [(tx_id, commit_lsn, commit_time_seconds), ...] on the old primary, in commit order.
    standby_lsn: the last LSN the standby has flushed. A commit survives if commit_lsn <= standby_lsn.

    Return (lost, window):
        lost   = tx ids of the commits that do not survive, in commit order
        window = 0.0 if nothing is lost; otherwise the time of the last lost commit minus the time of
                 the last surviving commit (or minus the first lost commit, if none survives)
    Raise ValueError if standby_lsn is negative or the commit LSNs do not strictly increase.
    """
    # TODO
    raise NotImplementedError
