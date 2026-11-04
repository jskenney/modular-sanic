#!/bin/bash

# Script will create a redirect so that port 443 redirects to the port of
# ./start.sh production (PORT, default 8443), so Sanic does not have to run as
# a superuser.  It is for production mode: the development server only
# listens on 127.0.0.1, which external traffic cannot be redirected to.
#   PORT=8443 ./install-443-redirect.sh
PORT=${PORT:-8443}

# Make sure that this provides only one response.
DEST=$(ip a | grep -v inet6 | grep -v 127.0.0.1 | grep inet | tr -s ' ' | cut -d ' ' -f 3 | cut -d '/' -f 1)

IPT="PREROUTING -p tcp --destination $DEST --dport 443 -j REDIRECT --to-ports $PORT"

sudo /usr/sbin/iptables -t nat -A $IPT

sudo apt update
sudo apt install -y iptables-persistent
