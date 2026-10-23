CREATE SCHEMA IF NOT EXISTS lab07;

CREATE TABLE IF NOT EXISTS lab07.accounts (
    id integer PRIMARY KEY CHECK (id > 0),
    owner text NOT NULL,
    balance integer NOT NULL CHECK (balance >= 0),
    version integer NOT NULL DEFAULT 0 CHECK (version >= 0)
);
