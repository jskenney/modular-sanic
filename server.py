###############################################################################
# Import Required Python Libraries
from sanic import Sanic, Blueprint
from sanic.exceptions import NotFound, SanicException
from sanic.response import json, html
from sanic.log import logger
from datetime import datetime, timezone
from urllib.parse import urlsplit
from sanic_session import Session, MemcacheSessionInterface, InMemorySessionInterface
import aiomysql, aiomcache, pymemcache
import os, importlib.util, time, uuid, sys, environs, hashlib, re, base64
import pymysql
from dotenv import dotenv_values

###############################################################################
# Use environmental variables and the .env file for configuration settings
env = environs.Env()
env_path = env.read_env(return_path=True)

# Sanic reads its own settings (SANIC_PROXIES_COUNT, SANIC_REAL_IP_HEADER, ...)
# from the process environment, but environs keeps .env values to itself, so
# pass the SANIC_ ones on before the app is created.  A value already set in
# the environment wins over .env, matching environs.
if env_path:
    for key, value in dotenv_values(env_path).items():
        if key.startswith('SANIC_') and value is not None:
            os.environ.setdefault(key, value)

###############################################################################
# Create Sanic Application
app = Sanic(env.str("APP_NAME", default="SanicApp"))
app.config.env = env

###############################################################################
# Enable Session Support (Default to Memcached interface),
# use in-memory model if Memcached is unavailable.
# Stored sessions expire after AUTH_VALID seconds of inactivity, and the
# __Host- cookie prefix stops other subdomains from planting a session cookie.
# SameSite=Strict (the default) keeps the cookie off all cross-site requests.
# sanic-session only saves sessions that changed, keeps memcached entries at
# most 30 days (the cookie keeps the full AUTH_VALID), and answers 503 when
# the session store cannot be written; verify() enforces AUTH_VALID itself.
session_expiry = app.config.env.int('AUTH_VALID', default=604800)
session_samesite = app.config.env.str('SAMESITE', default='Strict')
try:
    test_client = pymemcache.client.base.Client((app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'),
                                                 app.config.env.str('MEMCACHED_PORT', default='11211')))
    test = test_client.get('user')
    test_client.close()
    client = aiomcache.Client(app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'),
                              app.config.env.str('MEMCACHED_PORT', default='11211'))
    Session(app, interface=MemcacheSessionInterface(client, samesite=session_samesite, secure=True,
                                                     cookie_name="__Host-session", expiry=session_expiry))
    print("Notice: Using Memcached Session Handling")
    app.config.MEMCACHEAVAIL = True
except Exception as e:
    Session(app, interface=InMemorySessionInterface(samesite=session_samesite, secure=True,
                                                    cookie_name="__Host-session", expiry=session_expiry))
    print(f"Notice: Memcached connection failed: {type(e).__name__} | Message: {e}")
    print("Notice: Using InMemory Session Handling")
    app.config.MEMCACHEAVAIL = False

###############################################################################
# Determine where the root of the website exists and where
# the site favicon.ico and /html directory are.
app.static("/",
           app.config.env.str('HTML', default='./html/'),
           index="index.html",
           directory_view=app.config.env.bool('SHOW_SITE_CONTENTS', default=False))
app.static("/favicon.ico",
           app.config.env.str('FAVICON', default='./html/favicon.ico'),
           name='favicon')

###############################################################################
# Support providing a file not found page to the user vice a 404
# (the pages are read once at startup)
page_404 = app.config.env.str('PAGE_404', default='./errors/404.html')
if os.path.exists(page_404):
    print("Notice: Configuring Page 404.")
    with open(page_404) as f:
        page_404_html = f.read()
    @app.exception(NotFound)
    async def handle_not_found(request, exception):
        return html(page_404_html, status=404)

page_500 = app.config.env.str('PAGE_500', default='./errors/500.html')
if os.path.exists(page_500):
    print("Notice: Configuring Page 500.")
    with open(page_500) as f:
        page_500_html = f.read()
    @app.exception(Exception)
    async def handle_server_errors(request, exception):
        # Client errors (400, 405, 413, ...) keep Sanic's normal response
        if isinstance(exception, SanicException) and exception.status_code < 500:
            return request.app.error_handler.default(request, exception)
        logger.error(f"Unhandled error on {request.path}", exc_info=exception)
        return html(page_500_html, status=500)

###############################################################################
# Block documentation generation
if not app.config.env.bool('DOCUMENTATION', default=False):
    app.config.OAS=False
    print("Notice: Documentation is unavailable.")

###############################################################################
# To support HSTS, a common organizational security requirement.
if app.config.env.str('HSTS', default=''):
    print("Notice: Set HSTS to", app.config.env.str('HSTS', default='86400'))
    hsts_value = "max-age="+app.config.env.str('HSTS', default='86400')
    if app.config.env.bool('HSTS_INCLUDE_SUBDOMAINS', default=True):
        hsts_value += "; includeSubDomains"
    @app.middleware("response")
    async def add_hsts_headers(request, response):
        if request.scheme == 'https':
            response.headers["Strict-Transport-Security"] = hsts_value

###############################################################################
# Browser security headers.  The default Content-Security-Policy only allows
# scripts from this site plus the inline scripts found (at startup) in the
# HTML directory and the error pages, by their SHA-256 hash; restart after
# changing an inline script.  Set CONTENT_SECURITY_POLICY to replace the
# policy, or to an empty value to disable it.  The generated API
# documentation loads its own scripts, so it is left without a policy.
def inline_script_hashes(*locations):
    hashes = set()
    pattern = re.compile(r'<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>', re.S | re.I)
    files = set()
    for location in locations:
        if os.path.isfile(location):
            files.add(os.path.realpath(location))
        for root, _, filenames in os.walk(location):
            files.update(os.path.realpath(os.path.join(root, f)) for f in filenames if f.endswith(('.html', '.htm')))
    for filename in sorted(files):
        with open(filename, encoding='utf-8', errors='replace') as f:
            for script in pattern.findall(f.read()):
                digest = hashlib.sha256(script.encode()).digest()
                hashes.add("'sha256-" + base64.b64encode(digest).decode() + "'")
    return sorted(hashes)

security_headers = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': app.config.env.str('REFERRER_POLICY', default='strict-origin-when-cross-origin'),
}
content_security_policy = app.config.env.str('CONTENT_SECURITY_POLICY', default=
    "default-src 'self'; script-src 'self' " +
    ' '.join(inline_script_hashes(app.config.env.str('HTML', default='./html/'), page_404, page_500)) +
    "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'")
@app.middleware("response")
async def add_security_headers(request, res):
    for header, value in security_headers.items():
        if header not in res.headers:
            res.headers[header] = value
    if content_security_policy and not request.path.startswith(getattr(request.app.config, 'OAS_URL_PREFIX', '/docs')):
        if 'Content-Security-Policy' not in res.headers:
            res.headers['Content-Security-Policy'] = content_security_policy

###############################################################################
# Configuration warnings that only show up with real traffic (logged once
# per worker): forwarded headers from a reverse proxy that Sanic has not been
# told to trust (so every client shares one address for rate limiting and
# HTTPS is not detected), and plain HTTP from another host (the Secure
# session cookie is not stored, so logons do not stick).
proxy_configured = any(app.config.get(k) for k in ('PROXIES_COUNT', 'REAL_IP_HEADER', 'FORWARDED_SECRET'))
config_warnings = set()
@app.middleware("request")
async def warn_about_configuration(request):
    if len(config_warnings) == 2:
        return
    if not proxy_configured and 'proxy' not in config_warnings and (
            'x-forwarded-for' in request.headers or 'forwarded' in request.headers):
        config_warnings.add('proxy')
        logger.warning("Forwarded headers received but no proxy is configured: set SANIC_PROXIES_COUNT "
                       "(or SANIC_REAL_IP_HEADER / SANIC_FORWARDED_SECRET) so client addresses and HTTPS are detected.")
    if 'http' not in config_warnings and request.scheme == 'http' and request.host and \
            urlsplit('//' + request.host).hostname not in ('localhost', '127.0.0.1', '::1'):
        config_warnings.add('http')
        logger.warning(f"Plain HTTP request for {request.host}: browsers only keep the Secure session cookie "
                       "over HTTPS (or on localhost), so logons will not stick.  Use TLS.")

###############################################################################
# Lets try autodiscovery of Endpoints (authentication APIs and site APIs)
# Note, you must name all blueprints inside of the .py files as sub_bp,
# so you should see something like the following in each file:
#    sub_bp = Blueprint("auth", url_prefix="/auth")
# Relative locations are resolved against the directory holding server.py,
# files are loaded in sorted order, and files starting with _ are skipped.
# Each file gets its own module name, and one failing file is reported
# without stopping the others from loading.
base_dir = os.path.dirname(os.path.abspath(__file__))
for source in (app.config.env.list('API_LOCATIONS', default=['./api', './external'])):
    source = os.path.join(base_dir, source)
    if not os.path.isdir(source):
        print("Notice: API location not found", source)
        continue
    for root, dirnames, filenames in os.walk(source):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            filename = os.path.join(root, filename)
            with open(filename) as f:
                if 'sub_bp' not in f.read():
                    continue
            name = 'modsanic_ext_' + re.sub(r'\W', '_', os.path.relpath(filename, base_dir)[:-3])
            try:
                spec = importlib.util.spec_from_file_location(name, filename)
                bp = importlib.util.module_from_spec(spec)
                sys.modules[name] = bp
                spec.loader.exec_module(bp)
                if not isinstance(getattr(bp, 'sub_bp', None), Blueprint):
                    del sys.modules[name]
                    print("Notice: Skipped", filename, "(no sub_bp Blueprint defined)")
                    continue
                if bp.sub_bp.name in app.blueprints:
                    raise ValueError(f'A blueprint named "{bp.sub_bp.name}" is already loaded, blueprint names must be unique.')
            except Exception as e:
                sys.modules.pop(name, None)
                logger.error(f"Failed to load blueprint from {filename}: {type(e).__name__} | Message: {e}", exc_info=e)
                continue
            # A route clash leaves some of the blueprint's routes registered and
            # they cannot be removed again, so stop rather than run half loaded.
            try:
                app.blueprint(bp.sub_bp)
            except Exception as e:
                raise RuntimeError(f"Unable to register the blueprint from {filename}: {e}") from e
            print("Notice: Loaded blueprint from", filename)

###############################################################################
# Configure and connect to memcached.
@app.listener('before_server_start')
async def setup_memcache(app):
    if app.config.MEMCACHEAVAIL:
        app.ctx.mc = aiomcache.Client(app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'),
                                      app.config.env.str('MEMCACHED_PORT', default='11211'))
        print("Notice: Memcached connection pool created.")

@app.listener('after_server_stop')
async def close_memcache(app):
    if app.config.MEMCACHEAVAIL:
        await app.ctx.mc.close()
        print("Notice: Memcached connection pool closed.")

###############################################################################
# Configure and connect to the MySQL database, this is optional but not having
# MySQL available will limit functionality, including authentication options.
@app.listener('before_server_start')
async def setup_db(app):
    try:
        app.ctx.pool = await aiomysql.create_pool(
            host=app.config.env.str(       'DB_HOST', default='127.0.0.1'),
            port=app.config.env.int(       'DB_PORT', default=3306),
            user=app.config.env.str(       'DB_USER', default='username'),
            password=app.config.env.str(   'DB_PASS', default='password'),
            db=app.config.env.str(         'DB_NAME', default='dbname'),
            maxsize=app.config.env.int(    'DB_POOL_MAX', default=10),
            autocommit=True
        )
        app.config.MYSQLAVAIL = True
        print("Notice: Database connection pool created.")
    except Exception as e:
        app.ctx.pool = None
        app.config.MYSQLAVAIL = False
        print(f"Notice: Database connection failed: {type(e).__name__} | Message: {e}")

@app.listener('after_server_stop')
async def close_db(app):
    if app.config.MYSQLAVAIL:
        app.ctx.pool.close()
        await app.ctx.pool.wait_closed()
        print("Notice: Database connection pool closed.")

###############################################################################
# Configure global Authentication & Verification methods, this depends
# on storing user information in the session cache, and retrieving
# access information from the MySQL database's
# sanic_info, sanic_access, and sanic_challenge tables.
class AuthVerification:
    # Session keys that hold the logged on identity
    AUTH_KEYS = ('user', 'visit', 'logon_at', 'access', 'info', 'apikey', 'original_user', 'access_at', 'access_manual')
    # API key values that mean "use the web session instead of a key"
    SESSION_KEYS = ('session', '-', '')
    # Defaults for the page and email settings used by the endpoints
    SETTINGS = {
        'REDIRECT_LOGON_SUCCESSFUL': '/index.html',
        'REDIRECT_LOGON_FAILED': '/logon/logon.html',
        'REDIRECT_LOGOFF': '/index.html',
        'CHALLENGE_PAGE': '/logon/challenge.html',
        'LOGON_LOGO': '/logon/logo.webp',
        'AUTH_MESSAGE': '',
        'AUTH_TITLE': 'SanicApp',
        'AUTH_EMAILER': 'noreply@example.com',
        'AUTH_DOMAIN': 'example.com',
        'AUTH_EMAIL_SERVER': 'localhost',
        'PAM_SERVICE': 'login',
    }
    def __init__(self):
        self.attempts = {}
    # A page or email setting, from the environment or its default
    def setting(self, request, name):
        return request.app.config.env.str(name, default=self.SETTINGS[name])
    # Required values from a JSON object body, as strings (numbers are accepted
    # and converted); returns None when the body or any value is missing or invalid
    @staticmethod
    def json_fields(request, *names):
        data = request.json
        if not isinstance(data, dict):
            return None
        values = []
        for name in names:
            value = data.get(name)
            if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) == '':
                return None
            values.append(str(value))
        return tuple(values)
    # 400 response for a request body without the required values
    def bad_request(self, request, *names):
        return reply(request, False, {}, status=400, error="The request must be a JSON object with: " + ", ".join(names) + ".")
    # API keys are stored as a SHA-256 hash, only the user ever sees the key itself
    @staticmethod
    def hashkey(apikey):
        return hashlib.sha256(str(apikey).encode()).hexdigest()
    # sanic_info row as shared with the user: no key hash, dates as ISO-8601 text
    @staticmethod
    def _public_info(row):
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items() if k != 'apikey'}
    # Load a user's sanic_info row (public form) and access dict with an open cursor
    async def _load_user(self, cur, user):
        await cur.execute('SELECT * FROM sanic_info WHERE user = %s', (user,))
        rows = await cur.fetchall()
        if len(rows) == 0:
            return None, {}
        await cur.execute('SELECT access, value FROM sanic_access WHERE user = %s ORDER BY access, value', (user,))
        access = {}
        for row in await cur.fetchall():
            access.setdefault(row['access'], []).append(row['value'])
        return self._public_info(rows[0]), access
    # Returns a 503 response when the database is unavailable, otherwise None
    def db_unavailable(self, request):
        if request.app.config.MYSQLAVAIL:
            return None
        return reply(request, False, {}, status=503, error="The database is unavailable.")
    # A session is expired when idle longer than AUTH_VALID, or older than AUTH_MAX since logon
    def _session_expired(self, request):
        session = request.ctx.session
        now = time.time()
        return (not session.get('user') or not session.get('visit') or not session.get('logon_at')
                or now - session.get('visit') > request.app.config.env.int('AUTH_VALID', default=604800)
                or now - session.get('logon_at') > request.app.config.env.int('AUTH_MAX', default=2592000))
    # Remove only the authentication values, leaving other session data in place
    def _clear_auth(self, request):
        for key in self.AUTH_KEYS:
            request.ctx.session.pop(key, None)
    # Set a session value only when it changes, so unchanged sessions are not saved
    @staticmethod
    def _set(session, key, value):
        if session.get(key) != value:
            session[key] = value
    # Issue a new session id whenever the logged on identity changes, so a
    # session id planted before logon (session fixation) is never authenticated.
    async def _rotate_session(self, request, user):
        session = request.ctx.session
        # Drop any stale identity first so an expired session starts a fresh logon
        if self._session_expired(request):
            self._clear_auth(request)
        if session.get('user') == user:
            return
        if not session.get('user'):
            session['logon_at'] = time.time()
        await request.app.ctx.extensions['session'].interface.regenerate(request)
    # Count one attempt against a fixed window, returns True once over the limit.
    # Memcached shares the counts between workers, otherwise they are per worker.
    async def _count_attempt(self, request, key, limit, window):
        key = 'ratelimit:' + hashlib.sha256(key.encode()).hexdigest()
        if request.app.config.MEMCACHEAVAIL:
            try:
                await request.app.ctx.mc.add(key.encode(), b'0', exptime=window)
                count = await request.app.ctx.mc.incr(key.encode())
                return count is not None and count > limit
            except Exception as e:
                logger.warning(f"Rate limit check failed: {type(e).__name__} | Message: {e}")
                return False
        now = time.time()
        if len(self.attempts) > 10000:
            self.attempts = {k: v for k, v in self.attempts.items() if now - v[0] <= window}
        start, count = self.attempts.get(key, (now, 0))
        if now - start > window:
            start, count = now, 0
        self.attempts[key] = (start, count + 1)
        return count + 1 > limit
    # Rate limit authentication attempts by client address and (optionally) username
    async def throttled(self, request, bucket, username=None):
        limit = request.app.config.env.int('AUTH_RATE_LIMIT', default=10)
        window = request.app.config.env.int('AUTH_RATE_WINDOW', default=300)
        over = await self._count_attempt(request, f'{bucket}:ip:{request.remote_addr or request.ip}', limit, window)
        if username is not None:
            over = await self._count_attempt(request, f'{bucket}:user:{username}', limit, window) or over
        if over:
            logger.warning(f"Rate limit exceeded: bucket={bucket} ip={request.remote_addr or request.ip} user={username}")
        return over
    # Verify User's Status by checking the session.  With MySQL available the
    # user's access and info are re-read from the database (at most every
    # ACCESS_CACHE_SECONDS), so granted or revoked access applies right away;
    # access set by logon(..., forceNoMySQL=True) is left as it was given.
    async def verify(self, request):
        session = request.ctx.session
        if self._session_expired(request):
            self._clear_auth(request)
            return False, None, None, {}, {}
        now = time.time()
        if request.app.config.MYSQLAVAIL and not session.get('access_manual') and now - session.get('access_at', 0) >= request.app.config.env.int('ACCESS_CACHE_SECONDS', default=0):
            async with request.app.ctx.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    info, access = await self._load_user(cur, session['user'])
            self._set(session, 'access', access)
            self._set(session, 'info', info or {})
            if request.app.config.env.int('ACCESS_CACHE_SECONDS', default=0) > 0:
                session['access_at'] = now
        # The idle timer only needs minute resolution, which keeps session writes down
        if now - session.get('visit') >= 60:
            session['visit'] = now
        return True, session.get('user'), session.get('apikey'), session.get('access'), session.get('info')
    # Verify User's Status by API key, the key comes from an Authorization: Bearer
    # header when one is sent, otherwise from mykey (e.g. the URL).  A key of
    # 'session', '-' or '' checks the web session only; any other key is checked
    # against the database and the session is not used or changed.
    async def verifyapi(self, request, mykey):
        header = request.headers.get('authorization', '')
        if header[:7].lower() == 'bearer ':
            mykey = header[7:].strip()
        if mykey in self.SESSION_KEYS:
            return await self.verify(request)
        if not request.app.config.MYSQLAVAIL:
            return False, None, None, {}, {}
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'SELECT user FROM sanic_info WHERE apikey=%s AND (apikey_expires IS NULL OR apikey_expires > NOW())'
                values = (self.hashkey(mykey),)
                await cur.execute(query, values)
                info = await cur.fetchall()
        if len(info) != 1:
            return False, None, None, {}, {}
        user, apikey, info, access = await self.access_show(request, info[0]['user'])
        return True, user, apikey, access, info
    # Remove Session Variables effectively logging off the user
    async def logoff(self, request):
        request.ctx.session.clear()
    # Generate an API key, requires MySQL.  Only the hash is stored, so the key
    # returned here is the only time it is available.  Keys expire after
    # APIKEY_VALID seconds (0 for never).
    async def genapikey(self, request, user):
        if not request.app.config.MYSQLAVAIL:
            return None
        valid = request.app.config.env.int('APIKEY_VALID', default=31536000)
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = ('INSERT INTO sanic_info (user, apikey, apikey_created, apikey_expires) '
                         'VALUES (%s, %s, NOW(), IF(%s > 0, NOW() + INTERVAL %s SECOND, NULL)) '
                         'ON DUPLICATE KEY UPDATE apikey=%s, apikey_created=NOW(), '
                         'apikey_expires=IF(%s > 0, NOW() + INTERVAL %s SECOND, NULL)')
                apikey = str(uuid.uuid4())
                hashed = self.hashkey(apikey)
                values = (user, hashed, valid, valid, hashed, valid, valid, )
                await cur.execute(query, values)
                return apikey
    # Update Access Information, requires MySQL.  Returns True when added,
    # False for an unknown user or an access that is already present.
    async def access_add(self, request, user, access, value):
        if not request.app.config.MYSQLAVAIL:
            return False
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'INSERT INTO sanic_access (user, access, value) VALUES (%s, %s, %s)'
                values = (user, access, value,)
                try:
                    await cur.execute(query, values)
                except pymysql.err.IntegrityError as e:
                    logger.info(f"Access not added for {user}: {e}")
                    return False
                return True
    # Delete Access Information, requires MySQL.  Returns True when removed.
    async def access_del(self, request, user, access, value):
        if not request.app.config.MYSQLAVAIL:
            return False
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'DELETE FROM sanic_access WHERE user = %s AND access = %s AND value =%s'
                values = (user, access, value,)
                await cur.execute(query, values)
                return cur.rowcount > 0
    # Show a user's access (via MySQL, or for the current user only, via session)
    async def access_show(self, request, user):
        if not request.app.config.MYSQLAVAIL:
            ok, username, apikey, access, info = await self.verify(request)
            if not ok or username != user:
                return user, '', {}, {}
            return user, apikey, info, access
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                info, access = await self._load_user(cur, user)
        if info is None:
            return user, '', [], {}
        return info['user'], '', info, access
    # Log on a user, if MySQL is available use the database to provide access levels
    # Otherwise they can be set from the function.  With MySQL the session
    # holds the user name exactly as stored in sanic_info.
    async def logon(self, request, user, access=None, info='', apikey='', forceNoMySQL=False):
        if access is None:
            access = {}
        if not request.app.config.MYSQLAVAIL or forceNoMySQL:
            await self._rotate_session(request, user)
            request.ctx.session['apikey'] = apikey
            request.ctx.session['access'] = access
            request.ctx.session['info'] = info
            request.ctx.session['user'] = user
            request.ctx.session['visit'] = time.time()
            request.ctx.session['access_manual'] = True
            return user, apikey, info, access
        apikey = ''
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                info, access = await self._load_user(cur, user)
                # First logon creates the user's row (API keys are only made by /auth/rekey)
                if info is None:
                    await cur.execute('INSERT INTO sanic_info (user) VALUES (%s) ON DUPLICATE KEY UPDATE user=user', (user,))
                    info, access = await self._load_user(cur, user)
        user = info['user']
        await self._rotate_session(request, user)
        request.ctx.session['apikey'] = apikey
        request.ctx.session['access'] = access
        request.ctx.session['info'] = info
        request.ctx.session['user'] = user
        request.ctx.session['visit'] = time.time()
        request.ctx.session.pop('access_at', None)
        request.ctx.session.pop('access_manual', None)
        return user, apikey, info, access

###############################################################################
# Standard JSON response envelope used by the endpoints
def reply(request, success, data, status=200, error=None):
    body = {'success': success, 'sent': datetime.now(timezone.utc).isoformat(), 'endpoint': request.path, 'data': data}
    if error:
        body['error'] = error
    return json(body, status=status)

@app.listener('before_server_start')
async def setup_auth(app):
    app.ctx.auth = AuthVerification()
    app.ctx.reply = reply
