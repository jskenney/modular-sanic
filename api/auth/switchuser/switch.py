from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_switch", url_prefix="/auth")

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
