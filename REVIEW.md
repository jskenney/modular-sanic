# Modular Sanic: Repository Review (third pass)

Reviewed: `main` at `0bdcbee` (2026-10-20). This pass covers fix batch 3 (#3), the `.env` fix (#4), the move to sanic-session v0.9.0 (#5), and your two commits since: `96b1771` removes `mysqlclient` and `0bdcbee` adds `PORT` to the `start.sh` development mode.

This pass focuses on **performance, bugs, runtime errors, architecture/design, and project health**. Each finding is tagged:

- **[verified]**: reproduced against a running instance (main, Sanic 25.12.1, sanic-session v0.9.0, MariaDB, memcached).
- **[measured]**: has numbers.
- **[reasoned]**: from reading the code.

No application code was changed.

## 1. Project map (what changed since the second pass)

- **Session handling** now comes entirely from the fork (v0.9.0):
  - the session is opened at request-middleware priority 1000 and saved at response priority -1000;
  - it is saved only when it changed;
  - `interface.regenerate()` is used on logon;
  - a store write failure becomes a 503.
- **`verify()`** re-reads `sanic_info` and `sanic_access` on each request, unless the request falls inside `ACCESS_CACHE_SECONDS` (default 0). It updates `visit` at most once a minute.
- **Rate limiting:**
  - memcached `add`/`incr` when memcached was reachable at import;
  - otherwise a per-worker dict.
- **`SANIC_*` settings in `.env`** are copied into `os.environ` before Sanic reads them.
- **`requirements.txt`:**
  - `mysqlclient` is gone; nothing imported `MySQLdb`, so removing it is safe [verified: fresh install and start];
  - the fork is pinned with `@v0.9.0`.
- **`start.sh` development mode:** `--host=127.0.0.1 --port=${PORT:-8000}`.

## 2. Tool and test results

| Check | Result |
|---|---|
| `ruff check --select E9,F .` | Clean. |
| `bandit -r server.py api` | No findings. |
| `pip-audit`, resolved environment | No known vulnerabilities. |
| Batch-1 regression probe | 34/35. The one failure is a missing `boss` test user in the reseeded DB, not a code change. |
| Batch-2 regression probe | 36/37. The failure is expected: it looks for the old 500-page fixture text. |
| Batch-3 regression probe | 17/20. The failures are the PAM checks, whose system users no longer exist in this container. |
| fork v0.9.0 test suite | 46 passed. |
| fork CI (GitHub Actions) | Green on `main` and `v0.9.0`. |

**Per-request cost, measured by `Questions` and memcached `cmd_get`/`cmd_set` deltas over 200 requests:**

| Request (with a logged-on session cookie) | SQL statements | memcached get | memcached set |
|---|---|---|---|
| `GET /auth/key` | **2.00** | 1 | 0 |
| `GET /index.html`, `/logon/logo.webp` | 0 | **1** | 0 |
| `GET` of an extension route that only reads the session | 0 | 1 | 0 |
| `GET /auth/info` **without** a cookie | 0 | 0 | **1** (a new stored session) |

**Other measurements:**

- **Throughput:** on one worker with a Python client, a session-only route served about 1,270 requests/s, and `/auth/key` noticeably fewer. The client limited both numbers, so read them as relative only.
- **`environs`:** about 4 µs per `env.int` and 2 µs per `env.str`. That is tens of microseconds per request, which is negligible, so there is no finding for it.

## 3. Findings

### HIGH

#### H-1. If memcached fails while running, logon rate limiting turns off, and the 503 shows which guess was right **[verified]**

`server.py:374-383`. `_count_attempt` catches every memcached error and returns `False`, meaning "not throttled". `MEMCACHEAVAIL` is fixed at import, so the in-memory fallback is never used once the server started with memcached.

**What I saw with memcached stopped mid-run:**
- 15 consecutive `POST /auth/apikey` attempts for one user, against a limit of 10, all got a credential check and no 429.
- Wrong keys returned **401**.
- The correct key returned **503** ("session store is unavailable"). The logon succeeded and only the session save failed.

So during a memcached outage an attacker gets unlimited guesses and a clear signal when one is right. The same applies to `/auth/pam`, `/auth/challenge` and `/auth/request/challenge`.

**Fix:** make the limiter fail closed. When memcached raises, either:
- count in the in-memory dict instead (per worker, but still a limit); or
- return "throttled" and have the endpoint answer 503 **before** checking credentials.

The second is simplest and also removes the oracle. Add a probe test that stops memcached.

### MEDIUM

#### M-1. A database failure while running returns the HTML 500 page from JSON endpoints **[verified]**

`MYSQLAVAIL` is decided once, at startup. When MariaDB stops later:
- every authenticated `GET /auth/key` returns `500 text/html` (the `PAGE_500` page), not the JSON envelope;
- Bearer-key requests and the access routes do the same;
- each failure logs a full `OperationalError` traceback.

Recovery is fine: once MariaDB was back, the next request succeeded, because aiomysql opens new connections.

The `db_unavailable()` 503 exists, but only covers "down at startup". Clients such as the bundled `AuthUI`, which expects JSON, get an unparseable reply.

**Fix:** register an exception handler for `pymysql.err.OperationalError`, `pymysql.err.InterfaceError` and `asyncio.TimeoutError`. It should return `reply(request, False, {}, status=503, error="The database is unavailable.")` for non-HTML routes and log one line, not a traceback.

#### M-2. Every request without a cookie to `/auth/info`, `/auth/refresh` or `/auth/deauth` stores a new session for 7 days **[verified]**

`api/auth/general/auth.py:15-17,43-45,59-61` set `session['motd'] = True` for anyone who hasn't seen the banner. A client that doesn't keep cookies therefore creates a new memcached entry on every request. Such clients include monitors, scripts, health checks, crawlers and an attacker.

**Measured:** 200 cookieless `GET /auth/info` → `curr_items` grew by 200, `cmd_set` by 200. Each entry lives `AUTH_VALID` (7 days).

It is cheap memory growth, and with modular-sanic-docker's 32 GB memcached limit there is no eviction to hide it. It also undoes much of the fork's "store only when modified" saving.

**Fix:** only remember `motd` for logged-on sessions, or keep it client-side (the pages can track "banner shown" in `sessionStorage`). Alternatively, return the message whenever the user is not logged on, and let the page decide.

#### M-3. Each authenticated request makes two database queries, and static files make a memcached read **[measured]**

`verify()` (`server.py:406-423`) with the default `ACCESS_CACHE_SECONDS=0` calls `_load_user` (`server.py:329-338`). That is two statements per request:
- `SELECT * FROM sanic_info`;
- `SELECT … FROM sanic_access`.

This is the cost of fix H-1 from the second review, "revocation applies immediately". It is a reasonable default for an admin tool but will dominate under load.

Separately, the fork opens the session eagerly. Every static file fetched with a session cookie, such as `index.html` or `logo.webp`, costs a memcached `get` [measured: 1.00 per request].

**Fix (cheap first):**
- Merge `_load_user` into one round trip: either a `LEFT JOIN`, or both `SELECT`s in one `execute` with `cur.nextset()`.
- Document `ACCESS_CACHE_SECONDS=5..30` as the production setting.
- Optionally keep a per-user "access version" in memcached, bumped by `access_add`/`access_del`. Then `verify()` only hits MySQL when the version changes.
- For static files, see the fork's review (lazy session loading).

#### M-4. `/auth/refresh` without MySQL wipes the user's access and info **[reasoned]**

`auth.py:65` calls `logon(request, username)` with no `access`. In the no-MySQL branch (`server.py:510-519`) that stores `access = {}`, `info = ''` and `access_manual = True`.

As a result, a user logged on with application-provided access (the only option without MySQL) loses all of it on refresh. (`/auth/rekey` also calls `logon`, but returns 503 first without MySQL.)

**Fix:** when `not MYSQLAVAIL` (or `session['access_manual']`), have refresh return the current session values instead of calling `logon`.

#### M-5. The fork drops in-place changes to nested session values (affects extensions) **[verified]**

This affects every extension endpoint that does:

```python
cart = request.ctx.session.setdefault("cart", [])
cart.append(...)
```

**Test with a two-route extension:**
- first `/add` → cart `[1]`;
- second `/add` → returns `[1, 2]`;
- `/show` → `[1]`.

The second change was never saved, because the session itself wasn't marked modified.

modular-sanic's own code is not affected: every write in `server.py` and `api/` assigns a top-level key, and I checked them all with grep. Extension authors will hit this, though.

**Fix:** in the fork; see its REVIEW.md, H-1. Until then, document in the README that extensions must reassign the key (`session['cart'] = cart`).

#### M-6. The session backend is still chosen once at import (open from the second review's M-5)

`server.py:43-61`. The backend is picked by one `pymemcache` probe at import:
- if memcached is down at that moment, the app silently runs with per-worker in-memory sessions, and with `--workers 2` logons stick only half the time;
- if it goes down later, see H-1 and the fork's 503 behaviour.

There are also two separate aiomcache clients: the session store's (`:50`) and `app.ctx.mc` (`:235`). The session one is never closed at shutdown.

**Fix:**
- Fail startup, or log loudly, when memcached is configured but unreachable, rather than switching backend silently.
- Use one aiomcache client for both, and close it in `after_server_stop`.

(Pool size 2 was not a bottleneck at 50 concurrent requests in my test.)

#### M-7. Dependencies (open from the second review's M-7)

`requirements.txt` lists packages nothing imports: `six`, `orjson`, `ujson` and `pydantic`. `cryptography` is only needed by PyMySQL for `caching_sha2_password`/`sha256_password` logins, so keep it and say why in a comment.

Everything is unpinned except the fork. There is no lock file, so two installs a week apart can differ.

pip-audit is clean today.

**Fix:**
- Remove the four unused packages.
- Add a `requirements.lock` (`pip-compile`, or `pip freeze` from a tested venv) and install from it in Docker.

#### M-8. No automated tests or CI (open from the second review's M-8)

The three regression probes used for these reviews (about 90 checks) live outside the repository and depend on hand-made fixtures. This pass hit exactly that problem: missing fixture users caused 5 false failures.

**Fix:**
- Commit the probes as `tests/` with a fixture script that creates its users (admin, alice, helper, boss, pamtest).
- Run them in GitHub Actions with MariaDB and memcached services, as the fork now does.

### LOW

| ID | Where | Issue | Fix |
|---|---|---|---|
| L-1 | `server.py:384-391` | The in-memory rate limiter rebuilds its dict when it holds more than 10,000 keys, but only drops expired ones. With more than 10,000 live keys (the `user:` bucket uses attacker-chosen usernames), **every** attempt rebuilds the whole dict, which takes about 2 ms at 20,000 entries [measured], and the dict keeps growing within the window. | Prune at most once per `window`, or keep an `OrderedDict` by start time and pop from the front; cap the size. |
| L-2 | `server.py:110`, `env-example:5-6` | `HSTS_INCLUDE_SUBDOMAINS` defaults to **True** in code, but the example presents it as an opt-in ("Add includeSubDomains", commented out). Turning on `HSTS` therefore also pins every subdomain to HTTPS, which can break plain-HTTP sibling hosts for up to `max-age`. | Default to `False`, or make the example say it is on by default. |
| L-3 | `server.py:503` | `access_show` returns `info=[]` for an unknown user, and `{}` or a dict elsewhere. Callers that do `info.get(...)` would fail. | Return `{}`. |
| L-4 | `start.sh`, `setup/install-443-redirect.sh` | `start.sh` still has to be run twice (the first run only installs) and sets a dead `SANIC_CONFIG_FILE=config.py` (old L-10). With `0bdcbee`, development mode listens on `127.0.0.1:$PORT`, production defaults to 8443, and `install-443-redirect.sh` redirects 443 to **8000**. That redirect now reaches neither mode: external traffic can't be redirected to a loopback-only listener, and production isn't on 8000. | Install, then fall through to start. Make the redirect target `${PORT:-8443}` and document that it is for production mode. |
| L-5 | `api/auth/general/auth.py:13-17` | `/auth/deauth` clears the session, then sets `motd`, so the logged-off session is re-saved under the **same** id instead of being deleted. That is harmless today, because it holds no identity, but it is another stored session per logoff (see M-2). | Call `logoff` last, or regenerate after clearing. |
| L-6 | (carried over) | Still open from the second review: M-6 (`admin/permissions` unrestricted, no audit log of access changes), M-9 (`setup.sh` adds the user to `shadow`; the example enables `SHOW_SITE_CONTENTS`), L-9 (the `AuthUI` script and CSS duplicated across 8 pages), L-11 (`install-mysql.sh`: `GRANT ALL … '%'`, `query_cache_size`), L-15 (the redirect script duplicates rules on every run). | As in the second review. |

## 4. Prioritized top 10

1. **H-1:** make the logon rate limiter fail closed when memcached errors, and answer 503 before checking credentials.
2. **M-1:** map database errors to a JSON 503, not the HTML 500 page.
3. **M-5:** document "reassign nested values" for extensions until the fork fixes it (fork H-1).
4. **M-2:** stop storing a session for every cookieless `/auth/info`, `/auth/refresh` and `/auth/deauth`.
5. **M-3:** make `verify()` a single query, and recommend `ACCESS_CACHE_SECONDS` of 5 to 30 s in production.
6. **M-8:** move the regression probes into `tests/` with fixtures and CI.
7. **M-4:** stop `/auth/refresh` wiping access without MySQL.
8. **M-6:** stop the silent backend switch at startup, and share and close one memcached client.
9. **M-7:** remove the unused dependencies and add a lock file.
10. **L-1 and L-2:** bound the in-memory limiter, and fix the HSTS subdomain default.

## 5. Status of findings from the second review

| Item | Status | Notes |
|---|---|---|
| H-1 revoked access still works | **Fixed** (#3) | Verified (batch-3 probe). Its cost is M-3. |
| H-2 bad bodies give 500s; debug on all interfaces | **Fixed** (#3, `0bdcbee`) | Development mode binds `127.0.0.1`. |
| H-3 proxy rate limit and HSTS | **Fixed** (#3, #4) | `SANIC_PROXIES_COUNT` from `.env` works. |
| M-1 logon name case | **Fixed** (#3) | |
| M-2 half-registered blueprints | **Fixed** (#3) | |
| M-3 start script cookies | **Fixed** (#3) | |
| M-4 `AUTH_VALID` above 30 days | **Fixed** (#5, fork) | |
| M-5 backend chosen at import | **Open** | Now M-6. |
| M-6 `admin/permissions` and audit | **Open** | L-6. |
| M-7 dependencies | **Partly fixed** | `setuptools`, `wheel` and `mysqlclient` removed. The rest is now M-7. |
| M-8 tests and CI | **Open** | Now M-8. |
| M-9 `shadow` and directory listing | **Open** | L-6. |
| L-1 to L-8, L-12, L-13, L-DOC-1 | **Fixed** (#3) | |
| L-5 session rewritten on every response | **Fixed** (#5, fork) | Verified: 0 sets for static files. |
| L-14 client-chosen session ids | **Fixed** (#5, fork) | |
| L-9, L-10, L-11, L-15 | **Open** | L-4 and L-6. |
