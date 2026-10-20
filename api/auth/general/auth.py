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
    await request.app.ctx.auth.logoff(request)
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.env.str('AUTH_MESSAGE', default="")
        request.ctx.session['motd'] = True
    page_title = request.app.config.env.str('AUTH_TITLE', default="SanicApp")
    res = request.app.ctx.reply(request, True, {'apikey': None, 'username': None, 'access': {}, 'info': {}, 'redirect': request.app.config.env.str('REDIRECT_LOGOFF', default="/index.html"), 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp"), 'message': message, 'page_title': page_title})
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/key", methods=['GET'])
async def system_key(request):
    """
    Show current API key and user data.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    res = request.app.ctx.reply(request, ok, {'apikey': apikey, 'username': username, 'access': access, 'info': info}, status=200 if ok else 401)
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/info", methods=['GET'])
async def system_info(request):
    """
    Show current API key and user data, along with site information.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    redirect = request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")
    if ok:
        redirect = request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default='/index.html')
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.env.str('AUTH_MESSAGE', default="")
        request.ctx.session['motd'] = True
    page_title = ''
    if request.app.config.env.str('AUTH_TITLE', default="SanicApp"):
        page_title = request.app.config.env.str('AUTH_TITLE', default="SanicApp")
    res = request.app.ctx.reply(request, ok, {'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp"), 'message': message, 'page_title': page_title})
    return res

# Refresh Accesses
@sub_bp.route("/auth/refresh", methods=['GET'])
async def system_refresh(request):
    """
    Refresh current logged on users access and info, reloads from database, returns same information as /auth/info.
    """
    message = ""
    if not request.ctx.session.get('motd'):
        message = request.app.config.env.str('AUTH_MESSAGE', default="")
        request.ctx.session['motd'] = True
    page_title = request.app.config.env.str('AUTH_TITLE', default="SanicApp")
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if ok:
        user, apikey, info, access = await request.app.ctx.auth.logon(request, username)
        redirect = request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")
        res = request.app.ctx.reply(request, ok, {'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp"), 'message': message, 'page_title': page_title})
    else:
        redirect = request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")
        res = request.app.ctx.reply(request, ok, {'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp"), 'message': message, 'page_title': page_title}, status=401)
    return res

# Show current apikey, assumes we are logged on
@sub_bp.route("/auth/rekey", methods=['GET'])
async def system_rekey(request):
    """
    Generate new API Key and provide updated API key and user information
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    redirect = request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")
    # Do not let a switched (su) session rotate the other user's API key
    if ok and request.ctx.session.get('original_user'):
        return request.app.ctx.reply(request, False, {'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html"), 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp")}, status=403, error="The API key cannot be changed while switched to another user.")
    if ok:
        apikey = await request.app.ctx.auth.genapikey(request, username)
        user, apikey, info, access = await request.app.ctx.auth.logon(request, username)
        redirect = request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")
    res = request.app.ctx.reply(request, ok, {'apikey': apikey, 'username': username, 'access': access, 'info': info, 'redirect': redirect, 'logo': request.app.config.env.str('LOGON_LOGO', default="/logon/logo.webp")}, status=200 if ok else 401)
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/auth/<apikey>/access/list/<user>", methods=['GET'])
async def system_access_list(request, apikey, user):
    """
    Provides the access key/value pairs for a specific user.  Must be either current user or have admin/permissions access.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if username == user or ('admin' in access and 'permissions' in access['admin']):
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = request.app.ctx.reply(request, True, {'username': user, 'access': access})
    else:
        res = request.app.ctx.reply(request, False, {'username': username, 'access': {}}, status=403 if ok else 401)
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/auth/<apikey>/access/add/<user>/<access>/<value>", methods=['GET'])
async def system_access_add(request, apikey, user, access, value):
    """
    Add specific access key/value pairs for a user, must be a user with admin/permissions access.
    """
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_add(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = request.app.ctx.reply(request, True, {'username': user, 'access': access})
    else:
        res = request.app.ctx.reply(request, False, {'username': username, 'access': {}}, status=403 if ok else 401)
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/auth/<apikey>/access/remove/<user>/<access>/<value>", methods=['GET'])
async def system_access_remove(request, apikey, user, access, value):
    """
    Remove a specific access key/value pair for a user, must be a user with admin/permissions access.
    """
    naccess = access
    nvalue = value
    ok, username, apikey, access, info = await request.app.ctx.auth.verifyapi(request, apikey)
    if 'admin' in access and 'permissions' in access['admin']:
        await request.app.ctx.auth.access_del(request, user, naccess, nvalue)
        user, apikey, info, access = await request.app.ctx.auth.access_show(request, user)
        res = request.app.ctx.reply(request, True, {'username': user, 'access': access})
    else:
        res = request.app.ctx.reply(request, False, {'username': username, 'access': {}}, status=403 if ok else 401)
    return res

# Show redirect if logged on
@sub_bp.route("/auth/redirect_if_logged_on", methods=['GET'])
async def system_if_logged_on(request):
    """
    Provide redirect to REDIRECT_LOGON_SUCCESSFUL if logged on.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if ok:
        redirect = request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")
        res = request.app.ctx.reply(request, ok, {'redirect': redirect})
    else:
        res = request.app.ctx.reply(request, ok, {})
    return res

# Show redirect if logged off
@sub_bp.route("/auth/redirect_if_logged_off", methods=['GET'])
async def system_if_logged_off(request):
    """
    Provide redirect to REDIRECT_LOGON_FAILED if logged off.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    if ok:
        res = request.app.ctx.reply(request, ok, {})
    else:
        redirect = request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")
        res = request.app.ctx.reply(request, ok, {'redirect': redirect})
    return res
