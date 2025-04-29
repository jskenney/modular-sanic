#!/bin/bash

# Script will create a redirect so that port 443 redirects to port 8000 (default for Sanic)
# This will prevent having to run as a superuser or using a non-standard port.

# Make sure that this provides only one response.
DEST=$(ip a | grep -v inet6 | grep -v 127.0.0.1 | grep inet | tr -s ' ' | cut -d ' ' -f 3 | cut -d '/' -f 1)

IPT="PREROUTING -p tcp --destination $DEST --dport 443 -j REDIRECT --to-ports 8000"

sudo /usr/sbin/iptables -t nat -A $IPT

sudo apt update
sudo apt install -y iptables-persistent
