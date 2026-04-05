-- Migration: add service_type column
-- Applies to: any deployment running before service_type was introduced
--
-- Run with:
--   mysql -u <user> -p <database> < migrations/add_service_type.sql

ALTER TABLE web_ui
  ADD COLUMN service_type VARCHAR(20) NOT NULL DEFAULT 'web',
  MODIFY COLUMN url VARCHAR(768) NULL;
