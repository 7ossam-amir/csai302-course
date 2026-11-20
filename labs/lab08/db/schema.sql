CREATE SCHEMA IF NOT EXISTS lab08;

-- Business table whose changes are audited.
CREATE TABLE IF NOT EXISTS lab08.accounts (
    id integer PRIMARY KEY CHECK (id > 0),
    owner text NOT NULL,
    balance integer NOT NULL CHECK (balance >= 0)
);

-- Audit trail written by a trigger in the same transaction as the change.
CREATE TABLE IF NOT EXISTS lab08.audit_log (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    happened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    db_user text NOT NULL DEFAULT current_user,
    app_user text,
    xact_id bigint NOT NULL DEFAULT pg_current_xact_id()::text::bigint,
    operation text NOT NULL,
    table_name text NOT NULL,
    row_id integer,
    old_row jsonb,
    new_row jsonb
);

CREATE OR REPLACE FUNCTION lab08.audit_row_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO lab08.audit_log (app_user, operation, table_name, row_id, old_row)
        VALUES (current_setting('lab08.app_user', true), TG_OP, TG_TABLE_NAME, OLD.id, to_jsonb(OLD));
        RETURN OLD;
    END IF;
    INSERT INTO lab08.audit_log (app_user, operation, table_name, row_id, old_row, new_row)
    VALUES (
        current_setting('lab08.app_user', true), TG_OP, TG_TABLE_NAME, NEW.id,
        CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END, to_jsonb(NEW)
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER accounts_audit
AFTER INSERT OR UPDATE OR DELETE ON lab08.accounts
FOR EACH ROW EXECUTE FUNCTION lab08.audit_row_change();

-- Two otherwise identical tables: one WAL-logged, one UNLOGGED.
CREATE TABLE IF NOT EXISTS lab08.wal_logged (id integer PRIMARY KEY, payload text NOT NULL);
CREATE UNLOGGED TABLE IF NOT EXISTS lab08.wal_unlogged (id integer PRIMARY KEY, payload text NOT NULL);

-- Rows used by the optional server-crash demonstration.
CREATE TABLE IF NOT EXISTS lab08.crash_markers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
