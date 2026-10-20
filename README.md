# Modular Sanic

Using Sanic (https://sanic.dev, https://github.com/sanic-org/sanic) as the core, the goal of Modular Sanic is to handle basic tasks such as authentication, sessions, and connections to memcached and MySQL/MariaDB, while loading API endpoints by searching directories for python scripts with the appropriate blueprints.  It allows easy modification to APIs and allows the developer to structure the files in a way that is intuitive.

# Initial Setup

This software requires various Python libraries to operate, see requirements.txt.
A simple start.sh script is provided to create a demo Python virtual environment (venv) location and install the python packages via pip.  The first run of start.sh installs the packages; run it again to start the server.

On a fresh Ubuntu machine the scripts in `setup/` install the supporting services:

- `setup/setup.sh` installs Python, memcached and the build tools, and adds the current user to the `shadow` group for PAM logons (see [PAM logons](#pam-logons)).
- `setup/install-mysql.sh` installs MySQL, creates the database user and database, and loads `setup/auth_tables.sql`.  Run it from inside the `setup/` directory.
- `setup/auth_tables.sql` creates the authentication tables and is safe to re-run.  `setup/auth_tables_reset.sql` drops them (and all their data).
- `setup/migrate_apikey_hash.sql` is a one time upgrade for databases created before API keys were stored hashed (see [API keys](#api-keys)).

## TLS is required

The session cookie is named `__Host-session` and is marked `Secure`, so browsers only store it over HTTPS (browsers treat `http://localhost` as secure, so local development works).  Over plain HTTP to any other host, logons appear to succeed but the session is never kept.  Give Sanic a certificate, for example:

```
sanic server --host=server.example.com --cert=../ssl/bundle.crt --key=../ssl/bundle.key
```

or run it behind a reverse proxy that terminates TLS.  `setup/install-443-redirect.sh` redirects port 443 to Sanic's default port 8000.

## Creating the first administrator

Administrative rights are stored in the `sanic_access` table and there is no web page to create the first administrator.  Log on once (for example with PAM, which creates the user's `sanic_info` row), then grant the rights directly in MySQL:

```sql
INSERT INTO sanic_info (user) VALUES ('alice') ON DUPLICATE KEY UPDATE user=user;
INSERT INTO sanic_access (user, access, value) VALUES
  ('alice', 'admin', 'permissions'),   -- may list, add and remove access for any user
  ('alice', 'admin', 'become');        -- may switch to (su) other users
```

The user picks up new access at their next logon, or immediately through `GET /auth/refresh`.  After that, further access can be managed with the `/auth/<apikey>/access/...` endpoints.

# Basic Usage

The program uses environment variables for most configuration items, take a look at env-example, these can be used on the command line, or you can create a .env file that will be read inside of the scripts, this also makes use in docker and docker compose easier.

The API_LOCATIONS setting is one of the most important, and will point to a list of directories that Modular Sanic should search through upon startup.  Specifically, it will search for all .py files that have a Blueprint line (called sub_bp):

```
sub_bp = Blueprint("auth_api_options", url_prefix="/auth")
```

If that line is present, specifically the sub_bp portion, Modular Sanic will attempt to load the API endpoints from this file.  Details of the discovery:

- Relative API_LOCATIONS are resolved against the directory holding `server.py`, not the current directory.
- Directories and files are loaded in sorted order.  Files whose name starts with `_` (including `__init__.py`) are skipped, which is a convenient place for helper code.
- A file that mentions `sub_bp` but does not define a `sub_bp` Blueprint is skipped with a notice.  A file that fails to import (or whose blueprint name clashes with another) is reported with its traceback and the remaining files still load.
- Every blueprint needs a unique name (the first argument to `Blueprint`).
- Any file in these directories is executed with the server's privileges, so only allow trusted users to write to them.

When Sanic is started with `--reload` and `-R <directory>`, editing a file in a watched directory reloads the server.  Adding a new file does not trigger a reload by itself; it is picked up at the next reload (for example after editing any watched file) or restart.

## Writing an endpoint

Endpoint files get everything they need from `request.app.ctx`:

| Name | Purpose |
|---|---|
| `request.app.ctx.auth` | The `AuthVerification` helper (logon checks, access lookups) |
| `request.app.ctx.reply` | Builds the standard JSON response envelope |
| `request.app.ctx.pool` | aiomysql connection pool, `None` when the database is unavailable |
| `request.app.ctx.mc` | aiomcache client, present when memcached is available |
| `request.app.config.MYSQLAVAIL` / `MEMCACHEAVAIL` | Whether the database / memcached are available |
| `request.app.config.env` | The `environs` reader for configuration values |
| `request.ctx.session` | The user's session (a dict) |

A typical endpoint that requires a logged on user with a particular access:

```python
from sanic import Blueprint
import aiomysql

sub_bp = Blueprint("reports", url_prefix="/api/reports")

@sub_bp.get("/summary")
async def summary(request):
    ok, user, apikey, access, info = await request.app.ctx.auth.verify(request)
    if not ok:
        return request.app.ctx.reply(request, False, {}, status=401)
    if 'reports' not in access or 'read' not in access['reports']:
        return request.app.ctx.reply(request, False, {}, status=403)
    unavailable = request.app.ctx.auth.db_unavailable(request)
    if unavailable:
        return unavailable
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT COUNT(*) AS n FROM sanic_info')
            row = await cur.fetchone()
    return request.app.ctx.reply(request, True, {'users': row['n']})
```

Things to know:

- `auth.verify(request)` checks the web session only and returns `(ok, username, apikey, access, info)`.
- `auth.verifyapi(request, key)` accepts an API key.  The key is read from an `Authorization: Bearer <key>` header when one is sent, otherwise from `key` (for example a URL segment).  A key of `session`, `-` or an empty string checks the web session instead.  Any other key is checked against the database, and the session is neither used nor changed.
- `access` is a dict that maps an access name to a list of values, for example `{'admin': ['permissions', 'become'], 'reports': ['read']}`.  Rows in `sanic_access` are `(user, access, value)`.
- `info` is the user's `sanic_info` row (`user`, `fullname`, `department`, and the API key's `apikey_created` / `apikey_expires` times; the key itself is never included).
- `reply(request, success, data, status=200, error=None)` returns `{"success", "sent", "endpoint", "data"}` (plus `"error"` when given), where `sent` is an ISO-8601 UTC time and `endpoint` is the request path.
- Use `POST` for anything that changes state.  The session cookie is `SameSite=Strict` by default, so it is never sent on cross-site requests; if you relax `SAMESITE`, state-changing POST endpoints become reachable from other sites.
- Release a database connection before calling `auth.logon()` (or other `auth` helpers that use the database), so a request never holds two pooled connections at once.

## API keys

API keys are stored as a SHA-256 hash, so a key is only shown once, in the response to `POST /auth/rekey` (or with the Generate new API key button on `/index.html`).  Generating a new key replaces the old one.  Keys expire `APIKEY_VALID` seconds after they are generated (one year by default, `0` for never).

Send a key as an `Authorization: Bearer <key>` header where possible.  Keys placed in a URL end up in server and proxy logs and browser history.

Databases created before keys were hashed need `setup/migrate_apikey_hash.sql`, run once.  It hashes the existing keys, which keep working with no expiry.

## PAM logons

`/auth/pam` checks a Linux username and password through PAM (`PAM_SERVICE`, default `login`).  Checking passwords with the default service requires the server's user to read `/etc/shadow`, which is why `setup/setup.sh` adds it to the `shadow` group.  That gives the server process, and every endpoint file it loads, read access to the password hashes.  Prefer a dedicated PAM service that limits who may log on (for example with `pam_succeed_if`), and run the server as a dedicated user.

# Built in endpoints

All responses use the JSON envelope described above.  Failed logons return 401, missing rights 403, invalid input 400, too many attempts 429 and an unavailable database or mail server 503.

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/auth/pam` | form: `username`, `password` | PAM logon |
| POST | `/auth/apikey` | JSON: `username`, `apikey` | API key logon |
| POST | `/auth/apifile` | multipart: `files[]` (a file containing the key) | API key file logon |
| POST | `/auth/request/challenge` | JSON: `username` | Email a 7 digit logon code to `username` + `AUTH_DOMAIN` |
| POST | `/auth/challenge` | JSON: `username`, `challenge` | Log on with the emailed code |
| POST | `/auth/deauth` | | Log off |
| GET | `/auth/key` | | Current user and access (401 when logged off) |
| GET | `/auth/info` | | Current user plus site settings used by the logon pages (always 200) |
| GET | `/auth/refresh` | | Reload the current user's access from the database |
| POST | `/auth/rekey` | | Generate a new API key, returned only in this response |
| POST | `/auth/su` | JSON: `username` | Switch to another user (requires `admin`/`become`; never to a user with more admin access) |
| POST | `/auth/return` | | Return to the original user after `/auth/su` |
| GET | `/auth/<apikey>/access/list/<user>` | | List a user's access (own user, or `admin`/`permissions`) |
| POST | `/auth/<apikey>/access/add/<user>/<access>/<value>` | | Grant access (`admin`/`permissions`) |
| POST | `/auth/<apikey>/access/remove/<user>/<access>/<value>` | | Remove access (`admin`/`permissions`) |
| GET | `/auth/redirect_if_logged_on` | | Returns a redirect when logged on |
| GET | `/auth/redirect_if_logged_off` | | Returns a redirect when logged off |

In the `/auth/<apikey>/access/...` paths use `session` or `-` as `<apikey>` to act with your web session, or send the key in an `Authorization: Bearer` header.

The logon pages in `html/logon/` (`logon.html`, `apikey.html`, `apifile.html`, `challenge.html`, `logoff.html`, `su.html`, `return.html`) use these endpoints.

# Configuration

Settings are read from the environment or a `.env` file (see `env-example`).  File paths are relative to the directory the server is started from, except API_LOCATIONS (see above).

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `SanicApp` | Sanic application name |
| `API_LOCATIONS` | `./api,./external` | Comma separated directories searched for endpoint files |
| `HTML` | `./html/` | Static site served at `/` |
| `FAVICON` | `./html/favicon.ico` | Site icon |
| `SHOW_SITE_CONTENTS` | `False` | Directory listings for static directories without an index.html |
| `PAGE_404` | `./errors/404.html` | Page for not found errors (used when the file exists) |
| `PAGE_500` | `./errors/500.html` | Page for unhandled server errors (used when the file exists) |
| `DOCUMENTATION` | `False` | Serve the generated API documentation at `/docs` |
| `HSTS` | not set | When set, the `max-age` in seconds for the Strict-Transport-Security header (HTTPS only) |
| `HSTS_INCLUDE_SUBDOMAINS` | `True` | Add `includeSubDomains` to the HSTS header |
| `CONTENT_SECURITY_POLICY` | self-only policy allowing inline scripts/styles | Content-Security-Policy header for every page except `/docs`; empty to disable |
| `REFERRER_POLICY` | `strict-origin-when-cross-origin` | Referrer-Policy header |
| `DB_HOST`, `DB_PORT` | `127.0.0.1`, `3306` | MySQL/MariaDB server |
| `DB_USER`, `DB_PASS`, `DB_NAME` | `username`, `password`, `dbname` | MySQL/MariaDB credentials and database |
| `DB_POOL_MAX` | `10` | Largest number of pooled database connections per worker |
| `MEMCACHED_HOST`, `MEMCACHED_PORT` | `127.0.0.1`, `11211` | memcached server (sessions and rate limits) |
| `SAMESITE` | `Strict` | Session cookie SameSite setting (`Strict`, `Lax` or `None`) |
| `AUTH_VALID` | `604800` | Seconds of inactivity before a session expires |
| `AUTH_MAX` | `2592000` | Seconds after logon before a session expires, regardless of activity |
| `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW` | `10`, `300` | Logon attempts allowed per client address and per username in each window (seconds) |
| `APIKEY_VALID` | `31536000` | Seconds before a generated API key expires (`0` for never) |
| `PAM_SERVICE` | `login` | PAM service used by `/auth/pam` |
| `REDIRECT_LOGON_SUCCESSFUL` | `/index.html` | Redirect after a successful logon |
| `REDIRECT_LOGON_FAILED` | `/logon/logon.html` | Redirect after an unsuccessful logon |
| `REDIRECT_LOGOFF` | `/index.html` | Redirect after logoff |
| `CHALLENGE_PAGE` | `/logon/challenge.html` | Page for email challenges |
| `LOGON_LOGO` | `/logon/logo.webp` | Image shown on the logon pages |
| `AUTH_MESSAGE` | empty | Sign on / consent banner shown on the logon pages (HTML) |
| `AUTH_TITLE` | `SanicApp` | Logon page title and challenge email subject |
| `AUTH_EMAILER` | `noreply@example.com` | Challenge email sender |
| `AUTH_DOMAIN` | `example.com` | Challenge emails go to `<username>@<AUTH_DOMAIN>` (a leading `@` is allowed) |
| `AUTH_EMAIL_SERVER` | `localhost` | SMTP server for challenge emails |

Without memcached the server falls back to in-memory sessions, which are not shared between workers.  Without the database, PAM logons still work, but API keys, email challenges, switching users and managing access are unavailable (they return 503, or 403 when the session has no access).
