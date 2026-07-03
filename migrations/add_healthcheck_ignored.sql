-- Migration: add healthcheck_ignored column
-- Applies to: any deployment running before per-service healthcheck exclusion was introduced
--
-- Run with:
--   mysql -u <user> -p <database> < migrations/add_healthcheck_ignored.sql

ALTER TABLE web_ui
  ADD COLUMN healthcheck_ignored BOOLEAN NOT NULL DEFAULT 0;
