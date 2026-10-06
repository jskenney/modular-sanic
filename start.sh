#!/bin/bash

# Sample Start Script

if [ ! -d /tmp/demo-venv ]; then

  # Create and source a Python virtual environment
  python3 -B -m venv /tmp/demo-venv
  source /tmp/demo-venv/bin/activate

  # Install required packages
  pip install --upgrade pip
  pip install --upgrade setuptools
  pip install -r requirements.txt --no-build-isolation

else

  # Source the Python virtual environment
  source /tmp/demo-venv/bin/activate

  # Start Modular Sanic
  SANIC_CONFIG_FILE=config.py python3 -B $(which sanic) server \
        --debug \
  	    --reload -R . \
  	    --host=0.0.0.0

  # Additional / Extra command line arguments and examples:
  # sanic server --fast --no-access-logs --reload --host=server.example.com -R ../site/ -R ../auth/ --cert=../ssl/bundle.crt --key=../ssl/bundle.key

fi
