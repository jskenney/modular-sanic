from sanic import Blueprint, response
from sanic.log import logger
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_switch", url_prefix="/auth")

# Return to original user after su
@sub_bp.route("/return", methods=['POST'])
async def system_su_return(request):
    """
    Return to original user after switching.
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    original = request.ctx.session.get('original_user') if ok else None
    if not original:
        if ok:
            res = request.app.ctx.reply(request, False, {'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")}, status=400)
        else:
            res = request.app.ctx.reply(request, False, {'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")}, status=401)
        return res
    # The original user must still be allowed to switch users, otherwise log off entirely
    _, _, _, original_access = await request.app.ctx.auth.access_show(request, original)
    if 'admin' not in original_access or 'become' not in original_access['admin']:
        logger.warning(f"su return refused: {original} no longer has admin/become (was {username}) from {request.remote_addr or request.ip}")
        await request.app.ctx.auth.logoff(request)
        return request.app.ctx.reply(request, False, {'username': None, 'apikey': None, 'access': {}, 'info': {}, 'redirect': request.app.config.env.str('REDIRECT_LOGON_FAILED', default="/logon/logon.html")}, status=403)
    del(request.ctx.session['original_user'])
    user, apikey, info, access = await request.app.ctx.auth.logon(request, original)
    logger.info(f"su return: {username} -> {original} from {request.remote_addr or request.ip}")
    res = request.app.ctx.reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")})
    return res

# Switch Users (assuming admin access)
@sub_bp.route("/su", methods=['POST'])
async def system_su(request):
    """
    Switch to another user, works when you are an admin with become access
    """
    ok, username, apikey, access, info = await request.app.ctx.auth.verify(request)
    failed = {'username': username, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")}
    if not ok:
        return request.app.ctx.reply(request, False, failed, status=401)
    if 'admin' not in access or 'become' not in access['admin']:
        return request.app.ctx.reply(request, False, failed, status=403)
    # The database is needed to confirm the target user exists and to load their access
    if not request.app.config.MYSQLAVAIL:
        return request.app.ctx.reply(request, False, failed, status=503, error="Switching users requires the database.")
    target = (request.json or {}).get('username')
    if not target or not isinstance(target, str):
        return request.app.ctx.reply(request, False, failed, status=400, error="A username is required.")
    _, _, target_info, target_access = await request.app.ctx.auth.access_show(request, target)
    if not target_info:
        return request.app.ctx.reply(request, False, failed, status=404, error="Unknown user.")
    # Never become a user holding administrative access the current user lacks
    if not set(target_access.get('admin', [])) <= set(access.get('admin', [])):
        logger.warning(f"su refused: {username} -> {target} (target has more admin access) from {request.remote_addr or request.ip}")
        return request.app.ctx.reply(request, False, failed, status=403, error="Cannot switch to a user with more administrative access.")
    if not request.ctx.session.get('original_user'):
        request.ctx.session['original_user'] = username
    user, apikey, info, access = await request.app.ctx.auth.logon(request, target_info['user'])
    logger.info(f"su: {username} -> {user} (original user {request.ctx.session.get('original_user')}) from {request.remote_addr or request.ip}")
    res = request.app.ctx.reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default="/index.html")})
    return res
