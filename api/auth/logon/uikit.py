from sanic import Blueprint, response
from sanic_ext import openapi
import asyncio, aiomysql
import time, re

sub_bp = Blueprint("uikit_pages", url_prefix="/uikit")

sub_bp.static("/", "./uikit", directory_view=False)
