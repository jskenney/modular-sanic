###############################################################################
# Import Required Python Libraries
import asyncio, aiomysql, aiomcache
from sanic import Sanic, response
from sanic.response import text, json, html, redirect, empty
from sanic_session import Session, MemcacheSessionInterface
import pam, os, importlib.util, time, uuid, sys

###############################################################################
# Define the possible locations for the config.py file, will be tried in order.
# Or use the environmental variable SANIC_CONFIG to provide the path and filename
config_file_locations = ('../config.py', '../site/config.py', './site/config.py', './config.py')
if 'SANIC_CONFIG_FILE' in os.environ:
    config_file_locations = [os.environ['SANIC_CONFIG_FILE']]

###############################################################################
# Import site configs (config.py) from either the site or local directory.
alt_site = None
for possible_site in config_file_locations:
    if alt_site is None and os.path.exists(possible_site):
        alt_site = possible_site
if alt_site is not None:
    spec = importlib.util.spec_from_file_location("myconfigs", alt_site)
    myconfigs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(myconfigs)
    print("Notice: Loaded config file from", alt_site)
else:
    print("Notice: No configuration file detected, exiting.")
    sys.exit()

###############################################################################
# Create Sanic Application
app = Sanic(myconfigs.site_settings['NAME'])

###############################################################################
# Loading in settings from config file
for variable in dir(myconfigs):
    if not variable.startswith('_'):
        obj = getattr(myconfigs, variable)
        app.config.update(obj)

###############################################################################
# Enable Session Support (Default to Memcached interface)
client = aiomcache.Client(app.config.MEMCACHED_SERVER, app.config.MEMCACHED_PORT)
Session(app, interface=MemcacheSessionInterface(client))

###############################################################################
# Determine where the root of the website exists and where
# the site favicon.ico and /html directory are.
app.static("/", app.config.INITIAL_PAGE, name="root_html")
app.static("/favicon.ico", app.config.FAVICON, name='favicon')
app.static("/html/", app.config.HTML, directory_view=app.config.SHOW_SITE_CONTENTS)

###############################################################################
# Javascript and CSS for Logon Purposes.
# UIKit (https://getuikit.com/) is a MIT License based Web Framework
# jQuery (https://jquery.com/license/) is a MIT License based Javascript Library
app.static("/uikit/", "./uikit/", directory_view=app.config.SHOW_SITE_CONTENTS, name='uikit')

###############################################################################
# To support HSTS, a common organizational security requirement.
if 'HSTS' in app.config:
    print("Notice: Set HSTS to", app.config.HSTS)
    @app.middleware("response")
    async def add_hsts_headers(request, response):
        if request.scheme == 'https':
            response.headers["Strict-Transport-Security"] = "max-age="+app.config.HSTS+"; includeSubDomains"

###############################################################################
# Lets try autodiscovery of Endpoints (authentication APIs and site APIs)
# Note, you must name all blueprints inside of the .py files as sub_bp,
# so you should see something like the following in each file:
#    sub_bp = Blueprint("auth", url_prefix="/auth")
for source in (app.config.API_LOCATIONS):
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
@app.listener('before_server_start')
async def setup_memcache(app, loop):
    app.ctx.mc = aiomcache.Client(app.config.MEMCACHED_SERVER, app.config.MEMCACHED_PORT)
    print("Notice: Memcached connection pool created.")

@app.listener('after_server_stop')
async def close_memcache(app, loop):
    await app.ctx.mc.close()
    print("Notice: Memcached connection pool closed.")

###############################################################################
# Configure and connect to the MySQL database.
@app.listener('before_server_start')
async def setup_db(app, loop):
    app.ctx.pool = await aiomysql.create_pool(
        host=app.config.DB_HOST,
        port=app.config.DB_PORT,
        user=app.config.DB_USER,
        password=app.config.DB_PASS,
        db=app.config.DB_NAME,
        loop=loop,
        autocommit=True
    )
    app.ctx.loop = loop
    print("Notice: Database connection pool created.")

@app.listener('after_server_stop')
async def close_db(app, loop):
    app.ctx.pool.close()
    await app.ctx.pool.wait_closed()
    print("Notice: Database connection pool closed.")

###############################################################################
# Configure global Authentication & Verification methods, this depends
# on storing user information in the session cache, and retrieving
# access information from the MySQL database's
# sanic_info, sanic_access, and sanic_challenge tables.
class AuthVerification:
    async def verify(self, request):
        if not request.ctx.session.get('user') or not request.ctx.session.get('visit') or time.time() - request.ctx.session.get('visit') > request.app.config.AUTH_VALID:
            await self.logoff(request)
            return False, None, None, {}, {}
        access = request.ctx.session.get('access')
        info = request.ctx.session.get('info')
        apikey = request.ctx.session.get('apikey')
        username = request.ctx.session.get('user')
        request.ctx.session['visit'] = time.time()
        return True, username, apikey, access, info
    async def verifyapi(self, request, mykey):
        if not request.ctx.session.get('user') or not request.ctx.session.get('visit') or time.time() - request.ctx.session.get('visit') > request.app.config.AUTH_VALID:
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
    async def genapikey(self, request, user):
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
    async def access_add(self, request, user, access, value):
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'INSERT INTO sanic_access (user, access, value) VALUES (%s, %s, %s)'
                values = (user, access, value,)
                try:
                    await cur.execute(query, values)
                except:
                    pass
    async def access_del(self, request, user, access, value):
        async with request.app.ctx.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = 'DELETE FROM sanic_access WHERE user = %s AND access = %s AND value =%s'
                values = (user, access, value,)
                try:
                    await cur.execute(query, values)
                except:
                    pass
    async def access_show(self, request, user):
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
    async def logon(self, request, user):
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
async def setup_auth(app, loop):
    app.ctx.auth = AuthVerification()
    app.ctx.pam = pam.pam()
