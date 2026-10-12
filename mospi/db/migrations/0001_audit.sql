-- Review and audit trail (moved from one SQLite file per Fusion run; implementation_plan.md §2.3, §5.2).
-- Column types are chosen so the SHA-256 hash chain stays byte-identical to mospi/pipeline/stages/fusion/review.py:
-- timestamps and the evidence snapshot are TEXT (inside the hash), seconds_on_case is double precision,
-- actor_authenticated is a 0/1 integer.  event_id is per run, so the key is (run_id, event_id).

CREATE TABLE audit_events (
    run_id                 text             NOT NULL,
    event_id               bigint           NOT NULL CHECK (event_id > 0),
    case_id                text             NOT NULL,
    event_type             text             NOT NULL,
    actor                  text             NOT NULL,
    event_timestamp_utc    text             NOT NULL,
    decision               text,
    comment                text,
    evidence_snapshot_json text,
    reason_code            text,
    verification_source    text,
    corrected_field        text,
    corrected_value        text,
    lane                   text,
    opened_at_utc          text,
    seconds_on_case        double precision,
    actor_authenticated    smallint CHECK (actor_authenticated IN (0, 1)),
    actor_role             text,
    previous_hash          text,
    event_hash             text,
    origin                 text             NOT NULL DEFAULT 'postgres' CHECK (origin IN ('postgres', 'sqlite_migration')),
    stored_utc             timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, event_id),
    CHECK ((previous_hash IS NULL) = (event_hash IS NULL))
);
CREATE UNIQUE INDEX audit_events_hash_uq ON audit_events (run_id, event_hash) WHERE event_hash IS NOT NULL;
CREATE INDEX audit_events_case_idx ON audit_events (run_id, case_id, event_id);
CREATE INDEX audit_events_decision_idx ON audit_events (run_id, case_id, event_id) WHERE event_type = 'DECISION_MADE';

-- Append-only, enforced by the database for every role (the application role also lacks UPDATE/DELETE).
CREATE FUNCTION audit_reject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit trail is append-only';
END
$$;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_reject();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION audit_reject();

-- Result of every chain verification (local checks, scheduled checks, migration).
CREATE TABLE audit_verifications (
    verification_id bigserial   PRIMARY KEY,
    run_id          text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('INTACT', 'BROKEN', 'NOT_CHAINED', 'NO_AUDIT_STORE')),
    events          integer     NOT NULL DEFAULT 0,
    chained_events  integer,
    last_hash       text,
    detail          text,
    checked_by      text        NOT NULL,
    checked_utc     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_verifications_run_idx ON audit_verifications (run_id, checked_utc DESC);

-- One row per migrated SQLite store (the source file itself is never modified).
CREATE TABLE audit_migrations (
    run_id                text        PRIMARY KEY,
    source_path           text        NOT NULL,
    source_sha256         text        NOT NULL,
    source_format         text        NOT NULL CHECK (source_format IN ('legacy', 'chained')),
    source_events         integer     NOT NULL,
    source_chain_status   text        NOT NULL,
    source_last_hash      text,
    migrated_events       integer     NOT NULL,
    chain_start_added     boolean     NOT NULL,
    destination_status    text        NOT NULL,
    destination_events    integer     NOT NULL,
    destination_last_hash text,
    migrated_by           text        NOT NULL,
    migrated_utc          timestamptz NOT NULL DEFAULT now()
);
