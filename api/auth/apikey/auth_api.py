from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_api_options", url_prefix="/auth")

@sub_bp.route("/apikey", methods=['POST'])
async def system_apikey(request):
    """
    Authenticate a user using their apikey.
    """
    endpoint = '/auth/apikey/'
    data = request.json
    user = data['username']
    apikey = data['apikey']
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = 'SELECT * FROM sanic_info WHERE user = %s AND apikey = %s'
            values = (user, apikey, )
            info = {}
            access = {}
            apikey = ''
            await cur.execute(query, values)
            info = await cur.fetchall()
            if len(info) == 0:
                res = response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
                return res
            user, apikey, info, access = await request.app.ctx.auth.logon(request, user)
            res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
            return res

@sub_bp.route("/apifile", methods=['POST'])
async def system_apifile(request):
    endpoint = '/auth/apifile'
    if not request.files:
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "No files uploaded", 'data':{}})
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
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "Only one file may be submitted at a time.", 'data':{}})
    if files_info[0]['size'] > 10000:
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "The file uploaded was too large and was rejected.", 'data':{}})
    uploaded_file = str(request.files.get('files[]'))
    if not uploaded_file:
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "No files were sent to the server.", 'data':{}})
    uuid_pattern_strict = r'\b[0-9a-fA-F]{8}-' \
                      r'[0-9a-fA-F]{4}-' \
                      r'[1-5][0-9a-fA-F]{3}-' \
                      r'[89abAB][0-9a-fA-F]{3}-' \
                      r'[0-9a-fA-F]{12}\b'
    uuids = re.findall(uuid_pattern_strict, uploaded_file)
    if len(uuids) != 1:
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "Unable to find the appropriate API key", 'data':{}})
    uuids = uuids[0]
    await request.app.ctx.auth.logoff(request)
    async with request.app.ctx.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = 'SELECT user FROM sanic_info WHERE apikey=%s'
            values = (uuids, )
            await cur.execute(query, values)
    info = await cur.fetchall()
    if len(info) == 0:
        return response.json({'success': False, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, "error": "API key that was sent was invalid.", 'data':{}})
    user, apikey, info, access = await request.app.ctx.auth.logon(request, info[0]['user'])
    res = response.json({'success': True, 'sent': time.asctime(time.localtime(time.time())), 'endpoint': endpoint, 'data':{'username': user, 'apikey': apikey, 'access': access, 'info': info, 'redirect': request.app.config.REDIRECT_LOGON_SUCCESSFUL}})
    return res

