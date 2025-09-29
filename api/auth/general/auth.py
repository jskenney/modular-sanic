from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth", url_prefix="/")

###############################################################################
# Deauthenticate / Logoff (remove cookie and any database references)
@sub_bp.route("/auth/deauth", methods=['GET'])
async def system_deauth(request):
    """
    Log off and invalidate current session.
    """
    endpoint = '/auth/deauth'
    await request.app.ctx.auth.logoff(request)
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.AUTH_MESSAGE
        request.ctx.session['motd'] = True
    page_title = ''
    if request.app.config.AUTH_TITLE:
        page_title = request.app.config.AUTH_TITLE
    res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': None, 'username': None, 'access': {}, 'info': {}, 'redirect': request.app.config.REDIRECT_LOGOFF, 'logo': request.app.config.LOGON_LOGO, 'message': message, 'page_title': page_title}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/key", methods=['GET'])
async def system_key(request):
    """
    Show current API key and user data.
    """
    endpoint = '/auth/key'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/info", methods=['GET'])
async def system_info(request):
    """
    Show current API key and user data, along with site information.
    """
    endpoint = '/auth/info'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    redirect = request.app.config.REDIRECT_LOGON_FAILED
    if ok:
        redirect = request.app.config.REDIRECT_LOGON_SUCCESSFUL
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.AUTH_MESSAGE
        request.ctx.session['motd'] = True
    page_title = ''
    if request.app.config.AUTH_TITLE:
        page_title = request.app.config.AUTH_TITLE
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.LOGON_LOGO, 'message': message, 'page_title': page_title}})
    return res

# Refresh Accesses
@sub_bp.route("/auth/refresh", methods=['GET'])
async def system_refresh(request):
    """
    Refresh current logged on users access and info, reloads from database, returns same information as /auth/info.
    """
    endpoint = '/auth/refresh'
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.AUTH_MESSAGE
        request.ctx.session['motd'] = True
    page_title = ''
    if request.app.config.AUTH_TITLE:
        page_title = request.app.config.AUTH_TITLE
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if ok:
        user, apikey, info, access = await request.app.ctx.auth.logon(request, username)
        redirect = request.app.config.REDIRECT_LOGON_SUCCESSFUL
        res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.LOGON_LOGO, 'message': message, 'page_title': page_title}})
    else:
        redirect = request.app.config.REDIRECT_LOGON_FAILED
        res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.LOGON_LOGO, 'message': message, 'page_title': page_title}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/rekey", methods=['GET'])
async def system_rekey(request):
    """
    Generate new API Key and provide updated API key and user information
    """
    endpoint = '/auth/rekey'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    redirect = request.app.config.REDIRECT_LOGON_FAILED
    if ok:
        apikey = await request.app.ctx.auth.genapikey(request, username)
        user, apikey, info, access = await request.app.ctx.auth.logon(request, username)
        redirect = request.app.config.REDIRECT_LOGON_SUCCESSFUL
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.LOGON_LOGO}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/<apikey>/auth/access/list/<user>", methods=['GET'])
async def system_access_list(request, apikey, user):
    """
    Provides the access key/value pairs for a specific user.  Must be either current user or have admin/permissions access.
    """
    endpoint = '/<apikey>/auth/access/list/'+user
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if username == user or ('admin' in access and 'permissions' in access['admin']):
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/<apikey>/auth/access/add/<user>/<access>/<value>", methods=['GET'])
async def system_access_add(request, apikey, user, access, value):
    """
    Add specific access key/value pairs for a user, must be a user with admin/permissions access.
    """
    endpoint = '/<apikey>/auth/access/add/'+user+'/'+access+'/'+value
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_add(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/<apikey>/auth/access/remove/<user>/<access>/<value>", methods=['GET'])
async def system_access_remove(request, apikey, user, access, value):
    """
    Remove a specific access key/value pair for a user, must be a user with admin/permissions access.
    """
    endpoint = '/<apikey>/auth/access/remove/'+user+'/'+access+'/'+value
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_del(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res
