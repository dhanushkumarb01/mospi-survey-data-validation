-- What the hosted (Vercel) reader role may see.  The reader role is granted these views only, never a base table,
-- so even a leaked hosted credential reveals nothing about runs that are not cleared for hosting
-- (data class SYNTHETIC, or APPROVED_REAL with a recorded approval).
-- Audit rows omit the free-text comment, the evidence snapshot and corrected values (survey values; plan D18);
-- chain verification is therefore published as the result recorded on the processing machine.

CREATE VIEW hosted_runs AS
SELECT run_id, release, observation, fusion_version, status, data_class, records, manifest_sha256, code_version, registered_utc, published_utc
FROM runs
WHERE hosted_visible AND status IN ('PUBLISHED', 'REGISTERED');

CREATE VIEW hosted_audit_events AS
SELECT e.run_id, e.event_id, e.case_id, e.event_type, e.actor, e.event_timestamp_utc, e.decision, e.reason_code, e.verification_source,
       e.corrected_field, e.lane, e.opened_at_utc, e.seconds_on_case, e.actor_authenticated, e.actor_role, e.event_hash
FROM audit_events e
JOIN runs r ON r.run_id = e.run_id
WHERE r.hosted_visible AND r.status IN ('PUBLISHED', 'REGISTERED');

CREATE VIEW hosted_audit_verifications AS
SELECT DISTINCT ON (v.run_id) v.run_id, v.status, v.events, v.chained_events, v.last_hash, v.checked_utc
FROM audit_verifications v
JOIN runs r ON r.run_id = v.run_id
WHERE r.hosted_visible AND r.status IN ('PUBLISHED', 'REGISTERED')
ORDER BY v.run_id, v.checked_utc DESC, v.verification_id DESC;

CREATE VIEW hosted_jobs AS
SELECT j.job_id, j.kind, j.status, j.trigger, j.run_id, j.created_utc, j.started_utc, j.finished_utc, j.current_stage, j.error_class
FROM jobs j
WHERE j.kind = 'INTEGRITY_CHECK'
   OR j.run_id IN (SELECT run_id FROM runs WHERE hosted_visible);

CREATE VIEW hosted_integrity_checks AS
SELECT c.check_id, c.job_id, c.target_kind, c.target_id, c.check_name, c.status, c.created_utc
FROM integrity_checks c
WHERE c.target_kind IN ('RUN', 'AUDIT') AND c.target_id IN (SELECT run_id FROM runs WHERE hosted_visible);
