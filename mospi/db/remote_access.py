"""Direct connectivity from the hosted (Vercel) instance to PostgreSQL on this machine, locked down.

    python -m mospi.db.remote_access tls [--dns name]   # private CA + server certificate; PostgreSQL ssl = on
    python -m mospi.db.remote_access hba --tunnel-only   # Cloudflare Tunnel set-up: NO login from beyond this computer (current)
    python -m mospi.db.remote_access hba                 # direct set-up (superseded): reader-only, TLS-only rule; other remote logins rejected
    python -m mospi.db.remote_access status              # what is configured, and what is still missing
    python -m mospi.db.remote_access check --host H      # log in as mospi_reader over TLS with CA verification

What remote clients can do after ``tls`` + ``hba``:
* only the role ``mospi_reader`` (SELECT on the hosted_* views, read-only sessions, connection limit 20),
* only to the database of MOSPI_DB_ADMIN_URL, only over TLS (``hostssl``), only with SCRAM-SHA-256;
* ``postgres``, ``mospi_app`` and every other role are rejected from beyond this computer (``reject`` rules).

The CA private key stays in ``%LOCALAPPDATA%/MoSPI/pki`` (never in the repository); the CA *certificate* (public) is
written to ``deploy/postgres/mospi-db-ca.crt`` so the hosted client can verify the server (``sslmode=verify-ca``).
Each change backs up the file it replaces and is validated by PostgreSQL before the configuration is reloaded.
The router port forwarding and the Windows firewall rule are outside PostgreSQL and are done by the operator
(docs/deployment/POSTGRESQL.md); this tool reports whether they are still missing.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mospi.paths import REPO_ROOT

from .connection import Database, DatabaseUnavailable, redact
from .migrate import READER_ROLE, admin_database

BEGIN, END = "# >>> MoSPI hosted reader (managed by python -m mospi.db.remote_access) >>>", "# <<< MoSPI hosted reader <<<"
CA_PUBLIC = REPO_ROOT / "deploy" / "postgres" / "mospi-db-ca.crt"


def pki_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    folder = Path(base) / "MoSPI" / "pki"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def lan_addresses() -> list[str]:
    found = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))        # no packet is sent; this only selects the outgoing interface
        found.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return sorted(found)


def _write_server_file(db: Database, path: str, content: bytes) -> None:
    """Write a file as the PostgreSQL service account (superuser large-object export); never through the shell."""
    with db.transaction() as connection:
        oid = connection.execute("SELECT lo_from_bytea(0, %s) AS oid", (content,)).fetchone()["oid"]
        try:
            connection.execute("SELECT lo_export(%s, %s)", (oid, path))
        finally:
            connection.execute("SELECT lo_unlink(%s)", (oid,))


def _ca(folder: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key_path, cert_path = folder / "mospi-db-ca.key", folder / "mospi-db-ca.crt"
    if key_path.is_file() and cert_path.is_file():
        return serialization.load_pem_private_key(key_path.read_bytes(), None), x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MoSPI survey validation database CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def configure_tls(db: Database, *, dns: list[str], public_ip: str | None) -> dict[str, object]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    folder = pki_dir()
    ca_key, ca_cert = _ca(folder)
    ips = {"127.0.0.1", *lan_addresses(), *([public_ip] if public_ip else [])}
    names = ["localhost", socket.gethostname(), *dns]
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns[0] if dns else "mospi-postgres")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([*(x509.DNSName(n) for n in dict.fromkeys(names)), *(x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256()))
    data_dir = db.fetchone("SELECT current_setting('data_directory') AS d")["d"]
    _write_server_file(db, f"{data_dir}/mospi_server.crt", cert.public_bytes(serialization.Encoding.PEM))
    _write_server_file(db, f"{data_dir}/mospi_server.key", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                                              serialization.NoEncryption()))
    import psycopg
    with psycopg.connect(db._url, autocommit=True, connect_timeout=10) as connection:      # ALTER SYSTEM cannot run inside a transaction
        for setting, value in (("ssl_cert_file", "mospi_server.crt"), ("ssl_key_file", "mospi_server.key"), ("ssl_min_protocol_version", "TLSv1.2"),
                               ("ssl", "on"), ("password_encryption", "scram-sha-256")):
            connection.execute(f"ALTER SYSTEM SET {setting} = '{value}'")
        connection.execute("SELECT pg_reload_conf()")
    CA_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    CA_PUBLIC.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    return {"server_certificate_names": names, "server_certificate_ips": sorted(ips), "ca_certificate": str(CA_PUBLIC.relative_to(REPO_ROOT)),
            "ca_private_key": str(folder / "mospi-db-ca.key"), "expires": cert.not_valid_after_utc.date().isoformat()}


def hba_block(database: str, *, remote_reader: bool = True) -> str:
    if not remote_reader:
        return "\n".join([BEGIN,
                          "# Cloudflare Tunnel set-up: the hosted instance reaches the read gateway (python -m mospi.gateway serve), which logs in",
                          "# on the loopback interface. No login is accepted from beyond this computer.",
                          "host all all 0.0.0.0/0 reject",
                          "host all all ::/0 reject",
                          END, ""])
    return "\n".join([BEGIN,
                      "# Hosted reader (Vercel): TLS only, one role, one database, SCRAM. Its source addresses are not fixed, so it is not narrowed by IP;",
                      "# the role can only SELECT the hosted_* views. Every other login from beyond this computer is rejected below.",
                      f"hostssl {database} {READER_ROLE} 0.0.0.0/0 scram-sha-256",
                      f"hostssl {database} {READER_ROLE} ::/0 scram-sha-256",
                      "host all all 0.0.0.0/0 reject",
                      "host all all ::/0 reject",
                      END, ""])


def configure_hba(db: Database, *, remote_reader: bool = True) -> dict[str, object]:
    hba_file = db.fetchone("SELECT current_setting('hba_file') AS f")["f"]
    database = db.fetchone("SELECT current_database() AS d")["d"]
    current = db.fetchone("SELECT pg_read_file(%s) AS t", (hba_file,))["t"]
    backup = pki_dir() / f"pg_hba.conf.{_stamp()}.bak"
    backup.write_text(current, encoding="utf-8")
    kept = current.split(BEGIN)[0].rstrip("\n") + ("\n" + current.split(END, 1)[1].lstrip("\n") if END in current else "")
    updated = kept.rstrip("\n") + "\n\n" + hba_block(database, remote_reader=remote_reader)
    _write_server_file(db, hba_file, updated.encode("utf-8"))
    errors = db.fetch("SELECT line_number, error FROM pg_hba_file_rules WHERE error IS NOT NULL")
    if errors:
        _write_server_file(db, hba_file, current.encode("utf-8"))
        raise RuntimeError(f"PostgreSQL rejected the new pg_hba.conf ({errors[0]['error']}); the previous file was restored unchanged.")
    db.fetchone("SELECT pg_reload_conf() AS ok")
    rules = db.fetch("SELECT line_number, type, database, user_name, address, auth_method FROM pg_hba_file_rules ORDER BY line_number")
    return {"hba_file": hba_file, "backup": str(backup), "rules": [{k: (list(v) if isinstance(v, list) else v) for k, v in r.items()} for r in rules]}


def status(db: Database) -> dict[str, object]:
    settings = {r["name"]: r["setting"] for r in db.fetch("SELECT name, setting FROM pg_settings WHERE name IN "
                                                          "('ssl', 'listen_addresses', 'port', 'password_encryption', 'ssl_min_protocol_version', 'ssl_cert_file')")}
    hba = db.fetchone("SELECT pg_read_file(current_setting('hba_file')) AS t")["t"]
    reader = db.fetchone("SELECT rolconnlimit, rolconfig FROM pg_roles WHERE rolname = %s", (READER_ROLE,))
    block = hba.split(BEGIN, 1)[1].split(END, 1)[0] if BEGIN in hba else ""
    return {"settings": settings, "managed_block_installed": bool(block), "remote_reader_login_allowed": "hostssl" in block, "reader_role": dict(reader) if reader else None,
            "ca_certificate_in_repo": CA_PUBLIC.is_file(), "lan_addresses": lan_addresses(),
            "note": "Cloudflare Tunnel set-up (docs/deployment/CLOUDFLARE_TUNNEL.md): no port forward or inbound firewall rule; use hba --tunnel-only."}


def check(host: str, port: int = 5432) -> dict[str, object]:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    admin = conninfo_to_dict(os.environ["MOSPI_DB_ADMIN_URL"])
    password = os.environ.get("MOSPI_DB_READER_PASSWORD", "")
    out: dict[str, object] = {"host": host, "port": port}
    try:
        with psycopg.connect(host=host, port=port, dbname=admin["dbname"], user=READER_ROLE, password=password, sslmode="verify-ca",
                             sslrootcert=str(CA_PUBLIC), connect_timeout=8) as connection:
            row = connection.execute("SELECT current_user, (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS ssl, "
                                     "(SELECT version FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS tls").fetchone()
            out.update(reader_login="OK", role=row[0], ssl=row[1], tls=row[2])
    except psycopg.Error as error:
        out["reader_login"] = f"FAILED: {redact(error)}".splitlines()[0]
    try:
        with psycopg.connect(host=host, port=port, dbname=admin["dbname"], user=admin.get("user", "postgres"), password=admin.get("password", ""),
                             sslmode="require", connect_timeout=8):
            out["superuser_from_this_address"] = "ALLOWED"
    except psycopg.Error as error:
        out["superuser_from_this_address"] = "rejected" if "reject" in str(error) or "no pg_hba.conf entry" in str(error) else f"failed: {redact(error)}".splitlines()[0]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure and check direct, TLS-only reader access to this PostgreSQL server.")
    sub = parser.add_subparsers(dest="command", required=True)
    tls = sub.add_parser("tls")
    tls.add_argument("--dns", action="append", default=[], help="a DNS name the hosted client will use (repeatable)")
    tls.add_argument("--public-ip", help="the public IPv4 address, if stable, to include in the certificate")
    hba = sub.add_parser("hba")
    hba.add_argument("--tunnel-only", action="store_true", help="reject every login from beyond this computer (Cloudflare Tunnel set-up)")
    sub.add_parser("status")
    probe = sub.add_parser("check")
    probe.add_argument("--host", required=True)
    probe.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    try:
        if args.command == "check":
            admin_database()            # loads .env
            print(json.dumps(check(args.host, args.port), indent=2, default=str))
            return 0
        db = admin_database()
        result = configure_tls(db, dns=args.dns, public_ip=args.public_ip) if args.command == "tls" else configure_hba(db, remote_reader=not args.tunnel_only) if args.command == "hba" else status(db)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (RuntimeError, DatabaseUnavailable, ImportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
