from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_challenge_option", url_prefix="/auth")

@sub_bp.route("/challenge", methods=['POST'])
async def system_challenge(request):
    """
    Verify a authentication challenge request.  Challenge response code will need to be added by a script outside of the default library.
    """
    endpoint = '/auth/challenge/'
    data = request.json
    user = data['username']
    token = data['challenge']
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = 'SELECT * FROM sanic_challenge WHERE user=%s AND expect=%s AND attempts < 10 AND sent > NOW() - INTERVAL 10 MINUTE'
            values = (user, token,)
            await cur.execute(query, values)
            info = await cur.fetchall()
            if len(info) == 0:
                query = 'UPDATE sanic_challenge SET attempts = attempts + 1 WHERE user=%s'
                values = (user, )
                await cur.execute(query, values)
                res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint':endpoint, 'data':{'username': None, 'apikey': '', 'access': {}, 'info': {}, 'redirect': request.app.config.REDIRECT_LOGON_FAILED}})
                return res
            query = 'DELETE FROM sanic_challenge WHERE user=%s'
            values = (user,)
            await cur.execute(query, values)
            user, apikey, info, access = await request.app.ctx.auth.logon(request, user)
            res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
            return res

