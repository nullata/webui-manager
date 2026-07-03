-- Migration: add show_host_service_counts column
-- Applies to: any deployment running before the dashboard "service counts per host" toggle was introduced
--
-- Run with:
--   mysql -u <user> -p <database> < migrations/add_show_host_service_counts.sql

ALTER TABLE app_setting
  ADD COLUMN show_host_service_counts BOOLEAN NOT NULL DEFAULT 1;
