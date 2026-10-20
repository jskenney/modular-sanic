###############################################################################
## One time upgrade for databases created before API keys were hashed.
## Adds the key creation/expiry columns and replaces each stored key with its
## SHA-256 hash, so existing keys keep working (with no expiry).  Run it once:
##   sudo mysql -u root <dbname> < migrate_apikey_hash.sql

ALTER TABLE sanic_info
  ADD COLUMN `apikey_created` DATETIME NULL,
  ADD COLUMN `apikey_expires` DATETIME NULL;

UPDATE sanic_info
  SET apikey = SHA2(apikey, 256), apikey_created = NOW()
  WHERE apikey IS NOT NULL AND LENGTH(apikey) <> 64;
