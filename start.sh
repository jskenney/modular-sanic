#!/bin/bash

# Sample Start Script
#   ./start.sh              development (debug, auto reload, localhost only)
#   ./start.sh production   production example (no debug, TLS, needs CERT and KEY)
# The first run creates the virtual environment and installs the packages.

if [ ! -d /tmp/demo-venv ]; then

  # Create the Python virtual environment and install the required packages
  python3 -B -m venv /tmp/demo-venv
  source /tmp/demo-venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt || { rm -rf /tmp/demo-venv; exit 1; }

else

  # Source the Python virtual environment
  source /tmp/demo-venv/bin/activate

fi

if [ "$1" = "production" ]; then

  # Production example: no debug or auto reload, TLS on all interfaces.
  # The session cookie is only kept over HTTPS, so a certificate is required
  # (or run on 127.0.0.1 behind a reverse proxy that terminates TLS, and set
  # SANIC_PROXIES_COUNT=1, see README.md).
  if [ -z "$CERT" ] || [ -z "$KEY" ]; then
    echo "Set CERT and KEY to the TLS certificate and key files, e.g."
    echo "  CERT=../ssl/bundle.crt KEY=../ssl/bundle.key ./start.sh production"
    exit 1
  fi
  python3 -B $(which sanic) server \
      --host=0.0.0.0 --port=${PORT:-8443} \
      --cert="$CERT" --key="$KEY" \
      --workers=${WORKERS:-2}

else

  # Development: debug output and auto reload, reachable from this machine
  # only (debug responses include tracebacks).  Browse to http://localhost:8000
  python3 -B $(which sanic) server \
      --debug \
      --reload -R . \
      --host=127.0.0.1 --port=${PORT:-8000}

fi

# Additional / Extra command line arguments and examples:
# sanic server --fast --no-access-logs --reload --host=server.example.com -R ../site/ -R ../auth/ --cert=../ssl/bundle.crt --key=../ssl/bundle.key
