# Modular Sanic: Repository Review (second pass)

Reviewed at `af93b86` on main, 2026-10-20. This is after the two fix batches ([#1](https://github.com/jskenney/modular-sanic/pull/1) and [#2](https://github.com/jskenney/modular-sanic/pull/2)). It replaces the first review. Section 5 shows what happened to each earlier finding. No application code was changed.

**How it was reviewed:** I re-read all of the Python, shell, SQL and HTML in the repo, and the `jskenney/sanic-session` fork it installs. I ran `ruff`, `bandit` and `pip-audit`, plus the fork's test suite. Then I ran the server (Sanic 25.12.1) against real memcached and MariaDB 10.11, with `env-example` as `.env` and an SMTP sink. I tested it over HTTP and in headless Chromium. Findings marked **[verified]** were reproduced against that running instance. The others come from reading the code.

---

## 1. Project map

### Purpose
This is a layer on top of Sanic. You drop a `.py` file that defines `sub_bp = Blueprint(...)` into a directory listed in `API_LOCATIONS`, and it is mounted at startup. The framework supplies:

- **Sessions** through the `sanic_session` fork, stored in memcached, with an in-memory fallback.
- **Logon methods:** PAM, an API key, an API-key file, an emailed one-time code, and admin "become user" (su).
- **Shared helpers** for endpoint files: a MySQL/MariaDB pool, a memcached client, an auth helper and a response helper.

### Layout

| Path | Role |
|---|---|
| `server.py` | The framework: env config, sessions, static files, error pages, security headers, blueprint discovery, DB and memcache listeners, `AuthVerification`, `reply()` |
| `api/auth/general/auth.py` | `POST /auth/deauth`, `GET /auth/key`, `/auth/info` and `/auth/refresh`, `POST /auth/rekey`, `/auth/<apikey>/access/{list (GET), add, remove (POST)}`, `/auth/redirect_if_*` |
| `api/auth/pam/auth_pam.py` | `POST /auth/pam` |
| `api/auth/apikey/auth_api.py` | `POST /auth/apikey`, and `POST /auth/apifile` (streamed) |
| `api/auth/email/auth_email.py`, `auth_challenge.py` | `POST /auth/request/challenge` (emails a code), and `POST /auth/challenge` (checks it) |
| `api/auth/switchuser/switch.py` | `POST /auth/su` and `POST /auth/return` |
| `html/logon/*.html`, `html/index.html` (a symlink to `logon/index.html`) | The logon UI. Each page has the same inline `AuthUI` script |
| `errors/404.html` | The default 404 page. There is no `500.html` |
| `setup/` | Install scripts, `auth_tables.sql` (safe to re-run), `auth_tables_reset.sql`, `migrate_apikey_hash.sql` |
| `start.sh` | Creates a venv in `/tmp/demo-venv` on the first run; starts `sanic server --debug --reload --host=0.0.0.0` on later runs |
| `env-example`, `README.md` | Configuration reference, and the developer guide (endpoint authoring, endpoint table, configuration table) |

### Startup and request flow
1. **Import, in the main process and in each worker:**
   - Read `.env`, then probe memcached synchronously. If memcached answers, use `MemcacheSessionInterface`; otherwise use `InMemorySessionInterface`. Either way the cookie is `__Host-session`, Secure, with SameSite taken from `SAMESITE`, and it expires after `AUTH_VALID`.
   - Register the static routes, the error pages, HSTS and the security headers middleware.
   - Discover blueprints: walk `API_LOCATIONS` (resolved against `server.py`'s directory) in sorted order and skip `_*.py`. Import each file that mentions `sub_bp` under a unique module name, and register it if `sub_bp` is a `Blueprint`. A file that fails is logged and skipped.
2. **`before_server_start`, in each worker:** create the aiomcache client, the aiomysql pool (`DB_POOL_MAX`, `autocommit=True`; `app.ctx.pool` is `None` if the database is down), `AuthVerification` and `reply()`.
3. **Each request:**
   - sanic-session loads `request.ctx.session` from the cookie and saves it back on the response.
   - `verify()` uses the session only. It enforces the `AUTH_VALID` idle timeout and the `AUTH_MAX` absolute limit, and returns the user and access **cached in the session**.
   - `verifyapi()` takes a key from a Bearer header or the URL. A key of `session`, `-` or `''` falls back to `verify()`. Any other key is hashed and looked up, then the access is loaded fresh with `access_show()`, without touching the session.
   - `logon()` loads `sanic_info` and `sanic_access` into the session, issuing a new session ID when the identity changes. Logon routes are rate-limited per client address and per username, through memcached.
4. **Authorization** checks the `access` dict in code: `admin/permissions` to manage access, and `admin/become` to su.

---

## 2. Tool and test results

| Check | Result |
|---|---|
| Test suite | **None in this repo**, and no CI. Verification for this review used ad-hoc scripts against a live instance (see section 3). |
| `ruff check --select E,F,W,B,S` | **52 findings**: 34 F401 unused imports, 14 E401 multi-import lines, 3 S608 and 1 B006 (`server.py:401` mutable default). |
| `bandit -r .` | 3 × B608 "SQL built from strings" at `auth_api.py:27`, `auth_api.py:104` and `server.py:317`. **All false positives**: the appended text is the constant `AuthVerification.KEY_VALID`, and user data is always passed as parameters. |
| `pip-audit` | No known vulnerabilities in the resolved set: sanic 25.12.1, sanic-ext 25.12.0, aiomysql 0.3.2, aiomcache 0.8.2, pymemcache 4.0.0, python-pam 2.1.0, environs 15.2.0, cryptography 50.0.2. These are the latest releases. |
| `pip install -r requirements.txt` | Still fails on Python ≥3.12 unless you pass `--no-build-isolation`, because the fork pins `setuptools<60`. `mysqlclient` still needs native headers and nothing uses it. |
| sanic-session fork tests | **21 failed, 18 passed, 1 error.** Nothing has changed in the fork since the first review (`f1494fb`). |

---

## 3. Findings

There are no **critical** findings in this pass. The cross-site admin grant (old C-1) is fixed and verified.

### HIGH

#### H-1. Revoked access keeps working in existing sessions **[verified]**
- `server.py:293-302`: `verify()` returns the `access` that `logon()` copied into the session. Nothing re-reads `sanic_access` until that user logs on again or calls `/auth/refresh`.
- Every session-authenticated permission check relies on this copy: `auth.py:105,121,144` (through `verifyapi` with `-`/`session`) and `switch.py:45`.

**Why it matters.** I deleted **all** of `admin`'s rows from `sanic_access`, then made a request with admin's existing session. It still granted `admin/permissions` to `alice`. The same admin using an API key, which is looked up fresh, got 403. Because `AUTH_VALID` is a sliding window, an admin who has been removed keeps full rights for up to `AUTH_MAX`, 30 days by default, as long as they stay active. The README's advice to "use `/auth/refresh`" only helps if the removed user chooses to call it.

**Fix.** Load access from the database in `verify()` when MySQL is available. It is one indexed query on `sanic_access(user, …)`. Optionally cache it for a few seconds (`ACCESS_CACHE_SECONDS`). Alternatively, keep an `access_version` per user in `sanic_info`, bump it in `access_add`/`access_del`, and reload when the session's copy is stale.

#### H-2. Bad request bodies still crash with a 500, and `start.sh` runs debug mode on all interfaces **[verified]**
- The handlers read `request.json[...]` without checking it: `auth_api.py:19-21`, `auth_challenge.py:16-18`, `auth_email.py:23-25`.
- `start.sh:22-25` runs `--debug --reload -R . --host=0.0.0.0`.

**Why it matters.** I got 500s from:
- `POST /auth/apikey` with an empty body, and with `{}`;
- `/auth/challenge` without `challenge`;
- `/auth/request/challenge` with a JSON list.

`errors/500.html` doesn't exist, so the custom 500 page is not active by default. Under `start.sh`'s `--debug`, those 500s return full tracebacks to anyone who can reach the server. (`/auth/su` already validates its input and returns 400.)

**Fix.** Validate input and return 400, with `sanic-ext` `@validate` or with `data = request.json if isinstance(request.json, dict) else {}` plus `.get()` and type checks. Split `start.sh` into a development mode (`--dev` bound to `127.0.0.1`) and a production example (no debug, with `--cert`/`--key`).

#### H-3. Behind a reverse proxy, everyone shares one rate-limit bucket and HSTS is never sent **[verified]**
- The rate limiter keys on `request.remote_addr or request.ip` (`server.py:286`).
- HSTS checks `request.scheme == 'https'` (`server.py:100`).
- Neither is correct behind a proxy unless Sanic's proxy settings (`SANIC_PROXIES_COUNT`, `SANIC_REAL_IP_HEADER` or `SANIC_FORWARDED_SECRET`) are configured. The README recommends a TLS-terminating proxy (`README.md:25`) but mentions none of these.

**Why it matters.**
- With the default config, 10 failed logons from 10 different `X-Forwarded-For` addresses exhausted the single per-IP bucket. The **real admin's** next logon then got **429**. Behind a proxy, any one person can lock every user out of every logon route, in a loop, for as long as they like.
- With `X-Forwarded-Proto: https`, no `Strict-Transport-Security` header was sent. With `SANIC_PROXIES_COUNT=1` it was.

**Fix.** Document the proxy settings in the README and `env-example`, and recommend `SANIC_PROXIES_COUNT=1` (or `FORWARDED_SECRET`) for the nginx/caddy setup. Consider logging a startup warning when `X-Forwarded-For` headers arrive but none of the proxy settings are configured.

### MEDIUM

#### M-1. Users are logged on under the name they typed, not the name in the database **[verified]**
- `auth_challenge.py:41` calls `logon(request, user)` and `auth_pam.py:28` calls `logon(request, u)` with the name as typed.
- `logon()` (`server.py:415-418`) looks it up with MySQL's case-insensitive collation, but stores the typed string as `session['user']`. (`/auth/apikey`, `/auth/apifile` and su already use the canonical `info[0]['user']`.)

**Why it matters.**
- A challenge logon as `CAROL` succeeded with carol's access, but the session user was `CAROL`. Carol then got **403** listing her own access, because `auth.py:105` compares `username == user` in Python.
- For PAM, two system accounts that differ only in case, or a case-insensitive PAM backend such as SSSD or LDAP, map onto the **same** `sanic_info` row and access. A newly created `Admin` account would inherit `admin`'s rights.
- The per-user rate-limit bucket is keyed by the raw string, so case variants each get their own bucket.

**Fix.** In `logon()`, use `info[0]['user']` as the identity. Make `sanic_info.user` case-sensitive (`VARCHAR(64) COLLATE utf8mb4_bin`), or normalise usernames to lower case everywhere, including in the rate-limit key.

#### M-2. A blueprint that fails partway through registration stays half-loaded **[verified]**
`server.py:159-163`. `app.blueprint()` registers routes one at a time. When a later route clashes with an existing one, Sanic raises `RouteExists` and the `except` logs "Failed to load blueprint". The routes registered before the clash stay live. In my test, `ext/b_two.py` was reported as failed, yet its `/ext/other` route answered 200.

**Fix.** Before calling `app.blueprint()`, check the blueprint's routes against `app.router` (or register into a scratch app first). Or treat a route conflict as fatal, because two files claiming the same path is a deployment error.

#### M-3. The default start script gives remote browsers logons that never stick **[verified]**
`start.sh:22-25` serves plain HTTP on `0.0.0.0`, but the session cookie is `__Host-`/`Secure` (`server.py:38-44`). In Chromium, using a non-localhost hostname over HTTP, the logon page reported success and redirected to `/index.html`. **No cookie was stored**, and `/auth/key` returned 401. The README says TLS is required, but the sample script ignores that.

**Fix.** Bind `start.sh` to `127.0.0.1` for development, and add a TLS example. Optionally log a warning on the first request whose scheme is `http` and whose host isn't localhost.

#### M-4. `AUTH_VALID` above 30 days logs everyone out immediately **[verified]**
`server.py:29,38` passes `AUTH_VALID` to `MemcacheSessionInterface`. When the value is over 2,592,000 seconds, the fork switches it to `0` (`sanic_session/memcache.py:70-72`) and uses it as the cookie `Max-Age` (`base.py:71`). With `AUTH_VALID=3000000`, the logon response carried `Max-Age=0`, so the browser drops the cookie at once and nobody can stay logged on.

**Fix.** In `server.py`, pass `min(AUTH_VALID, 2592000)` to the memcache interface. `verify()` still enforces `AUTH_VALID` itself. Fix the fork so `expiry=0` doesn't produce `Max-Age=0`.

#### M-5. The session backend is still chosen once at import, and memcached is a single point of failure (old M-3) **[verified]**
`server.py:31-47`. If memcached is down at boot, every worker silently uses its own in-memory store. Users then get logged out at random under `--workers N`, and sessions are lost on every reload. If memcached goes down while the server is running, every logon returns **500** (verified), and so does every request that carries a session cookie, static pages included. The memcached client is also created twice (`server.py:36` and `:170`), and the session one is never closed.

**Fix.** Choose the backend explicitly (`SESSION_BACKEND=memcache|memory`) and fail fast. Create one client in `before_server_start` and use it for both. Catch backend errors in the session layer: treat the session as empty and return 503 on logon.

#### M-6. `admin/permissions` is unrestricted, and access changes aren't logged
`auth.py:113-156`. A user holding `admin/permissions` can grant **any** access to anyone, including themselves. I verified a self-grant of `admin/super`, which defeats su's "never become a user with more admin access" rule (`switch.py:56-59`). su and return are logged (`switch.py:26,31,58,63`), but grants and removals are not, so there is no audit trail for the most powerful operation.

**Fix.** Log every `access_add`/`access_del` with actor, target, access, value and client address. Decide whether `permissions` may grant `admin/*` values, and if not, enforce it. At minimum, document that `permissions` is equivalent to root.

#### M-7. Dependency health (old M-13)
- `requirements.txt` pins nothing.
- The fork is installed from a moving `git+https://…` HEAD. Its `pyproject.toml` pins `setuptools<60`, which breaks a normal install on Python ≥3.12. Its tests are red.
- `mysqlclient` (which needs native build headers), `six`, `orjson` and `pydantic` are unused. `pymemcache` is only used for the startup probe.

**Fix.** Use a lock file (`pip-tools` or `uv`) and pin the fork to a tag or SHA. Fix the fork's build requirement (`setuptools>=61`) and its tests. Drop the unused packages.

#### M-8. No automated tests or CI (old M-14)
The auth logic is now substantial: rotation, rate limits, su rules, key hashing and expiry, 503 handling, discovery. None of it is protected against regressions.

**Fix.** Add `pytest` with `sanic-testing`, using the in-memory session backend and a MariaDB service container in GitHub Actions. The ad-hoc checks used for PRs #1 and #2 (about 70 cases) are a ready-made starting list. Add `ruff` to CI.

#### M-9. Setup still grants `shadow`, and the example enables directory listings (old M-12)
`setup/setup.sh:23` adds the service user to the `shadow` group. The README now explains the risk, but the script still does it by default. `env-example:11` sets `SHOW_SITE_CONTENTS=True`.

**Fix.** Make the `shadow` step opt-in, and point to a dedicated `PAM_SERVICE` instead. Set `SHOW_SITE_CONTENTS=False` in `env-example`.

### LOW

| ID | Location | Issue | Fix |
|---|---|---|---|
| L-1 | `server.py:401` | Mutable default `access={}` in `logon()`. | Use `access=None`. |
| L-2 | `server.py:332,349,363,373,402` | `AuthVerification` reads the module-global `app` instead of `request.app`. | Use `request.app.config.MYSQLAVAIL`. |
| L-3 | `server.py:372-398` and `:410-442`; every endpoint | The access-dict query and build are duplicated. Reply payloads repeat the same `env.str('REDIRECT_…')`/`LOGON_LOGO` lookups dozens of times. | Add a `_load_user(cur, user)` helper and small payload helpers. |
| L-4 | `api/auth/*/*.py:1-5`, `server.py:3-11,456` | 34 unused imports. `app.ctx.pam` is now dead code, because `auth_pam.py` creates its own handle, yet `server.py` still imports `pam`, so libpam is required even when the PAM endpoint isn't loaded. | `ruff --fix`; remove `app.ctx.pam` and the import. |
| L-5 | `sanic_session/base.py:166-168` (fork) | Every response to a request carrying a session cookie rewrites the session in memcached and re-sends `Set-Cookie`, including static files (verified for `/logon/logo.webp`, `/favicon.ico` and `/index.html`). | In the fork, save only when the session was modified, or refresh the cookie at most once per interval. |
| L-6 | `setup/auth_tables.sql:9`; `html/logon/index.html:254`; `auth.py:76-96` | API keys: `sanic_info.apikey` has no index, so each API-key request scans the whole table (verified with `EXPLAIN`: `type=ALL`). Keys are still accepted in the URL path, and the `index.html` examples put the new key into URLs, which then land in logs. `POST /auth/rekey` needs no re-authentication, so a stolen session can mint a 1-year key that outlives logoff. | Add `KEY idx_apikey (apikey)`. Show Bearer-header examples. Require a recent logon (`logon_at` within N minutes) for rekey. |
| L-7 | `auth_email.py:25` | `'?user=' + username` is not URL-encoded, and a non-string username raises `TypeError` (500). | `urllib.parse.quote(str(username))` after validation (H-2). |
| L-8 | `auth_api.py:27,104`, `server.py:317` | Bandit B608 false positives from string concatenation. | Inline `KEY_VALID` into the literal, or add `# nosec B608` with a comment. |
| L-9 | `html/logon/*.html` | The same roughly 350-line `AuthUI` script and CSS appear in 8 pages. (`html/index.html` is a symlink, not a copy, which corrects the first review.) | Move them to shared `/logon/auth-ui.js` and `.css`, which also enables L-12. |
| L-10 | `start.sh:5-28`, `setup/setup.sh:7-9` | `start.sh` must be run twice, keeps the venv in `/tmp`, sets a dead `SANIC_CONFIG_FILE=config.py`, and watches the whole tree with `-R .`. `setup.sh` installs Python 3.11 while `start.sh` uses `python3` (3.12 on Ubuntu 24.04). | Install if needed, then start. Use `./.venv` and `-R api`. Use one Python version. |
| L-11 | `setup/install-mysql.sh:29,38-48`; `setup/migrate_apikey_hash.sql` | `install-mysql.sh` echoes the password, splices unquoted input into SQL, grants `ALL` to `'user'@'%'`, sets `query_cache_size` (removed in MySQL 8), and uses a relative path to `auth_tables.sql`. The migration fails if run twice: `ADD COLUMN` has no `IF NOT EXISTS` on MySQL 8. | `read -s`, quoting, least privilege, `"$(dirname "$0")"`. Guard the migration with `information_schema` checks. |
| L-12 | `server.py:113-115` | The default CSP must allow `'unsafe-inline'` scripts and styles for the bundled pages, so it gives little XSS protection. | After L-9, drop `'unsafe-inline'` from `script-src`. |
| L-13 | `errors/` | There is no `500.html`, so the `PAGE_500` default does nothing out of the box. | Ship a simple `errors/500.html`. |
| L-14 | `sanic_session/base.py:121-133` (fork) | The fork still accepts any client-chosen session ID. Session rotation on logon prevents fixation, but anonymous data such as `motd` is still stored under the attacker's ID. | Generate a new ID when the cookie's ID has no stored value. |
| L-15 | `install-443-redirect.sh:7-11` | Breaks with more than one IPv4 address, redirects external traffic only, and appends a duplicate rule on every run. | Drop `--destination`; use `-C` before `-A`. |
| L-DOC-1 | `README.md` | The README doesn't cover reverse-proxy settings (H-3). It says to run `start.sh` while also requiring TLS (M-3). It mentions Docker and compose, but there is no Dockerfile, only a `.dockerignore`. `.gitignore` has duplicate entries plus LaTeX and wine leftovers. | Add a "Running behind a proxy" section; align `start.sh`; drop the Docker mention or add a `Dockerfile`. |

---

## 4. Prioritized top 10

1. **H-1.** Re-read access from the database in `verify()` (or version it), so revoking rights takes effect immediately.
2. **H-3.** Document and set Sanic's proxy settings. Otherwise, behind the recommended proxy, one person can lock everyone out and HSTS is silently off.
3. **H-2.** Validate request bodies (400, not 500) and stop shipping `--debug --host=0.0.0.0` as the default way to run.
4. **M-1.** Log users on under the canonical database username, and make `sanic_info.user` case-sensitive.
5. **M-3 and M-4.** Make the out-of-box run actually keep sessions: TLS or localhost in `start.sh`, and cap the memcache expiry so an `AUTH_VALID` over 30 days doesn't produce `Max-Age=0`.
6. **M-6.** Audit-log access grants and removals, and decide what `admin/permissions` may grant.
7. **M-5.** Choose the session backend explicitly and handle memcached outages without 500s on every page.
8. **M-8.** Add a pytest and `sanic-testing` suite plus CI, seeded from the PR #1/#2 verification cases.
9. **M-7.** Pin dependencies, pin and fix the sanic-session fork (build pin, tests, L-5, L-14), and drop unused packages.
10. **M-2 and L-6.** Make blueprint registration all-or-nothing, and index `sanic_info.apikey`.

---

## 5. Status of findings from the first review

| First review | Status | Notes |
|---|---|---|
| C-1 CSRF admin grant | **Fixed** (#2) | Verified: GETs return 405; a bogus key no longer falls back to the session; `SameSite=Strict`. |
| H-1 Session fixation | **Fixed** (#1) | The ID is rotated on identity change and the cookie uses the `__Host-` prefix. The fork's acceptance of unknown IDs remains as L-14. |
| H-2 Challenge brute force | **Fixed** (#1) | Attempts are counted atomically, rate limits added, and responses are the same for known and unknown users. The proxy caveat is now H-3. |
| H-3 Blocking PAM/SMTP | **Fixed** (#1) | |
| H-4 Debug mode and input 500s | **Open** | Now H-2. |
| H-5 su rules | **Fixed** (#1) | |
| H-6 No-DB crashes | **Fixed** (#2) | |
| M-1 API keys | **Fixed** (#2) | Keys are hashed, expire and are shown once. Residual issues are in L-6. |
| M-2 Swallowed access errors | **Fixed** (#2) | |
| M-3 Session backend fallback | **Open** | Now M-5. |
| M-4 Secure cookie over HTTP | **Partly fixed** | Documented in the README, but `start.sh` still contradicts it: M-3. |
| M-5 Session lifetime | **Fixed** (#1) | The new edge case is M-4. |
| M-6 `env-example` `AUTH_DOMAIN` | **Fixed** (#1) | |
| M-7 `DB_AUTOCOMMIT` | **Fixed** (#1) | |
| M-8 Pool nesting | **Fixed** (#2) | Verified with `DB_POOL_MAX=1`. |
| M-9 Discovery | **Fixed** (#2) | The new partial-registration issue is M-2. |
| M-10 Error pages | **Fixed** (#2) | No `500.html` is shipped: L-13. |
| M-11 Security headers | **Fixed** (#2) | `'unsafe-inline'` remains: L-12. |
| M-12 `shadow` and directory listing | **Open** | Now M-9. |
| M-13 Dependencies | **Open** | Now M-7. |
| M-14 Tests and CI | **Open** | Now M-8. |
| L-1, L-2, L-3, L-8, L-9, L-10, L-11, L-13 | **Open** | Now L-1, L-2, L-3, L-4, L-9, L-10, L-11, L-15. |
| L-4, L-5, L-6, L-7, L-12 | **Fixed** (#1) | |
| L-14 (`MEMCACHED_PORT` as a string, a double probe) | **Open** | Folded into M-5. |
| L-15 (error-page file handles) | **Fixed** (#2) | |
| L-DOC-1 README | **Fixed** (#2) | The remaining gaps are in the new L-DOC-1. |
| L-DOC-2, L-DOC-3 | **Open** | Folded into the new L-DOC-1. |

**Corrections to the first review:**
- `html/index.html` is a symlink to `html/logon/index.html`, not a copy.
- The original evidence for the challenge race (a correct guess "succeeding as the 13th of 40") was not conclusive, because concurrent requests aren't processed in the order they are sent. The check-then-act weakness was real, and the fix in #1 was verified separately.
