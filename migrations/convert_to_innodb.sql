-- Migration: convert all tables to the InnoDB storage engine
-- Applies to: any deployment whose tables were created as MyISAM (e.g. on a
--   MySQL/MariaDB server whose default_storage_engine is MyISAM).
--
-- Why: MyISAM does not support transactions (so the app's commit/rollback logic
--   silently does nothing), ignores the foreign keys the schema declares, and
--   raises error 1020 ("Record has changed since last read in table 'web_ui';
--   try restarting transaction") under the concurrent writes from the
--   healthcheck and favicon-refresh threads. InnoDB fixes all three.
--
-- Safe to run more than once: converting an already-InnoDB table is a no-op
--   rebuild. Check current engines first with:
--     SELECT table_name, engine FROM information_schema.tables
--      WHERE table_schema = DATABASE();
--
-- Run with:
--   mysql -u <user> -p <database> < migrations/convert_to_innodb.sql

ALTER TABLE `user` ENGINE=InnoDB;
ALTER TABLE `host` ENGINE=InnoDB;
ALTER TABLE `category` ENGINE=InnoDB;
ALTER TABLE `app_setting` ENGINE=InnoDB;
ALTER TABLE `web_ui` ENGINE=InnoDB;
ALTER TABLE `healthcheck_log` ENGINE=InnoDB;
ALTER TABLE `webui_categories` ENGINE=InnoDB;
