from sanic import Blueprint
import aiomysql
import secrets

sub_bp = Blueprint("auth_challenge_option", url_prefix="/auth")

@sub_bp.route("/challenge", methods=['POST'])
async def system_challenge(request):
    """
    Verify a authentication challenge request.
    """
    unavailable = request.app.ctx.auth.db_unavailable(request)
    if unavailable:
        return unavailable
    fields = request.app.ctx.auth.json_fields(request, 'username', 'challenge')
    if fields is None:
        return request.app.ctx.auth.bad_request(request, 'username', 'challenge')
    user, token = fields
    failed = {'username': None, 'apikey': '', 'access': {}, 'info': {}, 'redirect': request.app.ctx.auth.setting(request, 'REDIRECT_LOGON_FAILED')}
    if await request.app.ctx.auth.throttled(request, 'logon', user):
        return request.app.ctx.reply(request, False, failed, status=429, error="Too many attempts, please wait and try again.")
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Count the attempt before checking it, in one statement, so concurrent
            # guesses cannot get past the attempt limit.
            query = 'UPDATE sanic_challenge SET attempts = attempts + 1 WHERE user=%s AND attempts < 10 AND sent > NOW() - INTERVAL 10 MINUTE'
            values = (user, )
            await cur.execute(query, values)
            if cur.rowcount != 1:
                return request.app.ctx.reply(request, False, failed, status=401)
            query = 'SELECT expect FROM sanic_challenge WHERE user=%s'
            await cur.execute(query, values)
            info = await cur.fetchone()
            if not info or not secrets.compare_digest(str(info['expect']).encode(), token.encode()):
                return request.app.ctx.reply(request, False, failed, status=401)
            query = 'DELETE FROM sanic_challenge WHERE user=%s'
            values = (user,)
            await cur.execute(query, values)
    # Log on after the connection is returned, logon() uses its own connection
    user, apikey, info, access = await request.app.ctx.auth.logon(request, user)
    res = request.app.ctx.reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.ctx.auth.setting(request, 'REDIRECT_LOGON_SUCCESSFUL')})
    return res
