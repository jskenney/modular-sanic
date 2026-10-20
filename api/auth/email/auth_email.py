from sanic import Blueprint
from sanic.log import logger
import asyncio, aiomysql
import secrets
import smtplib
from urllib.parse import quote
from email.message import EmailMessage

sub_bp = Blueprint("auth_challenge_response", url_prefix="/auth/request/challenge")

def send_email(server, msg):
    with smtplib.SMTP(server) as smtp:
        smtp.send_message(msg)

@sub_bp.route("/", methods=['POST'])
async def system_request_challenge(request):
    """
    Send an email with a 7 digit challenge.
    """
    unavailable = request.app.ctx.auth.db_unavailable(request)
    if unavailable:
        return unavailable
    fields = request.app.ctx.auth.json_fields(request, 'username')
    if fields is None:
        return request.app.ctx.auth.bad_request(request, 'username')
    username, = fields
    redirect = request.app.ctx.auth.setting(request, 'CHALLENGE_PAGE') + '?user=' + quote(username)
    if await request.app.ctx.auth.throttled(request, 'challenge', username):
        return request.app.ctx.reply(request, False, {'redirect': redirect}, status=429, error="Too many attempts, please wait and try again.")
    # Generate a Token (7 digits)
    token = str(secrets.randbelow(10**7))
    # Add the token to the database.  A new request does not reset the attempt
    # counter unless the previous challenge has expired (attempts is assigned
    # before sent, so it sees the previous sent time).
    query = 'INSERT INTO sanic_challenge (user, expect) VALUES (%s, %s) ON DUPLICATE KEY UPDATE attempts=IF(sent < NOW() - INTERVAL 10 MINUTE, 0, attempts), expect=%s, sent=NOW()'
    values = (username, token, token, )
    ok = True
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await cur.execute(query, values)
            except Exception as e:
                logger.info(f"Challenge not sent for {username}: {type(e).__name__} | Message: {e}")
                ok = False
    # Now send the token to the user so they can log on.  Email / Text Etc.
    if ok:
        message = "Please enter the following into the challenge box provided on the website\n\n"+token+"\n\n"
        msg = EmailMessage()
        msg['Subject'] =     request.app.ctx.auth.setting(request, 'AUTH_TITLE')+' Logon Request'
        msg['From'] =        request.app.ctx.auth.setting(request, 'AUTH_EMAILER')
        msg['To'] = username + '@' + request.app.ctx.auth.setting(request, 'AUTH_DOMAIN').lstrip('@')
        msg.set_content(message)
        try:
            await asyncio.to_thread(send_email, request.app.ctx.auth.setting(request, 'AUTH_EMAIL_SERVER'), msg)
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f"Unable to send challenge email: {type(e).__name__} | Message: {e}")
            return request.app.ctx.reply(request, False, {'redirect': redirect}, status=503, error="Unable to send the challenge email, please try again later.")
    # Respond back to the user the same way whether or not the user exists.
    res = request.app.ctx.reply(request, True, {'redirect': redirect})
    return res
