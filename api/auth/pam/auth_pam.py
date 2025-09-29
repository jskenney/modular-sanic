from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_pam_option", url_prefix="/auth")

# Perform basic PAM authentication (system level)
@sub_bp.route("/pam", methods=['POST'])
async def system_pamauth(request):
    """
    Perform basic PAM authentication (requires username and password).
    """
    endpoint = '/auth/pam'
    data = request.form
    u = data.get('username')
    p = data.get('password')
    apikey = None
    await request.app.ctx.auth.logoff(request)
    if u and p and request.app.ctx.pam.authenticate(u, p):
        user, apikey, info, access = await request.app.ctx.auth.logon(request, u)
        res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': u, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    else:
        res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': None, 'apikey': apikey, 'access': {}, 'info': {}, 'redirect': request.app.config.REDIRECT_LOGON_FAILED}})
    return res
