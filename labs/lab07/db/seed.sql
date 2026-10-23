INSERT INTO lab07.accounts (id, owner, balance, version)
VALUES
    (1, 'Lab 7 account A', 1000, 0),
    (2, 'Lab 7 account B', 1000, 0)
ON CONFLICT (id) DO UPDATE
SET owner = EXCLUDED.owner,
    balance = EXCLUDED.balance,
    version = EXCLUDED.version;
