-- Hosted serving set: the stored-run files the review workspace reads (Fusion outputs and the evidence of the stage runs
-- they were built from), kept in the database so the hosted instance (Vercel: no persistent disk) reads them from here
-- and never from its deployment bundle.  Files are Parquet/JSON exactly as the local workspace reads them, so the
-- engines, queue order and every query stay identical (one system).  Loaded by an operator with
-- ``python -m mospi.db.serving load`` (docs/deployment/POSTGRESQL.md §5); verified by size, SHA-256 per file and per chunk,
-- row count and a content digest compared with the source Parquet.
--
-- Bytes are stored in chunks (bytea, uncompressed by PostgreSQL: Parquet is already compressed).  The reader role sees
-- them only through hosted_serving_files / hosted_serving_chunks, i.e. only for runs cleared for hosting.

CREATE TABLE serving_files (
    run_id          text        NOT NULL REFERENCES runs (run_id),
    path            text        NOT NULL CHECK (path ~ '^[a-z_]+/runs/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'),
    stage           text        NOT NULL,
    bytes           bigint      NOT NULL CHECK (bytes >= 0),
    sha256          text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    chunks          integer     NOT NULL CHECK (chunks >= 0),
    rows            bigint,
    source_path     text        NOT NULL,
    source_bytes    bigint      NOT NULL,
    source_sha256   text        NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_rows     bigint,
    content_digest  text,
    transform       text        NOT NULL,
    loaded_by       text        NOT NULL,
    loaded_utc      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, path),
    CHECK ((rows IS NULL) = (source_rows IS NULL)),
    CHECK (rows IS NULL OR rows = source_rows)
);

CREATE TABLE serving_chunks (
    run_id text    NOT NULL,
    path   text    NOT NULL,
    seq    integer NOT NULL CHECK (seq >= 0),
    sha256 text    NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    data   bytea   NOT NULL,
    PRIMARY KEY (run_id, path, seq),
    FOREIGN KEY (run_id, path) REFERENCES serving_files (run_id, path) ON DELETE CASCADE
);
ALTER TABLE serving_chunks ALTER COLUMN data SET STORAGE EXTERNAL;

-- Serving files belong to a registered run that is reviewable.
CREATE FUNCTION serving_files_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM runs WHERE run_id = NEW.run_id AND status IN ('PUBLISHED', 'REGISTERED')) THEN
        RAISE EXCEPTION 'run % is not registered as reviewable; register it before loading its serving files', NEW.run_id;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER serving_files_guard BEFORE INSERT OR UPDATE ON serving_files FOR EACH ROW EXECUTE FUNCTION serving_files_guard();

CREATE VIEW hosted_serving_files AS
SELECT f.run_id, f.path, f.stage, f.bytes, f.sha256, f.chunks, f.rows, f.transform, f.loaded_utc
FROM serving_files f
JOIN runs r ON r.run_id = f.run_id
WHERE r.hosted_visible AND r.status IN ('PUBLISHED', 'REGISTERED');

CREATE VIEW hosted_serving_chunks AS
SELECT c.run_id, c.path, c.seq, c.sha256, c.data
FROM serving_chunks c
JOIN runs r ON r.run_id = c.run_id
WHERE r.hosted_visible AND r.status IN ('PUBLISHED', 'REGISTERED');

-- What the hosted health check may report: the applied schema version, nothing else.
CREATE VIEW hosted_schema_version AS
SELECT max(version) AS version, count(*) AS migrations FROM schema_migrations;
