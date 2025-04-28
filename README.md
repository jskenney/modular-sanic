# Modular Sanic

Using Sanic (https://sanic.dev, https://github.com/sanic-org/sanic) as the core, the goal of Modular Sanic is to handle basic tasks such as authentication and connections to memcached and MySQL, while loading API endpoints by searching directories for python scripts with the appropriate modules.

# Initial Setup

The assumption is that this will be run on Ubuntu 24.04 using Python3.11 (due to sanic-session cookie issues), review the setup.sh script in the setup directory to get to a state where the default repo configuration will run.

# Basic Usage

In the config.py file, you will see something like:

```
site_settings = {
    'NAME':           "SanicApp_Version_1",  # Title of Application
    'API_LOCATIONS': [
                      'api/auth/general',    # General Authentication (Required)
                      'api/auth/pam',        # PAM (Local Logon) Support
                      'api/auth/apikey',     # APIKey and APIFile-Upload Support
                      'api/auth/email'       # Email Challenge Support
                      ]
}
```

The API_LOCATIONS key will point to a list of places that Modular Sanic should search through upon startup.  
Specifically, it will search for all .py files, that have a Blueprint line (called sub_bp):

```
sub_bp = Blueprint("auth_api_options", url_prefix="/auth")
```

If that line is present, Modular Sanic will attempt to load the API endpoints from this file.
