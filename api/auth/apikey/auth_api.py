from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_api_options", url_prefix="/auth")

# Largest request body accepted by /auth/apifile (the key file itself is limited to 10000 bytes)
APIFILE_MAX_BODY = 65536

@sub_bp.route("/apikey", methods=['POST'])
async def system_apikey(request):
    """
    Authenticate a user using their API key.
    """
    unavailable = request.app.ctx.auth.db_unavailable(request)
    if unavailable:
        return unavailable
    data = request.json
    user = data['username']
    apikey = data['apikey']
    if await request.app.ctx.auth.throttled(request, 'logon', user):
        return request.app.ctx.reply(request, False, {'username': user, 'apikey': '', 'access': {}, 'info': {}, 'redirect': request.app.config.env.str('REDIRECT_LOGON_FAILED', default='/logon/logon.html')}, status=429, error="Too many attempts, please wait and try again.")
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = 'SELECT user FROM sanic_info WHERE user = %s AND apikey = %s AND ' + request.app.ctx.auth.KEY_VALID
            values = (user, request.app.ctx.auth.hashkey(apikey), )
            info = {}
            access = {}
            apikey = ''
            await cur.execute(query, values)
            info = await cur.fetchall()
    if len(info) == 0:
        res = request.app.ctx.reply(request, False, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default='/index.html')}, status=401)
        return res
    # Log on after the connection is returned, logon() uses its own connection
    user, apikey, info, access = await request.app.ctx.auth.logon(request, info[0]['user'])
    res = request.app.ctx.reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default='/index.html')})
    return res

@sub_bp.route("/apifile", methods=['POST'], stream=True)
async def system_apifile(request):
    """
    Authenticate a user by uploading a file with their API key.
    """
    reply = request.app.ctx.reply
    unavailable = request.app.ctx.auth.db_unavailable(request)
    if unavailable:
        return unavailable
    if await request.app.ctx.auth.throttled(request, 'logon'):
        return reply(request, False, {}, status=429, error="Too many attempts, please wait and try again.")
    # Read the body here (streamed route) so an oversized upload is rejected before it is buffered
    length = request.headers.get('content-length', '')
    if length.isdigit() and int(length) > APIFILE_MAX_BODY:
        return reply(request, False, {}, status=413, error="The file uploaded was too large and was rejected.")
    body = bytearray()
    while True:
        chunk = await request.stream.read()
        if chunk is None:
            break
        body += chunk
        if len(body) > APIFILE_MAX_BODY:
            return reply(request, False, {}, status=413, error="The file uploaded was too large and was rejected.")
    request.body = bytes(body)
    if not request.files:
        return reply(request, False, {}, status=400, error="No files uploaded")
    files_info = []
    for field_name, files in request.files.items():
        if isinstance(files, list):
            for uploaded_file in files:
                files_info.append({
                    "field_name": field_name,
                    "file_name": uploaded_file.name,
                    "content_type": uploaded_file.type,
                    "size": len(uploaded_file.body) })
        else:
            uploaded_file = files
            files_info.append({
                "field_name": field_name,
                "file_name": uploaded_file.name,
                "content_type": uploaded_file.type,
                "size": len(uploaded_file.body) })
    if len(files_info) != 1:
        return reply(request, False, {}, status=400, error="Only one file may be submitted at a time.")
    if files_info[0]['size'] > 10000:
        return reply(request, False, {}, status=413, error="The file uploaded was too large and was rejected.")
    uploaded_file = request.files.get('files[]')
    if uploaded_file is None:
        return reply(request, False, {}, status=400, error="No files were sent to the server.")
    contents = uploaded_file.body.decode('utf-8', errors='replace')
    uuid_pattern_strict = r'\b[0-9a-fA-F]{8}-' \
                      r'[0-9a-fA-F]{4}-' \
                      r'[1-5][0-9a-fA-F]{3}-' \
                      r'[89abAB][0-9a-fA-F]{3}-' \
                      r'[0-9a-fA-F]{12}\b'
    uuids = re.findall(uuid_pattern_strict, contents)
    if len(uuids) != 1:
        return reply(request, False, {}, status=400, error="Unable to find the appropriate API key")
    uuids = uuids[0]
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = 'SELECT user FROM sanic_info WHERE apikey=%s AND ' + request.app.ctx.auth.KEY_VALID
            values = (request.app.ctx.auth.hashkey(uuids), )
            await cur.execute(query, values)
            info = await cur.fetchall()
            if len(info) == 0:
                return reply(request, False, {}, status=401, error="API key that was sent was invalid.")
    user, apikey, info, access = await request.app.ctx.auth.logon(request, info[0]['user'])
    res = reply(request, True, {'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.env.str('REDIRECT_LOGON_SUCCESSFUL', default='/index.html')})
    return res
