# Modular Sanic

Using Sanic (https://sanic.dev, https://github.com/sanic-org/sanic) as the core, the goal of Modular Sanic is to handle basic tasks such as authentication and connections to memcached and MySQL, while loading API endpoints by searching directories for python scripts with the appropriate modules.

# Initial Setup

The assumption is that this will be run on Ubuntu 24.04 using Python3.11 (due to sanic-session cookie issues), review the setup.sh script in the setup directory to get to a state where the default repo configuration will run.
