#!/bin/bash

# Assumes a clean Ubuntu 24.04 install with no other packages installed,
# the steps below will get you to a functioning instance.

# Install Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt install -y python3.11 python3.11-dev python3.11-venv

# Install Memcached to support quick data access and sessions
sudo apt install -y memcached
sudo sed -i 's|-m 64|-m 4096|g' /etc/memcached.conf
sudo service memcached restart
sudo service memcached status

# Install requirements for the various pip installs that will
# occuring during startup
sudo apt install -y pkg-config build-essential libmysqlclient-dev

# If you want to use pam authentication (log on via local username/password combinations)
# You will need to add the user that sanic will be running as to the shadow group
sudo usermod -aG shadow $(whoami)
