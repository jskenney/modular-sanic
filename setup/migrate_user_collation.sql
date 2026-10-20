###############################################################################
## One time upgrade for databases created before user names were
## case-sensitive and sanic_info.apikey was indexed.  Run it once:
##   sudo mysql -u root <dbname> < migrate_user_collation.sql
## The foreign keys are dropped so the three linked user columns can change
## together, then added back.

ALTER TABLE sanic_access DROP FOREIGN KEY FK_sanic_access_user;
ALTER TABLE sanic_challenge DROP FOREIGN KEY FK_sanic_challenge_user;

ALTER TABLE sanic_info
  MODIFY `user` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  ADD KEY idx_sanic_info_apikey (apikey);
ALTER TABLE sanic_access
  MODIFY `user` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE sanic_challenge
  MODIFY `user` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;

ALTER TABLE sanic_access ADD CONSTRAINT FK_sanic_access_user FOREIGN KEY (user)
  REFERENCES sanic_info (user) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE sanic_challenge ADD CONSTRAINT FK_sanic_challenge_user FOREIGN KEY (user)
  REFERENCES sanic_info (user) ON DELETE CASCADE ON UPDATE CASCADE;
