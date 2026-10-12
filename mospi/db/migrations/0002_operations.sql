-- Operational state: datasets and their files, the run registry, jobs with stage events,
-- periodic integrity-check findings and persistent alerts.  No survey row is stored here.

CREATE TABLE datasets (
    dataset_id          text        PRIMARY KEY CHECK (dataset_id ~ '^[0-9a-f]{32}$'),
    contract_name       text        NOT NULL,
    release             text        NOT NULL,
    observation         text        NOT NULL,
    source              text        NOT NULL CHECK (source IN ('UPLOAD', 'REGISTERED_PATH')),
    data_class          text        NOT NULL CHECK (data_class IN ('SYNTHETIC', 'INTERNAL_REAL', 'APPROVED_REAL')),
    hosted_approval     text,
    status              text        NOT NULL CHECK (status IN ('RECEIVING', 'PREFLIGHT_PASSED', 'PREFLIGHT_BLOCKED', 'QUEUED', 'VALIDATING',
                                                              'VALIDATED', 'FAILED', 'REJECTED')),
    label               text        CHECK (label IS NULL OR label ~ '^[a-z0-9][a-z0-9_]{0,23}$'),
    input_root          text,
    fingerprint         text,
    mapping_profile     text,
    preflight           jsonb,
    record_counts       jsonb,
    idempotency_key     text        UNIQUE,
    created_by          text        NOT NULL,
    created_by_verified boolean     NOT NULL DEFAULT FALSE,
    created_utc         timestamptz NOT NULL DEFAULT now(),
    confirmed_by        text,
    confirmed_utc       timestamptz,
    updated_utc         timestamptz NOT NULL DEFAULT now(),
    CHECK (data_class <> 'APPROVED_REAL' OR hosted_approval IS NOT NULL)
);
CREATE UNIQUE INDEX datasets_label_uq ON datasets (release, observation, label) WHERE label IS NOT NULL AND status NOT IN ('REJECTED', 'PREFLIGHT_BLOCKED');
CREATE INDEX datasets_fingerprint_idx ON datasets (fingerprint);

CREATE TABLE dataset_files (
    file_id             text        PRIMARY KEY CHECK (file_id ~ '^[0-9a-f]{32}$'),
    dataset_id          text        NOT NULL REFERENCES datasets (dataset_id) ON DELETE RESTRICT,
    level               text        CHECK (level IN ('household', 'person')),
    display_name        text        NOT NULL,
    relative_path       text,
    size_bytes          bigint      NOT NULL CHECK (size_bytes >= 0),
    sha256              text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    content_fingerprint text,
    encoding            text,
    stored_path         text        NOT NULL,
    mtime_ns            bigint,
    created_utc         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dataset_files_dataset_idx ON dataset_files (dataset_id);
CREATE INDEX dataset_files_sha_idx ON dataset_files (sha256);
CREATE INDEX dataset_files_fingerprint_idx ON dataset_files (content_fingerprint);

CREATE TABLE jobs (
    job_id                text        PRIMARY KEY CHECK (job_id ~ '^[0-9a-f]{32}$'),
    kind                  text        NOT NULL CHECK (kind IN ('VALIDATION', 'INTEGRITY_CHECK')),
    status                text        NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'FAILED_QA_GATE', 'INTERRUPTED', 'CANCELLED')),
    trigger               text        NOT NULL CHECK (trigger IN ('MANUAL', 'SCHEDULED', 'CHANGE_DETECTED', 'RETRY')),
    dataset_id            text        REFERENCES datasets (dataset_id),
    run_id                text,
    label                 text,
    idempotency_key       text        UNIQUE,
    attempt               integer     NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    max_attempts          integer     NOT NULL DEFAULT 2,
    parent_job_id         text        REFERENCES jobs (job_id),
    requested_by          text        NOT NULL,
    requested_by_verified boolean     NOT NULL DEFAULT FALSE,
    created_utc           timestamptz NOT NULL DEFAULT now(),
    started_utc           timestamptz,
    finished_utc          timestamptz,
    heartbeat_utc         timestamptz,
    worker                text,
    pid                   integer,
    current_stage         text,
    error_class           text,
    error_message         text,
    result                jsonb,
    updated_utc           timestamptz NOT NULL DEFAULT now(),
    CHECK (kind <> 'VALIDATION' OR dataset_id IS NOT NULL)
);
-- Duplicate-job prevention: one active validation per dataset, one active integrity check overall.
CREATE UNIQUE INDEX jobs_one_active_validation_per_dataset ON jobs (dataset_id) WHERE kind = 'VALIDATION' AND status IN ('QUEUED', 'RUNNING');
CREATE UNIQUE INDEX jobs_one_active_check ON jobs (kind) WHERE kind = 'INTEGRITY_CHECK' AND status IN ('QUEUED', 'RUNNING');
CREATE INDEX jobs_queue_idx ON jobs (kind, status, created_utc);

-- A finished job never changes state again (a retry is a new job), so a failure cannot be turned into a success.
CREATE FUNCTION jobs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('SUCCEEDED', 'FAILED', 'FAILED_QA_GATE', 'INTERRUPTED', 'CANCELLED') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'job % is finished (%); start a retry instead', OLD.job_id, OLD.status;
    END IF;
    IF OLD.status = 'QUEUED' AND NEW.status NOT IN ('QUEUED', 'RUNNING', 'CANCELLED', 'FAILED') THEN
        RAISE EXCEPTION 'job % cannot go from QUEUED to %', OLD.job_id, NEW.status;
    END IF;
    NEW.updated_utc := now();
    RETURN NEW;
END
$$;
CREATE TRIGGER jobs_guard BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION jobs_guard();

CREATE TABLE job_events (
    event_id    bigserial   PRIMARY KEY,
    job_id      text        NOT NULL REFERENCES jobs (job_id),
    stage       text        NOT NULL,
    status      text        NOT NULL CHECK (status IN ('STARTED', 'COMPLETED', 'REUSED', 'FAILED', 'INFO', 'WARNING')),
    message     text,
    created_utc timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_events_job_idx ON job_events (job_id, event_id);

-- Run registry: every Fusion run the system knows.  PENDING/FAILED runs are never listed as reviewable.
CREATE TABLE runs (
    run_id          text        PRIMARY KEY,
    release         text,
    observation     text,
    fusion_version  text,
    dataset_id      text        REFERENCES datasets (dataset_id),
    job_id          text        REFERENCES jobs (job_id),
    status          text        NOT NULL CHECK (status IN ('PENDING', 'PUBLISHED', 'REGISTERED', 'FAILED', 'WITHDRAWN')),
    data_class      text        NOT NULL CHECK (data_class IN ('SYNTHETIC', 'INTERNAL_REAL', 'APPROVED_REAL')),
    hosted_visible  boolean     NOT NULL DEFAULT FALSE,
    records         bigint,
    manifest        jsonb,
    manifest_sha256 text,
    code_version    text,
    registered_utc  timestamptz NOT NULL DEFAULT now(),
    published_utc   timestamptz,
    updated_utc     timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT hosted_visible OR data_class IN ('SYNTHETIC', 'APPROVED_REAL')),
    CHECK (status <> 'PUBLISHED' OR manifest_sha256 IS NOT NULL)
);

CREATE FUNCTION runs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('PUBLISHED', 'REGISTERED') AND NEW.status NOT IN (OLD.status, 'WITHDRAWN') THEN
        RAISE EXCEPTION 'run % is % and can only be withdrawn', OLD.run_id, OLD.status;
    END IF;
    IF OLD.status IN ('PUBLISHED', 'REGISTERED') AND NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 THEN
        RAISE EXCEPTION 'the manifest of a published run never changes (run %)', OLD.run_id;
    END IF;
    IF OLD.status IN ('FAILED', 'WITHDRAWN') AND NEW.status <> OLD.status AND NEW.status <> 'PENDING' THEN
        RAISE EXCEPTION 'run % is % and must be validated again before publication', OLD.run_id, OLD.status;
    END IF;
    NEW.updated_utc := now();
    RETURN NEW;
END
$$;
CREATE TRIGGER runs_guard BEFORE UPDATE ON runs FOR EACH ROW EXECUTE FUNCTION runs_guard();

CREATE TABLE integrity_checks (
    check_id    bigserial   PRIMARY KEY,
    job_id      text        NOT NULL REFERENCES jobs (job_id),
    target_kind text        NOT NULL CHECK (target_kind IN ('RUN', 'DATASET', 'AUDIT', 'STORAGE')),
    target_id   text        NOT NULL,
    check_name  text        NOT NULL,
    status      text        NOT NULL CHECK (status IN ('PASSED', 'FAILED', 'WARNING', 'CHANGED')),
    detail      text,
    created_utc timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX integrity_checks_job_idx ON integrity_checks (job_id);
CREATE INDEX integrity_checks_target_idx ON integrity_checks (target_kind, target_id, created_utc DESC);

CREATE TABLE notifications (
    notification_id  bigserial   PRIMARY KEY,
    severity         text        NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    kind             text        NOT NULL,
    job_id           text        REFERENCES jobs (job_id),
    dataset_id       text        REFERENCES datasets (dataset_id),
    run_id           text,
    message          text        NOT NULL,
    created_utc      timestamptz NOT NULL DEFAULT now(),
    acknowledged_by  text,
    acknowledged_utc timestamptz
);
CREATE INDEX notifications_open_idx ON notifications (created_utc DESC) WHERE acknowledged_utc IS NULL;
