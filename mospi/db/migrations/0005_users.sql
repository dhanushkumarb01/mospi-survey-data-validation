-- Named user accounts and their sign-in record (mospi/auth).  Three roles: admin, supervisor, analyst.
--
-- * Passwords are stored as scrypt hashes only (mospi/auth/passwords.py); the format is checked here, so a clear-text
--   value can never be written.
-- * Administrator accounts are created and changed only through the administrative connection (the table owner:
--   python -m mospi.auth create-admin).  The runtime roles can add and manage supervisor and analyst accounts, and an
--   administrator can change their own password, but the guard below refuses any runtime statement that would create
--   an administrator, promote an account to one, or change, deactivate or demote one.
-- * session_version is raised whenever a password is set or an account is changed, which ends the account's sessions.
-- * The hosted (Vercel) instance never reads these tables: the reader role may only call auth_login_record and
--   auth_session_record, and the optional insert-only reviewer role auth_note_attempt and auth_change_password
--   (granted in mospi/db/migrate.py).

CREATE TABLE app_users (
    user_id               bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username              text        NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,39}$'),
    display_name          text        NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
    role                  text        NOT NULL CHECK (role IN ('admin', 'supervisor', 'analyst')),
    password_hash         text        NOT NULL CHECK (password_hash ~ '^scrypt\$[0-9]+\$[0-9]+\$[0-9]+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+$'),
    active                boolean     NOT NULL DEFAULT true,
    must_change_password  boolean     NOT NULL DEFAULT true,
    session_version       integer     NOT NULL DEFAULT 1 CHECK (session_version >= 1),
    failed_attempts       integer     NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until          timestamptz,
    last_login_utc        timestamptz,
    created_by            text        NOT NULL,
    created_utc           timestamptz NOT NULL DEFAULT now(),
    updated_utc           timestamptz NOT NULL DEFAULT now()
);

-- Append-only: the runtime role is granted SELECT and INSERT only.
CREATE TABLE auth_events (
    event_id    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type  text        NOT NULL CHECK (event_type IN ('SIGNED_IN', 'SIGN_IN_FAILED', 'ACCOUNT_LOCKED', 'SIGNED_OUT', 'PASSWORD_CHANGED',
                                                           'PASSWORD_RESET', 'USER_CREATED', 'USER_UPDATED')),
    username    text        NOT NULL,
    actor       text        NOT NULL,
    detail      text,
    origin      text        NOT NULL CHECK (origin IN ('local', 'hosted', 'cli')),
    event_utc   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_events_recent ON auth_events (event_utc DESC);

CREATE FUNCTION app_users_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    owner name := (SELECT pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.oid = TG_RELID);
BEGIN
    IF current_user <> owner THEN
        IF TG_OP = 'INSERT' AND NEW.role = 'admin' THEN
            RAISE EXCEPTION 'administrator accounts are created only with the administrative connection (python -m mospi.auth create-admin)';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF NEW.username <> OLD.username OR NEW.created_by <> OLD.created_by OR NEW.created_utc <> OLD.created_utc THEN
                RAISE EXCEPTION 'the username and creation record of an account cannot be changed';
            END IF;
            IF (OLD.role = 'admin' OR NEW.role = 'admin')
               AND (NEW.role <> OLD.role OR NEW.active <> OLD.active OR NEW.display_name <> OLD.display_name) THEN
                RAISE EXCEPTION 'administrator accounts are changed only with the administrative connection';
            END IF;
        END IF;
    END IF;
    NEW.updated_utc := now();
    RETURN NEW;
END
$$;
CREATE TRIGGER app_users_guard BEFORE INSERT OR UPDATE ON app_users FOR EACH ROW EXECUTE FUNCTION app_users_guard();

-- Hosted sign-in: one account by username (with its hash, which the hosted instance verifies itself).
CREATE FUNCTION auth_login_record(p_username text)
RETURNS TABLE (user_id bigint, username text, display_name text, role text, password_hash text, active boolean,
               must_change_password boolean, session_version integer, failed_attempts integer, locked_until timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path FROM CURRENT AS $$
    SELECT u.user_id, u.username, u.display_name, u.role, u.password_hash, u.active, u.must_change_password, u.session_version,
           u.failed_attempts, u.locked_until
    FROM app_users u
    WHERE u.username = lower(btrim(p_username))
$$;

-- Hosted session check on each request: never the hash.
CREATE FUNCTION auth_session_record(p_user_id bigint)
RETURNS TABLE (user_id bigint, username text, display_name text, role text, active boolean, must_change_password boolean,
               session_version integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path FROM CURRENT AS $$
    SELECT u.user_id, u.username, u.display_name, u.role, u.active, u.must_change_password, u.session_version
    FROM app_users u
    WHERE u.user_id = p_user_id
$$;

-- Hosted sign-in outcome: failed-attempt count, lock (5 failures: 15 minutes), last sign-in, and the sign-in record.
CREATE FUNCTION auth_note_attempt(p_username text, p_success boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
DECLARE
    account app_users%ROWTYPE;
BEGIN
    SELECT * INTO account FROM app_users u WHERE u.username = lower(btrim(p_username)) FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO auth_events (event_type, username, actor, detail, origin)
        VALUES ('SIGN_IN_FAILED', left(lower(btrim(p_username)), 40), 'anonymous', 'unknown username', 'hosted');
        RETURN;
    END IF;
    IF p_success THEN
        UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login_utc = now() WHERE user_id = account.user_id;
        INSERT INTO auth_events (event_type, username, actor, origin) VALUES ('SIGNED_IN', account.username, account.username, 'hosted');
    ELSIF account.failed_attempts + 1 >= 5 THEN
        UPDATE app_users SET failed_attempts = 0, locked_until = now() + interval '15 minutes' WHERE user_id = account.user_id;
        INSERT INTO auth_events (event_type, username, actor, detail, origin)
        VALUES ('ACCOUNT_LOCKED', account.username, 'anonymous', '5 failed sign-ins', 'hosted');
    ELSE
        UPDATE app_users SET failed_attempts = failed_attempts + 1 WHERE user_id = account.user_id;
        INSERT INTO auth_events (event_type, username, actor, origin) VALUES ('SIGN_IN_FAILED', account.username, 'anonymous', 'hosted');
    END IF;
END
$$;

-- Hosted password change by the account holder: only when the current hash still matches, never for an administrator.
CREATE FUNCTION auth_change_password(p_user_id bigint, p_old_hash text, p_new_hash text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
DECLARE
    account app_users%ROWTYPE;
BEGIN
    SELECT * INTO account FROM app_users u WHERE u.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR NOT account.active OR account.role = 'admin' OR account.password_hash <> p_old_hash OR p_new_hash = p_old_hash THEN
        RETURN false;
    END IF;
    UPDATE app_users SET password_hash = p_new_hash, must_change_password = false, session_version = session_version + 1
    WHERE user_id = p_user_id;
    INSERT INTO auth_events (event_type, username, actor, origin) VALUES ('PASSWORD_CHANGED', account.username, account.username, 'hosted');
    RETURN true;
END
$$;
