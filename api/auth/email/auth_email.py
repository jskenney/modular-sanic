from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, secrets
import smtplib
from email.message import EmailMessage

sub_bp = Blueprint("auth_challenge_response", url_prefix="/auth/request/challenge")

@sub_bp.route("/", methods=['POST'])
async def system_request_challenge(request):
    """
    Send an email with a 7 digit challenge.
    """
    endpoint = '/auth/request/challenge'
    data = request.json
    username = data['username']
    # Generate a Token (7 digits)
    token = str(secrets.randbelow(10**7))
    # Add the token to the database
    query = 'INSERT INTO sanic_challenge (user, expect) VALUES (%s, %s) ON DUPLICATE KEY UPDATE expect=%s, attempts=0, sent=NOW()'
    values = (username, token, token, )
    ok = True
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await cur.execute(query, values)
            except:
                ok = False
    # Now send the token to the user so they can log on.  Email / Text Etc.
    if ok:
        message = "Please enter the following into the challenge box provided on the website\n\n"+token+"\n\n"
        msg = EmailMessage()
        msg['Subject'] =     request.app.config.env.str('AUTH_TITLE',        default='SanicApp')+' Logon Request'
        msg['From'] =        request.app.config.env.str('AUTH_EMAILER',      default='noreply@example.com')
        msg['To'] = username+request.app.config.env.str('AUTH_DOMAIN',       default='example.com')
        msg.set_content(message)
        with smtplib.SMTP(   request.app.config.env.str('AUTH_EMAIL_SERVER', default='localhost')) as server:
            server.send_message(msg)
    # Respond back to the user.
    redirect = request.app.config.env.str(              'CHALLENGE_PAGE',    default='/logon/challenge.html') +'?user='+username
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'redirect': redirect}})
    return res
