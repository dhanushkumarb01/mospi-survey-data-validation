# User accounts and sign-in

Every instance of the workspace requires sign-in with a named account. There are three roles.

| Role | Can do |
|---|---|
| Administrator | Everything a supervisor can do, plus uploads, validation runs and batches, retries and integrity checks. Manages supervisor and analyst accounts. |
| Supervisor | Reviews cases, records decisions, exports case lists. |
| Analyst | Reads review lists, analytics, jobs, checks and alerts. Records no decisions and exports nothing. |

The server enforces these permissions; the workspace only hides what a role cannot use. They are defined in
`mospi/auth/roles.py`.

## Where accounts are stored

| Instance | Store |
|---|---|
| Local, with `MOSPI_DATABASE_URL` | The `app_users` table in PostgreSQL (Supabase), migration `0005_users.sql`. The hosted instance uses the same accounts. |
| Local or Docker without a database | A SQLite file: `MOSPI_USERS_DB`, by default `data/auth/users.sqlite` (Docker: the `mospi-auth` volume). |
| Hosted (Vercel) | The same PostgreSQL table, read through two functions (see below). |

Only scrypt hashes of passwords are stored. Sign-in events, password changes and account changes are recorded in
`auth_events`, which is append-only.

## The first administrator

Administrator accounts cannot be created from the workspace. The database refuses to create one on any runtime role
connection, or to change one. Create an administrator on the server:

```
python -m mospi.db.migrate                     # once, to add the account tables
python -m mospi.auth create-admin --username admin --name "Full Name"
```

With PostgreSQL this uses the administrative connection (`MOSPI_DB_ADMIN_URL`). The command prints a temporary
password once. The administrator chooses their own password at their first sign-in.

Other commands, also run on the server:

```
python -m mospi.auth reset-password --username NAME   # any account, including an administrator; also unlocks it
python -m mospi.auth deactivate --username NAME       # or: activate
python -m mospi.auth list
```

## Supervisor and analyst accounts

An administrator opens **Users** in the workspace sidebar to manage these accounts:

1. Enter the person's name, a username and the role, then select **Create account**. The workspace shows a temporary
   password once.
2. Give the username and temporary password to the person through a separate channel, such as a phone call or in person.
   Never send both in the same email.
3. At their first sign-in, the person must choose their own password before anything else opens. It must have at least
   12 characters and must not contain their name or username.

From the same page an administrator can also:
* reset a password, which issues a new temporary password and ends the person's sessions;
* switch a role between supervisor and analyst;
* deactivate or reactivate an account.

Recorded decisions stay attributed to the person after their account is deactivated.

## Sessions and protection against guessing

* After sign-in the browser holds an HttpOnly, SameSite=Strict cookie, which is also Secure on HTTPS. It expires after
  10 hours. Page scripts never see it.
* The cookie is signed with `MOSPI_SESSION_SECRET` (32 or more random characters). Without the variable, a local server
  uses a random secret, so everyone signs in again after a restart. The hosted instance refuses sign-in until the
  variable is set.
* A role change, a deactivation or a password change takes effect within 15 seconds, and it ends the account's other
  sessions.
* Requests that change data must carry the `X-MoSPI-Request` header, which the workspace always sends. This blocks
  cross-site request forgery.
* Five failed sign-ins lock an account for 15 minutes. Each server also limits failed attempts per username and per
  client address.

## Hosted instance (Vercel)

The hosted instance connects as the reader role. That role cannot read the account table. It may only call:

* `auth_login_record(username)`, which returns one account, including its hash, for verification;
* `auth_session_record(user_id)`, which returns one account without the hash.

When `MOSPI_REVIEW_DATABASE_URL` (the insert-only reviewer role) is configured, the hosted instance can also call:

* `auth_note_attempt`, which records sign-in outcomes and locks;
* `auth_change_password`, which lets supervisors and analysts set their own password there. Administrators change
  theirs on the processing machine.

Without the reviewer role:
* account locks are not recorded on the hosted instance (its in-memory limit still applies);
* first-sign-in password changes cannot happen there. People should set their password on the processing machine first.

Accounts are always managed on the processing machine.

Vercel environment variables: `MOSPI_SESSION_SECRET` (Sensitive) replaces the removed `MOSPI_USERS_JSON`.

After pulling this change, apply the migration and the grants with the administrative connection:
`python -m mospi.db.migrate`.
