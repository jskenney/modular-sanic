from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth", url_prefix="/auth")

sub_bp.static("/", "./logon/logon.html", name="auth_login_html")
sub_bp.static("/logon/", "./logon/", directory_view=False)

###############################################################################
# Deauthenticate / Logoff (remove cookie and any database references)
@sub_bp.route("/deauth", methods=['GET'])
async def system_deauth(request):
    """
    Log out of the system
    """
    endpoint = '/auth/deauth'
    await request.app.ctx.auth.logoff(request)
    res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': None, 'username': None, 'access': {}, 'info': {}, 'redirect': request.app.config.REDIRECT_LOGOFF}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/key", methods=['GET'])
async def system_key(request):
    """
    Show current apikey and user information
    """
    endpoint = '/auth/key'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'apikey': apikey, 'username': username, 'access': access, 'info': info}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/info", methods=['GET'])
async def system_info(request):
    """
    Show current apikey and user information
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

# Return to original user after su
@sub_bp.route("/return", methods=['GET'])
async def system_su_return(request):
    """
    Return to original user after switching.
    """
    endpoint = '/auth/return'
    if request.ctx.session.get('original_user'):
        user = request.ctx.session.get('original_user')
        del(request.ctx.session['original_user'])
        user, apikey, info, access = await request.app.ctx.auth.logon(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    else:
        ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
        if ok:
            res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
        else:
            res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_FAILED}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/su", methods=['POST'])
async def system_su(request):
    """
    Switch to another user, works when you are an admin with become access
    """
    endpoint = '/auth/su'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if 'admin' in access and 'become' in access['admin']:
        if not request.ctx.session.get('original_user'):
            request.ctx.session['original_user'] = username
        data = request.json
        user, apikey, info, access = await request.app.ctx.auth.logon(request, data['username'])
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    return res

# Refresh Accesses
@sub_bp.route("/refresh", methods=['POST'])
async def system_refresh(request):
    """
    Refresh your access and info
    """
    endpoint = '/auth/refresh'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if ok:
        user, apikey, info, access = await request.app.ctx.auth.logon(request, data['username'])
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_FAILED}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/access/list/<user>", methods=['GET'])
async def system_access_list(request, user):
    """
    Provies the access key/value pairs for a specific user.  Must be that user or have admin/permissions access.
    """
    endpoint = '/auth/access/list'
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if username == user or ('admin' in access and 'permissions' in access['admin']):
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/access/add/<user>/<access>/<value>", methods=['GET'])
async def system_access_add(request, user, access, value):
    """
    Add specific access key/value pairs for a user, must be a user with admin/permissions access.
    """
    endpoint = '/auth/access/add'
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_add(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/access/remove/<user>/<access>/<value>", methods=['GET'])
async def system_access_remove(request, user, access, value):
    """
    Remove a specific access key/value pair for a user, must be a user with admin/permissions access.
    """
    endpoint = '/auth/access/remove'
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_del(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': user, 'access': access}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': username, 'access': {}}})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/rekey", methods=['GET'])
async def system_rekey(request):
    """
    Replace API Key and then show current apikey and user information
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

