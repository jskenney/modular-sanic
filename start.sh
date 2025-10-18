#!/bin/bash

# Sample Start Script

if [ ! -d venv ]; then

  # Create and source a Python 3.11 virtual environment
  python3.11 -B -m venv venv
  source ./venv/bin/activate

  # Install required packages
  pip install --upgrade pip
  pip install --upgrade setuptools
  pip install sanic sanic-ext aiomysql python-pam six aiomcache cryptography mysqlclient pymemcache oracledb

  # There is a bug in sanic-session, so we need python 3.11 and the repo below until it is fixed
  python -B -m pip install sanic_session@git+https://github.com/jskenney/sanic-session

else

  # Source the Python 3.11 virtual environment
  source ./venv/bin/activate

  # Start Modular Sanic
  SANIC_CONFIG_FILE=config.py python3 -B $(which sanic) server \
        --debug \
  	    --reload -R . \
  	    --host=0.0.0.0

  # Additional / Extra command line arguments and examples:
  # sanic server --fast --no-access-logs --reload --host=server.example.com -R ../site/ -R ../auth/ --cert=../ssl/bundle.crt --key=../ssl/bundle.key

fi
