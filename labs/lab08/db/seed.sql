-- Repeatable fixture: restores the two accounts and clears Lab 8 demo rows.
TRUNCATE lab08.audit_log, lab08.wal_logged, lab08.wal_unlogged, lab08.crash_markers RESTART IDENTITY;

ALTER TABLE lab08.accounts DISABLE TRIGGER accounts_audit;
INSERT INTO lab08.accounts (id, owner, balance)
VALUES
    (1, 'Lab 8 account A', 1000),
    (2, 'Lab 8 account B', 1000)
ON CONFLICT (id) DO UPDATE
SET owner = EXCLUDED.owner,
    balance = EXCLUDED.balance;
DELETE FROM lab08.accounts WHERE id NOT IN (1, 2);
ALTER TABLE lab08.accounts ENABLE TRIGGER accounts_audit;
