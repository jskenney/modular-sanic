from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("auth_logon_pages", url_prefix="/auth")

sub_bp.static("/", "./logon/logon.html", name="auth_login_html")
sub_bp.static("/logon/", "./logon/", directory_view=False)
