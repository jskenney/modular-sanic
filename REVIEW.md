# Modular Sanic: Repository Review (fourth pass)

Reviewed: `main` at `e20d493` (2026-11-04). That is fix batch 6 ([jskenney/modular-sanic#6](https://github.com/jskenney/modular-sanic/pull/6)) and the pydantic restore ([jskenney/modular-sanic#7](https://github.com/jskenney/modular-sanic/pull/7)), with sanic-session v0.10.0.

This pass covers bugs, runtime errors, security, design, performance and project health, as before. It also adds **§4 Enhancement opportunities**: things that aren't defects but would make the framework easier to run, extend or trust.

Tags:
- **[verified]**: reproduced against a running instance (Sanic 25.12.1, MariaDB, memcached).
- **[measured]**: has numbers.
- **[reasoned]**: from reading the code.

No application code was changed.

## 1. Where the project stands

The core is in good shape. Every High and Medium finding from the first three reviews is fixed except tests and CI:
- session fixation, CSRF and API-key storage;
- revocation, proxy trust, fail-open rate limiting and outage handling;
- the earlier session-library bugs.

On the current code:
- an authenticated `/auth/key` needs **0 SQL queries** and 2 memcached reads per request;
- static files need no memcached access;
- outages return JSON 503s.

What remains:
- **No automated tests.** Two regressions reached `main` in the last batch (§3 H-1).
- **Configuration is checked only when it is first used** (M-1).
- **A few unsafe defaults:** request size, keys in URLs, directory listings.
- **A large single file:** `server.py` (680 lines) holds configuration, sessions, discovery, security headers and the whole `AuthVerification` class.

## 2. Checks run

| Check | Result |
|---|---|
| Regression probes from the earlier batches (about 115 checks) | Batch 1: 33/35. Batch 2: 36/37. Batch 3: 17/20. Batch 6: **24/24**. Every failure is a test-fixture gap (no `boss`, `carol` or PAM accounts in this container) or the intended `motd` and 500-page changes. Nothing has regressed. |
| `ruff --select E9,F` | Clean. With `E,W,B,S`: only 144 long lines and 3 multi-imports. |
| `bandit -r server.py api` | No findings. |
| `pip-audit` on `requirements.lock` | No known vulnerabilities. |
| Throughput, 1 worker, 3 client processes | 3,000 requests: `/auth/key` in 3.6 s, a session-only route in 3.3 s, `/index.html` in 4.5 s [measured]. Static files are the slowest path through Sanic; serve them from the reverse proxy in production, as modular-sanic-docker does. |
| Request bodies | Five parallel 60 MB bodies to `/auth/apikey` took one worker from **60 MB to about 300 MB** resident, then each got a 400 [measured]. Sanic's default `REQUEST_MAX_SIZE` is 100 MB. |
| `.env` typo (`AUTH_RATE_LIMIT=ten`) | The server starts normally. **Every logon then returns the HTML 500 page** (`ValidationError: Not a valid integer`) [verified]. |
| MySQL idle timeout (`wait_timeout=5`, then 8 s idle) | No errors: aiomysql replaces the closed connections [verified]. This is not a finding. |

## 3. Findings

### HIGH

#### H-1. No automated tests or CI, and the last batch shipped two regressions (open since the first review)

Last round:
- **The pydantic removal ([jskenney/modular-sanic#6](https://github.com/jskenney/modular-sanic/pull/6)) broke things,** and was only fixed in [jskenney/modular-sanic#7](https://github.com/jskenney/modular-sanic/pull/7). Sanic silently skipped sanic-ext, so `DOCUMENTATION=True` served no `/docs`, and any extension importing `sanic_ext.openapi` failed to load.
- **aiomcache's `incr` raises instead of returning `None`.** That broke the new access versions and was caught only by a probe that happened to use `flush_all`.

Both would have failed a basic CI run. The probe scripts used for these reviews exist (about 115 checks, plus a browser check of the logon pages), but they live outside the repository and depend on hand-made fixtures.

**Fix:** see E-1.

### MEDIUM

#### M-1. Settings are parsed when first used, so a typo becomes a 500 on every request that reads it **[verified]**

`server.py` and the endpoints call `app.config.env.int(...)`, `env.bool(...)` and `env.str(...)` inside request handlers: `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW`, `AUTH_VALID`, `AUTH_MAX`, `ACCESS_CACHE_SECONDS`, `APIKEY_VALID`, `AUTH_REKEY_WINDOW` and more.

`AUTH_RATE_LIMIT=ten` starts cleanly, then every logon returns the HTML 500 page. Nothing at startup says the configuration is wrong.

**Fix:** read every setting once at startup into a settings object, and stop with a clear message on a bad value (E-2). This also removes about 10 environment lookups per request.

#### M-2. Request bodies up to 100 MB are accepted by every route **[measured]**

Sanic's default `REQUEST_MAX_SIZE` is 100 MB, and modular-sanic doesn't lower it. The JSON endpoints need a few hundred bytes, and `/auth/apifile` streams and limits itself to 64 KB. Yet five anonymous 60 MB requests to `/auth/apikey` pushed a worker from 60 MB to about 300 MB.

Behind modular-sanic-docker, nginx's default `client_max_body_size` (1 MB) protects you. Running Sanic directly (`start.sh production`) doesn't.

**Fix:** a default such as `app.config.REQUEST_MAX_SIZE = env.int('REQUEST_MAX_SIZE', default=1_048_576)`, documented, and overridable with `SANIC_REQUEST_MAX_SIZE` for extensions that take uploads.

#### M-3. API keys in URL paths are echoed back and written to logs **[verified]**

`/auth/<apikey>/access/...`, and every extension that follows the same pattern (modular-sanic-schedules), put the key in the path. `reply()` copies `request.path` into `endpoint`. So `GET /auth/<key>/access/list/admin` returns the full key in the response body. It also lands in Sanic's access log, nginx's log and browser history.

Bearer headers already work everywhere.

**Fix:**
- mask the key in `reply()`, by replacing the segment matched as `<apikey>` with `<apikey>`;
- document Bearer as the way to send keys;
- add an `APIKEY_IN_PATH=False` switch, and later make it the default.

#### M-4. JSON clients get HTML error pages **[verified]**

`GET /auth/nope` with `Accept: application/json` returns `404 text/html` (the `PAGE_404` page). An exception in an extension endpoint returns `500 text/html`. The bundled pages and API clients parse JSON, so they report "unexpected token <" instead of the error.

**Fix:** in `handle_not_found` and `handle_server_errors`, return `reply(..., status=404/500)` when the path is under an API prefix (`/auth/`, `/api/`, or a configurable list) or the client accepts JSON. Keep the HTML pages for browsers.

#### M-5. Unsafe defaults left from earlier reviews (open) **[reasoned]**

- **Directory listings:** `env-example` still ships `SHOW_SITE_CONTENTS=True`, and copying the example is the documented setup. Every directory under `html/` is then listed.
- **`setup/setup.sh`:** adds the service user to `shadow` (a PAM requirement, but undocumented there).
- **`setup/install-mysql.sh`:**
  - `GRANT ALL` to `'user'@'%'`;
  - `sed`s `query_cache_size`, a setting MySQL 8 removed;
  - echoes the password prompt input back.
- **`setup/install-443-redirect.sh`:** appends a duplicate iptables rule on every run.

**Fix:**
- `SHOW_SITE_CONTENTS=False` in the example;
- least-privilege grants (`SELECT, INSERT, UPDATE, DELETE` on the database) for `localhost`;
- `read -s`;
- `iptables -C` before `-A`.

#### M-6. Sessions can lose a concurrent change when the session library refreshes them (sanic-session H-1) **[verified in the fork]**

sanic-session v0.10.0 rewrites an unchanged session once it is older than `refresh_interval`, from whatever the request read. A read-only request that refreshes while another request saves a change writes the old data back, and the change is lost. With `cas=True`, the read-only request gets a 409.

For modular-sanic the window is small: `verify()` already rewrites `visit` every minute, and the refresh interval is AUTH_VALID / 10 (16.8 hours). But it is a silent loss when it happens.

**Fix:** in the fork (its H-1). Until then, `refresh_interval=0` in `server.py` is a safe choice, because `verify()` keeps sessions alive anyway.

#### M-7. Who may change access is still unrestricted, and there is no audit trail (open since the second review) **[reasoned]**

`admin/permissions` lets a user grant anything to anyone, including `admin/permissions` to themselves or others. Logons, failed logons, key generation and access changes aren't recorded anywhere (only `su` is logged, as plain text). For a framework meant for organisational use, "who granted X to Y, and when" can't be answered.

**Fix:** E-4 (audit log). Optionally, a protected set of access names that only a configured super-admin can grant.

### LOW

| ID | Where | Issue | Fix |
|---|---|---|---|
| L-1 | `api/auth/apikey/auth_api.py:97` | A failed key logon (401) returns `redirect: REDIRECT_LOGON_SUCCESSFUL`. | Use `REDIRECT_LOGON_FAILED`. |
| L-2 | `auth_api.py:86`, `auth_pam.py:20`, `auth_challenge.py` | A **failed** logon attempt logs the current session off first, because `logoff()` runs before the credential check. Mistyping a key while logged on loses the session. | Check first, then log off and log on (`logon()` already rotates the id). |
| L-3 | `sanic_challenge.expect` | Email challenge codes are stored in plain text (valid for 10 minutes). Anyone with database read access during that window can log on as the user. | Store `sha256(code)` and compare hashes. |
| L-4 | `GET /auth/refresh` | A GET that writes the session and can insert a `sanic_info` row (via `logon`). Harmless with `SameSite=Strict`, but against the framework's own "POST for state changes" rule. | Make it POST, or make it read-only (use `verify()` with a forced reload). |
| L-5 | `/auth/pam` | Takes form data, while every other logon takes JSON. Extension authors have to know which. | Accept both, or JSON only (the pages already build the request). |
| L-6 | `server.py` | Startup messages use `print("Notice: ...")` while everything else uses `logger`. Under `--workers` they interleave without timestamps or worker ids. | `logger.info`. |
| L-7 | `start.sh` | The venv lives in `/tmp/demo-venv` (lost on reboot). Development mode reloads on changes anywhere under `.` (including `html/`). | `./.venv`; `-R api -R ext`. |
| L-8 | `html/` | Each of the 8 auth pages carries its own copy of the 5 to 10 KB `AuthUI` script and about 10 KB of CSS, and the CSP lists 10 script hashes. A change has to be made 8 times. | E-5. |

## 4. Enhancement opportunities

Each line says what the enhancement gives, and roughly how much work it is.

| ID | Enhancement | Why | Effort |
|---|---|---|---|
| **E-1** | **Test suite and CI.** Move the review probes into `tests/`: <ul><li>a fixture script that creates the users (`admin`, `alice`, `helper`, `boss`, `carol`, `pamtest`);</li><li>pytest with `sanic-testing` for unit checks, plus the live checks against a server;</li><li>a GitHub Actions workflow with MariaDB and memcached services (as sanic-session already has);</li><li>`pip-audit` on the lock file.</li></ul> | Catches regressions like H-1's two before they merge, and makes every later change cheaper to review. | Medium (the checks exist) |
| **E-2** | **A settings object, validated at startup.** One `Settings` class (environs schema, or a pydantic model now that pydantic is installed). Every value is typed and read once; startup stops with a list of bad values. Add `python server.py --check-config`. | Fixes M-1; documents every setting in one place; removes per-request parsing. | Small to medium |
| **E-3** | **Health and readiness endpoint.** `GET /health` returns `{"db": ok, "memcached": ok}`, with 503 when a required one is down; `GET /health/live` for liveness. | modular-sanic-docker's health check and any load balancer can use it (docker review L-1). Outages become visible without reading logs. | Small |
| **E-4** | **Audit log.** A `sanic_audit` table (or structured log lines) for logon success and failure (method, IP), `su`/return, rekey, and access added or removed (by whom). An admin endpoint to read it. | Answers "who did what"; supports M-7; needed by many organisational policies. | Small to medium |
| **E-5** | **One shared logon UI.** `/logon/auth-ui.js` and `/logon/auth-ui.css` used by all 8 pages. | <ul><li>Pages shrink from about 20 KB to about 3 KB each, and the shared files are cacheable.</li><li>One place to change the pages.</li><li>The CSP can drop inline script hashes entirely (`script-src 'self'`).</li></ul> | Medium |
| **E-6** | **API key management.** <ul><li>Several named keys per user, with an optional scope (an access subset) and `last_used`;</li><li>list and revoke endpoints (POST);</li><li>Bearer-only mode (M-3).</li></ul> | Scripts and integrations get their own keys that can be revoked separately. A leaked key doesn't require replacing the one key a user has. | Medium |
| **E-7** | **Admin page for users and access.** A page under `/logon/` (or `/admin/`), on the existing access endpoints plus a "list users" endpoint. | Granting access today means hand-written POST URLs. | Medium |
| **E-8** | **A helper for logon methods.** For example, `await auth.complete_logon(request, user, method='pam')`, which rotates the session, logs on, audits, and builds the standard reply. Plus `auth.require(request, 'admin', 'permissions')` for endpoints. | <ul><li>Every logon method (PAM, key, file, email, and third-party ones such as USNA SSO) repeats throttle, logoff, logon and reply.</li><li>Every protected endpoint repeats the access check.</li><li>Less code in extensions, and fewer chances to get it wrong (L-2).</li></ul> | Small |
| **E-9** | **Generic OIDC / SAML logon.** A standard single-sign-on module (for example with `authlib`), configured from `.env`. | Most institutions offer OIDC. The USNA SSO module shows the need; a standard one avoids hand-rolled token schemes. | Medium to large |
| **E-10** | **OpenAPI for the built-in endpoints.** Request and response models with sanic-ext/pydantic, which would also replace `json_fields`. | `/docs` then documents the auth API, and validation errors become consistent 400s. | Medium |
| **E-11** | **Revoke sessions per user.** "Log out everywhere", and automatic revocation when a user's access is reduced or their key is replaced. Needs sanic-session's per-user index (fork E-3). | Today a stolen session cookie stays valid until AUTH_MAX, even after the user notices. | Medium (across both repos) |
| **E-12** | **`Origin` check on state-changing requests.** Refuse POSTs whose `Origin` isn't the site's own. | Defence in depth if `SAMESITE` is relaxed to `Lax`/`None` for an embedding use case. A few lines. | Small |
| **E-13** | **Structured logging and request ids.** JSON log lines with the user, request id and duration; optionally Prometheus metrics (requests, logons, 4xx/5xx, DB and memcached latency). | Makes the outage and abuse cases from these reviews visible in production. | Small to medium |
| **E-14** | **Split `server.py`, and package it.** Separate `settings.py`, `sessions.py`, `security.py`, `discovery.py` and `auth.py`; a `pyproject.toml` with a `modsanic` console entry point; the Python versions supported. | Easier to test (E-1) and to read. Extensions can import `modsanic.auth` instead of reaching through `request.app.ctx`. | Medium |
| **E-15** | **Email challenge improvements.** Async SMTP (`aiosmtplib`) instead of a thread, an HTML template, optional magic links, and hashed codes (L-3). | Better deliverability and user experience; fixes L-3. | Small |
| **E-16** | **Housekeeping.** `ruff format` and pre-commit, Dependabot (or Renovate) for `requirements.lock`, and a `CHANGELOG.md` (each review batch so far changed behaviour). | Keeps the codebase and dependencies current with little effort. | Small |

## 5. Prioritized top 10 (issues and enhancements together)

1. **E-1 / H-1:** tests and CI, since the probes already exist.
2. **M-1 / E-2:** validate the settings at startup.
3. **M-2:** a 1 MB default request size.
4. **M-3:** mask path keys in replies and logs; move toward Bearer-only (E-6).
5. **M-6:** set `refresh_interval=0` until the fork fixes its refresh race.
6. **M-4:** JSON 404/500 for API clients.
7. **E-3:** a `/health` endpoint, and use it in modular-sanic-docker.
8. **M-7 / E-4:** audit log, and protection of `admin/permissions`.
9. **M-5:** safe defaults in `env-example` and the setup scripts.
10. **E-5, E-8:** a shared logon UI and a logon helper (smaller pages, a stricter CSP, simpler extensions).

## 6. Status of findings from the third review

| Item | Status | Notes |
|---|---|---|
| H-1 rate limiter fails open | **Fixed** (#6) | Verified: logons get a JSON 503 before any check when memcached fails. |
| M-1 DB failure gives an HTML 500 | **Fixed** (#6) | JSON 503, and recovers. |
| M-2 cookieless requests store sessions | **Fixed** (#6) | Banner cookie; 0 new sessions for 50 requests. |
| M-3 two queries per request | **Fixed** (#6) | 0 queries with access versions; static files make 0 memcached reads. |
| M-4 refresh wipes manual access | **Fixed** (#6) | |
| M-5 nested session changes | **Fixed** (#6, sanic-session v0.10.0) | |
| M-6 backend chosen at import | **Fixed** (#6) | `MEMCACHED_REQUIRED`; one shared client. |
| M-7 dependencies | **Fixed** (#6, #7) | #6 removed `pydantic` wrongly; #7 restored it. |
| M-8 tests and CI | **Open** | Now H-1 / E-1. |
| L-1 to L-5 | **Fixed** (#6) | |
| L-6 carried items | **Open** | M-5 (setup and defaults), M-7 (admin and audit), L-8 (shared UI). |
