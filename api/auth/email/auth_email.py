from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, random
import smtplib
from email.message import EmailMessage

sub_bp = Blueprint("auth_challenge_response", url_prefix="/auth/request/challenge")

@sub_bp.route("/", methods=['POST'])
async def system_request_challenge(request):
    endpoint = '/auth/request/challenge'
    data = request.json
    username = data['username']
    # Generate a Token (7 digits)
    token = ''.join(str(random.randint(0, 9)) for _ in range(7))
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
        msg['Subject'] = request.app.config.AUTH_TITLE+' Logon Request'
        msg['From'] = request.app.config.AUTH_EMAILER
        msg['To'] = username+request.app.config.AUTH_DOMAIN
        msg.set_content(message)
        with smtplib.SMTP(request.app.config.AUTH_EMAIL_SERVER) as server:
            server.send_message(msg)
    # Respond back to the user.
    redirect = request.app.config.CHALLENGE_PAGE +'?user='+username
    res = response.json({'success': ok, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'redirect': redirect}})
    return res
