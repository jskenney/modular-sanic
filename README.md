# Modular Sanic

Using Sanic (https://sanic.dev, https://github.com/sanic-org/sanic) as the core, the goal of Modular Sanic is to handle basic tasks such as authentication and connections to memcached and MySQL, while loading API endpoints by searching directories for python scripts with the appropriate modules.

# Initial Setup

Planned use for this software is on Ubuntu using Python3.11 (due to sanic-session cookie issues), the following are recommended packages in Ubuntu:

 ```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt install -y python3.11 python3.11-dev python3.11-venv

sudo apt install -y memcached
sudo sed -i 's|-m 64|-m 4096|g' /etc/memcached.conf
sudo service memcached restart
sudo service memcached status

sudo apt install pkg-config build-essential libmysqlclient-dev
```

Additionally you will want to install and configure MySQL on your server.  Take a look at start.sh and config.py for other basic setup and configuration options.
