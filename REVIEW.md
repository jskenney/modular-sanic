# Modular Sanic: Repository Review

Reviewed at `3cb18e8` (main), 2026-10-19. No application code was changed. This file is the only addition.

**How it was reviewed:** I read all of the Python, shell, SQL and HTML in the repo, plus the `jskenney/sanic-session` fork it depends on. I installed the dependencies in a Python 3.13 venv and ran `ruff` and `bandit`. Then I ran the server against real memcached 1.6 and MariaDB 10.11, loaded `setup/auth_tables.sql`, used `env-example` as `.env`, and tested the auth endpoints over HTTP. Findings marked **[verified]** were reproduced against that running instance.

---

## 1. Project map

### Purpose
This is a thin layer on top of Sanic. It provides:

- **Endpoint auto-discovery.** You drop a `.py` file that defines `sub_bp = Blueprint(...)` into a directory listed in `API_LOCATIONS`, and it is mounted at startup.
- **Sessions** through the `sanic_session` fork, stored in memcached, or in memory as a fallback.
- **Logon methods:** PAM, an API key, an uploaded API-key file, an emailed one-time code, and admin "become user" (su).
- **Shared clients:** a MySQL/MariaDB pool (`app.ctx.pool`), a memcached client (`app.ctx.mc`) and an auth helper (`app.ctx.auth`) that endpoint files can use.
- **A static front end:** the `html/` directory, with logon pages under `html/logon/`.

### Layout

| Path | Role |
|---|---|
| `server.py` | The whole framework: env config, session setup, static routes, error pages, HSTS, blueprint discovery, DB and memcache listeners, and the `AuthVerification` class |
| `api/auth/general/auth.py` | `/auth/deauth`, `/auth/key`, `/auth/info`, `/auth/refresh`, `/auth/rekey`, and `/auth/<apikey>/access/{list,add,remove}/...` |
| `api/auth/pam/auth_pam.py` | `POST /auth/pam` (system username and password) |
| `api/auth/apikey/auth_api.py` | `POST /auth/apikey` and `POST /auth/apifile` |
| `api/auth/email/auth_email.py` | `POST /auth/request/challenge` (emails a 7-digit code) |
| `api/auth/email/auth_challenge.py` | `POST /auth/challenge` (checks the code) |
| `api/auth/switchuser/switch.py` | `POST /auth/su` and `GET /auth/return` |
| `html/`, `html/logon/*.html` | Static UI. Each page has the same inline `AuthUI` JS and CSS (about 350 lines) |
| `errors/404.html` | A 404 page. Nothing points at it by default |
| `setup/*.sh`, `setup/auth_tables.sql` | Ubuntu install helpers and the schema (`sanic_info`, `sanic_access`, `sanic_challenge`) |
| `start.sh` | Creates a venv in `/tmp/demo-venv` and starts `sanic server --debug --reload` |
| `env-example` | Reference configuration |

### Startup and request flow
1. `sanic server` imports `server.py`. This happens in the main process and again in every worker. On import it reads `.env` with `environs`, then probes memcached synchronously with `pymemcache` (`server.py:23-37`). If the probe works it registers `MemcacheSessionInterface`; otherwise it falls back to `InMemorySessionInterface`.
2. It mounts `HTML` at `/` (`server.py:42-48`). It registers the 404 and 500 handlers only if those files exist (`server.py:52-62`).
3. It walks each `API_LOCATIONS` directory. Any `.py` file whose text contains `sub_bp` is executed and its `sub_bp` is registered (`server.py:84-96`).
4. In `before_server_start`, each worker creates its aiomcache client, its aiomysql pool (`MYSQLAVAIL` is set to True or False), `AuthVerification` and `pam.pam()`.
5. For each request, sanic-session middleware loads `request.ctx.session` from the `session` cookie and saves it back on the response. Endpoints call `request.app.ctx.auth.verify(request)`, which only looks at the session, or `verifyapi(request, key)`, which tries the session first and then the DB API key. `logon()` loads `sanic_info` and `sanic_access` into the session.
6. Authorization uses the `access` dict, which maps each access name to a list of values. The checks are hard-coded: `'admin' in access and 'permissions' in access['admin']`, and `... 'become' ...`.

### How a dropped-in endpoint is expected to look
```python
from sanic import Blueprint, response
sub_bp = Blueprint("my_feature", url_prefix="/api/my")

@sub_bp.get("/thing")
async def thing(request):
    ok, user, apikey, access, info = await request.app.ctx.auth.verify(request)
    if not ok: return response.json({"success": False}, status=401)
    async with request.app.ctx.pool.acquire() as conn: ...
```
The README does not document this. See **L-DOC-1**.

---

## 2. Tool results

| Check | Result |
|---|---|
| Test suite | **No tests exist** in this repo. There is no CI, no `pyproject`/`setup.cfg`, and no linter config. |
| `ruff check --select E,F,W,B,S` | **47 findings**: 36 unused imports (`asyncio`, `re`, `openapi` and `aiomysql` in every endpoint file; `text`, `json`, `redirect`, `empty`, `sys` and `response` in `server.py`), multi-import lines, 2 bare `except:` (`server.py:206`, `server.py:218`), 1 in `auth_email.py:28`, a mutable default argument (`server.py:249`) and an unused loop variable (`server.py:85`). |
| `bandit -r .` | 2 low findings: `try/except/pass` at `server.py:206` and `server.py:218`. |
| `pip-audit` (installed env) | No known CVEs in the versions that resolved: sanic 25.12.1, sanic-ext 25.12.0, aiomysql 0.3.2, aiomcache 0.8.2, pymemcache 4.0.0, python-pam 2.1.0, environs 15.2.0, cryptography 50.0.2. |
| `pip install -r requirements.txt` | **Fails** on Python 3.12+ unless you pass `--no-build-isolation`. The `sanic_session` fork pins `setuptools<60` in `pyproject.toml`, and that version imports `pkgutil.ImpImporter`, which no longer exists. `mysqlclient` also fails without `libmysqlclient-dev`, and nothing in the code uses it. |
| sanic-session fork tests (`pytest tests`) | **21 failed, 18 passed, 1 error.** 10 failures are `TypeError: 'CookieJar' object is not subscriptable`: the fork moved to the new cookie API but the tests still index cookies like a dict. The error is a missing `event_loop` fixture (pytest-asyncio ≥0.23). The redis tests fail for the same reasons. |
| `env-example` parsed by python-dotenv | `python-dotenv could not parse statement starting at line 38`. **`AUTH_DOMAIN` is silently dropped** (see M-6). |

---

## 3. Findings

Severity reflects impact × likelihood for a deployment that follows the README and `env-example`.

### CRITICAL

#### C-1. Cross-site request forgery can grant admin: permission changes are cookie-authenticated GETs **[verified]**
- `api/auth/general/auth.py:111-126` (`/auth/<apikey>/access/add/<user>/<access>/<value>`), `:129-144` (`.../remove/...`), `:80-93` (`/auth/rekey`), `:10-23` (`/auth/deauth`)
- `server.py:158-176`: `verifyapi()` **ignores the `<apikey>` path segment whenever the session cookie is valid**.
- `server.py:30,34`: the session cookie is `SameSite=Lax`, and Lax cookies are still sent on top-level cross-site GET navigations.

**Why it matters.** An admin who has `admin/permissions` and is logged in clicks a link, or is redirected by any page, to
`https://site/auth/x/access/add/attacker/admin/permissions`. The browser sends the admin's cookie, the bogus `x` key is ignored, and the attacker becomes an admin. I reproduced this: a request carrying only the admin's cookie and `whatever` as the key wrote `alice|admin|permissions` to `sanic_access`. The same mechanism lets a third party rotate a user's API key (`/auth/rekey`, verified) and log users out.

**Fix.**
- Make every state-changing route `POST`, `PUT` or `DELETE`, and parse its parameters from the body.
- Require an anti-CSRF token or a custom header (for example `X-Requested-With`, which a cross-site form cannot set) on cookie-authenticated mutations. You can also check `Origin`.
- In `verifyapi`, when a key is supplied, validate **the key**. Do not fall back to the session. Better still, take the key from an `Authorization: Bearer` header rather than the URL (see M-1).
- Consider `SameSite=Strict` for the session cookie, since the logon pages are same-origin anyway.

### HIGH

#### H-1. Session fixation: the session ID is never rotated at logon, and client-chosen IDs are accepted **[verified]**
- `server.py:249-285` (`logon`) and `server.py:178-179` (`logoff` only does `session.clear()`).
- `sanic-session/sanic_session/base.py:121-133`: any cookie value is accepted as the session ID, even one that does not exist in the store.

**Why it matters.** I sent `Cookie: session=attackerchosen` to `/auth/apikey`. The response set `session=attackerchosen`, and a second client using that same value was then authenticated as `alice`. Anyone who can plant a cookie can do this: a sibling subdomain, an HTTP downgrade before HSTS is in place, or XSS on any `*.domain`.

**Fix.** Issue a fresh session ID in `logon()`, `su` and `return`: delete the old store key, assign a new `uuid4().hex` to `session.sid`, and mark the session modified. In the sanic-session fork, ignore a cookie ID that has no stored value and generate a new one. Name the cookie `__Host-session` so subdomains cannot set it.

#### H-2. The email challenge can be brute-forced, has a race, and leaks which users exist **[verified]**
- `api/auth/email/auth_email.py:19-29`: a 7-digit code, and `ON DUPLICATE KEY UPDATE ... attempts=0` resets the counter whenever a new code is requested.
- `api/auth/email/auth_challenge.py:20-27`: `SELECT ... attempts < 10` followed by a separate `UPDATE attempts+1`. This is check-then-act with no lock.

**Why it matters.**
- With 40 concurrent wrong guesses, a correct guess placed **13th still succeeded**, so the 10-attempt limit can be exceeded.
- There is no rate limit per IP or per user anywhere. Requesting a new challenge resets the counter, so an attacker can keep guessing indefinitely. It costs about 10⁶ guesses on average, and the victim's inbox gets flooded (an email-bomb vector too).
- Responses reveal whether a user exists: an unknown user returns `200 {"success": false}` because the `sanic_challenge → sanic_info` foreign key rejects the insert, while a known user returns `success: true`, or a 500 if SMTP is down.
- The attempt counter is not compared in constant time, though that is minor next to the issues above.

**Fix.**
- Increment and check atomically: `UPDATE sanic_challenge SET attempts=attempts+1 WHERE user=%s AND attempts<5 AND sent > NOW()-INTERVAL 10 MINUTE`, then check `rowcount` before comparing the code.
- Do not reset `attempts` on re-request, or cap requests per user per hour.
- Add rate limiting per IP and per user (a memcached counter works) for `/auth/request/challenge`, `/auth/challenge`, `/auth/pam` and `/auth/apikey`.
- Always return the same response for "challenge requested".

#### H-3. PAM and SMTP block the event loop, so a few failed logons stall every request **[verified]**
- `api/auth/pam/auth_pam.py:20`: `request.app.ctx.pam.authenticate(u, p)` is synchronous.
- `api/auth/email/auth_email.py:38-39`: `smtplib.SMTP(...).send_message` is synchronous.

**Why it matters.** One wrong-password PAM call took **3.4 s**, mostly `pam_faildelay`. While 5 bad logons were in flight, a simple `GET /auth/key` took **13.6 s**. Anyone can freeze a worker with a handful of requests, and with no rate limit (H-2) PAM is also an online brute-force oracle for **system accounts**, root included.

**Fix.** Use `await asyncio.to_thread(pam.pam().authenticate, u, p)` with a fresh `pam` object per call, because the shared object stores `code` and `reason` state. Do the same for SMTP, or use `aiosmtplib`. Add rate limiting, and restrict PAM logon to an allow-listed group, for example with a `pam_succeed_if` service file instead of the default `login` service.

#### H-4. `start.sh` runs debug mode on all interfaces, and bad input becomes a 500 with a traceback **[verified]**
- `start.sh:22-25`: `--debug --reload -R . --host=0.0.0.0`
- `auth_api.py:14-16`, `auth_challenge.py:14-16`, `auth_email.py:16-17` and `switch.py:39-40` all use `request.json[...]` without validation.

**Why it matters.** A `POST /auth/apikey` with no body returned 500 with a full Python traceback (`TypeError: 'NoneType' object is not subscriptable`). `{}` returned a JSON body that exposed `KeyError: 'username'` and the exception chain. A malformed `session` cookie (`"a b"`, or longer than 250 characters) also returns 500 (aiomcache `ValidationException`). The sample script is what people copy, and it exposes internals on every interface.

**Fix.** Ship two scripts: dev (`--dev`, bound to `127.0.0.1`) and prod (no `--debug`, workers, TLS). Validate inputs. `sanic-ext` and `pydantic` are already installed, so use `@validate(json=Model)`, or at least `data = request.json or {}` with `.get()` and a 400 response. Catch `aiomcache.exceptions.ValidationException` in the session layer and treat that cookie as absent.

#### H-5. "Become" (su) is too strong and `/auth/return` skips the session timeout
- `api/auth/switchuser/switch.py:29-44`:
  - Any user with `admin/become` can become **any** user, including other admins with `permissions`, which is privilege escalation.
  - They receive the target's **permanent API key** in the response (`:41`), so the access outlives the su session.
  - `logon(request, data['username'])` **creates a `sanic_info` row for any string** (verified: `su` to `ghost-user` created a row with a fresh key).
- `switch.py:9-19`: `/auth/return` restores `original_user` without calling `verify()`. It ignores `AUTH_VALID`, so an idle session up to the 30-day memcache lifetime can be returned to admin, and it never re-checks that the original user still has `become`. None of these actions is logged for audit.

**Fix.**
- Refuse to become users who have `admin/*`, unless the actor has a higher privilege.
- Do not return the target's `apikey` in the su response.
- Refuse unknown usernames: check `sanic_info` first.
- Call `verify()` in `/auth/return` and re-check the original user's rights.
- Log every su and return.

#### H-6. Running without MySQL crashes most auth endpoints, though the README says MySQL is optional **[verified]**
- `server.py:114-115` says MySQL is optional, and `setup_db` sets `MYSQLAVAIL=False` without creating `app.ctx.pool`.
- `verifyapi` (`server.py:160`), `auth_api.py:18,75`, `auth_challenge.py:18` and `auth_email.py:24` all use `request.app.ctx.pool` with no guard. Each returns a 500 `AttributeError`.
- `access_show` (`server.py:222-224`) returns the **calling** user's session data instead of the `user` that was asked for.

**Fix.** Set `app.ctx.pool = None`. Have each DB-backed endpoint return a clear `503 {"error": "database unavailable"}`, or skip loading those blueprints when `MYSQLAVAIL` is false. Fix `access_show` to return empty data for other users.

### MEDIUM

#### M-1. API keys are stored in plain text, never expire, and travel in URLs
- `setup/auth_tables.sql:11` stores `apikey` in plain text.
- `server.py:162` and `auth_api.py:20` look keys up directly.
- `auth.py:96,111,129` put the key in the **URL path**, so it lands in Sanic access logs, proxy logs, browser history and `Referer` headers.
- `/auth/key`, `/auth/info` and `/auth/refresh` return the key to any page script, so any XSS turns into a permanent credential.

**Fix.** Store `sha256(key)` and compare against the hash. Accept keys only through `Authorization: Bearer`. Add `created`/`expires` columns. Return the key only once, at creation or `rekey`.

#### M-2. Permission writes swallow errors and always report success **[verified]**
`server.py:204-207` and `:216-219` use bare `except: pass`. Granting access to a user who does not exist fails the foreign key check, the error is discarded, and the endpoint still returns `success: true`. Fix: catch `pymysql.err.IntegrityError`, return `success: false` with a reason, and log the rest.

#### M-3. The session backend is chosen once, at import, and the in-memory fallback is silently per-worker
`server.py:23-37`. If memcached is down at boot, or slow to start under systemd or compose, every worker uses its own `InMemorySessionInterface`. With `--workers N` or `--fast`, users then get randomly logged out and sessions vanish on reload. I saw this when starting with 2 workers. The only signal is a `print`. Fix: make the fallback opt-in (`SESSION_BACKEND=memcache|memory`) and fail fast otherwise. Use one aiomcache client for both the session interface and `app.ctx.mc`, created in `before_server_start`. Today there are two clients, and the session one is never closed. Use `env.int('MEMCACHED_PORT')`.

#### M-4. A `Secure` cookie plus plain HTTP means logon "works" but never sticks
`server.py:30,34` set `secure=True`, while `start.sh` serves plain HTTP on `0.0.0.0`. Browsers drop `Secure` cookies on non-localhost `http://`. Logon returns `success` and then every page acts as if you are logged off. The README never mentions TLS. Fix: document that TLS is required (the `--cert`/`--key` example belongs in the README), or make it `SESSION_SECURE` and default it to true only when TLS is configured.

#### M-5. The session timeout is idle-only, and different expiry values conflict
- `AUTH_VALID` (`server.py:148,159`) is a **sliding** idle timeout, because `visit` is refreshed on every call.
- The memcache entry and the cookie live 30 days (sanic-session default `expiry=2592000`) and slide as well.
- There is no absolute session lifetime, and expired data stays readable by anything that does not call `verify()`, which is how H-5's `/auth/return` gap arises.

**Fix.** Pass `expiry=AUTH_VALID` to the session interface. Add `logon_at` and enforce an absolute maximum (`AUTH_MAX`).

#### M-6. `env-example` breaks email logon: an unterminated quote, plus a default with no `@` **[verified]**
- `env-example:38`: `AUTH_DOMAIN='@example.com` is missing its closing quote, so python-dotenv drops the line.
- `auth_email.py:36` then falls back to `default='example.com'`, which has no `@`, and mails `aliceexample.com`.
- The inline `# comments` after values (lines 23-39) only work because of dotenv's unquoted-value rules. They are fragile and break the same way.

**Fix.** Close the quote. Change the default to `'@example.com'`, or better, build the address as `f"{user}@{domain}"`. Move comments onto their own lines.

#### M-7. `DB_AUTOCOMMIT=False` silently loses every write
`server.py:125` exposes `DB_AUTOCOMMIT`, but nothing calls `await conn.commit()`. If someone sets it to False, new keys, grants and challenges are rolled back when the connection returns to the pool. Fix: remove the option, or commit explicitly in each write helper.

#### M-8. `logon()` holds one pooled connection while `genapikey()` acquires a second
`server.py:260-267` → `server.py:184`. Each first-time logon needs 2 of the pool's default 10 connections. Under a burst of new-user logons, the pool can be exhausted with every holder waiting on its second connection, which is a deadlock. **I could not reproduce this with 30 concurrent first logons** on a local DB, because requests finished too fast, but the pattern is unsafe. Fix: pass `cur` into `genapikey`, or generate the key inline. Also set `maxsize` from the environment.

#### M-9. Blueprint auto-discovery is fragile
`server.py:84-96`:
- **Substring match.** Any file that merely mentions `sub_bp`, even in a comment or docstring, is executed. If it does not define `sub_bp`, startup crashes with `AttributeError`.
- **Every module is named `"sub_bp"`.** Tracebacks are confusing, `pickle` and `multiprocessing` cannot resolve the module, and helper modules in the same folder cannot be imported (`from . import util` fails), because nothing is added to `sys.modules` or `sys.path`.
- **Order is not deterministic.** `os.walk` filenames are unsorted. If two files define the same route, which one wins depends on filesystem order. Duplicate blueprint names crash startup with a vague error.
- **One bad file stops the whole server.** There is no per-file `try/except` with a clear log line.
- **Paths are relative to the current directory**, not to `server.py`, which contradicts the `env-example` comment. Starting from another directory loads nothing.
- **Code in these directories runs with the server's privileges**, which include `shadow` group membership (see M-12). Directory permissions are the security boundary, and the README does not say so.

**Fix.**
- Sort the walk.
- Import with a unique name, for example `modsanic.ext.<relpath>`, and register it in `sys.modules`.
- Detect the blueprint with `isinstance(getattr(mod, 'sub_bp', None), Blueprint)` after import, not with a text search.
- Wrap each file in `try/except` and log failures.
- Resolve paths against `Path(__file__).parent`.
- Skip `_*.py` and `__init__.py`.

#### M-10. Error pages are misconfigured by default and read synchronously on every hit **[verified]**
- `server.py:52` and `env-example:25` default `PAGE_404` to `./html/404.html`, but the file lives at `errors/404.html`. 404s are therefore plain text (verified: `text/plain`).
- `PAGE_500` handles only `ServerError`, so unhandled exceptions, which are what actually happen (H-4), bypass it.
- `open(...).read()` runs on every error and never closes the file.

**Fix.** Point the default at `errors/404.html`. Read both pages once at startup. Register the 500 page for `Exception`, and log the exception.

#### M-11. Missing browser security headers
No CSP, `X-Frame-Options`/`frame-ancestors`, `X-Content-Type-Options` or `Referrer-Policy` headers are sent (verified on `/`). The logon and su pages can be framed, which allows clickjacking. HSTS is enabled only when `HSTS` is in `os.environ` (`server.py:72`), and it adds `includeSubDomains` unconditionally. `showModal(data.message, {html:true})` (for example `html/logon/logon.html:344`) puts `AUTH_MESSAGE` into the page with `innerHTML`. That is acceptable as trusted config, but it is one more reason for a CSP. Fix: add a single response middleware that sets these headers.

#### M-12. Setup adds the service user to `shadow` and enables directory listing
- `setup/setup.sh:23` adds the user to the `shadow` group, so the web process and every auto-loaded endpoint can read `/etc/shadow`.
- `env-example:4` sets `SHOW_SITE_CONTENTS=True`, which lists any directory under `html/` that has no `index.html`.

**Fix.** Use a dedicated PAM service, or `unix_chkpwd`, which is setuid and avoids shadow membership. If you keep shadow membership, run as a dedicated user and document the risk. Default the listing to `False` in `env-example`.

#### M-13. Dependency health
- `requirements.txt` pins nothing. Sanic makes breaking changes between yearly LTS releases (`24.12` → `25.x`). A fresh install today pulls sanic 25.12, and nothing stops a future major release.
- `sanic_session@git+https://github.com/jskenney/sanic-session` follows the moving `HEAD` of a fork. That is a supply-chain and reproducibility risk. The fork's `pyproject.toml` (`setuptools<60`) breaks normal `pip install` on Python ≥3.12, and its own test suite is red (section 2).
- These packages are unused, or not needed directly: `mysqlclient` (needs native build headers and nothing imports it), `six`, `orjson`, `pydantic` (unless adopted for H-4), and `ujson` (pulled in by sanic-session anyway). `pymemcache` exists only for the startup probe, which aiomcache can do.
- `setuptools` and `wheel` in runtime requirements only exist to support `--no-build-isolation`.

**Fix.** Pin to a lock file (`pip-tools` or `uv`). Pin the fork to a tag or commit (`@v0.8.1` or `@<sha>`). Fix the fork's build requirement (`setuptools>=61`) and its tests. Drop unused packages.

#### M-14. No tests, CI or lint configuration
There are no tests at all, so none of the auth logic above (CSRF, timeouts, su, challenge) is protected against regressions.

**Fix.** Add a `pytest` suite using `sanic-testing` (`app.asgi_client`), the in-memory session backend and a MySQL service container in GitHub Actions. Start with these cases:
- logon via apikey, success and failure;
- the `verify()` timeout;
- the `access/add` permission check, including the CSRF case;
- su and return privilege rules;
- challenge attempt limits;
- the no-MySQL behaviour;
- blueprint discovery with fixtures (bad file, comment-only `sub_bp`, duplicate name).

Add `ruff` and a GitHub workflow.

### LOW

| ID | Location | Issue | Fix |
|---|---|---|---|
| L-1 | `server.py:249` | Mutable default `access={}`. With the in-memory backend and no MySQL, the same dict object is shared by every caller's session. | Use `access=None`, then `access = access or {}`. |
| L-2 | `server.py:182,198,210,222,250` | `AuthVerification` reads the module-global `app` rather than `request.app`. This couples it to `server.py` and blocks testing or reuse. | Use `request.app.config.MYSQLAVAIL`, or pass config into `__init__`. |
| L-3 | `server.py:147-176` vs `:178-285` | `verify`/`verifyapi` and `logon`/`access_show` duplicate their session and DB loading code (the access-dict build appears twice). | Write `_load_user(cur, user)` and `_session_tuple(session)` helpers. |
| L-4 | Every endpoint | The response envelope `{'success','sent','endpoint','data'}` is built inline about 30 times. `endpoint` is hard-coded and sometimes wrong (`'/auth/apikey/'` has a trailing slash; the access routes echo raw user input). `sent` is local-time `asctime`. Failures return HTTP 200. | Add one `reply(request, ok, data, status=...)` helper using `request.path` and an ISO-8601 UTC time. Return 401/403 on auth failure. |
| L-5 | `api/auth/apikey/auth_api.py:62-70` | `/auth/apifile` regex-scans `str(File(...))`, the repr of the uploaded bytes. The field must be named `files[]`, and the 10 KB check runs only after Sanic has buffered up to `REQUEST_MAX_SIZE` (100 MB by default). | Decode `request.files.get('files[]').body` explicitly. Lower `REQUEST_MAX_SIZE` for this route, or check `Content-Length`. |
| L-6 | `server.py:148-150` | `verify()` calls `logoff()`, which clears the session, on every anonymous request. Besides the extra writes, this wipes `motd` and anything else an endpoint stored before logon. | Clear only the auth keys (`user`, `access`, `info`, `apikey`, `visit`). |
| L-7 | `api/auth/email/auth_email.py:38` | An SMTP failure raises a 500 after the code has already been stored, and the user gets no clear message. | `try/except smtplib.SMTPException`, then return `success: false`. |
| L-8 | `api/auth/*/*.py:2-4`, `server.py:3-8` | 36 unused imports (see ruff in section 2). | `ruff --fix`. |
| L-9 | `html/logon/*.html` | The same roughly 350-line `AuthUI` script and identical CSS are copied into 8 pages (7 of the `<style>` blocks are byte-identical). `html/index.html` is byte-identical to `html/logon/index.html`. | Move them to `/logon/auth-ui.js` and `/logon/auth-ui.css`, which also makes a strict CSP possible (M-11). |
| L-10 | `start.sh:5-28` | The first run only installs and exits, so you must run it twice. The venv lives in `/tmp` and is wiped on reboot. It sets a dead `SANIC_CONFIG_FILE=config.py`, though `config.py` was removed. It uses `python3`, while `setup.sh:7-9` installs `python3.11` from the deadsnakes PPA (Ubuntu 24.04 ships 3.12). `-R .` reload-watches the whole tree, including `html/`. | Install if needed, then always start. Use `./.venv`. Drop `SANIC_CONFIG_FILE`. Pick one Python version. Use `-R api`. |
| L-11 | `setup/install-mysql.sh` | `read -p` echoes the password (`:39`). The user, password and database name are spliced into SQL and shell unquoted (`:43-45`). It creates `'user'@'%'` (any host) and grants `ALL PRIVILEGES`. It sets `query_cache_size` (`:29`), which MySQL 8 no longer has. `< auth_tables.sql` is relative (`:48`), so it must be run from `setup/`. Ten repeated `sed` passes (`:18-27`). The comment mentions `config.py` (`:50`). | `read -s`. Use `'localhost'` and least-privilege grants (`SELECT, INSERT, UPDATE, DELETE`). Use `"$(dirname "$0")/auth_tables.sql"`. Use `sed -E 's/ +/ /g'`. |
| L-12 | `setup/auth_tables.sql:4-6` | Re-running the schema `DROP`s all user data with no warning. | Use `CREATE TABLE IF NOT EXISTS`, and put destructive resets in a separate file. |
| L-13 | `setup/install-443-redirect.sh:7-11` | `DEST` breaks with more than one IPv4 address (the comment admits it). It adds a `PREROUTING` rule only, so local `https://host` does not redirect. Each run appends a duplicate rule. | Use `--dport 443` without `--destination`, or `-C` before `-A`. Also suggest Sanic behind nginx or caddy. |
| L-14 | `server.py:24-29` | `MEMCACHED_PORT` is read as a string and probed with a second library at import time, in every process (the main process plus each worker). | Use `env.int`, and probe once in `before_server_start` with aiomcache. |
| L-15 | `server.py:56,62` | Error-page handlers `open()` files without closing them. | See M-10. |

#### Docs and developer experience
- **L-DOC-1 (README).** The README covers discovery only. It is missing:
  - how an endpoint checks auth and permissions (`app.ctx.auth.verify`, the `access` dict format);
  - how to use `app.ctx.pool` and `app.ctx.mc`;
  - the DB schema and how to create the first admin. There is no bootstrap: someone has to hand-insert `sanic_access(user,'admin','permissions')`;
  - the TLS requirement (M-4) and the Linux PAM and `shadow` requirement;
  - a table of every environment variable with its default. `PAGE_500`, `DB_AUTOCOMMIT` and `DOCUMENTATION` are undocumented, and `HSTS` has odd semantics;
  - the list of built-in `/auth/*` endpoints and their contracts.

  It also has typos ("te most important"), and its reload claim is overstated: `-R` reloads existing files, but **new** files are found only when the server restarts, because discovery happens at import.
- **L-DOC-2.** `.dockerignore` exists but there is no `Dockerfile` or `compose.yml`, even though the README mentions Docker.
- **L-DOC-3.** `.gitignore` lists `__pycache__` three times and `*.log` twice, and includes LaTeX and wine entries. That is harmless clutter.

---

## 4. Prioritized top 10

1. **C-1.** Move `/auth/.../access/add|remove`, `/auth/rekey` and `/auth/deauth` to POST with CSRF protection, and have `verifyapi` validate the supplied key instead of falling back to the session. *(This is the one exploitable admin takeover.)*
2. **H-1.** Rotate the session ID on logon, su and return, reject unknown session IDs in the sanic-session fork, and use a `__Host-` cookie.
3. **H-2 and H-3.** Add rate limiting to every logon route. Make the challenge attempt counter atomic and stop resetting it. Run PAM and SMTP off the event loop.
4. **H-4.** Stop shipping `--debug --host=0.0.0.0` as the default start script, and validate request bodies (return 400, not 500 with a traceback).
5. **H-5.** Restrict su: no becoming admins, no leaking target API keys, no creating users. Enforce `verify()` in `/auth/return`, and log su events.
6. **M-1.** Hash API keys at rest, move them out of URL paths into the `Authorization` header, and add expiry.
7. **H-6 and M-3.** Make the backend modes explicit: guard every DB endpoint when MySQL is down, and fail fast instead of silently falling back to per-worker in-memory sessions.
8. **M-13.** Pin dependencies (lock file, fork pinned to a commit), fix the fork's `setuptools<60` build pin and failing tests, and drop unused packages such as `mysqlclient`.
9. **M-14.** Add a pytest and `sanic-testing` suite and CI covering the auth flows above, plus ruff.
10. **M-6, M-10, M-4 and L-DOC-1.** Fix `env-example` (the `AUTH_DOMAIN` quote and the 404 path), document TLS, and expand the README with the endpoint-authoring guide, an environment variable reference and the first-admin bootstrap.
