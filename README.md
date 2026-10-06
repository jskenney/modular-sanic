# Modular Sanic

Using Sanic (https://sanic.dev, https://github.com/sanic-org/sanic) as the core, the goal of Modular Sanic is to handle basic tasks such as authentication, sessions, and connections to memcached and MySQL/MariaDB, while loading API endpoints by searching directories for python scripts with the appropriate blueprints.  It allows easy modification to APIs and allows the developer to structure the files in a way that is intuitive.

# Initial Setup

This software requires various Python libraries to operate, see requirements.txt.
A simple start.sh script is provided to create a demo Python virtual environment (venv) location and install the python packages via pip.

# Basic Usage

The program uses environment variables for most configuration items, take a look at env-example, these can be used on the command line, or you can create a .env file that will be read inside of the scripts, this also makes use in docker and docker compose easier.

The API_LOCATIONS setting is one of te most important, and will point to a list of directories that Modular Sanic should search through upon startup.  Specifically, it will search for all .py files that have a Blueprint line (called sub_bp):

```
sub_bp = Blueprint("auth_api_options", url_prefix="/auth")
```

If that line is present, specifically the sub_bp portion, Modular Sanic will attempt to load the API endpoints from this file and you can add new endpoints on the fly by simply adding additional python files in those directories or editing existing files, as long as sanic was started with the -R option it will attempt to reload when it finds the files.
