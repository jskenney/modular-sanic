###############################################################################
## WARNING: Deletes all authentication tables and their data.
## Run auth_tables.sql afterwards to recreate empty tables.

DROP TABLE IF EXISTS sanic_challenge;
DROP TABLE IF EXISTS sanic_access;
DROP TABLE IF EXISTS sanic_info;
