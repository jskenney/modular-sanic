#!/bin/bash

# Sample Start Script

if [ ! -d venv ]; then

  python3.11 -m venv venv
  source ./venv/bin/activate

  pip install --upgrade pip
  pip install --upgrade setuptools
  pip install sanic sanic-ext aiomysql python-pam six aiomcache cryptography mysqlclient pymemcache oracledb

  # There is a bug in sanic-session, so we need python 3.11 and the repo below until it is fixed
  python -m pip install sanic_session@git+https://github.com/zhujunling-nj/sanic-session

else

  source ./venv/bin/activate

fi

sanic server --debug --reload --host=0.0.0.0 -R .

# in Production
# sanic server --fast --no-access-logs --reload --host=server.example.com -R ../site/ -R ../auth/ --cert=../ssl/bundle.crt --key=../ssl/bundle.key
