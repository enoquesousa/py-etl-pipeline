# Security Policy

## Supported versions

Security updates are applied to the latest release on the default branch (`main` / `master`). Older tags may not receive patches.

## Reporting a vulnerability

If you believe you have found a security vulnerability in this project, please **do not** open a public issue.

Instead, report it through one of these channels:

1. **GitHub Security Advisories** — open a [private security advisory](https://github.com/enoquesousa/py-etl-pipeline/security/advisories/new) for this repository (preferred when the feature is enabled).
2. **Maintainer contact** — reach out via the contact options on the maintainer’s [GitHub profile](https://github.com/enoquesousa).

Include a short description of the issue, affected components (if known), and steps to reproduce or a proof of concept where safe to share.

You should receive an initial response within a reasonable time frame. Please allow maintainers time to investigate and coordinate a fix before public disclosure.

## Scope

This policy covers the `py-etl-pipeline` codebase, example scripts, and documented deployment patterns (for example Docker Compose). Third-party services and databases you connect to are governed by their own providers’ policies.

## Runtime access model

The ETL worker is a CLI/scheduler running with the caller's OS and database
permissions. It has no user accounts, application sessions, JWTs, API keys, or
refresh tokens. Database authentication is performed by the configured driver.
Use a database account scoped to the tables and schema operations the worker
needs; migrations may require broader schema permissions than normal loads.

The optional GraphQL HTTP probe is separate from the worker. It returns only
health, package version, normalized load mode, batch size, and a scheduling
flag. It has no database resolver, mutation, sales/log-record API, or ability to
run the ETL. Do not add sensitive fields without defining an authorization
model for them.

By default, the probe accepts local clients only: actual loopback peer, local
Host, and compatible Origin/fetch metadata. Keep its listener on loopback and
use Uvicorn `--no-proxy-headers`. Local mode rejects forwarding headers. It
trusts other software/users on the same machine and must not be published
through a proxy whose backend connection would appear local.

`ETL_GRAPHQL_PUBLIC=1` explicitly publishes metadata without authentication.
Public mode does not use forwarding headers to make access decisions. If a
deployment requires authenticated monitoring, use an independently configured
gateway and keep its backend private. No Bearer token or password is accepted
as a substitute for that deployment policy. The server supports only GET/POST
at `/graphql`, with GraphiQL and WebSockets disabled. Each body/query string is
limited to 64 KiB before parsing; this is not a concurrency or general query-cost
limit.

## Credential configuration and diagnostics

Supply a complete `DATABASE_URL`, or the required `POSTGRES_USER`,
`POSTGRES_PASSWORD`, and `POSTGRES_DB` fields plus optional host/port. A full URL
is used unchanged and can carry external authentication, TLS, or socket
configuration. The operator is responsible for those settings. For remote
PostgreSQL, configure certificate-verified TLS according to the database's
deployment; the local Compose example does not provision TLS.

Separate fields are validated and encoded through SQLAlchemy 2.1+. Avoid
manually interpolating passwords into URLs. The generated string still contains
credentials needed by the driver, including potentially sensitive query
options, and must not be printed. The diagnostic script and PG fixture failures
omit connection values and raw exceptions; diagnostics use the exact selected
destination and do not fall back to another host or remove TLS options.

CLI/script/Alembic entry points explicitly load the checkout-root `.env` at
startup without overriding exported values. Imports and configuration getters
do not load dotenv files. Library users can deliberately call
`load_environment(path)`. Real dotenv files, keys, and secret directories are
excluded from Git and the Docker build context. Keep local secret files private
and inject deployment credentials through your environment or secret manager.
Avoid credentials in CLI arguments, process logs, shell history, crash dumps,
and serialized configuration.

Compose requires a nonempty password and publishes PostgreSQL only on host
loopback. It passes separate fields to the worker so password characters cannot
change the URL structure. Environment variables remain visible to processes
and Docker administrators. Updating an environment value does not rotate a
password stored in an existing Postgres volume: change the database account and
client configuration together, then restart clients as needed.

Sales data, SQL parameters, audit records, and CSV files can contain business
information even when connection credentials are absent. Protect these files,
database backups, and logs. Enable `SQLALCHEMY_ECHO` only when its disclosure of
SQL/data is appropriate. Use disposable databases for opt-in PostgreSQL tests;
fixtures may create schema objects even though test transactions are rolled
back.
