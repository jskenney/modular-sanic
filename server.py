###############################################################################
# Import Required Python Libraries
from sanic import Sanic, response
from sanic.exceptions import NotFound, ServerError
from sanic.response import text, json, html, redirect, empty
from sanic_session import Session, MemcacheSessionInterface, InMemorySessionInterface
import asyncio, aiomysql, aiomcache, pymemcache
import pam, os, importlib.util, time, uuid, sys, environs

###############################################################################
# Use environmental variables and the .env file for configuration settings
env = environs.Env()
env.read_env()

###############################################################################
# Create Sanic Application
app = Sanic(env.str("APP_NAME", default="SanicApp"))
app.config.env = env

###############################################################################
# Enable Session Support (Default to Memcached interface),
# use in-memory model if Memcached is unavailable.
try:
    print('MEMCACHED_HOST:',app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'))
    print('MEMCACHED_PORT:',app.config.env.str('MEMCACHED_PORT', default='11211'))
    test_client = pymemcache.client.base.Client((app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'),
                                                 app.config.env.str('MEMCACHED_PORT', default='11211')))
    test = test_client.get('user')
    test_client.close()
    client = aiomcache.Client(app.config.env.str('MEMCACHED_HOST', default='127.0.0.1'),
                              app.config.env.str('MEMCACHED_PORT', default='11211'))
    Session(app, interface=MemcacheSessionInterface(client))
    print("Notice: Using Memcached Session Handling")
    app.config.MEMCACHEAVAIL = True
except:
    Session(app)
    print("Notice: Using InMemory Session Handling")
    app.config.MEMCACHEAVAIL = False

###############################################################################
# Determine where the root of the website exists and where
# the site favicon.ico and /html directory are.
app.static("/",
           app.config.env.str('HTML', default='./html/'),
           index="index.html",
           directory_view=app.config.env.bool('SHOW_SITE_CONTENTS', default=True))
app.static("/favicon.ico",
           app.config.env.str('FAVICON', default='./html/favicon.ico'),
           name='favicon')

###############################################################################
# Support providing a file not found page to the user vice a 404
if os.path.exists(app.config.env.str('PAGE_404', default='./html/404.html')):
    print("Notice: Configuring Page 404.")
    @app.exception(NotFound)
    async def handle_not_found(request, exception):
        return html(open(app.config.env.str('PAGE_404', default='./html/404.html')).read(), status=404)

if os.path.exists(app.config.env.str('PAGE_500', default='./html/500.html')):
    print("Notice: Configuring Page 500.")
    @app.exception(ServerError)
    async def handle_server_errors(request, exception):
        return html(open(app.config.env.str('PAGE_500', default='./html/500.html')).read(), status=500)
    @app.exception(Exception)
    async def handle_all_server_errors(request, exception):
        return html(open(app.config.env.str('PAGE_500', default='./html/500.html')).read(), status=500)

###############################################################################
# Block documentation generation
if not app.config.env.bool('DOCUMENTATION', default=True):
    print("Notice: Documentation is unavailable.")
    app.config.OAS=False

###############################################################################
# To support HSTS, a common organizational security requirement.
if 'HSTS' in os.environ:
    print("Notice: Set HSTS to", app.config.env.str('HSTS', default='86400'))
    @app.middleware("response")
    async def add_hsts_headers(request, response):
        if request.scheme == 'https':
            response.headers["Strict-Transport-Security"] = "max-age="+app.config.env.str('HSTS', default='86400')+"; includeSubDomains"

###############################################################################
# Lets try autodiscovery of Endpoints (authentication APIs and site APIs)
# Note, you must name all blueprints inside of the .py files as sub_bp,
# so you should see something like the following in each file:
#    sub_bp = Blueprint("auth", url_prefix="/auth")
for source in (app.config.env.list('API_LOCATIONS', default=['./api', './external'])):
    for root, dirnames, filenames in os.walk(source):
        for filename in filenames:
            if filename.endswith('.py'):
                filename = os.path.join(root, filename)
                with open(filename) as f:
                    data = f.read()
                    if 'sub_bp' in data:
                        spec = importlib.util.spec_from_file_location("sub_bp", filename)
                        bp = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(bp)
                        app.blueprint(bp.sub_bp)
                        print("Notice: Loaded blueprint from", filename)

###############################################################################
# Configure and connect to memcached (Variable Caching, schedules, etc.)
# Optional, but functionality will be limited.
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
# Set MYSQLAVAIL = False in the config file to prevent MySQL from Loading.
@app.listener('before_server_start')
async def setup_db(app):
    try:
        print('DB_HOST:',app.config.env.str('DB_HOST', default='127.0.0.1'))
        print('DB_PORT:',app.config.env.str('DB_PORT', default='3306'))
        print('DB_USER:',app.config.env.str('DB_USER', default='username'))
        print('DB_PASS:',app.config.env.str('DB_PASS', default='password'))
        print('DB_NAME:',app.config.env.str('DB_NAME', default='dbname'))
        app.ctx.pool = await aiomysql.create_pool(
            host=app.config.env.str(       'DB_HOST', default='127.0.0.1'),
            port=app.config.env.str(       'DB_PORT', default='3306'),
            user=app.config.env.str(       'DB_USER', default='username'),
            password=app.config.env.str(   'DB_PASS', default='password'),
            db=app.config.env.str(         'DB_NAME', default='dbname'),
            autocommit=app.config.env.bool('DB_AUTOCOMMIT', default=True)
        )
        app.config.MYSQLAVAIL = True
        print("Notice: Database connection pool created.")
    except:
        app.config.MYSQLAVAIL = False
        print("Notice: Database connection failed.")

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
    # Verify User's Status by _ONLY_ checking session information
    async def verify(self, request):
        if not request.ctx.session.get('user') or not request.ctx.session.get('visit') or time.time() - request.ctx.session.get('visit') > request.app.config.env.int('AUTH_VALID', default=604800):
            await self.logoff(request)
            return False, None, None, {}, {}
        access = request.ctx.session.get('access')
        info = request.ctx.session.get('info')
        apikey = request.ctx.session.get('apikey')
        username = request.ctx.session.get('user')
        request.ctx.session['visit'] = time.time()
        return True, username, apikey, access, info
    # Verify User's Status by Checkinging Session then MySQL Database
    async def verifyapi(self, request, mykey):
        if not request.ctx.session.get('user') or not request.ctx.session.get('visit') or time.time() - request.ctx.session.get('visit') > request.app.config.env.int('AUTH_VALID', default=604800):
            async with request.app.ctx.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    query = 'SELECT user FROM sanic_info WHERE apikey=%s'
                    values = (mykey,)
                    await cur.execute(query, values)
                    info = await cur.fetchall()
                    if len(info) != 1:
                        return False, None, None, {}, {}
                    user, apikey, info, access = await self.logon(request, info[0]['user'])
                    return True, user, apikey, access, info
        else:
            access = request.ctx.session.get('access')
            info = request.ctx.session.get('info')
            apikey = request.ctx.session.get('apikey')
            username = request.ctx.session.get('user')
            request.ctx.session['visit'] = time.time()
            return True, username, apikey, access, info
    # Remove Session Variables effectively logging off the user
    async def logoff(self, request):
        if request.ctx.session.get('apikey'):
            del(request.ctx.session['apikey'])
        if request.ctx.session.get('access'):
            del(request.ctx.session['access'])
        if request.ctx.session.get('info'):
            del(request.ctx.session['info'])
        if request.ctx.session.get('user'):
            del(request.ctx.session['user'])
        if request.ctx.session.get('motd'):
            del(request.ctx.session['motd'])
        if request.ctx.session.get('visit'):
            del(request.ctx.session['visit'])
        if request.ctx.session.get('original_user'):
            del(request.ctx.session['original_user'])
    # Generate an API key, requires MySQL
    async def genapikey(self, request, user):
        if not app.config.MYSQLAVAIL:
            return None
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'INSERT INTO sanic_info (user, apikey) VALUES (%s, %s) ON DUPLICATE KEY UPDATE apikey=%s'
                apikey = str(uuid.uuid4())
                values = (user, apikey, apikey, )
                await cur.execute(query, values)
                query = 'SELECT * FROM sanic_info WHERE user = %s'
                values = (user,)
                await cur.execute(query, values)
                info = await cur.fetchall()
                apikey = info[0]['apikey']
                return apikey
    # Update Access Information, requires MySQL
    async def access_add(self, request, user, access, value):
        if not app.config.MYSQLAVAIL:
            return None
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'INSERT INTO sanic_access (user, access, value) VALUES (%s, %s, %s)'
                values = (user, access, value,)
                try:
                    await cur.execute(query, values)
                except:
                    pass
    # Delete Access Information, requires MySQL
    async def access_del(self, request, user, access, value):
        if not app.config.MYSQLAVAIL:
            return None
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'DELETE FROM sanic_access WHERE user = %s AND access = %s AND value =%s'
                values = (user, access, value,)
                try:
                    await cur.execute(query, values)
                except:
                    pass
    # Show current user's access (either via session or MySQL)
    async def access_show(self, request, user):
        if not app.config.MYSQLAVAIL:
            username, apikey, access, info = self.verify(request)
            return user, apikey, info, access
        info = {}
        access = {}
        apikey = ''
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'SELECT * FROM sanic_info WHERE user = %s'
                values = (user,)
                await cur.execute(query, values)
                info = await cur.fetchall()
                if len(info) == 0:
                    return user, apikey, info, access
                info = info[0]
                apikey = info['apikey']
                query3 = 'SELECT access, value FROM sanic_access WHERE user = %s'
                values3 = (user,)
                await cur.execute(query3, values3)
                x = await cur.fetchall()
                for row in x:
                    if row['access'] not in access:
                        access[row['access']] = []
                    access[row['access']].append(row['value'])
                return user, apikey, info, access
    # Log on a user, if MySQL is available use the database to provide access levels
    # Otherwise they can be set from the function.
    async def logon(self, request, user, access={}, info='', apikey='', forceNoMySQL=False):
        if not app.config.MYSQLAVAIL or forceNoMySQL:
            request.ctx.session['apikey'] = apikey
            request.ctx.session['access'] = access
            request.ctx.session['info'] = info
            request.ctx.session['user'] = user
            request.ctx.session['visit'] = time.time()
            return user, apikey, info, access
        info = {}
        access = {}
        apikey = ''
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'SELECT * FROM sanic_info WHERE user = %s'
                values = (user,)
                await cur.execute(query, values)
                info = await cur.fetchall()
                if len(info) == 0 or info[0]['apikey'] is None:
                    apikey = await self.genapikey(request, user)
                    await cur.execute(query, values)
                    info = await cur.fetchall()
                info = info[0]
                apikey = info['apikey']
                query3 = 'SELECT access, value FROM sanic_access WHERE user = %s'
                values3 = (user,)
                await cur.execute(query3, values3)
                x = await cur.fetchall()
                for row in x:
                    if row['access'] not in access:
                        access[row['access']] = []
                    access[row['access']].append(row['value'])
                request.ctx.session['apikey'] = apikey
                request.ctx.session['access'] = access
                request.ctx.session['info'] = info
                request.ctx.session['user'] = user
                request.ctx.session['visit'] = time.time()
                return user, apikey, info, access

@app.listener('before_server_start')
async def setup_auth(app):
    app.ctx.auth = AuthVerification()
    app.ctx.pam = pam.pam()
