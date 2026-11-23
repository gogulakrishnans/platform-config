-- BigQuery seed down (architecture §9, C7): a scheduled query run as the customer's prod identity
-- reads the prod dataset and exports an anonymized copy as Parquet into the customer's seed bucket
-- in data-exchange (7-day lifecycle). The non-prod import job loads it into the target dataset;
-- no prod identity writes into non-prod.
--
-- Parameters (BigQuery scripting, set by the scheduled query):
--   @salt          per-run random salt (never stored)
-- Placeholders substituted by data-flows/seed-down/main.py:
--   {{source}}       pfx-data-prod.acme_corp_reporting_prod
--   {{seed_bucket}}  pfx-acme-corp-seed
--   {{run_id}}       seed-down run ID
-- One statement per table; this is the template for a table with the standard PII columns.

EXPORT DATA OPTIONS (
  uri = 'gs://{{seed_bucket}}/bigquery/{{run_id}}/events/*.parquet',
  format = 'PARQUET',
  overwrite = true
) AS
SELECT
  event_id,
  event_time,
  event_type,
  -- stable pseudonyms so joins and aggregates still work
  TO_HEX(SHA256(CONCAT(CAST(user_id AS STRING), @salt)))                                  AS user_id,
  CONCAT('user-', SUBSTR(TO_HEX(SHA256(CONCAT(email, @salt))), 1, 16), '@seed.invalid')  AS email,
  CAST(NULL AS STRING)                                                                    AS ip_address,
  -- coarsened: useful for testing, useless for re-identification
  country_code,
  ROUND(amount, -1)                                                                       AS amount,
  currency,
  -- free text may contain anything: dropped
  CAST(NULL AS STRING)                                                                    AS notes
FROM `{{source}}.events`
WHERE event_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY);                  -- recent window only
