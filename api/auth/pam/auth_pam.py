from sanic import Blueprint
import asyncio
import pam

sub_bp = Blueprint("auth_pam_option", url_prefix="/auth")

# Perform basic PAM authentication (system level)
@sub_bp.route("/pam", methods=['POST'])
async def system_pamauth(request):
    """
    Perform basic PAM authentication (requires username and password).
    """
    data = request.form
    u = data.get('username')
    p = data.get('password')
    apikey = None
    failed = {'username': None, 'apikey': apikey, 'access': {}, 'info': {}, 'redirect': request.app.ctx.auth.setting(request, 'REDIRECT_LOGON_FAILED')}
    if await request.app.ctx.auth.throttled(request, 'logon', u or ''):
        return request.app.ctx.reply(request, False, failed, status=429, error="Too many attempts, please wait and try again.")
    await request.app.ctx.auth.logoff(request)
    # PAM blocks (including its failure delay), so run it off the event loop with its own handle
    service = request.app.ctx.auth.setting(request, 'PAM_SERVICE')
    if u and p and await asyncio.to_thread(pam.pam().authenticate, u, p, service=service):
        user, apikey, info, access = await request.app.ctx.auth.logon(request, u)
        res = request.app.ctx.reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.ctx.auth.setting(request, 'REDIRECT_LOGON_SUCCESSFUL')})
    else:
        res = request.app.ctx.reply(request, False, failed, status=401)
    return res
