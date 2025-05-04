# Sanic Framework Configurations, Sample configuration file

# Site Specific Settings (location of directories, names, etc.)
site_settings = {
    'NAME':           "SanicApp_Version_1",  # Title of Application
    'API_LOCATIONS': [
                      'api/auth/general',    # General Authentication (Required)
                      'api/auth/pam',        # PAM (Local Logon) Support
                      'api/auth/apikey',     # APIKey and APIFile-Upload Support
                      'api/auth/email'       # Email Challenge Support
                      ],
    #'HSTS':'86400',                         # Use if you want to set HSTS headers
    #'DOCUMENTATION': False,                 # Disable OpenAPI Documentation
}

# MySQL Connection Settings
db_settings = {
    'DB_HOST': '127.0.0.1',                  # MySQL Database Host
    'DB_USER': 'username',                   # MySQL Database User
    'DB_PASS': 'password',                   # MySQL User Password
    'DB_NAME': 'dbname',                     # MySQL Database/Schema Name
    'DB_PORT':  3306                         # MySQL Port
}

# Memcached Connection Settings
memcached_settings = {
    'MEMCACHED_SERVER': '127.0.0.1',         # Memcached Server
    'MEMCACHED_PORT':    11211               # Memcached Port
}

# Web Page Settings and Locations
web_settings = {
    'SHOW_SITE_CONTENTS':         True,                       # Allow directory listings
    # The following values are located relative to server.py's filesystem location
    # Note the intial page will be 'HTML'/index.html to follow convention
    'HTML':                      './html/',                   # Location of html directory
    'FAVICON':                   './html/favicon.ico',        # Site icon
    'PAGE_404':                  './html/404.html',           # Location of 404 Error (doc not found)
    # The following values are located depending on system configurations and are
    # NOT relative to the location of server.py.
    'REDIRECT_LOGON_SUCCESSFUL': '/index.html',          # Redirect after successful logon
    'REDIRECT_LOGON_FAILED':     '/auth/logon/apifile.html',  # Redirect after unsuccessful logon
    'REDIRECT_LOGOFF':           '/index.html',          # Redirect after logoff
    'CHALLENGE_PAGE':            '/auth/logon/challenge.html',# Page for authentication challenges
    'LOGON_LOGO':                '/auth/logon/logo.webp',     # Large image for logon pages
}

auth_settings = {
    'AUTH_VALID':       604800,               # A Session is valid for 7 days
    'AUTH_MESSAGE':    "",                    # Sign on Banner / Consent Banner
    'AUTH_TITLE':      'SanicApp V1',         # Email Challenge - Title
    'AUTH_EMAILER':    'noreply@example.com', # Email Challenge - Return Address
    'AUTH_DOMAIN':     '@example.com',        # Email Challenge - Email Domain
    'AUTH_EMAIL_SERVER': 'localhost'          # Email Challenge - Local SMTP Server
}
